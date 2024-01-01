import random

from loguru import logger
from spade.behaviour import OneShotBehaviour

from pygomas.config import POWER_UNIT
from pygomas.ontology import Service
from pygomas.packs.ammopack import AmmoPack
from .bditroop import BDITroop, CLASS_FIELDOPS


class BDIFieldOp(BDITroop):
    packs_delivered = 0
    ammo_pack_offset = 5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.services.append(Service.AMMO)
        self.eclass = CLASS_FIELDOPS

    def add_custom_actions(self, actions):
        super().add_custom_actions(actions)

        @actions.add(".reload", 0)
        def _cure(agent, term, intention):
            class CreateAmmoPackBehaviour(OneShotBehaviour):
                async def run(self):
                    await self.agent.create_ammo_pack()

            b = CreateAmmoPackBehaviour()
            self.add_behaviour(b)
            yield

    def perform_ammo_action(self):
        # We can give ammo paks if we have power enough...
        if self.get_power() >= POWER_UNIT:
            self.use_power()
            return True
        return False

    async def create_ammo_pack(self):
        """
        Creates ammo packs if possible.

        This method allows to create ammo packs if there is enough power in the agent's power bar.

        :returns number of ammo packs created
        """

        logger.info("{} Creating ammo packs.".format(self.name))
        while self.perform_ammo_action():
            BDIFieldOp.packs_delivered += 1
            name = "ammopack_{}_{}@{}".format(
                self.jid.localpart, BDIFieldOp.packs_delivered, self.jid.domain
            )
            x = self.movement.position.x + random.random() * BDIFieldOp.ammo_pack_offset
            z = self.movement.position.z + random.random() * BDIFieldOp.ammo_pack_offset

            while not self.check_static_position(x, z):
                x = (
                    self.movement.position.x
                    + random.random() * BDIFieldOp.ammo_pack_offset
                )
                z = (
                    self.movement.position.z
                    + random.random() * BDIFieldOp.ammo_pack_offset
                )

            try:
                pack = AmmoPack(
                    name=name, passwd="secret", x=x, z=z, manager_jid=self.manager
                )
                await pack.start()
            except Exception as e:
                logger.warning(
                    "FieldOps {} could not create AmmoPack: {}".format(self.name, e)
                )

            logger.info("AmmoPack {} created.".format(name))
