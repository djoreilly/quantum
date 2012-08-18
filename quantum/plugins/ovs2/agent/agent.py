import sys
import fcntl
import time
import logging
import tempfile
from threading import Thread
import Queue
import re
from optparse import OptionParser
import ConfigParser

import pyudev
import redis

import ovs_lib as ovs
import kv_api

Q = Queue.Queue(0)
LOG = logging.getLogger()

# the last 8 hex chars of bridges are the first 8 of the quantum network uuid
ACCESS_BR_PAT  = '^bracc-[0-9a-f]{8}$'
TUNNEL_BR_PAT  = '^brtun-[0-9a-f]{8}$'
# nova creates devices like gw-12ab34cd-56 and tap78ef01ab-cd
DEV_PAT = '^gw-[0-9a-f]{8}-[0-9a-f]{2}$|^tap[0-9a-f]{8}-[0-9a-f]{2}$'


class NetDeviceMonitor(Thread):
    '''
    This thread listens for udev events when nova creates or deletes
    access bridges, gateway devices and vm tap devices
    '''
    def __init__(self):
        Thread.__init__(self)
          
    def run(self):
        monitor = pyudev.Monitor.from_netlink(pyudev.Context())
        monitor.filter_by(subsystem = 'net')
        observer = pyudev.MonitorObserver(monitor, self.handler)
        observer.daemon = False
        observer.start()
        
    def handler(self, action, device):
        dev_name = device.sys_name
        if re.match(ACCESS_BR_PAT, dev_name):
            net_id = dev_name[6:14]
            if action == 'add':
                Q.put(AddTunnelBridge(net_id ))
            elif action == 'remove':
                Q.put(DelTunnelBridge(net_id ))
        elif re.match(DEV_PAT, dev_name):
            if action == 'add':
                Q.put(SetMacLocation(dev_name))
            elif action == 'remove':
                Q.put(DelMacLocation(dev_name))

              
class Subscriber(Thread):
    '''
    This thread listens for notifications from agents when they 
    add or remove tunnel bridges for networks that this node has.
    Each node subscribes to its own channel.
    '''
    def __init__(self, host, port, channel):
        Thread.__init__(self)
        self.host = host
        self.port = port
        self.channel = channel
        
    def run(self):       
        r = redis.StrictRedis(host=self.host, port=self.port, db=0)        
        ps = r.pubsub()
        while True:
            try:
                ps.subscribe(self.channel) 
                ret = ps.listen()
            except redis.exceptions.ConnectionError as e:
                LOG.warning("Problem subscribing: %s" % str(e))
                time.sleep(5)
                continue
            LOG.debug("Subscriber listening on channel %s" % self.channel)
            while True:
                try:
                    msg = ret.next()
                except redis.exceptions.ConnectionError: 
                    LOG.exception("Connection problem getting message")
                    time.sleep(5)
                    # need to re-subscribe at outer loop after broken socket
                    break  
                net_id = msg['data']
                Q.put( SyncTunnels(net_id) )
 

class Command:
    """The Command Abstract class"""
    def __init__(self):
        pass
 
    def execute(self):
        pass

        
class AddTunnelBridge(Command):
    '''
    Creates a tunnel bridge and patch it to the corresponding access bridge
    for this network. Configure it to use an OpenFlow controller. Notify all
    nodes that hold part of this network so they can create a tunnel to it.
    '''
    def __init__(self, net_id):
        self.net_id = net_id
        self.br_name = 'brtun-' + net_id
           
    def __str__(self):
        return "AddTunnelBridge(%s)" % self.net_id
    
    def execute(self, config, db):
        ovs.run_vsctl(['add-br', self.br_name])
        
        patch_name = 'p-acc-%s' % self.net_id
        ovs.create_patch_port(self.br_name, patch_name, 
                              'p-tun-%s' % self.net_id)
        patch_num = ovs.get_ofport(patch_name)
        br_mac = ovs.get_br_mac(self.br_name)
        # OFC needs to know the patch port number - though 1st port always 
        # seems to be 1
        db.set_patch(br_mac, patch_num)
        
        # never want the bridge to fail to default L2 learner in a full mesh
        ovs.run_vsctl(['set-fail-mode', self.br_name, 'secure'])
        of_controller_url = config.get("OPENFLOW", "ofc_connection")
        ovs.run_vsctl(['set-controller', self.br_name, of_controller_url])
        
        db.add_net_nodeip(self.net_id, config.get("LOCAL", "ipaddr"))     
        net_nodeips = db.get_net_nodeips(self.net_id)
        # the local node will be notified too
        for nodeip in net_nodeips:
            channel = kv_api.CHANNEL_PREFIX + "-" + nodeip
            db.publish(channel, self.net_id)
        
        LOG.info("Created bridge %s with mac %s" % (self.br_name, br_mac))
  
        
