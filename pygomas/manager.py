import datetime
import json
import time
import math

from loguru import logger

from spade.behaviour import OneShotBehaviour, PeriodicBehaviour, CyclicBehaviour, TimeoutBehaviour
from spade.message import Message
from spade.template import Template

from .ontology import PERFORMATIVE_GAME, PERFORMATIVE_PACK_TAKEN, PERFORMATIVE_PACK, PERFORMATIVE_SERVICES, \
    PERFORMATIVE_INFORM, PERFORMATIVE_PACK_LOST, PERFORMATIVE_SHOT, PERFORMATIVE_SIGHT, PERFORMATIVE_DATA, \
    MANAGEMENT_SERVICE, PERFORMATIVE_INIT, PERFORMATIVE, NAME, TYPE, TEAM, MAP, X, Y, Z, QTY, ANGLE, DISTANCE, HEALTH, \
    AIM, SHOTS, DEC_HEALTH, VEL_X, VEL_Y, VEL_Z, HEAD_X, HEAD_Y, HEAD_Z, AMMO, PERFORMATIVE_OBJECTIVE
from .stats import GameStatistic
from .mobile import Mobile
from .vector import Vector3D
from .pack import PACK_NAME, PACK_NONE, PACK_OBJPACK, PACK_MEDICPACK, PACK_AMMOPACK
from .agent import AbstractAgent, LONG_RECEIVE_WAIT
from .config import Config
from .service import Service
from .server import Server, TCP_AGL, TCP_COM
from .troop import TEAM_ALLIED, TEAM_AXIS, CLASS_SOLDIER, TEAM_NONE
from .objpack import ObjectivePack
from .map import TerrainMap
from .sight import Sight

MILLISECONDS_IN_A_SECOND: int = 1000

DEFAULT_PACK_QTY: int = 20

ARG_PLAYERS: int = 0
ARG_MAP_NAME: int = 1
ARG_FPS: int = 2
ARG_MATCH_TIME: int = 3
ARG_MAP_PATH: int = 4

WIDTH: int = 3


class MicroAgent:

    def __init__(self, ):
        self.jid = ""
        self.team = TEAM_NONE
        self.locate = Mobile()
        self.is_carrying_objective = False
        self.is_shooting = False
        self.health = 0
        self.ammo = 0
        self.type = 0


class DinObject:
    # index = 0

    def __str__(self):
        return "DO({},{})".format(PACK_NAME[self.type], self.position)

    def __init__(self):
        self.position = Vector3D()
        self.type = PACK_NONE
        self.team = TEAM_NONE
        self.is_taken = False
        self.owner = 0
        # DinObject.index += 1
        # self.jid = DinObject.index
        self.jid = None


