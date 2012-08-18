from sqlalchemy import Column, String

from quantum.db.models import BASE

class ReservedID(BASE):
    """Represents a used 8 character hex netid """
    __tablename__ = 'reserved_ids'

    short_net_id = Column(String(8), primary_key=True)

    def __init__(self, net_id):
        self.short_net_id = net_id

    def __repr__(self):
        return "<ReservedID(%s)>" % self.short_net_id