class DelTunnelBridge(Command):
    def __init__(self, net_id):
        self.net_id = net_id
        self.br_name = 'brtun-' + net_id
        
    def __str__(self):
        return "DelTunnelBridge(%s)" % self.net_id 
    
    def execute(self, config, db):
        br_mac = ovs.get_br_mac(self.br_name)
        ovs.run_vsctl(['del-br', self.br_name])
        
        db.remove_patch(br_mac)
        db.del_gre_ports(br_mac)
        db.remove_net_nodeip(self.net_id, config.get("LOCAL", "ipaddr"))
        
        net_nodeips = db.get_net_nodeips(self.net_id)
        for nodeip in net_nodeips:
            channel = kv_api.CHANNEL_PREFIX + "-" + nodeip
            db.publish(channel, self.net_id)

        LOG.info("Removed bridge %s with mac %s" % (self.br_name, br_mac))

        
class SyncTunnels(Command):
    '''
    Synchronise the gre ports on the tunnel bridge for net_id with the database.
    Keep db mapping between gre remote_ips and port numbers.  
    The OpenFlow controller will read these to find out what port to forward to.
    '''
    def __init__(self, net_id):
        self.net_id = net_id
    
    def __str__(self):
        return "SyncTunnels(%s)" % self.net_id
        
    def execute(self, config, db):
        current_gre_ips = set( ovs.get_gre_ips(self.net_id) )
        required_gre_ips = set( db.get_net_nodeips(self.net_id) )
        local_ip = config.get("LOCAL", "ipaddr")
        if local_ip in required_gre_ips:
            required_gre_ips.remove(local_ip)
        
        if current_gre_ips == required_gre_ips:
            LOG.debug("GRE tunnels for net %s already up-to-date" % self.net_id)
            return
        
        br_name = 'brtun-' + self.net_id
        br_mac = ovs.get_br_mac(br_name)
        
        for old_ip in current_gre_ips - required_gre_ips:
            LOG.debug("Removing GRE endpoint for net %s to %s"
                      % (self.net_id, old_ip))
            port_name = ovs.get_gre_port_name(self.net_id, old_ip)
            ovs.run_vsctl(['del-port', port_name])
            db.del_gre_port(br_mac, old_ip)
            
        for new_ip in required_gre_ips - current_gre_ips:
            LOG.debug("Adding GRE endpoint for net %s to %s" 
                      % (self.net_id, new_ip))
            port_name = ovs.get_gre_port_name(self.net_id, new_ip)
            ovs.create_gre_port(br_name, port_name, new_ip, self.net_id)
            port_num = ovs.get_ofport(port_name)
            db.add_gre_port(br_mac, new_ip, port_num)
        
        LOG.info("Synchronised tunnels for net %s " % self.net_id)


class SetMacLocation(Command):
    '''
    Add a mapping to the db for a virtual mac to this node's ip address.
    The virtual mac can be from a vm or a gateway device. 
    The OpenFlow controller will use this k/v to find which node a vmac is on.
    '''
    def __init__(self, dev_name):
        self.dev_name = dev_name
      
    def __str__(self):
        return "SetMacLocation(%s)" % self.dev_name
          
    def execute(self, config, db):
        mac = ovs.get_attached_mac(self.dev_name)
        local_ip = config.get("LOCAL", "ipaddr")
        db.set_vmac_nodeip(mac, local_ip)
        # also store a dev-mac mapping so we'll be able to find out what mac 
        # a device had after it gets removed
        db.set_dev_mac(local_ip, self.dev_name, mac)
        
        
class DelMacLocation(Command):
    def __init__(self, dev_name):
        self.dev_name = dev_name
      
    def __str__(self):
        return "DelMacLocation(%s)" % self.dev_name
          
    def execute(self, config, db):
        local_ip = config.get("LOCAL", "ipaddr")
        # need to lookup db to find what mac this device had
        mac = db.get_dev_mac(local_ip, self.dev_name)
        db.del_vmac(mac)
        db.del_dev(local_ip, self.dev_name)

        
