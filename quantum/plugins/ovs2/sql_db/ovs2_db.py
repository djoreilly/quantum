
from sqlalchemy.orm import exc

import quantum.db.api as db

import ovs2_models as models


def reserve_id(net_id):
    session = db.get_session()
    short_id = models.ReservedID(net_id)
    session.add(short_id)
    session.flush()
    
def unreserve_id(net_id):
    session = db.get_session() 
    try:
        short_id = session.query(models.ReservedID).\
                    filter_by(short_net_id=net_id).\
                    one()
        session.delete(short_id)
    except exc.NoResultFound:
        pass
    session.flush()
    
def is_reserved_id(net_id):
    session = db.get_session() 
    try:
        session.query(models.ReservedID).\
                    filter_by(short_net_id=net_id).\
                    one()
        reserved = True
    except exc.NoResultFound:
        reserved = False
    return reserved

