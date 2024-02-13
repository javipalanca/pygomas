import asyncio
import datetime
import json
import math
import random
import time
import traceback

import spade
from loguru import logger
from spade.agent import Agent
from spade.behaviour import (
    OneShotBehaviour,
    PeriodicBehaviour,
    CyclicBehaviour,
    TimeoutBehaviour,
)
from spade.message import Message
from spade.template import Template

from pygomas.agents.agent import AbstractAgent, LONG_RECEIVE_WAIT
from pygomas.agents.bditroop import CLASS_SOLDIER
from pygomas.agents.service import ServiceAgent
from pygomas.packs.objpack import ObjectivePack
from pygomas.packs.pack import PACK_NAME, PACK_NONE, PACK_OBJPACK, PACK_MEDICPACK, PACK_AMMOPACK
from pygomas.utils.mobile import Mobile
from pygomas.utils.sight import Sight
from pygomas.utils.vector import Vector3D
from . import __version__
from .config import (
    Config,
    MIN_HEALTH,
    TEAM_NONE,
    TEAM_ALLIED,
    TEAM_AXIS,
    MISSING_SHOT_PROBABILITY,
)
from .map import TerrainMap
from .ontology import Action, Belief, Performative, Service as ServiceOnto
from .server import Server, TCP, Msg
from .stats import GameStatistic

MILLISECONDS_IN_A_SECOND: int = 1000

DEFAULT_PACK_QTY: int = 20

ARG_PLAYERS: int = 0
ARG_MAP_NAME: int = 1
ARG_FPS: int = 2
ARG_MATCH_TIME: int = 3
ARG_MAP_PATH: int = 4

WIDTH: int = 3


class MicroAgent:
    def __init__(self):
        self.jid = ""
        self.team = TEAM_NONE
        self.locate = Mobile()
        self.is_carrying_objective = False
        self.is_shooting = False
        self.health = 0
        self.ammo = 0
        self.type = 0
        self.is_updated = False

    def __str__(self):
        return "<{} Team({}) Health({}) Ammo({}) Obj({})>".format(
            self.jid, self.team, self.health, self.ammo, self.is_carrying_objective
        )


class DinObject:
    def __str__(self):
        return "DO({},{})".format(PACK_NAME[self.type], self.position)

    def __init__(self):
        self.position = Vector3D()
        self.type = PACK_NONE
        self.team = TEAM_NONE
        self.is_taken = False
        self.owner = 0
        self.jid = None