class Manager(AbstractAgent):

    def __init__(self,
                 name="cmanager@localhost",
                 passwd="secret",
                 players=10,
                 fps=0.033,
                 #fps=1,
                 match_time=380,
                 path=None,
                 map_name="map_01",
                 service_jid="cservice@localhost"):

        super().__init__(name, passwd, service_jid=service_jid)
        self.game_statistic = GameStatistic()
        self.max_total_agents = players
        self.fps = fps
        self.match_time = match_time
        self.map_name = str(map_name)
        self.config = Config()
        if path is not None:
            self.config.set_data_path(path)
        self.number_of_agents = 0
        self.agents = {}
        self.match_init = 0
        self.domain = name.split('@')[1]
        self.objective_agent = None
        self.service_agent = Service(self.service_jid)
        self.render_server = Server(self.map_name)
        self.din_objects = dict()
        self.map = TerrainMap()

    def stop(self, timeout=5):
        self.objective_agent.stop()
        super().stop(timeout=timeout)

    # def start(self, auto_register=True):
    async def setup(self):
        class InitBehaviour(OneShotBehaviour):
            async def run(self):
                logger.success("Manager (Expected Agents): {}".format(self.agent.max_total_agents))

                for i in range(1, self.agent.max_total_agents + 1):
                    msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                    if msg:
                        content = json.loads(msg.body)

                        name = content[NAME]
                        type_ = content[TYPE]
                        team = content[TEAM]

                        self.agent.agents[name] = MicroAgent()

                        self.agent.agents[name].jid = name
                        self.agent.agents[name].type = type_
                        self.agent.agents[name].team = team

                        logger.success("Manager: [" + name + "] is Ready!")
                        self.agent.number_of_agents += 1

                logger.success("Manager (Accepted Agents): " + str(self.agent.number_of_agents))
                for agent in self.agent.agents.values():
                    msg = Message()
                    msg.set_metadata(PERFORMATIVE, PERFORMATIVE_INIT)
                    msg.to = agent.jid
                    msg.body = json.dumps({MAP: self.agent.map_name})
                    await self.send(msg)
                    logger.success("Manager: Sending notification to fight to: " + agent.jid)

                await self.agent.inform_objectives(self)
                self.agent.match_init = time.time()

        logger.success("pyGOMAS v. 0.1 (c) GTI-IA 2005 - 2019 (DSIC / UPV)")
        import spade
        logger.success(spade.__version__)
        # manager_future = super().start(auto_register=auto_register)

        # Manager notify its services in a different way
        coro = self.service_agent.start(auto_register=True)
        await coro

        self.register_service(MANAGEMENT_SERVICE)

        self.render_server.start()

        self.map.load_map(self.map_name, self.config)

        # Behaviour to listen to data (position, health?, an so on) from troop agents
        self.launch_data_from_troop_listener_behaviour()

        # Behaviour to handle Sight messages
        self.launch_sight_responder_behaviour()

        # Behaviour to handle Shot messages
        self.launch_shot_responder_behaviour()

        # Behaviour to attend the petitions for register services
        # self.launch_service_register_responder_behaviour()

        # Behaviour to handle Pack Management: Creation and Destruction
        self.launch_pack_management_responder_behaviour()

        # Behaviour to inform all agents that game has finished by time
        self.launch_game_timeout_inform_behaviour()

        template = Template()
        template.set_metadata(PERFORMATIVE, PERFORMATIVE_INIT)
        self.add_behaviour(InitBehaviour(), template)

        await self.create_objectives()  # We need to do this when online

        # // Behaviour to refresh all render engines connected
        self.launch_render_engine_inform_behaviour()

    # Behaviour to refresh all render engines connected
    def launch_render_engine_inform_behaviour(self):

        class InformRenderEngineBehaviour(PeriodicBehaviour):
            async def run(self):
                try:
                    if self.agent.render_server and self.agent.render_server.get_connections() is not {}:

                        msg = "" + str(self.agent.number_of_agents) + " "
                        for agent in self.agent.agents.values():
                            msg += agent.jid.split("@")[0] + " "
                            msg += str(agent.type) + " "
                            msg += str(agent.team) + " "

                            msg += str(agent.health) + " "
                            msg += str(agent.ammo) + " "
                            if agent.is_carrying_objective:
                                msg += str(1)
                            else:
                                msg += str(0)

                            msg += " (" + str(agent.locate.position.x) + ", "
                            msg += str(agent.locate.position.y) + ", "
                            msg += str(agent.locate.position.z) + ") "

                            msg += "(" + str(agent.locate.velocity.x) + ", "
                            msg += str(agent.locate.velocity.y) + ", "
                            msg += str(agent.locate.velocity.z) + ") "

                            msg += "(" + str(agent.locate.heading.x) + ", "
                            msg += str(agent.locate.heading.y) + ", "
                            msg += str(agent.locate.heading.z) + ") "

                        msg += str(len(self.agent.din_objects)) + " "

                        for din_object in self.agent.din_objects.values():
                            msg += str(din_object.jid) + " "
                            msg += str(din_object.type) + " "
                            msg += " (" + str(din_object.position.x) + ", "
                            msg += str(din_object.position.y) + ", "
                            msg += str(din_object.position.z) + ") "

                        for task in self.agent.render_server.get_connections():
                            self.agent.render_server.send_msg_to_render_engine(task, TCP_AGL, msg)
                        # logger.info("msg to render engine: {}".format(msg))
                except:
                    pass

        self.add_behaviour(InformRenderEngineBehaviour(self.fps))

    # Behaviour to listen to data (position, health?, an so on) from troop agents
    def launch_data_from_troop_listener_behaviour(self):
        class DataFromTroopBehaviour(CyclicBehaviour):
            async def on_start(self):
                self.counter = 0

            async def run(self):
                self.counter += 1
                # logger.error("INIT BEHAV [{}]".format(self.counter))
                #buffer = {}
                #for _ in range(self.agent.max_total_agents + 1):
                #   msg = await self.receive(timeout=0)
                #   if msg:
                #       buffer[msg.sender] = msg
                #   else:
                #       break
                msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                # logger.error("POST RECEIVE [{}]".format(self.counter))
                if self.mailbox_size() > 0:
                    logger.error("TOO MUCH PENDING MSG: {}".format(self.mailbox_size()))
                #for msg in buffer.values():
                if msg:
                    content = json.loads(msg.body)
                    id_agent = content[NAME]
                    self.agent.agents[id_agent].locate.position.x = float(content[X])
                    self.agent.agents[id_agent].locate.position.y = float(content[Y])
                    self.agent.agents[id_agent].locate.position.z = float(content[Z])

                    self.agent.agents[id_agent].locate.velocity.x = float(content[VEL_X])
                    self.agent.agents[id_agent].locate.velocity.y = float(content[VEL_Y])
                    self.agent.agents[id_agent].locate.velocity.z = float(content[VEL_Z])

                    self.agent.agents[id_agent].locate.heading.x = float(content[HEAD_X])
                    self.agent.agents[id_agent].locate.heading.y = float(content[HEAD_Y])
                    self.agent.agents[id_agent].locate.heading.z = float(content[HEAD_Z])

                    self.agent.agents[id_agent].health = int(content[HEALTH])
                    self.agent.agents[id_agent].ammo = int(content[AMMO])
                    # logger.error("PRE CHECK OBJECTS [{}] {}".format(self.counter, msg.sender))
                    await self.agent.check_objects_at_step(id_agent, self)
                    # logger.error("POST CHECK OBJECTS [{}] {}".format(self.counter, msg.sender))
                    if self.agent.check_game_finished(id_agent):
                        self.agent.inform_game_finished("ALLIED", self)
                        logger.success("\n\nManager:  GAME FINISHED!! Winner Team: ALLIED! (Target Returned)\n")

                # logger.info("[{}] BEHAV FINISHED".format(datetime.datetime.now()))

        template = Template()
        template.set_metadata(PERFORMATIVE, PERFORMATIVE_DATA)

        self.add_behaviour(DataFromTroopBehaviour(), template)

    # Behaviour to handle Sight messages
    def launch_sight_responder_behaviour(self):

        class SightResponderBehaviour(CyclicBehaviour):

            async def run(self):
                msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                if msg:
                    content = json.loads(msg.body)
                    name = content[NAME]

                    fov_objects = self.agent.get_objects_in_field_of_view(name)

                    content = []

                    for fov_object in fov_objects:
                        obj = {
                            TEAM: fov_object.team,
                            TYPE: fov_object.type,
                            ANGLE: fov_object.angle,
                            DISTANCE: fov_object.distance,
                            HEALTH: fov_object.health,
                            X: fov_object.position.x,
                            Y: fov_object.position.y,
                            Z: fov_object.position.z
                        }
                        content.append(obj)
                    reply = msg.make_reply()
                    reply.body = json.dumps(content)
                    reply.set_metadata(PERFORMATIVE, PERFORMATIVE_SIGHT)
                    await self.send(reply)

        template = Template()
        template.set_metadata(PERFORMATIVE, PERFORMATIVE_SIGHT)
        self.add_behaviour(SightResponderBehaviour(), template)

    # Behaviour to handle Shot messages
    def launch_shot_responder_behaviour(self):
        class ShotResponderBehaviour(CyclicBehaviour):
            async def run(self):
                msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                if msg:
                    content = json.loads(msg.body)

                    jid = content[NAME]
                    aim = int(content[AIM])
                    shots = int(content[SHOTS])

                    shooter_id = 0
                    for agent in self.agent.agents.values():
                        if agent.jid == jid:
                            shooter_id = agent.jid
                            break
                    if shooter_id == 0:
                        return

                    # Statistics
                    if self.agent.agents[shooter_id].team == TEAM_ALLIED:
                        team = TEAM_ALLIED
                    else:
                        team = TEAM_AXIS
                    self.agent.game_statistic.team_statistic[team].total_shots += 1

                    victim = self.agent.shot(jid)
                    if victim is None:
                        # Statistics
                        self.agent.game_statistic.team_statistic[team].failed_shots += 1
                        return

                    # Statistics
                    if self.agent.agents[shooter_id].team == victim.team:
                        self.agent.game_statistic.team_statistic[team].team_hit_shots += 1
                    else:
                        self.agent.game_statistic.team_statistic[team].enemy_hit_shots += 1

                    damage = 2
                    if self.agent.agents[shooter_id].type == CLASS_SOLDIER:
                        damage = 3

                    msg_shot = Message(to=victim.jid)
                    msg_shot.set_metadata(PERFORMATIVE, PERFORMATIVE_SHOT)

                    msg_shot.body = json.dumps({DEC_HEALTH: damage})
                    await self.send(msg_shot)

                    self.agent.agents[victim.jid].health -= damage
                    if self.agent.agents[victim.jid].health <= 0:
                        self.agent.agents[victim.jid].health = 0
                        logger.info("Agent", str(self.agent.agents[victim.jid].jid), "died")

                        if self.agent.agents[victim.jid].is_carrying_objective:
                            self.agent.agents[victim.jid].is_carrying_objective = False
                            logger.info("Agent", str(self.agent.agents[victim.jid].jid), "lost the ObjectivePack")

                            for din_object in self.agent.din_objects.values():

                                if din_object.type == PACK_OBJPACK:
                                    # is this necessary?: din_object.taken = False;
                                    din_object.owner = 0
                                    msg_pack = Message(to=din_object.jid)
                                    msg_pack.set_metadata(PERFORMATIVE, PERFORMATIVE_PACK_LOST)
                                    din_object.position.x = self.agent.agents[victim.jid].locate.position.x
                                    din_object.position.y = self.agent.agents[victim.jid].locate.position.y
                                    din_object.position.z = self.agent.agents[victim.jid].locate.position.z
                                    msg_pack.body = json.loads({
                                        X: self.agent.agents[victim.jid].locate.position.x,
                                        Y: self.agent.agents[victim.jid].locate.position.y,
                                        Z: self.agent.agents[victim.jid].locate.position.z})
                                    await self.send(msg_pack)

                                    # Statistics
                                    self.agent.game_statistic.team_statistic[0].total_objective_lost += 1

        template = Template()
        template.set_metadata(PERFORMATIVE, PERFORMATIVE_SHOT)
        self.add_behaviour(ShotResponderBehaviour(), template)

    # Ya no es necesario
    # Behaviour to attend the petitions for register services
    def launch_service_register_responder_behaviour(self):
        class ServiceRegisterResponderBehaviour(CyclicBehaviour):
            async def run(self):
                msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                if msg:
                    content = msg.body
                    self.agent.registry.register_service(content, False)

                    reply = msg.make_reply()
                    reply.body = " "
                    reply.set_metadata(PERFORMATIVE, PERFORMATIVE_INFORM)
                    await self.send(reply)

        template = Template()
        template.set_metadata(PERFORMATIVE, PERFORMATIVE_SERVICES)
        self.add_behaviour(ServiceRegisterResponderBehaviour(), template)

    # Behaviour to handle Pack Management: Creation and Destruction
    def launch_pack_management_responder_behaviour(self):

        class PackManagementResponderBehaviour(CyclicBehaviour):
            async def run(self):
                msg = await self.receive(LONG_RECEIVE_WAIT)
                if msg:
                    content = msg.body
                    tokens = content.split()

                    id_ = tokens[1]
                    action = tokens[2]

                    if action.upper() == "DESTROY":
                        # Statistics
                        din_object = self.agent.din_objects[id_]
                        if din_object.team == TEAM_ALLIED:
                            pack_team = TEAM_ALLIED
                        else:
                            pack_team = TEAM_AXIS
                        pack_type = -1
                        if din_object.type == PACK_MEDICPACK:
                            pack_type = PACK_MEDICPACK
                        elif din_object.type == PACK_AMMOPACK:
                            pack_type = PACK_AMMOPACK
                        if pack_type >= 0:
                            self.agent.game_statistic.team_statistic[pack_team].packs[pack_type].not_taken += 1
                        try:
                            del self.agent.din_objects[id_]
                            logger.info("Pack removed")
                        except:
                            logger.info("Pack", str(id_), "cannot be erased")
                        return

                    if action.upper() == "CREATE":

                        index = tokens.index("TYPE:")  # // Get "TYPE:"
                        type_ = int(tokens[index + 1])

                        index = tokens.index("TEAM:")  # // Get "TEAM:"
                        team = int(tokens[index + 1])

                        x = float(tokens[index + 3])  # skip "("
                        y = float(tokens[index + 5])  # skip ","
                        z = float(tokens[index + 7])  # skip ","

                        din_object = DinObject()
                        din_object.jid = msg.sender
                        din_object.type = type_
                        din_object.team = team
                        din_object.position.x = x
                        din_object.position.y = y
                        din_object.position.z = z

                        self.agent.din_objects[din_object.jid] = din_object
                        logger.info("Added DinObject", str(din_object))

                        # reply = msg.make_reply()
                        # reply.body = "ID: " + str(din_object.jid) + " "
                        # await self.send(reply)
                        # logger.info("CREATE sending: {}".format(reply))

                        # /Statistics
                        if team == TEAM_ALLIED:
                            pack_team = TEAM_ALLIED
                        else:
                            pack_team = TEAM_AXIS
                        pack_type = -1
                        if din_object.type == PACK_MEDICPACK:
                            pack_type = PACK_MEDICPACK
                        elif din_object.type == PACK_AMMOPACK:
                            pack_type = PACK_AMMOPACK

                        if pack_type >= 0:
                            self.agent.game_statistic.team_statistic[pack_team].packs[pack_type].delivered += 1

                    else:
                        logger.warning("Action not identified: " + str(action))
                        return

        template = Template()
        template.set_metadata(PERFORMATIVE, PERFORMATIVE_PACK)
        self.add_behaviour(PackManagementResponderBehaviour(), template)

    # Behaviour to inform all agents that game has finished by time
    def launch_game_timeout_inform_behaviour(self):
        class GameTimeoutInformBehaviour(TimeoutBehaviour):
            async def run(self):
                logger.success("\n\nManager:  GAME FINISHED!! Winner Team: AXIS! (Time Expired)\n")
                await self.agent.inform_game_finished("AXIS!", self)

        timeout = datetime.datetime.now() + datetime.timedelta(seconds=self.match_time)
        self.add_behaviour(GameTimeoutInformBehaviour(start_at=timeout))

    async def check_objects_at_step(self, id_agent, behaviour):

        if len(self.din_objects) <= 0:
            return

        if self.agents[id_agent].health <= 0:
            return

        xmin = self.agents[id_agent].locate.position.x - WIDTH
        zmin = self.agents[id_agent].locate.position.z - WIDTH
        xmax = self.agents[id_agent].locate.position.x + WIDTH
        zmax = self.agents[id_agent].locate.position.z + WIDTH

        for din_object in self.din_objects.values():
            if din_object.type == PACK_MEDICPACK and self.agents[id_agent].health >= 100:
                continue
            if din_object.type == PACK_AMMOPACK and self.agents[id_agent].ammo >= 100:
                continue
            if din_object.type == PACK_OBJPACK and din_object.is_taken and din_object.owner > 0:
                continue

            if xmin <= din_object.position.x <= xmax and zmin <= din_object.position.z <= zmax:

                # Agent has stepped on pack
                send = False
                id_ = din_object.jid
                type_ = din_object.type
                owner = str(din_object.jid)
                content = ""

                # Statistics
                team = self.agents[id_agent].team
                if din_object.team == TEAM_ALLIED:
                    pack_team = TEAM_ALLIED
                else:
                    pack_team = TEAM_AXIS

                if din_object.type == PACK_MEDICPACK:
                    # Statistics
                    if din_object.team == team:
                        self.game_statistic.team_statistic[pack_team].packs[PACK_MEDICPACK].team_taken += 1
                    else:
                        self.game_statistic.team_statistic[pack_team].packs[PACK_MEDICPACK].enemy_taken += 1

                    quantity = DEFAULT_PACK_QTY
                    try:
                        del self.din_objects[id_]
                        logger.info(self.agents[id_agent].jid + ": got a medic pack " + str(din_object.jid))
                        content = {TYPE: type_, QTY: quantity}
                        send = True

                    except:
                        logger.error("Could not delete the din object {}".format(id_))

                elif din_object.type == PACK_AMMOPACK:
                    # Statistics
                    if din_object.team == team:
                        self.game_statistic.team_statistic[pack_team].packs[PACK_AMMOPACK].team_taken += 1
                    else:
                        self.game_statistic.team_statistic[pack_team].packs[PACK_AMMOPACK].enemy_taken += 1

                    quantity = DEFAULT_PACK_QTY
                    try:
                        del self.din_objects[id_]
                        logger.info(self.agents[id_agent].jid + ": got an ammo pack " + str(din_object.jid))
                        content = {TYPE: type_, QTY: quantity}
                        send = True
                    except:
                        logger.error("Could not delete the din object {}".format(id_))

                elif din_object.type == PACK_OBJPACK:

                    if self.agents[id_agent].team == TEAM_ALLIED:
                        logger.info(self.agents[id_agent].jid + ": got the objective pack " + str(din_object.jid))
                        din_object.is_taken = True
                        din_object.owner = id_agent
                        din_object.position.x = din_object.position.y = din_object.position.z = 0.0
                        self.agents[id_agent].is_carrying_objective = True
                        content = {TYPE: type_, QTY: 0, TEAM: "ALLIED"}
                        send = True

                        # Statistics
                        self.game_statistic.team_statistic[TEAM_ALLIED].total_objective_taken += 1
                        self.game_statistic.team_statistic[TEAM_AXIS].total_objective_lost += 1

                    elif self.agents[id_agent].team == TEAM_AXIS:
                        if din_object.is_taken:
                            logger.info(f"{self.agents[id_agent].jid}: returned the objective pack {din_object.jid}")
                            din_object.is_taken = False
                            din_object.owner = 0
                            din_object.position.x = self.map.get_target_x()
                            din_object.position.y = self.map.get_target_y()
                            din_object.position.z = self.map.get_target_z()
                            content = {TYPE: type_, QTY: 0, TEAM: "AXIS"}
                            send = True

                            # Statistics
                            self.game_statistic.team_statistic[TEAM_AXIS].total_objective_taken += 1
                else:
                    content = {TYPE: PACK_NONE, QTY: 0}

                # // Send a destroy/taken msg to pack and an inform msg to agent
                if send:
                    content = json.dumps(content)
                    msg = Message(to=owner)
                    msg.set_metadata(PERFORMATIVE, PERFORMATIVE_PACK_TAKEN)
                    msg.body = content
                    await behaviour.send(msg)

                    msg = Message(to=self.agents[id_agent].jid)
                    msg.set_metadata(PERFORMATIVE, PERFORMATIVE_PACK_TAKEN)
                    msg.body = content
                    await behaviour.send(msg)

    def get_objects_in_field_of_view(self, id_agent):

        objects_in_sight = list()
        agent = None

        for a in self.agents.values():
            if a.jid == id_agent:
                agent = a

        if agent is None:
            return objects_in_sight

        dot_angle = float(agent.locate.angle)

        # am I watching agents?
        for a in self.agents.values():
            if a.jid == id_agent:
                continue
            if a.health <= 0:  # OJO, igual interesa ke veamos muertos :D
                continue

            v = Vector3D(v=a.locate.position)
            v.sub(agent.locate.position)

            distance = v.length()

            # check distance
            # get distance to the closest wall
            distance_terrain = self.intersect(agent.locate.position, v)  # a.locate.heading)

            # check distance
            if distance < agent.locate.view_radius and distance < distance_terrain:

                # check angle
                angle = agent.locate.heading.dot(v)
                try:
                    angle /= agent.locate.heading.length() * v.length()
                except ZeroDivisionError:
                    pass

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
                distance_terrain = self.intersect(agent.locate.position, v)  # a.locate.heading)

                if distance < agent.locate.view_radius and distance < distance_terrain:

                    angle = agent.locate.heading.dot(v)
                    angle /= (agent.locate.heading.length() * v.length())
                    if angle >= 0:
                        angle = min(1, angle)
                        angle = math.acos(angle)
                        if angle <= dot_angle:
                            s = Sight()
                            s.distance = distance
                            s.m_id = int(din_object.jid)
                            s.position = din_object.position
                            s.team = din_object.team
                            s.type = din_object.type
                            s.angle = angle
                            s.health = -1
                            objects_in_sight.append(s)

        return objects_in_sight

    def shot(self, id_agent):
        """
        Agent with id id_agent shots
        :param id_agent: agent who shots
        :return: agent shot or None
        """
        victim = None
        min_distance = 1e10  # big number

        agent = None

        for a in self.agents.values():
            if a.jid == id_agent:
                agent = a
                break

        if agent is None:
            return None

        # agents
        for a in self.agents.values():
            if a.jid == id_agent:
                continue

            if a.health <= 0:
                continue

            position = Vector3D(v=agent.locate.position)

            position.sub(a.locate.position)

            dv = position.dot(agent.locate.heading)
            d2 = agent.locate.heading.dot(agent.locate.heading)
            sq = (dv * dv) - ((d2 * position.dot(position)) - 4)

            if sq >= 0:

                sq = math.sqrt(sq)
                dist1 = (-dv + sq) / d2
                dist2 = (-dv - sq) / d2
                if dist1 < dist2:
                    distance = dist1
                else:
                    distance = dist2

                if 0 < distance < min_distance:
                    min_distance = distance
                    victim = a

        if victim is not None:
            v = Vector3D(v=victim.locate.position)
            v.sub(agent.locate.position)
            distance_terrain = self.intersect(agent.locate.position, agent.locate.heading)
            # logger.info "distanceTerrain: " + str(distance_terrain)
            if distance_terrain != 0.0 and distance_terrain < min_distance:
                victim = None

        return victim

    def intersect(self, origin, vector):
        """
        :param origin:
        :param vector:
        :return: 0.0 if it does not intersect
        """

        try:
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

                if not self.map.can_walk(int(math.floor(point.x / 8)), int(math.floor(point.z / 8))):
                    return error.length()

                if point.x < 0 or point.y < 0 or point.z < 0:
                    break
                if point.x >= (self.map.get_size_x() * 8) or point.z >= (self.map.get_size_z() * 8):
                    break
                error.add(step)
        except:
            logger.error("INTERSECT FAILED", origin, vector)

        return 0.0

    def check_game_finished(self, id_agent):

        if self.agents[id_agent].team == TEAM_AXIS:
            return False
        if not self.agents[id_agent].is_carrying_objective:
            return False

        if self.map.allied_base.init.x < self.agents[id_agent].locate.position.x < self.map.allied_base.end.x and \
                self.map.allied_base.init.z < self.agents[id_agent].locate.position.z < self.map.allied_base.end.z:
            return True
        return False

    async def create_objectives(self):

        self.objective_agent = ObjectivePack(name="objectivepack@" + self.domain, passwd="secret",
                                             manager_jid=str(self.jid),
                                             x=self.map.get_target_x() / 8,
                                             z=self.map.get_target_z() / 8, team=TEAM_NONE)
        await self.objective_agent.start()

    async def inform_objectives(self, behaviour):

        msg = Message()
        msg.set_metadata(PERFORMATIVE, PERFORMATIVE_OBJECTIVE)
        content = {X: self.map.get_target_x(), Y: self.map.get_target_y(), Z: self.map.get_target_z()}
        msg.body = json.dumps(content)
        for agent in self.agents.values():
            msg.to = agent.jid
            logger.info("Sending objective to {}: {}".format(agent.jid, msg))
            await behaviour.send(msg)
        logger.info("Manager: Sending Objective notification to agents")

    async def inform_game_finished(self, winner_team, behaviour):

        msg = Message()
        msg.set_metadata(PERFORMATIVE, PERFORMATIVE_GAME)
        msg.body = "GAME FINISHED!! Winner Team: " + str(winner_team)
        for agent in self.agents.values():
            msg.to = agent.name
            await behaviour.send(msg)
        for st in self.render_server.get_connections():
            try:
                st.send_msg_to_render_engine(TCP_COM, "FINISH " + " GAME FINISHED!! Winner Team: " + str(winner_team))
            except:
                pass

        self.print_statistics(winner_team)

        del self.render_server
        self.render_server = None
        self.stop()

    def print_statistics(self, winner_team):

        allied_alive_players = 0
        axis_alive_players = 0
        allied_health = 0
        axis_health = 0

        self.game_statistic.match_duration = time.time() * MILLISECONDS_IN_A_SECOND
        self.game_statistic.match_duration -= self.match_init

        for agent in self.agents.values():
            if agent.team == TEAM_ALLIED:
                allied_health += agent.health
                if agent.health > 0:
                    allied_alive_players = allied_alive_players + 1
            else:
                axis_health += agent.health
                if agent.health > 0:
                    axis_alive_players = axis_alive_players + 1

        self.game_statistic.calculate_data(allied_alive_players, axis_alive_players, allied_health, axis_health)

        try:
            fw = open("JGOMAS_Statistics.txt", 'w+')

            fw.write(self.game_statistic.__str__(winner_team))

            fw.close()

        except:
            logger.error("COULD NOT WRITE STATISTICS TO FILE")
