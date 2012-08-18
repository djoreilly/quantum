'''
called by nova - uses nova utils and will log to nova
'''

from nova import exception
from nova import log as logging
from nova.network import linux_net
from nova import utils
from nova.virt import vif

import quantum.plugins.ovs2.nova.ovs_lib_nova as ovs_lib


LOG = logging.getLogger()


class LibvirtOVSDriver(vif.VIFDriver):
 
    def get_dev_name(self, iface_id):
        return "tap" + iface_id[0:11]

    def plug(self, instance, network, mapping):
               
        LOG.info("ovs2 plug driver")
 
        iface_id = mapping['vif_uuid']
        dev = self.get_dev_name(iface_id)
        if not linux_net._device_exists(dev):
            utils.execute('ip', 'tuntap', 'add', dev, 'mode', 'tap',
                          run_as_root=True) 
            utils.execute('ip', 'link', 'set', dev, 'up', run_as_root=True)
        
        net_uuid = network['id']
        br_name = ovs_lib.get_access_br_name(net_uuid)
        if not ovs_lib.bridge_exists(br_name):
            ovs_lib.create_access_bridge(net_uuid)
            
        utils.execute('ovs-vsctl', '--', '--may-exist', 'add-port',
                br_name, dev,
                '--', 'set', 'Interface', dev,
                "external-ids:iface-id=%s" % iface_id,
                '--', 'set', 'Interface', dev,
                "external-ids:iface-status=active",
                '--', 'set', 'Interface', dev,
                "external-ids:attached-mac=%s" % mapping['mac'],
                '--', 'set', 'Interface', dev,
                "external-ids:vm-uuid=%s" % instance['uuid'],
                run_as_root=True)

        result = {
            'script': '',
            'name': dev,
            'mac_address': mapping['mac']}
        return result

    def unplug(self, instance, network, mapping):
        """Unplug the VIF from the network by deleting the port from
        the bridge."""
        LOG.info("ovs2 unplug driver")
        
        dev = self.get_dev_name(mapping['vif_uuid'])
        br_name = ovs_lib.get_access_br_name(network['id'])
        try:
            utils.execute('ovs-vsctl', 'del-port',
                          br_name, dev, run_as_root=True)
            utils.execute('ip', 'link', 'delete', dev, run_as_root=True)
        except exception.ProcessExecutionError:
            LOG.exception(_("Failed while unplugging vif of instance '%s'"),
                        instance['name'])
        
        if ovs_lib.bridge_empty(br_name):
            ovs_lib.delete_bridge(br_name)
            