class Manager(AbstractAgent, Agent):
    def __init__(
            self,
            name="cmanager@localhost",
            passwd="secret",
            players=10,
            fps=33,
            match_time=380,
            map_name="map_01",
            map_path=None,
            service_jid="cservice@localhost",
            service_passwd="secret",
            port=8001,
    ):

        AbstractAgent.__init__(self, name, service_jid=service_jid)
        Agent.__init__(self, name, passwd)

        self.game_statistic = GameStatistic()
        self.max_total_agents = players
        self.fps = 1 / fps
        self.match_time = match_time
        self.map_name = str(map_name)
        self.port = port
        self.config = Config(data_path=map_path)
        self.number_of_agents = 0
        self.agents = {}
        self.match_init = 0
        self.domain = name.split("@")[1]
        self.objective_agent = None
        self.service_agent = ServiceAgent(jid=self.service_jid, password=service_passwd)
        self.render_server = Server(map_name=self.map_name, port=self.port)
        self.din_objects = dict()
        self.map = TerrainMap()

    async def stop(self):
        del self.render_server
        self.render_server = None
        coro1 = self.objective_agent.stop()
        coro2 = self.service_agent.stop()
        coro3 = super().stop()
        await asyncio.gather(coro1, coro2, coro3)

    async def setup(self):
        class InitBehaviour(OneShotBehaviour):
            async def run(self):
                logger.success(
                    "Manager (Expected Agents): {}".format(self.agent.max_total_agents)
                )

                # for i in range(1, self.agent.max_total_agents + 1):
                while self.agent.number_of_agents < self.agent.max_total_agents:
                    msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                    if msg:
                        content = json.loads(msg.body)

                        name = content[Belief.NAME]
                        type_ = content[Action.TYPE]
                        team = content[Belief.TEAM]

                        self.agent.agents[name] = MicroAgent()
                        self.agent.agents[name].jid = name
                        self.agent.agents[name].type = int(type_)
                        self.agent.agents[name].team = int(team)
                        self.agent.agents[name].health = 100

                        logger.success("Manager: [" + name + "] is Ready!")
                        self.agent.number_of_agents += 1
                    else:
                        logger.warning("Manager: Still waiting for agents...")
                logger.success(
                    "Manager (Accepted Agents): " + str(self.agent.number_of_agents)
                )
                for agent in self.agent.agents.values():
                    msg = Message()
                    msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.INIT))
                    msg.to = agent.jid
                    msg.body = json.dumps({Action.MAP: self.agent.map_name})
                    await self.send(msg)
                    logger.success(
                        "Manager: Sending notification to fight to: " + agent.jid
                    )

                await self.agent.inform_objectives(self)
                self.agent.match_init = time.time()

                # Behaviour to check if all alied troops are alive
                self.agent.launch_check_allied_health()

                # Behaviour to refresh all render engines connected
                self.agent.launch_render_engine_inform_behaviour()

        logger.success(
            "pygomas {} (c) VRAIN 2005-{} (VRAIN/UPV)".format(
                __version__, time.strftime("%Y")
            )
        )
        logger.success("Powered by SPADE {}".format(spade.__version__))

        template = Template()
        template.set_metadata(str(Performative.PERFORMATIVE), str(Performative.INIT))
        self.add_behaviour(InitBehaviour(), template)

        await self.service_agent.start(auto_register=True)
        self.register_service(ServiceOnto.MANAGEMENT)

        await self.render_server.start()
        self.map.load_map(self.map_name, self.config)

        # Behaviour to listen to data (position, health?, and so on) from troop agents
        self.launch_data_from_troop_listener_behaviour()

        # Behaviour to handle Shot messages
        self.launch_shoot_responder_behaviour()

        # Behaviour to handle Pack Management: Creation and Destruction
        self.launch_pack_management_responder_behaviour()

        # Behaviour to inform all agents that game has finished by time
        self.launch_game_timeout_inform_behaviour()

        await self.create_objectives()  # We need to do this when online

        class RecvAllBehaviour(CyclicBehaviour):
            async def run(self):
                msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                if msg:
                    logger.info("Manager: Received message: {}".format(msg))
        #self.add_behaviour(RecvAllBehaviour())


    # Behaviour to refresh all render engines connected
    def launch_render_engine_inform_behaviour(self):
        class InformRenderEngineBehaviour(PeriodicBehaviour):
            async def run(self):
                if (
                        self.agent.render_server
                        and len(self.agent.render_server.get_connections()) != 0
                        and all([[a.is_updated for a in self.agent.agents.values()]])
                        and len(self.agent.agents) == self.agent.number_of_agents
                ):

                    msg = {
                        Msg.AGENTS: [
                            {
                                Msg.CONTENT_NAME: agent.jid.split("@")[0],
                                Msg.CONTENT_TYPE: agent.type,
                                Msg.CONTENT_TEAM: agent.team,
                                Msg.CONTENT_HEALTH: agent.health,
                                Msg.CONTENT_AMMO: agent.ammo,
                                Msg.CONTENT_CARRYINGFLAG: agent.is_carrying_objective,
                                Msg.CONTENT_POSITION: [
                                    agent.locate.position.x,
                                    agent.locate.position.y,
                                    agent.locate.position.z,
                                ],
                                Msg.CONTENT_VELOCITY: [
                                    agent.locate.velocity.x,
                                    agent.locate.velocity.y,
                                    agent.locate.velocity.z,
                                ],
                                Msg.CONTENT_HEADING: [
                                    agent.locate.heading.x,
                                    agent.locate.heading.y,
                                    agent.locate.heading.z,
                                ],
                            }
                            for agent in self.agent.agents.values()  # if agent.is_updated
                        ],
                        Msg.PACKS: [
                            {
                                Msg.CONTENT_NAME: pack.render_id,
                                Msg.CONTENT_TYPE: pack.type,
                                Msg.CONTENT_POSITION: [
                                    pack.position.x,
                                    pack.position.y,
                                    pack.position.z,
                                ],
                            }
                            for pack in self.agent.din_objects.values()
                            if not pack.is_taken
                        ],
                    }

                    for task in self.agent.render_server.get_connections():
                        if self.agent.render_server.is_ready(task):
                            self.agent.render_server.send_msg_to_render_engine(
                                task, TCP.AGL, msg
                            )

        self.add_behaviour(InformRenderEngineBehaviour(self.fps))
        logger.debug("InformRenderEngineBehaviour started.")

    # Behaviour to listen to data (position, health?, and so on) from troop agents
    def launch_data_from_troop_listener_behaviour(self):
        class DataFromTroopBehaviour(CyclicBehaviour):
            async def run(self):
                msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                if self.mailbox_size() > self.agent.max_total_agents + 1:
                    logger.error("TOO MUCH PENDING MSG: {}".format(self.mailbox_size()))
                try:
                    if msg:
                        content = json.loads(msg.body)
                        id_agent = content[Belief.NAME]

                        self.agent.agents[id_agent].locate.position.x = int(content[Action.X])
                        self.agent.agents[id_agent].locate.position.y = int(content[Action.Y])
                        self.agent.agents[id_agent].locate.position.z = int(content[Action.Z])
                        self.agent.agents[id_agent].is_updated = True

                        self.agent.agents[id_agent].locate.velocity.x = float(
                            content[Action.VEL_X]
                        )
                        self.agent.agents[id_agent].locate.velocity.y = float(
                            content[Action.VEL_Y]
                        )
                        self.agent.agents[id_agent].locate.velocity.z = float(
                            content[Action.VEL_Z]
                        )

                        self.agent.agents[id_agent].locate.heading.x = float(
                            content[Action.HEAD_X]
                        )
                        self.agent.agents[id_agent].locate.heading.y = float(
                            content[Action.HEAD_Y]
                        )
                        self.agent.agents[id_agent].locate.heading.z = float(
                            content[Action.HEAD_Z]
                        )

                        self.agent.agents[id_agent].health = int(content[Belief.HEALTH])
                        self.agent.agents[id_agent].ammo = int(content[Belief.AMMO])

                        packs = await self.agent.check_objects_at_step(
                            id_agent, behaviour=self
                        )
                        fov_objects = self.agent.look(id_agent)
                        content = {Action.PACKS: packs, Action.FOV: fov_objects}
                        msg = Message(to=id_agent)
                        msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.DATA))
                        msg.body = json.dumps(content)

                        await self.send(msg)
                        if self.agent.check_game_finished(id_agent):
                            await self.agent.inform_game_finished("ALLIED", self)
                            logger.success(
                                "\n\nManager:  GAME FINISHED!! Winner Team: ALLIED! (Target Returned)\n"
                            )
                except Exception as e:
                    logger.warning("Exception at DataFromTroopBehaviour: {}".format(e))
                    logger.warning(traceback.format_exc())

        template = Template()
        template.set_metadata(str(Performative.PERFORMATIVE), str(Performative.DATA))

        self.add_behaviour(DataFromTroopBehaviour(), template)

    # Behaviour to handle Shot messages
    def launch_shoot_responder_behaviour(self):
        class ShootResponderBehaviour(CyclicBehaviour):
            async def run(self):
                msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                if msg:
                    content = json.loads(msg.body)
                    shooter_id = content[Belief.NAME]
                    aim = int(content[Action.AIM])
                    shots = int(content[Action.SHOTS])
                    victim_pos = Vector3D(x=content[Action.X], y=content[Action.Y], z=content[Action.Z])
                    try:
                        shooter = self.agent.agents[shooter_id]
                    except KeyError:
                        return

                    victim = self.agent.shoot(shooter_id, victim_pos)
                    self.agent.game_statistic.shoot(victim, shooter.team)

                    if victim is None:
                        return

                    damage = 2 if shooter.type == CLASS_SOLDIER else 1
                    damage *= max(0, shots)
                    victim.health -= damage
                    logger.info("Victim hit: {}".format(victim))

                    if victim.health <= 0:
                        victim.health = 0
                        logger.info("Agent {} died.".format(victim.jid))

                        if victim.is_carrying_objective:
                            victim.is_carrying_objective = False
                            logger.info(
                                "Agent {} lost the ObjectivePack.".format(victim.jid)
                            )

                            for din_object in self.agent.din_objects.values():

                                if din_object.type == PACK_OBJPACK:
                                    din_object.is_taken = False
                                    din_object.owner = 0
                                    msg_pack = Message(to=str(din_object.jid))
                                    msg_pack.set_metadata(
                                        Performative.PERFORMATIVE, Performative.PACK_LOST
                                    )
                                    din_object.position.x = victim.locate.position.x
                                    din_object.position.y = victim.locate.position.y
                                    din_object.position.z = victim.locate.position.z
                                    msg_pack.body = json.dumps(
                                        {
                                            Action.X: victim.locate.position.x,
                                            Action.Y: victim.locate.position.y,
                                            Action.Z: victim.locate.position.z,
                                        }
                                    )
                                    await self.send(msg_pack)

                                    # Statistics
                                    self.agent.game_statistic.objective_lost(
                                        victim.team
                                    )
                                    break

                    msg_shot = Message(to=victim.jid)
                    msg_shot.set_metadata(str(Performative.PERFORMATIVE), str(Performative.SHOOT))
                    msg_shot.body = json.dumps({Action.DEC_HEALTH: damage})
                    await self.send(msg_shot)

        template = Template()
        template.set_metadata(str(Performative.PERFORMATIVE), str(Performative.SHOOT))
        self.add_behaviour(ShootResponderBehaviour(), template)

    # Behaviour to handle Pack Management: Creation and Destruction
    def launch_pack_management_responder_behaviour(self):
        class PackManagementResponderBehaviour(CyclicBehaviour):
            async def run(self):
                msg = await self.receive(LONG_RECEIVE_WAIT)
                if msg:
                    content = json.loads(msg.body)

                    id_ = content[Belief.NAME]
                    action = content[Action.ACTION]

                    if action == Action.DESTROY:
                        self.agent.game_statistic.pack_destroyed(
                            self.agent.din_objects[id_]
                        )

                        try:
                            del self.agent.din_objects[id_]
                            logger.info("Pack removed")
                        except KeyError:
                            logger.info("Pack {} cannot be erased".format(id_))
                        return

                    if action == Action.CREATE:
                        type_ = int(content[Action.TYPE])
                        team = int(content[Belief.TEAM])

                        x = float(content[Action.X])
                        y = float(content[Action.Y])
                        z = float(content[Action.Z])

                        din_object = DinObject()
                        din_object.jid = msg.sender
                        din_object.type = type_
                        if din_object.type == PACK_OBJPACK:
                            din_object.render_id = 1
                        else:
                            din_object.render_id = abs(hash(din_object.jid)) % 1024
                        din_object.team = team
                        din_object.position.x = x
                        din_object.position.y = y
                        din_object.position.z = z

                        self.agent.din_objects[din_object.jid] = din_object
                        logger.info("Added DinObject {}".format(din_object))

                        self.agent.game_statistic.pack_created(din_object, team)

                    else:
                        logger.warning("Action not identified: {}".format(action))
                        return

        template = Template()
        template.set_metadata(str(Performative.PERFORMATIVE), str(Performative.PACK))
        self.add_behaviour(PackManagementResponderBehaviour(), template)

    # Behaviour to inform all agents that game has finished by time
    def launch_game_timeout_inform_behaviour(self):
        class GameTimeoutInformBehaviour(TimeoutBehaviour):
            async def run(self):
                logger.success(
                    "\n\nManager:  GAME FINISHED!! Winner Team: AXIS! (Time Expired)\n"
                )
                await self.agent.inform_game_finished("AXIS!", self)

        timeout = datetime.datetime.now() + datetime.timedelta(seconds=self.match_time)
        self.add_behaviour(GameTimeoutInformBehaviour(start_at=timeout))

    # Behaviour to inform all agents that game has finished because all allied troops died
    def launch_check_allied_health(self):
        class CheckAlliedHealthBehaviour(PeriodicBehaviour):
            async def run(self):
                allied_alive = False
                for agent in self.agent.agents.values():
                    if agent.team == TEAM_AXIS:
                        continue
                    if agent.health > 0:
                        allied_alive = True
                        break
                if not allied_alive:
                    logger.success("\n\nManager:  GAME FINISHED!! Winner Team: AXIS!\n")
                    await self.agent.inform_game_finished("AXIS!", self)

        self.add_behaviour(CheckAlliedHealthBehaviour(20 * self.fps))

    async def check_objects_at_step(self, id_agent, behaviour):

        if len(self.din_objects) <= 0:
            return

        if self.agents[id_agent].health <= 0:
            return

        xmin = self.agents[id_agent].locate.position.x - WIDTH
        zmin = self.agents[id_agent].locate.position.z - WIDTH
        xmax = self.agents[id_agent].locate.position.x + WIDTH
        zmax = self.agents[id_agent].locate.position.z + WIDTH

        packs = []

        keys = list(self.din_objects.keys())
        for key in keys:
            if key not in self.din_objects:
                continue
            din_object = self.din_objects[key]
            if (
                    din_object.type == PACK_MEDICPACK
                    and self.agents[id_agent].health >= 100
            ):
                continue
            if din_object.type == PACK_AMMOPACK and self.agents[id_agent].ammo >= 100:
                continue
            if (
                    din_object.type == PACK_OBJPACK
                    and din_object.is_taken
                    and din_object.owner != 0
            ):
                continue

            if (
                    xmin <= din_object.position.x <= xmax
                    and zmin <= din_object.position.z <= zmax
            ):
                # Agent has stepped on pack
                id_ = din_object.jid
                type_ = din_object.type
                owner = str(din_object.jid)
                content = None

                team = self.agents[id_agent].team
                self.game_statistic.pack_taken(din_object, team)

                if din_object.type == PACK_MEDICPACK:
                    quantity = DEFAULT_PACK_QTY
                    try:
                        del self.din_objects[id_]
                        logger.info(
                            self.agents[id_agent].jid
                            + ": got a medic pack "
                            + str(din_object.jid)
                        )
                        content = {Action.TYPE: type_, Action.QTY: quantity}

                    except KeyError:
                        logger.error("Could not delete the din object {}".format(id_))

                elif din_object.type == PACK_AMMOPACK:
                    quantity = DEFAULT_PACK_QTY
                    try:
                        del self.din_objects[id_]
                        logger.info(
                            self.agents[id_agent].jid
                            + ": got an ammo pack "
                            + str(din_object.jid)
                        )
                        content = {Action.TYPE: type_, Action.QTY: quantity}
                    except KeyError:
                        logger.error("Could not delete the din object {}".format(id_))

                elif din_object.type == PACK_OBJPACK:
                    if team == TEAM_ALLIED:
                        logger.info(
                            "{}: got the objective pack ".format(
                                self.agents[id_agent].jid
                            )
                        )
                        din_object.is_taken = True
                        din_object.owner = id_agent
                        (
                            din_object.position.x,
                            din_object.position.y,
                            din_object.position.z,
                        ) = (0.0, 0.0, 0.0)
                        self.agents[id_agent].is_carrying_objective = True
                        content = {Action.TYPE: type_, Action.QTY: 0, Belief.TEAM: TEAM_ALLIED}

                    elif team == TEAM_AXIS:
                        if din_object.is_taken:
                            logger.info(
                                f"{self.agents[id_agent].jid}: returned the objective pack {din_object.jid}"
                            )
                            din_object.is_taken = False
                            din_object.owner = 0
                            din_object.position.x = self.map.get_target_x()
                            din_object.position.y = self.map.get_target_y()
                            din_object.position.z = self.map.get_target_z()
                            content = {Action.TYPE: type_, Action.QTY: 0, Belief.TEAM: TEAM_AXIS}

                # // Send a destroy/taken msg to pack and an inform msg to agent
                if content:
                    content = json.dumps(content)
                    msg = Message(to=owner)
                    msg.set_metadata(str(Performative.PERFORMATIVE), str(Belief.PACK_TAKEN))
                    msg.body = content
                    await behaviour.send(msg)
                    packs.append(content)
        return packs

    def look(self, name):
        fov_objects = self.get_objects_in_field_of_view(name)
        content = []
        for fov_object in fov_objects:
            obj = {
                Belief.TEAM: fov_object.team,
                Action.TYPE: fov_object.type,
                Action.ANGLE: fov_object.angle,
                Action.DISTANCE: fov_object.distance,
                Belief.HEALTH: fov_object.health,
                Action.X: fov_object.position.x,
                Action.Y: fov_object.position.y,
                Action.Z: fov_object.position.z,
            }
            content.append(obj)
        return content

    def get_objects_in_field_of_view(self, id_agent):
        objects_in_sight = list()
        agent = None

        # for k, a in self.agents.items():
        #    if a.jid == id_agent:
        #        agent = a
        #        break
        agent = self.agents[id_agent]

        if agent is None or agent.locate.heading.length() == 0:
            return objects_in_sight

        dot_angle = float(agent.locate.angle)

        # am I watching agents?
        for a in self.agents.values():
            if a.jid == id_agent:
                continue
            if (
                    a.health <= MIN_HEALTH
            ):  # WARNING, we may be interested in seeing dead agents
                continue

            v = Vector3D(v=a.locate.position)
            v.sub(agent.locate.position)

            distance = v.length()

            # check distance
            # get distance to the closest wall
            distance_terrain = self.intersect_with_walls(
                agent.locate.position, v
            )  # a.locate.heading)

            # check distance
            if distance < agent.locate.view_radius and distance < distance_terrain:

                # check angle
                angle = agent.locate.heading.dot(v)
                try:
                    angle /= agent.locate.heading.length() * v.length()
                except ZeroDivisionError:
                    angle = 0

                if angle >= 0:
                    angle = min(1, angle)
                    angle = math.acos(angle)
                    if angle <= dot_angle:
                        s = Sight()
                        s.distance = distance
                        s.m_id = a.jid
                        s.position = a.locate.position
                        s.team = a.team
                        s.type = a.type
                        s.angle = angle
                        s.health = a.health
                        objects_in_sight.append(s)

        # am I watching objects?
        if len(self.din_objects) > 0:

            for din_object in self.din_objects.values():

                v = Vector3D(v=din_object.position)
                v.sub(agent.locate.position)

                distance = v.length()

                # check distance
                # get distance to the closest wall
                distance_terrain = self.intersect_with_walls(
                    agent.locate.position, v
                )  # a.locate.heading)

                if distance < agent.locate.view_radius and distance < distance_terrain:

                    angle = agent.locate.heading.dot(v)
                    try:
                        angle /= agent.locate.heading.length() * v.length()
                    except ZeroDivisionError:
                        angle = 0

                    if angle >= 0:
                        angle = min(1, angle)
                        angle = math.acos(angle)
                        if angle <= dot_angle:
                            s = Sight()
                            s.distance = distance
                            s.m_id = din_object.jid
                            s.position = din_object.position
                            s.team = din_object.team
                            s.type = din_object.type
                            s.angle = angle
                            s.health = -1
                            objects_in_sight.append(s)

        return objects_in_sight

    def shoot(self, shooter_agent_id, victim_position):
        """
        Agent with id id_agent shoots
        :param shooter_agent_id: agent who shoots
        :param victim_position: the coordinates of the victim to be shot
        :return: agent shot or None
        """
        victim = None
        min_distance = 1e10

        if random.random() <= MISSING_SHOT_PROBABILITY:
            return None

        try:
            shooter_agent = Mobile()
            shooter_agent.position = self.agents[shooter_agent_id].locate.position
            shooter_agent.destination = Vector3D(victim_position)
            shooter_agent.calculate_new_orientation(shooter_agent.destination)
        except KeyError:
            return None

        victim, min_distance = self._check_agents_in_row(
            shooter_agent_id, shooter_agent, victim, min_distance
        )

        if victim is not None:
            shooter_agent.destination = victim.locate.position
            shooter_agent.calculate_new_orientation(shooter_agent.destination)
            distance_to_obstacle = self.intersect_with_walls(
                shooter_agent.position, shooter_agent.heading, min_distance
            )
            if distance_to_obstacle != 0.0 and distance_to_obstacle < min_distance:
                victim = None

        return victim

    def _check_agents_in_row(
            self, shooter_agent_id, shooter_agent, victim, min_distance
    ):
        for agent in self.agents.values():
            if agent.jid == shooter_agent_id:
                continue
            if agent.health <= 0:
                continue

            shooter_position = Vector3D(shooter_agent.position)
            shooter_position.sub(agent.locate.position)

            dv = shooter_position.dot(shooter_agent.heading)
            d2 = shooter_agent.heading.dot(shooter_agent.heading)
            sq = (dv * dv) - ((d2 * shooter_position.dot(shooter_position)) - 4)

            if sq >= 0 and d2 != 0:
                sq = math.sqrt(sq)
                dist1 = (-dv + sq) / d2
                dist2 = (-dv - sq) / d2
                distance = dist1 if dist1 < dist2 else dist2

                if 0 < distance < min_distance:
                    min_distance = distance
                    victim = agent
        return victim, min_distance

    def intersect_with_walls(self, origin, vector, distance=1e10):
        """
        :param origin:
        :param vector:
        :param distance:
        :return: 0.0 if it does not intersect
        """

        try:

            if vector.length() == 0:
                return 0.0

            step = Vector3D(v=vector)
            step.normalize()
            inc = 0
            sgn = 1.0
            e = 0.0

            if abs(step.x) > abs(step.z):

                if step.z < 0:
                    sgn = -1

                step.x /= abs(step.x)
                step.z /= abs(step.x)
            else:

                if step.x < 0:
                    sgn = -1

                inc = 1
                step.x /= abs(step.z)
                step.z /= abs(step.z)

            error = Vector3D(x=0, y=0, z=0)
            point = Vector3D(v=origin)

            while True:

                if inc == 0:

                    if e + abs(step.z) + 0.5 >= 1:
                        point.z += sgn
                        e -= 1

                    e += abs(step.z)
                    point.x += step.x
                else:

                    if e + abs(step.x) + 0.5 >= 1:
                        point.x += sgn
                        e -= 1

                    e += abs(step.x)
                    point.z += step.z

                if not self.map.can_walk(
                        int(math.floor(point.x)), int(math.floor(point.z))
                ):
                    return error.length()

                if point.x < 0 or point.y < 0 or point.z < 0:
                    break
                if point.x >= (self.map.get_size_x()) or point.z >= (
                        self.map.get_size_z()
                ):
                    break
                error.add(step)
                if error.length() > distance:
                    return error.length()
        except Exception as e:
            logger.error(
                "INTERSECT FAILED: (origin: {}) (vector: {}): {}".format(
                    origin, vector, e
                )
            )

        return 0.0

    def check_game_finished(self, id_agent):
        if self.agents[id_agent].team == TEAM_AXIS:
            return False
        if not self.agents[id_agent].is_carrying_objective:
            return False

        if (
                self.map.allied_base.init.x
                < self.agents[id_agent].locate.position.x
                < self.map.allied_base.end.x
                and self.map.allied_base.init.z
                < self.agents[id_agent].locate.position.z
                < self.map.allied_base.end.z
        ):
            return True
        return False

    async def create_objectives(self):

        jid = "objectivepack@" + self.domain
        self.objective_agent = ObjectivePack(
            name=jid,
            passwd="secret",
            manager_jid=str(self.jid),
            x=self.map.get_target_x(),
            z=self.map.get_target_z(),
            team=TEAM_NONE,
        )
        await self.objective_agent.start()

    async def inform_objectives(self, behaviour):

        msg = Message()
        msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.OBJECTIVE))
        content = {
            Action.X: self.map.get_target_x(),
            Action.Y: self.map.get_target_y(),
            Action.Z: self.map.get_target_z(),
        }
        msg.body = json.dumps(content)
        for agent in self.agents.values():
            msg.to = agent.jid
            logger.info("Sending objective to {}: {}".format(agent.jid, msg))
            await behaviour.send(msg)
        logger.info("Manager: Sending Objective notification to agents")

    async def inform_game_finished(self, winner_team, behaviour):

        for agent in self.agents.values():
            msg = Message()
            msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.GAME))
            msg.body = "GAME FINISHED!! Winner Team: " + str(winner_team)
            msg.to = agent.jid
            await behaviour.send(msg)
        for st in self.render_server.get_connections():
            try:
                # st.send_msg_to_render_engine(TCP_COM, "FINISH " + " GAME FINISHED!! Winner Team: " + str(winner_team))
                st.send_msg_to_render_engine(TCP.COM, Msg.QUIT)
            except:
                pass

        self.print_statistics(winner_team)

        await self.stop()

    def print_statistics(self, winner_team):

        allied_alive_players = 0
        axis_alive_players = 0
        allied_health = 0
        axis_health = 0

        self.game_statistic.match_duration = time.time() - self.match_init
        logger.info("Match took {} seconds".format(self.game_statistic.match_duration))

        for agent in self.agents.values():
            if agent.team == TEAM_ALLIED:
                allied_health += agent.health
                if agent.health > 0:
                    allied_alive_players = allied_alive_players + 1
            else:
                axis_health += agent.health
                if agent.health > 0:
                    axis_alive_players = axis_alive_players + 1

        self.game_statistic.calculate_data(
            allied_alive_players, axis_alive_players, allied_health, axis_health
        )

        try:
            fw = open("pygomas_stats.txt", "w+")

            fw.write(self.game_statistic.dumps(winner_team))

            fw.close()

        except Exception as e:
            logger.exception("COULD NOT WRITE STATISTICS TO FILE: {}".format(e))
