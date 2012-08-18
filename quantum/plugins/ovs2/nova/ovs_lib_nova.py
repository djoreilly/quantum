'''
common calls to open vswitch used by both drivers on access bridges

'''

from nova import utils

PATCH_TUN_PREFIX = 'p-tun-'
PATCH_ACC_PREFIX = 'p-acc-'
ACC_BR_PREFIX = 'bracc-'

def get_access_br_name(net_uuid):
    return ACC_BR_PREFIX + net_uuid[0:8]

  
def bridge_exists(br_name):
    (out,err) = utils.execute('ovs-vsctl', 'list-br', run_as_root=True)   
    return br_name in out

  
def create_access_bridge(net_uuid):
    br_name = get_access_br_name(net_uuid)  
    utils.execute('ovs-vsctl','add-br', br_name, run_as_root=True)  
    utils.execute('ovs-vsctl','br-set-external-id', br_name,
                   'net-uuid', net_uuid, run_as_root=True) 
    
    net_id = net_uuid[0:8]
    patch_name = PATCH_TUN_PREFIX + net_id
    patch_peer = PATCH_ACC_PREFIX + net_id
    utils.execute('ovs-vsctl', 'add-port', br_name, patch_name,
                    run_as_root=True)
    utils.execute('ovs-vsctl', 'set', 'Interface', patch_name,
                    'type=patch', run_as_root=True)
    utils.execute('ovs-vsctl', 'set', 'Interface', patch_name,
                    'options:peer=%s' % patch_peer, run_as_root=True)
    
    return br_name
    
    
def bridge_empty(br_name):
    # true if only the patch port remains
    (out,err) = utils.execute('ovs-vsctl', 'list-ports', 
                              br_name, run_as_root=True)      
    net_id = br_name[6:14]
    patch_port = PATCH_TUN_PREFIX + net_id
    if out.strip("\"\n") == patch_port:
        return True
    else:
        return False
        

def delete_bridge(br_name):
    utils.execute('ovs-vsctl', 'del-br', 
                   br_name, run_as_root=True)

    
def get_br_net_uuid(br_name):
    (out,err) = utils.execute('ovs-vsctl','br-get-external-id', 
                              br_name, 'net-uuid', run_as_root=True)
    return out.rstrip("\n\r")

      