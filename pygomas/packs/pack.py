import json

from loguru import logger
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour, CyclicBehaviour
from spade.message import Message
from spade.template import Template

from pygomas.agents.agent import AbstractAgent, LONG_RECEIVE_WAIT
from pygomas.ontology import Action, Performative, Belief
from pygomas.utils.vector import Vector3D

PACK_NONE: int = 1000
PACK_MEDICPACK: int = 1001
PACK_AMMOPACK: int = 1002
PACK_OBJPACK: int = 1003

PACK_NAME = {
    PACK_NONE: "NONE",
    PACK_MEDICPACK: "MEDIC",
    PACK_AMMOPACK: "AMMO",
    PACK_OBJPACK: "OBJ",
}

PACK_AUTODESTROY_TIMEOUT: int = 25


class Pack(AbstractAgent, Agent):
    def __str__(self):
        return "P(" + str(PACK_NAME[self.type]) + "," + str(self.position) + ")"

    def __init__(
        self, name, passwd="secret", manager_jid="cmanager@localhost", x=0, z=0, team=0
    ):
        Agent.__init__(self, name, passwd)
        AbstractAgent.__init__(self, name, team)

        self.type = PACK_NONE
        self.manager = manager_jid

        self.position = Vector3D()
        self.position.x = x
        self.position.y = 0
        self.position.z = z

    async def setup(self):
        self.add_behaviour(self.CreatePackBehaviour())

        t = Template()
        t.set_metadata(str(Performative.PERFORMATIVE), str(Belief.PACK_TAKEN))
        self.add_behaviour(self.PackTakenResponderBehaviour(), t)

    class CreatePackBehaviour(OneShotBehaviour):
        async def run(self):
            msg = Message(to=self.agent.manager)
            msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.PACK))
            msg.body = json.dumps(
                {
                    Belief.NAME: self.agent.name,
                    Belief.TEAM: self.agent.team,
                    Action.ACTION: Action.CREATE,
                    Action.TYPE: self.agent.type,
                    Action.X: self.agent.position.x,
                    Action.Y: self.agent.position.y,
                    Action.Z: self.agent.position.z,
                }
            )
            await self.send(msg)
            logger.info("CreatePack msg sent: {}".format(msg))

    class PackTakenResponderBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
            if msg is not None:
                content = msg.body
                await self.agent.perform_pack_taken(content)
                # await self.agent.stop()
