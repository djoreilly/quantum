import sys
import ConfigParser
from pox.core import core
from pox.lib.revent import EventMixin
import pox.openflow.libopenflow_01 as of
from pox.lib.util import dpidToStr
from pox.lib.addresses import EthAddr
from pox.lib.packet.packet_utils import ethtype_to_str 
import redis
import kv_api

LOG = core.getLogger()
DB = None
IDLE_TIMEOUT = 30
HARD_TIMEOUT = 60

class Bridge(EventMixin):
    
    def __init__ (self, connection, br_mac):
        self.connection = connection
        self.br_mac = br_mac
        self.patch_port = int(DB.get_patch(br_mac))
        self.listenTo(connection)
         
    def _handle_PacketIn (self, event):       
        packet = event.parse()
        if packet.type == 0x86dd:
            # dropping IPv6 for now
            return
        LOG.debug("%s: in_port %d %s -> %s type %s" 
                   % (self.br_mac, event.port, packet.src, packet.dst,
                      ethtype_to_str(packet.type)) )
                   
        if event.port == self.patch_port and packet.dst.isMulticast():
            # outbound multicast - flood to all ports except patch
            self.send_packet(self.patch_port, event.ofp.buffer_id, 
                             of.OFPP_FLOOD)
            # install a permentant rule for subseqent matches
            self.install_flow(self.patch_port, of.OFPP_FLOOD, packet.dst)
            LOG.debug("%s: installed flow: inport patch %d && dst %s - flood"
                      % (self.br_mac, self.patch_port, packet.dst))
        
        elif event.port == self.patch_port:
            # outbound unicast
            node_ip = DB.get_vmac_nodeip(str(packet.dst))  
            if node_ip is None:
                LOG.debug("dropping unknown dst %s" % packet.dst) 
                return      
            out_port = DB.get_gre_port(self.br_mac, node_ip)
            if out_port is None:
                # ignore access bridge unicast flood for a local vm
                LOG.debug("packet for VM on node_ip = %s, dropping" % node_ip )
                return      
            out_port = int(out_port)
            self.send_packet(self.patch_port, event.ofp.buffer_id, out_port)
            # install tempory flow for subsequent matches with this mac
            self.install_flow(self.patch_port, out_port, packet.dst,
                              IDLE_TIMEOUT, HARD_TIMEOUT)
            
            LOG.debug("%s: installed flow: inport patch %d dst %s output gre %d" 
                    % ( self.br_mac, self.patch_port, packet.dst, out_port ) )
        else:
            # packet came in on a gre tunnel port 
            # send all inbound packets straight to the access bridge
            self.send_packet(event.port, event.ofp.buffer_id, self.patch_port)
            self.install_flow(event.port, self.patch_port)
            LOG.debug("%s: installed flow: in_port gre %d - output patch %d" 
                       % ( self.br_mac, event.port, self.patch_port ) )      

    def install_flow(self, inport, outport, dst_mac=None,  
                     idle_timeout=0, hard_timeout=0):
        msg = of.ofp_flow_mod()  
        msg.match.in_port = inport
        if dst_mac is not None:
            msg.match.dl_dst = dst_mac
        msg.idle_timeout = idle_timeout
        msg.hard_timeout = hard_timeout
        msg.actions.append( of.ofp_action_output(port=outport))
        self.connection.send(msg)
                    
    def send_packet(self, inport, buffer_id, outport):
        msg = of.ofp_packet_out()
        msg.actions.append( of.ofp_action_output(port=outport))
        msg.buffer_id = buffer_id 
        msg.in_port = self.patch_port 
        self.connection.send(msg)  
 
            
class ConnectionManager(EventMixin):
    def __init__ (self):
        self.listenTo(core.openflow)

    def _handle_ConnectionUp (self, event):  
        Bridge(event.connection, dpidToStr(event.dpid))


def launch(cfgfile=None):
    if cfgfile is None:
        LOG.error("cfgfile required: --cfgfile=filepath")
        sys.exit(1)
    config = ConfigParser.ConfigParser()
    try:
        config.readfp(open(cfgfile))
    except:
        LOG.exception("Unable to parse config file %s" % cfgfile)
        sys.exit(1)
    try:
        db_host = config.get("DATABASE", "host")
        if len(db_host) == 0:
            raise Exception("[DATABASE] host can not be an empty string")     
        db_port = config.getint("DATABASE", "port")                               
    except:
        LOG.exception("Invalid database configuration in %s" % cfgfile)
        sys.exit(1) 
    global DB        
    DB = kv_api.DB(db_host, db_port)
    core.registerNew(ConnectionManager)
    
