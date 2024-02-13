import random

from loguru import logger
from spade.behaviour import OneShotBehaviour

from pygomas.config import POWER_UNIT
from pygomas.ontology import Service
from pygomas.packs.medicpack import MedicPack
from .bditroop import BDITroop, CLASS_MEDIC


class BDIMedic(BDITroop):
    packs_delivered = 0
    medic_pack_offset = 5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services.append(Service.MEDIC)
        self.eclass = CLASS_MEDIC

    def add_custom_actions(self, actions):
        super().add_custom_actions(actions)

        @actions.add(".cure", 0)
        def _cure(agent, term, intention):
            class CreateMedicPackBehaviour(OneShotBehaviour):
                async def run(self):
                    await self.agent.create_medic_pack()

            b = CreateMedicPackBehaviour()
            self.add_behaviour(b)
            yield

    def perform_medic_action(self):
        # We can give medic paks if we have power enough...
        if self.get_power() >= POWER_UNIT:
            self.use_power()
            return True

        return False

    async def create_medic_pack(self):
        """
        Creates medic packs if possible.

        This method allows to create medic packs if there is enough power in the agent's power bar.

        :returns number of medic packs created
        """
        logger.info("{} Creating medic packs.".format(self.name))
        while self.perform_medic_action():
            BDIMedic.packs_delivered += 1
            name = "medicpack_{}_{}@{}".format(
                self.jid.localpart, BDIMedic.packs_delivered, self.jid.domain
            )
            x = self.movement.position.x + random.random() * BDIMedic.medic_pack_offset
            z = self.movement.position.z + random.random() * BDIMedic.medic_pack_offset

            while not self.check_static_position(x, z):
                x = (
                    self.movement.position.x
                    + random.random() * BDIMedic.medic_pack_offset
                )
                z = (
                    self.movement.position.z
                    + random.random() * BDIMedic.medic_pack_offset
                )

            try:
                pack = MedicPack(
                    name=name, passwd="secret", x=x, z=z, manager_jid=self.manager
                )
                await pack.start()
            except Exception as e:
                logger.warning(
                    "Medic {} could not create MedicPack: {}".format(self.name, e)
                )
