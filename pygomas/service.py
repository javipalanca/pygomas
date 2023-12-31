import json

from loguru import logger
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.template import Template

from pygomas.agents.agent import LONG_RECEIVE_WAIT
from .config import TEAM_NONE, TEAM_ALLIED, TEAM_AXIS
from .ontology import (
    PERFORMATIVE,
    PERFORMATIVE_CFA,
    PERFORMATIVE_CFB,
    PERFORMATIVE_CFM,
    PERFORMATIVE_DEREGISTER_AGENT,
    PERFORMATIVE_DEREGISTER_SERVICE,
    PERFORMATIVE_GET,
    PERFORMATIVE_REGISTER_SERVICE,
    AMMO_SERVICE,
    BACKUP_SERVICE,
    MEDIC_SERVICE,
    NAME,
    TEAM,
)


class Service(Agent):
    def __init__(self, jid="cservice@localhost", password="secret"):
        self.services = {}
        super().__init__(jid=jid, password=password)

    def register_service(self, service_descriptor, jid):
        name = service_descriptor[NAME]
        team = service_descriptor[TEAM]

        if name not in self.services.keys():
            self.services[name] = {TEAM_AXIS: [], TEAM_ALLIED: [], TEAM_NONE: []}

        self.services[name][team].append(jid)
        logger.info("Service {} of team {} registered for {}".format(name, team, jid))

    def deregister_service(self, service_descriptor, jid):
        name = service_descriptor[NAME]
        team = service_descriptor[TEAM]

        if name in self.services.keys() and jid in self.services[name][team]:
            self.services[name][team].remove(jid)
        logger.info("Service {} of team {} deregistered for {}".format(name, team, jid))

    def deregister_agent(self, jid):
        logger.info("Deregistering all services of agent {}".format(jid))
        for name in self.services.keys():
            for team in [TEAM_ALLIED, TEAM_AXIS]:
                if jid in self.services[name][team]:
                    self.services[name][team].remove(jid)
                    logger.info(
                        "Service {} of team {} deregistered for {}".format(
                            name, team, jid
                        )
                    )

    def get_service(self, service_descriptor, questioner):
        logger.debug("get service: {}".format(service_descriptor))
        name = service_descriptor[NAME]
        team = service_descriptor[TEAM]

        if name in self.services.keys():
            logger.debug("I got service")
            request = self.services[name][team][:]
            if questioner in request:
                request.remove(questioner)
            return request
        else:
            logger.debug("No service")
            return []

    async def setup(self):
        template1 = Template()
        template1.set_metadata(PERFORMATIVE, PERFORMATIVE_REGISTER_SERVICE)
        self.add_behaviour(RegisterServiceBehaviour(), template1)

        template2 = Template()
        template2.set_metadata(PERFORMATIVE, PERFORMATIVE_DEREGISTER_SERVICE)
        self.add_behaviour(DeregisterServiceBehaviour(), template2)

        template3 = Template()
        template3.set_metadata(PERFORMATIVE, PERFORMATIVE_DEREGISTER_AGENT)
        self.add_behaviour(DeregisterAgentBehaviour(), template3)

        template4 = Template()
        template4.set_metadata(PERFORMATIVE, PERFORMATIVE_GET)
        self.add_behaviour(GetServiceBehaviour(), template4)


class RegisterServiceBehaviour(CyclicBehaviour):
    async def run(self):
        msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
        if msg:
            logger.info(
                "Register Service {} for {}.".format(msg.body, msg.sender.bare())
            )
            self.agent.register_service(json.loads(msg.body), str(msg.sender.bare()))


class DeregisterServiceBehaviour(CyclicBehaviour):
    async def run(self):
        msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
        if msg:
            logger.info(
                "Deregister Service {} for {}.".format(msg.body, msg.sender.bare())
            )
            self.agent.deregister_service(json.loads(msg.body), str(msg.sender.bare()))


class DeregisterAgentBehaviour(CyclicBehaviour):
    async def run(self):
        msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
        if msg:
            self.agent.deregister_agent(str(msg.sender.bare()))
            logger.info("Agent {} deregistered".format(msg.sender.bare()))


class GetServiceBehaviour(CyclicBehaviour):
    async def run(self):
        msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
        if msg:
            logger.info("Requesting service {}".format(msg.body))
            body = json.loads(msg.body)
            names = self.agent.get_service(body, str(msg.sender).split("/")[0])
            reply = msg.make_reply()
            reply.body = json.dumps(names)
            if body[NAME] == AMMO_SERVICE:
                reply.set_metadata(PERFORMATIVE, PERFORMATIVE_CFA)
            elif body[NAME] == MEDIC_SERVICE:
                reply.set_metadata(PERFORMATIVE, PERFORMATIVE_CFM)
            elif body[NAME] == BACKUP_SERVICE:
                reply.set_metadata(PERFORMATIVE, PERFORMATIVE_CFB)
            else:
                reply.set_metadata(PERFORMATIVE, body[NAME])
            await self.send(reply)
            logger.info("Services sent: {}".format(reply.body))