def init(config, db):
    '''
    If the agent has not been running for some time, then events may have been
    missed. This makes sure there is a tunnel bridge for every access bridge
    and that the gre tunnel ports are up to date. And update DB too.
    TODO taps and gws
    '''
    LOG.debug("Sychronising tunnel bridges with access bridges")
    all_bridges = ovs.run_vsctl(['list-br']).split("\n")
    LOG.debug("all bridges %s" % all_bridges)
    acc_br_nets = set()
    tun_br_nets = set()
    for br in all_bridges:
        if re.match(ACCESS_BR_PAT, br):
            acc_br_nets.add(br[6:14])
        elif re.match(TUNNEL_BR_PAT, br):
            tun_br_nets.add(br[6:14])
    
    for net_id in tun_br_nets - acc_br_nets:
        LOG.debug("removing tunnel bridge for net %s" % net_id)
        DelTunnelBridge(net_id).execute(config, db) 
    
    for net_id in acc_br_nets - tun_br_nets:
        LOG.debug("adding tunnel bridge for net %s" % net_id)
        AddTunnelBridge(net_id).execute(config, db)
        # the local listener is not running yet, so call directy
        SyncTunnels(net_id).execute(config, db)
                   
    for net_id in acc_br_nets & tun_br_nets:
        LOG.debug("syncing gre ports on tunnel bridge for net %s" % net_id)
        SyncTunnels(net_id).execute(config, db)
    
    LOG.debug("Syncing DB with devices on this node")
    current_devs = set()
    for bridge in all_bridges:
        if re.match(ACCESS_BR_PAT, bridge):
            ports = ovs.run_vsctl(['list-ports', bridge]).split("\n")
            for port in ports:
                if re.match(DEV_PAT, port):
                    current_devs.add(port)
    LOG.debug("current devices %s" % current_devs)
    db_devs = set(db.get_nodes_devs(config.get("LOCAL", "ipaddr")))
    LOG.debug("devices on db %s" % db_devs)
    for dev in current_devs - db_devs:
        LOG.debug("Adding device %s to database" % dev)
        SetMacLocation(dev).execute(config, db)
    
    for dev in db_devs - current_devs:
        LOG.debug("Removing device %s from database" % dev)
        DelMacLocation(dev).execute(config, db)
                                            
    LOG.debug("Initialization complete \n")                        

                            
def main():
    usagestr = "%prog [OPTIONS] <config file>"
    parser = OptionParser(usage=usagestr)
    parser.add_option("-v", "--verbose", dest="verbose",action="store_true",
                       default=False, help="turn on verbose logging")
    options, args = parser.parse_args()
    if options.verbose:
        LOG.setLevel(logging.DEBUG)
    else:
        LOG.setLevel(logging.WARNING)

    if len(args) != 1:
        parser.print_help()
        sys.exit(1)
    
    cfg_file = args[0]
    
    lockfile = tempfile.gettempdir() +"/.qagentlock"
    fp = open(lockfile, 'w')
    try:
        fcntl.lockf(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        LOG.error("Agent already running. Lock file is %s" % lockfile)
        sys.exit(1)    
    
    logging.basicConfig(format='%(asctime)s %(name)-8s %(message)s')
    LOG.info("******** Starting %s ********" % sys.argv[0])
    
    config = ConfigParser.ConfigParser()
    try:
        config.readfp(open(cfg_file))
    except:
        LOG.exception("Unable to open or parse %s" % cfg_file)
        sys.exit(1)

    try:
        db_host = config.get("DATABASE", "host")
        db_port = config.getint("DATABASE", "port")
        local_ip = config.get("LOCAL", "ipaddr")
        if len(db_host) == 0 or len(local_ip) == 0:
            raise Exception("[DATABASE] values can not be blank strings")                                    
    except Exception as e:
        LOG.exception("Invalid database configuration in %s" % cfg_file)
        sys.exit(1) 
                
    try:
        db = kv_api.DB(db_host, db_port)
    except Exception as e:
        LOG.exception("Unable to initaialise database connection")
        sys.exit(1)

    try:
        init(config, db)
    except Exception as e:
        LOG.exception("Problem initialising bridges")   
        sys.exit(1)
                   
    channel = kv_api.CHANNEL_PREFIX + "-" + local_ip
    Subscriber(db_host, db_port, channel).start()
    
    NetDeviceMonitor().start()
    
    while True:
        command = Q.get(block=True)
        LOG.debug("Got command %s from queue" % command )  
        try:
            command.execute(config, db)
        except:
            # allow thread to continue
            LOG.exception("Problem executing command")
        LOG.debug("Finished command %s \n" % command )    
   

if __name__ == '__main__':
    main()
            
    
    
