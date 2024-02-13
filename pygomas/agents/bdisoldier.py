from pygomas.ontology import Service
from .bditroop import BDITroop
from ..config import CLASS_SOLDIER


class BDISoldier(BDITroop):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services.append(Service.BACKUP)
        self.eclass = CLASS_SOLDIER
