import zlib
import utils 


def run_vsctl(args):
    full_args = ["ovs-vsctl", "--timeout=2"] + args
    return utils.execute(full_args, root_helper='sudo') #TODO

def dpid_to_mac(dpid):
    return dpid[4:6] +'-'+ dpid[6:8] +'-'+ dpid[8:10] +'-'+ \
            dpid[10:12] +'-'+ dpid[12:14] +'-'+ dpid[14:16]

def get_br_mac(br_name):
    dpid = run_vsctl(['get', 'bridge', br_name, 'datapath_id'])
    return dpid_to_mac(dpid.strip("\"\n"))
    
def get_ofport(port_name):
    port_num = run_vsctl(['get', 'Interface', port_name, 'ofport'])
    return port_num.rstrip("\n")

def create_patch_port(br_name, port_name, peer_name):    
    run_vsctl(['add-port', br_name, port_name])
    run_vsctl(['set', 'Interface', port_name, 'type=patch'] )
    run_vsctl(['set', 'Interface', port_name, 'options:peer=%s' %(peer_name)])

def get_gre_port_name(net_id, remote_ip):
    ''' needs to be <14 chars or tunnel won't work '''
    s = str(net_id) + str(remote_ip)
    return 'gre-%x' % abs(zlib.crc32(s))
     
def create_gre_port(br_name, port_name, remote_ip, gre_key): 
    run_vsctl(['add-port', br_name, port_name])
    run_vsctl(['set', 'Interface', port_name, 'type=gre'] )
    run_vsctl(['set', 'Interface', port_name, 'options:remote_ip=%s' 
               %(remote_ip)])
    run_vsctl(['set', 'Interface', port_name, 'options:key=0x%s' %(gre_key)])
        
def get_gre_ips(net_id):
    ports = run_vsctl(['--bare', '--','--columns=name', 
                       'find', 'interface', 'type=gre', 
                       'options:key=0x%s' %net_id])
    remote_ips = []
    for port in ports.split():
        remote_ip = run_vsctl(['get', 'Interface', port, 'options:remote_ip'])
        remote_ips.append(remote_ip.strip("\"\n"))
    return remote_ips     
        
def get_attached_mac(dev_name):
    utils.execute(["ovs-vsctl", "--timeout=10", "wait-until", 
                   "interface", dev_name], root_helper='sudo')
    out = run_vsctl(["get", "interface", dev_name, "external_ids:attached-mac"])
    return out.strip("\"\n")   
        