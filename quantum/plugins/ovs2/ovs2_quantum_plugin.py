import ConfigParser
import logging as LOG
import os

from quantum.api.api_common import OperationalStatus
from quantum.common import exceptions as q_exc
from quantum.common.config import find_config_file
from quantum.manager import find_config
from quantum.quantum_plugin_base import QuantumPluginBase

import quantum.db.api as db
import sql_db.ovs2_db as ovs2

CONF_FILE = find_config_file({"plugin": "ovs2"}, None, 
                             "ovs2_quantum_plugin.ini")

LOG.basicConfig(level=LOG.DEBUG)
LOG.getLogger(__name__)


class OVSQuantumPlugin(QuantumPluginBase):

    def __init__(self, configfile=None):
        config = ConfigParser.ConfigParser()
        if configfile is None:
            if os.path.exists(CONF_FILE):
                configfile = CONF_FILE
            else:
                configfile = find_config(os.path.abspath(
                        os.path.dirname(__file__)))
        if configfile is None:
            raise Exception("Configuration file %s does not exist" % configfile)
        LOG.debug("Using configuration file: %s" % configfile)
        config.read(configfile)
        options = {"sql_connection": config.get("DATABASE", "sql_connection")}
        LOG.debug("Using SQL DB: %s" % options)
        db.configure_db(options)

    def get_all_networks(self, tenant_id, **kwargs):
        nets = []
        for x in db.network_list(tenant_id):
            LOG.debug("Adding network: %s" % x.uuid)
            nets.append(self._make_net_dict(str(x.uuid), x.name,
                                            None, x.op_status))
        return nets

    def _make_net_dict(self, net_id, net_name, ports, op_status):
        res = { 'net-id': net_id,
                'net-name': net_name,
                'net-op-status': op_status}
        if ports:
            res['net-ports'] = ports
        return res

    def create_network(self, tenant_id, net_name, **kwargs):
        success = False
        while not success:
            net = db.network_create(tenant_id, net_name, 
                                    op_status=OperationalStatus.UP)
            short_id = str(net.uuid)[0:8]
            if ovs2.is_reserved_id(short_id):
                db.network_destroy(net.net_id)
            else:
                ovs2.reserve_id(short_id)
                success = True    
                          
        LOG.debug("Created network: %s" % net)
        return self._make_net_dict(str(net.uuid), net.name, [], net.op_status)

    def delete_network(self, tenant_id, net_id):
        db.validate_network_ownership(tenant_id, net_id)
        # Verify that no attachments are plugged into the network
        for port in db.port_list(net_id):
            if port.interface_id:
                raise q_exc.NetworkInUse(net_id=net_id)
        net = db.network_destroy(net_id)
        ovs2.unreserve_id(str(net.uuid)[0:8])
        return self._make_net_dict(str(net.uuid), net.name, [], net.op_status)

    def get_network_details(self, tenant_id, net_id):
        db.validate_network_ownership(tenant_id, net_id)
        net = db.network_get(net_id)
        ports = self.get_all_ports(tenant_id, net_id)
        return self._make_net_dict(str(net.uuid), net.name, 
                                   ports, net.op_status)

    def update_network(self, tenant_id, net_id, **kwargs):
        db.validate_network_ownership(tenant_id, net_id)
        net = db.network_update(net_id, tenant_id, **kwargs)
        return self._make_net_dict(str(net.uuid), net.name, None, net.op_status)

    def _make_port_dict(self, port):
        if port.state == "ACTIVE":
            op_status = port.op_status
        else:
            op_status = OperationalStatus.DOWN

        return {'port-id': str(port.uuid),
                'port-state': port.state,
                'port-op-status': op_status,
                'net-id': port.network_id,
                'attachment': port.interface_id}

    def get_all_ports(self, tenant_id, net_id, **kwargs):
        db.validate_network_ownership(tenant_id, net_id)
        ports = db.port_list(net_id)
        # This plugin does not perform filtering at the moment
        return [{'port-id': str(p.uuid)} for p in ports]

    def create_port(self, tenant_id, net_id, port_state=None, **kwargs):
        LOG.debug("Creating port with network_id: %s" % net_id)
        db.validate_network_ownership(tenant_id, net_id)
        port = db.port_create(net_id, port_state,
                                op_status=OperationalStatus.DOWN)
        return self._make_port_dict(port)

    def delete_port(self, tenant_id, net_id, port_id):
        db.validate_port_ownership(tenant_id, net_id, port_id)
        port = db.port_destroy(port_id, net_id)
        return self._make_port_dict(port)

    def update_port(self, tenant_id, net_id, port_id, **kwargs):
        """
        Updates the state of a port on the specified Virtual Network.
        """
        db.validate_port_ownership(tenant_id, net_id, port_id)
        port = db.port_get(port_id, net_id)
        db.port_update(port_id, net_id, **kwargs)
        return self._make_port_dict(port)

    def get_port_details(self, tenant_id, net_id, port_id):
        db.validate_port_ownership(tenant_id, net_id, port_id)
        port = db.port_get(port_id, net_id)
        return self._make_port_dict(port)

    def plug_interface(self, tenant_id, net_id, port_id, remote_iface_id):
        db.validate_port_ownership(tenant_id, net_id, port_id)
        db.port_set_attachment(port_id, net_id, remote_iface_id)
        db.port_update(port_id, net_id, op_status=OperationalStatus.UP)

    def unplug_interface(self, tenant_id, net_id, port_id):
        db.validate_port_ownership(tenant_id, net_id, port_id)
        db.port_set_attachment(port_id, net_id, "")
        db.port_update(port_id, net_id, op_status=OperationalStatus.DOWN)

    def get_interface_details(self, tenant_id, net_id, port_id):
        db.validate_port_ownership(tenant_id, net_id, port_id)
        res = db.port_get(port_id, net_id)
        return res.interface_id
