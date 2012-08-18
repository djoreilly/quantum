import sys
import logging

import redis

LOG = logging.getLogger(__name__)

CHANNEL_PREFIX = "node"
PATCH_KEY = "bridge_patches"
NET_NODES_PREFIX = "net_nodes"
GRE_PORTS_KEY = "gre_ports"
VMACS_KEY = "vmac_nodes"
DEVS_PREFIX = "node_devs"

class DB:
    def __init__(self, host, port):
        self.r = redis.StrictRedis(host=host, port=port, db=0)
               
    def set_patch(self, br_mac, port_num):          
        LOG.debug("redis: HSET %s %s %s" % (PATCH_KEY, br_mac, port_num))
        self.r.hset(PATCH_KEY, br_mac, port_num)
    
    def remove_patch(self, br_mac):
        LOG.debug("redis: HDEL %s %s" % (PATCH_KEY, br_mac))
        self.r.hdel(PATCH_KEY, br_mac)
            
    def get_patch(self, br_mac):
        port_num = self.r.hget(PATCH_KEY, br_mac) 
        LOG.debug("redis: HGET %s %s ==> %s" % (PATCH_KEY, br_mac, port_num))
        return port_num

    
    def add_net_nodeip(self, net_id, node_ip):
        key = NET_NODES_PREFIX +"::"+ net_id
        LOG.debug("redis: SADD %s %s" % (key, node_ip))
        self.r.sadd(key, node_ip)
    
    def remove_net_nodeip(self, net_id, node_ip):
        key = NET_NODES_PREFIX +"::"+ net_id
        LOG.debug("redis: SREM %s %s" % (key, node_ip))
        self.r.srem(key, node_ip)
        
    def get_net_nodeips(self, net_id):
        key = NET_NODES_PREFIX +"::"+ net_id
        ips = self.r.smembers(key)
        LOG.debug("redis: SMEMBERS %s ==> %s" % (key, ips))
        return ips    

     
    def add_gre_port(self, br_mac, remote_ip, port_num): 
        hash = GRE_PORTS_KEY +"::"+ br_mac
        LOG.debug("redis: HSET %s %s %s" % (hash, remote_ip, port_num))
        self.r.hset(hash, remote_ip, port_num)
        
    def del_gre_port(self, br_mac, remote_ip):    
        hash = GRE_PORTS_KEY +"::"+ br_mac
        LOG.debug("redis: HDEL %s %s" % (hash, remote_ip))
        self.r.hdel(hash, remote_ip)
    
    def del_gre_ports(self, br_mac):
        key = GRE_PORTS_KEY +"::"+ br_mac
        LOG.debug("redis: DEL %s" % key)
        self.r.delete(key)
        
    def get_gre_port(self, br_mac, remote_ip):
        hash = GRE_PORTS_KEY +"::"+ br_mac
        port_num = self.r.hget(hash, remote_ip)
        LOG.debug("redis: HGET %s %s ==> %s" % (hash, remote_ip, port_num))
        return port_num


    def set_vmac_nodeip(self, mac, nodeip):
        LOG.debug("redis: HSET %s %s %s" % (VMACS_KEY, mac, nodeip))
        self.r.hset(VMACS_KEY, mac, nodeip)
        
    def get_vmac_nodeip(self, mac):
        ip = self.r.hget(VMACS_KEY, mac)
        LOG.debug("redis: HGET %s %s ==> %s" % (VMACS_KEY, mac, ip) )  
        return ip
      
    def del_vmac(self, mac): 
        LOG.debug("redis: HDEL %s %s" % (VMACS_KEY, mac))
        self.r.hdel(VMACS_KEY, mac)


    def set_dev_mac(self, nodeip, dev, mac):
        key = DEVS_PREFIX +"::"+ nodeip
        LOG.debug("redis: HSET %s %s %s" % (key, dev, mac))
        self.r.hset(key, dev, mac)
    
    def get_dev_mac(self, nodeip, dev):
        key = DEVS_PREFIX +"::"+ nodeip
        mac = self.r.hget(key, dev)
        LOG.debug("redis: HGET %s %s ==> %s" % (key, dev, mac))
        return mac
            
    def del_dev(self, nodeip, dev):
        key = DEVS_PREFIX +"::"+ nodeip
        LOG.debug("redis: HDEL %s %s" % (key, dev))
        self.r.hdel(key, dev)
    
    def get_nodes_devs(self, nodeip):
        key = DEVS_PREFIX +"::"+ nodeip
        devs = self.r.hkeys(key)
        LOG.debug("redis: KEYS %s ==> %s" % (key, devs))
        return devs
        
    
    def publish(self, channel, message):
        LOG.debug("redis: PUBLISH %s %s" % (channel, message))
        self.r.publish(channel, message)
        
        
    def save(self): 
        self.r.save()   
            
        
    
    
    
    
