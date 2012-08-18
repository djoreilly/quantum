from nova import log as logging
from nova.network import linux_net
from nova import utils
from nova import flags
from nova.openstack.common import cfg

import quantum.plugins.ovs2.nova.ovs_lib_nova as ovs_lib


LOG = logging.getLogger()
FLAGS = flags.FLAGS
               

class LinuxOvsIfaceDriver(linux_net.LinuxNetInterfaceDriver):

    def plug(self, network, mac_address, gateway=True):
        '''
        always called when nova-network starts?
        '''
        LOG.debug("ovs2 plug driver")
        
        br_name = ovs_lib.get_access_br_name(network['uuid'])
        if not ovs_lib.bridge_exists(br_name):
            ovs_lib.create_access_bridge(network['uuid'])
        
        dev = self.get_dev(network)
        if not linux_net._device_exists(dev):
            utils.execute('ovs-vsctl',
                        '--', '--may-exist', 'add-port', br_name, dev,
                        '--', 'set', 'Interface', dev, "type=internal",
                        '--', 'set', 'Interface', dev,
                                "external-ids:iface-id=%s" % dev,
                        '--', 'set', 'Interface', dev,
                                "external-ids:iface-status=active",
                        '--', 'set', 'Interface', dev,
                                "external-ids:attached-mac=%s" % mac_address,
                        run_as_root=True)
            utils.execute('ip', 'link', 'set', dev, "address", mac_address,
                        run_as_root=True)
            if FLAGS.network_device_mtu:
                utils.execute('ip', 'link', 'set', dev, 'mtu',
                         FLAGS.network_device_mtu, run_as_root=True)
            utils.execute('ip', 'link', 'set', dev, 'up', run_as_root=True)
            if not gateway:
                # If we weren't instructed to act as a gateway then add the
                # appropriate flows to block all non-dhcp traffic.
                utils.execute('ovs-ofctl',
                    'add-flow', br_name, "priority=1,actions=drop",
                     run_as_root=True)
                utils.execute('ovs-ofctl', 'add-flow', br_name,
                    "udp,tp_dst=67,dl_dst=%s,priority=2,actions=normal" %
                    mac_address, run_as_root=True)
                # .. and make sure iptbles won't forward it as well.
                linux_net.iptables_manager.ipv4['filter'].add_rule('FORWARD',
                        '--in-interface %s -j DROP' % br_name)
                linux_net.iptables_manager.ipv4['filter'].add_rule('FORWARD',
                        '--out-interface %s -j DROP' % br_name)
            else:
                linux_net.iptables_manager.ipv4['filter'].add_rule('FORWARD',
                        '--in-interface %s -j ACCEPT' % br_name)
                linux_net.iptables_manager.ipv4['filter'].add_rule('FORWARD',
                        '--out-interface %s -j ACCEPT' % br_name)

        return dev

    def unplug(self, network):
        LOG.debug("ovs2 unplug driver")
    
        dev = self.get_dev(network)
        br_name = ovs_lib.get_access_br_name(network['uuid'])
        utils.execute('ovs-vsctl', '--', '--if-exists', 'del-port',
                               br_name, dev, run_as_root=True)
        
        if ovs_lib.bridge_empty(br_name):
            ovs_lib.delete_bridge(br_name)
            
        return dev

    def get_dev(self, network):
        dev = "gw-" + str(network['uuid'][0:11])
        return dev
