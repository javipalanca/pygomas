import json
import random
from collections import deque

import agentspeak as asp
from loguru import logger
from numpy import arctan2, cos, sin
from spade.behaviour import OneShotBehaviour, PeriodicBehaviour, CyclicBehaviour
from spade.message import Message
from spade.template import Template
from spade_bdi.bdi import BDIAgent

from pygomas.algorithms.jps import JPSAlgorithm
from pygomas.config import (
    Config,
    MIN_POWER,
    POWER_UNIT,
    MIN_STAMINA,
    STAMINA_UNIT,
    MIN_AMMO,
    TEAM_NONE,
    TEAM_ALLIED,
    TEAM_AXIS,
    INTERVAL_TO_MOVE,
)
from pygomas.map import TerrainMap
from pygomas.ontology import Action, Belief, Performative, Service
from pygomas.packs.pack import PACK_MEDICPACK, PACK_AMMOPACK, PACK_OBJPACK, PACK_NONE
from pygomas.utils.mobile import Mobile
from pygomas.utils.sight import Sight
from pygomas.utils.threshold import Threshold
from pygomas.utils.vector import Vector3D
from .agent import AbstractAgent, LONG_RECEIVE_WAIT

DEFAULT_RADIUS = 20
ESCAPE_RADIUS = 50

ARG_TEAM = 0

MV_OK = 0
MV_CANNOT_GET_POSITION = 1
MV_ALREADY_IN_DEST = 2


class BDITroop(AbstractAgent, BDIAgent):
    def __init__(
            self,
            jid,
            passwd,
            asl,
            team=TEAM_NONE,
            map_path=None,
            manager_jid="cmanager@localhost",
            service_jid="cservice@localhost",
            velocity_value=3,
            *args,
            **kwargs,
    ):
        AbstractAgent.__init__(self, jid, team=team, service_jid=service_jid)
        BDIAgent.__init__(self, jid=jid, password=passwd, asl=asl, **kwargs)
        self.pause_bdi()

        self.service_types = []

        # Variable used to store the AID of Manager
        self.manager = manager_jid
        self.service = service_jid
        self.map_path = map_path

        # Variable indicating if this agent is carrying the objective pack (flag)
        self.is_objective_carried = False

        # List of objects in the agent's Field Of Vision
        self.fov_objects = []

        # Current aimed enemy
        self.aimed_agent = None  # Sight

        self.eclass = 0
        self.health = 0
        self.protection = 0
        self.stamina = 0
        self.power = 0
        self.ammo = 0

        # Variable indicating if agent is fighting at this moment
        self.is_fighting = False

        # Variable indicating if agent is escaping at this moment
        self.is_escaping = False

        # Current position, direction, and so on...
        self.movement = Mobile()
        self.velocity_value = velocity_value

        self.soldiers_count = 0
        self.medics_count = 0
        self.engineers_count = 0
        self.fieldops_count = 0
        self.team_count = 0

        # Limits of some variables (to trigger some events)
        self.threshold = Threshold()

        # Current Map
        self.map = None  # TerrainMap

        # Destination Queue
        self.destinations = deque()

    def add_custom_actions(self, actions):
        @actions.add_function(".create_control_points", (tuple, float, int))
        def _create_control_points(center, radius, n):
            """
            Calculates an array of positions for patrolling.
            When this action is called, it creates an array of n random positions.
            Expects args to be [x,y,z],radius and number of points
            """

            center_x = int(center[0])
            center_z = int(center[2])
            radius = int(radius)

            possible_positions = []

            for i in range(center_x - radius, center_x + radius):
                for j in range(center_z - radius, center_z + radius):
                    if self.map.can_walk(i, j):
                        possible_positions.append((i, 0, j))

            control_points = random.sample(possible_positions, n)

            logger.info(
                "[{}] Control points: {}".format(self.jid.localpart, control_points)
            )
            return tuple(control_points)

        @actions.add_function(".shuffle", (tuple))
        def _shuffle(a_tuple):
            """
            Randomly shuffle a tuple
            """
            a_list = [i for i in a_tuple]
            random.shuffle(a_list)
            return tuple(a_list)

        @actions.add_function(".random_shift", (tuple))
        def _random_shift(a_tuple):
            """
            Randomly shift a tuple
            """
            rotated = deque(a_tuple)
            rotated.rotate(random.randint(-10, 10))
            return tuple(rotated)

        @actions.add(".goto", 1)
        def _goto(agent, term, intention):
            """Sets the pygomas destination. Expects args to be (x,y,z)"""
            args = asp.grounded(term.args, intention.scope)
            self.movement.destination.x = args[0][0]
            self.movement.destination.y = args[0][1]
            self.movement.destination.z = args[0][2]
            start = (self.movement.position.x, self.movement.position.z)
            end = (self.movement.destination.x, self.movement.destination.z)

            if self.map.can_walk(x=end[0], z=end[1]):
                path = self.path_finder.get_path(start, end)
                if path:
                    logger.info(f"[{self.jid.localpart}] goto: walking to {end} via {path}")
                    self.destinations = deque(path)
                    x, z = path[0]
                    self.movement.calculate_new_orientation(Vector3D(x=x, y=0, z=z))
                    self.bdi.set_belief(
                        Belief.DESTINATION, tuple((args[0][0], args[0][1], args[0][2]))
                    )
                    self.bdi.set_belief(
                        Belief.VELOCITY,
                        tuple(
                            (
                                self.movement.velocity.x,
                                self.movement.velocity.y,
                                self.movement.velocity.z,
                            )
                        ),
                    )
                    self.bdi.set_belief(
                        Belief.HEADING,
                        tuple(
                            (
                                self.movement.heading.x,
                                self.movement.heading.y,
                                self.movement.heading.z,
                            )
                        ),
                    )
                else:
                    self.destinations = deque()
                    self.movement.destination.x = self.movement.position.x
                    self.movement.destination.y = self.movement.position.y
                    self.movement.destination.z = self.movement.position.z
            else:
                logger.warning(f"[{self.jid.localpart}] goto: can't walk to {end}")
            yield

        @actions.add(".shoot", 2)
        def _shoot(agent, term, intention):
            """
            The agent shoots in the direction at which he is aiming.

            This method sends a FIPA INFORM message to Manager.
            Once message is sent, the variable ammo is decremented.

            :param shot_num: number of shots
            :param X,Y,Z: position at which to shoot
            :type shot_num: int
            :type X,Y,Z: list of float
            :returns True (shot done) | False (cannot shoot, has no ammo)
            :rtype bool
            """
            args = asp.grounded(term.args, intention.scope)

            shot_num = args[0]
            victim_x = args[1][0]
            victim_y = args[1][1]
            victim_z = args[1][2]

            class ShootBehaviour(OneShotBehaviour):
                async def run(self):
                    if self.agent.ammo <= MIN_AMMO:
                        return False

                    shots = min(self.agent.threshold.get_shot(), shot_num)
                    # Fill the REQUEST message
                    msg = Message()
                    msg.to = self.agent.manager
                    msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.SHOOT))
                    content = {
                        Belief.NAME: self.agent.name,
                        Action.AIM: self.agent.threshold.get_aim(),
                        Action.SHOTS: shots,
                        Action.X: victim_x,
                        Action.Y: victim_y,
                        Action.Z: victim_z,
                    }
                    logger.info("{} shot!".format(content[Belief.NAME]))
                    msg.body = json.dumps(content)
                    if self.agent.is_alive():
                        await self.send(msg)

                    return True

            b = ShootBehaviour()
            self.add_behaviour(b)
            yield

        @actions.add(".register_service", 1)
        def _register_service(agent, term, intention):
            """Register the service specified by <service>.

            :param service: service to register
            :type service: str

            """
            args = asp.grounded(term.args, intention.scope)
            service = str(args[0])
            self.register_service(service)
            yield

        @actions.add(".get_service", 1)
        def _get_service(agent, term, intention):
            """Request for troop agents that offer the service specified by
            <service>. This action sends a FIPA REQUEST
            message to the service agent asking for those who offer the
            <service> service.

            :param service: service requested
            :type service: str

            """
            args = asp.grounded(term.args, intention.scope)
            service = str(args[0])

            class GetServiceBehaviour(OneShotBehaviour):
                async def run(self):
                    msg = Message()
                    msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.GET))
                    msg.to = self.agent.service_jid
                    msg.body = json.dumps(
                        {Belief.NAME: service, Belief.TEAM: self.agent.team}
                    )
                    if self.agent.is_alive():
                        await self.send(msg)
                    result = await self.receive(timeout=LONG_RECEIVE_WAIT)
                    if result:
                        result = json.loads(result.body)
                        logger.info(
                            "{} got {} troops that offer {} service: {}".format(
                                self.agent.name, len(result), service, result
                            )
                        )
                        self.agent.bdi.set_belief(service, tuple(result))
                    else:
                        self.agent.bdi.set_belief(service, tuple())

            t = Template()
            t.set_metadata(str(Performative.PERFORMATIVE), str(service))
            b = GetServiceBehaviour()
            self.add_behaviour(b, t)
            yield

        @actions.add(".get_medics", 0)
        def _get_medics(agent, term, intention):
            """Request for medic agents. This action sends a FIPA REQUEST
            message to the service agent asking for those who offer the
            Medic service.
            """

            class GetMedicBehaviour(OneShotBehaviour):
                async def run(self):
                    msg = Message()
                    msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.GET))
                    msg.to = self.agent.service_jid
                    msg.body = json.dumps(
                        {Belief.NAME: Service.MEDIC, Belief.TEAM: self.agent.team}
                    )
                    if self.agent.is_alive():
                        await self.send(msg)
                    result = await self.receive(timeout=LONG_RECEIVE_WAIT)
                    if result:
                        result = json.loads(result.body)
                        self.agent.medics_count = len(result)
                        logger.info(
                            "{} got {} medics: {}".format(
                                self.agent.name, self.agent.medics_count, result
                            )
                        )
                        self.agent.bdi.set_belief(Belief.MY_MEDICS, tuple(result))
                    else:
                        self.agent.bdi.set_belief(Belief.MY_MEDICS, tuple())
                        self.agent.medics_count = 0

            t = Template()
            t.set_metadata(str(Performative.PERFORMATIVE), str(Performative.CFM))
            b = GetMedicBehaviour()
            self.add_behaviour(b, t)
            yield

        @actions.add(".get_fieldops", 0)
        def _get_fieldops(agent, term, intention):
            """Request for fieldop agents. This action sends a FIPA REQUEST
            message to the service agent asking for those who offer the
            Ammo service.
            """

            class GetFieldopsBehaviour(OneShotBehaviour):
                async def run(self):
                    msg = Message()
                    msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.GET))
                    msg.to = self.agent.service_jid
                    msg.body = json.dumps(
                        {Belief.NAME: Service.AMMO, Belief.TEAM: self.agent.team}
                    )
                    if self.agent.is_alive():
                        await self.send(msg)
                    result = await self.receive(timeout=LONG_RECEIVE_WAIT)
                    if result:
                        result = json.loads(result.body)
                        self.agent.fieldops_count = len(result)
                        logger.info(
                            "{} got {} fieldops: {}".format(
                                self.agent.name, self.agent.fieldops_count, result
                            )
                        )
                        self.agent.bdi.set_belief(Belief.MY_FIELDOPS, tuple(result))
                    else:
                        self.agent.bdi.set_belief(Belief.MY_FIELDOPS, tuple())
                        self.agent.fieldops_count = 0

            t = Template()
            t.set_metadata(str(Performative.PERFORMATIVE), str(Performative.CFA))
            b = GetFieldopsBehaviour()
            self.add_behaviour(b, t)
            yield

        @actions.add(".get_backups", 0)
        def _get_backups(agent, term, intention):
            """Request for backup agents. This action sends a FIPA REQUEST
            message to the service agent asking for those who offer the
            Backup service.
            """

            class GetBackupBehaviour(OneShotBehaviour):
                async def run(self):
                    msg = Message()
                    msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.GET))
                    msg.to = self.agent.service_jid
                    msg.body = json.dumps(
                        {Belief.NAME: Service.BACKUP, Belief.TEAM: self.agent.team}
                    )
                    if self.agent.is_alive():
                        await self.send(msg)
                    result = await self.receive(timeout=LONG_RECEIVE_WAIT)
                    if result:
                        result = json.loads(result.body)
                        self.agent.soldiers_count = len(result)
                        logger.info(
                            "{} got {} soldiers: {}".format(
                                self.agent.name, self.agent.soldiers_count, result
                            )
                        )
                        self.agent.bdi.set_belief(Belief.MY_BACKUPS, tuple(result))
                    else:
                        self.agent.bdi.set_belief(Belief.MY_BACKUPS, tuple())
                        self.agent.soldiers_count = 0

            t = Template()
            t.set_metadata(str(Performative.PERFORMATIVE), str(Performative.CFB))
            b = GetBackupBehaviour()
            self.add_behaviour(b, t)
            yield

        @actions.add(".look_at", 1)
        def _look_at(agent, term, intention):
            """
            Look at a point.

            :param position: Point to look at.
            :type position: tuple (x,y,z)

            """

            args = asp.grounded(term.args, intention.scope)
            point = args[0]

            point_x = point[0]
            point_z = point[2]

            look_at_z, look_at_x = (
                point_z - self.movement.position.z,
                point_x - self.movement.position.x,
            )

            self.movement.heading = Vector3D(x=look_at_x, y=0, z=look_at_z)
            self.movement.heading.normalize()
            self.bdi.set_belief(
                Belief.HEADING,
                tuple(
                    (
                        self.movement.heading.x,
                        self.movement.heading.y,
                        self.movement.heading.z,
                    )
                ),
            )
            yield

        @actions.add(".turn", 1)
        def _turn(agent, term, intention):
            """
            Turns an agent orientation given an angle.

            :param angle: angle to turn, in radians.
            :type angle: float (from -pi to pi)

            """

            args = asp.grounded(term.args, intention.scope)
            angle = args[0]
            z = self.movement.heading.z
            x = self.movement.heading.x
            if z == 0 and x == 0:
                self.movement.heading.z = random.random()
                self.movement.heading.x = random.random()
            atan_angle = arctan2(z, x)
            atan_angle += angle
            norm = self.movement.heading.length()
            self.movement.heading.x = norm * cos(atan_angle)
            self.movement.heading.z = norm * sin(atan_angle)
            self.bdi.set_belief(
                Belief.HEADING,
                tuple(
                    (
                        self.movement.heading.x,
                        self.movement.heading.y,
                        self.movement.heading.z,
                    )
                ),
            )
            yield

        @actions.add(".stop", 0)
        def _stop(agent, term, intention):
            """Stops the pygomas agent."""
            self.destinations = deque()
            self.movement.destination.x = self.movement.position.x
            self.movement.destination.y = self.movement.position.y
            self.movement.destination.z = self.movement.position.z
            yield

        @actions.add_function(
            ".delete",
            (
                    int,
                    tuple,
            ),
        )
        def _delete(index, tuple_):
            if index == 0:
                return tuple_[1:]
            elif index == len(tuple_) - 1:
                return tuple_[:index]
            else:
                return tuple_[0:index] + tuple_[index + 1:]

        super().add_custom_actions(actions)

    async def start(self, auto_register=True):
        self.protection = 25
        await super().start(auto_register)

    async def setup(self) -> None:
        # Behaviour to get the objective of the game, to create the corresponding task
        t = Template()
        t.set_metadata(str(Performative.PERFORMATIVE), str(Performative.OBJECTIVE))
        self.add_behaviour(self.ObjectiveBehaviour(), t)

        t = Template()
        t.set_metadata(str(Performative.PERFORMATIVE), str(Performative.INIT))
        self.add_behaviour(self.InitResponderBehaviour(), t)

        # Behaviour to listen to manager if game has finished
        t = Template()
        t.set_metadata(str(Performative.PERFORMATIVE), str(Performative.GAME))
        self.add_behaviour(self.GameFinishedBehaviour(), t)

        # Behaviour to handle Shot messages
        t = Template()
        t.set_metadata(str(Performative.PERFORMATIVE), str(Performative.SHOOT))
        self.add_behaviour(self.ShootResponderBehaviour(period=0), t)

        # Behaviour to inform manager our position, status, and so on
        t = Template()
        t.set_metadata(str(Performative.PERFORMATIVE), str(Performative.DATA))
        self.add_behaviour(self.DataFromTroopBehaviour(period=INTERVAL_TO_MOVE), t)

    class InitResponderBehaviour(CyclicBehaviour):
        async def send_manager_handshake(self):
            msg = Message(to=self.agent.manager)
            msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.INIT))
            msg.body = json.dumps(
                {
                    Belief.NAME: self.agent.name,
                    Action.TYPE: str(self.agent.eclass),
                    Belief.TEAM: str(self.agent.team),
                }
            )
            logger.info(f"[{self.agent.name}]:Sending handshake message: {msg}")
            await self.send(msg)

            if self.agent.service_types is not None:
                for service in self.agent.service_types:
                    self.agent.register_service(str(service))
            if self.agent.team == TEAM_ALLIED:
                self.agent.register_service("allied")
            else:
                self.agent.register_service("axis")

        async def run(self):
            agent_registered_in_manager = False
            while not agent_registered_in_manager:
                await self.send_manager_handshake()
                msg = await self.receive(timeout=5)
                if msg:
                    agent_registered_in_manager = True
                    content = json.loads(msg.body)
                    self.agent.health = content[Belief.HEALTH]
                    self.agent.ammo = content[Belief.AMMO]
                    self.agent.stamina = content[Belief.STAMINA]
                    self.agent.power = content[Belief.POWER]
                    logger.info(f"[{self.agent.name}]: Beginning to fight")
                    map_name = content[Action.MAP]
                    self.agent.map = TerrainMap()
                    config = Config(self.agent.map_path)
                    self.agent.map.load_map(map_name, config)
                    # self.agent.path_finder = AAlgorithm(self.agent.map.terrain[:, :, 1])
                    # self.agent.path_finder = JPSAlgorithm(self.agent.map.terrain[:, :, 1])
                    self.agent.path_finder = JPSAlgorithm(
                        self.agent.map.cost_terrain[:, :, 1]
                    )
                    self.agent.movement = Mobile(self.agent.velocity_value)
                    self.agent.movement.set_size(
                        self.agent.map.get_size_x(), self.agent.map.get_size_z()
                    )
                else:
                    logger.warning(f"[{self.agent.name}]: No handshake received. Retrying...")

                self.kill()
                self.agent.resume_bdi()

    # Behaviour to get the objective of the game, to create the corresponding task
    class ObjectiveBehaviour(CyclicBehaviour):
        async def run(self):
            logger.info("{} waiting for objective.".format(self.agent.name))
            msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
            if msg:
                content = json.loads(msg.body)
                if self.agent.bdi_enabled:
                    if self.agent.team == TEAM_ALLIED:
                        x = (((self.agent.map.allied_base.get_end_x()
                               - self.agent.map.allied_base.get_init_x()) / 2) +
                             self.agent.map.allied_base.get_init_x())
                        y = (((self.agent.map.allied_base.get_end_y() -
                               self.agent.map.allied_base.get_init_y()) / 2) +
                             self.agent.map.allied_base.get_init_y())
                        z = (((self.agent.map.allied_base.get_end_z() -
                              self.agent.map.allied_base.get_init_z()) / 2) +
                             self.agent.map.allied_base.get_init_z())
                    elif self.agent.team == TEAM_AXIS:
                        x = (
                                    (
                                            self.agent.map.axis_base.get_end_x()
                                            - self.agent.map.axis_base.get_init_x()
                                    )
                                    / 2
                            ) + self.agent.map.axis_base.get_init_x()
                        y = (
                                    (
                                            self.agent.map.axis_base.get_end_y()
                                            - self.agent.map.axis_base.get_init_y()
                                    )
                                    / 2
                            ) + self.agent.map.axis_base.get_init_y()
                        z = (
                                    (
                                            self.agent.map.axis_base.get_end_z()
                                            - self.agent.map.axis_base.get_init_z()
                                    )
                                    / 2
                            ) + self.agent.map.axis_base.get_init_z()
                    self.agent.bdi.set_belief(Belief.NAME, self.agent.name)
                    self.agent.bdi.set_belief(Belief.TEAM, self.agent.team)
                    self.agent.bdi.set_belief(Belief.CLASS, self.agent.eclass)
                    self.agent.bdi.set_belief(Belief.BASE, tuple((x, y, z)))
                    self.agent.bdi.set_belief(
                        Belief.POSITION,
                        tuple(
                            (
                                self.agent.movement.position.x,
                                self.agent.movement.position.y,
                                self.agent.movement.position.z,
                            )
                        ),
                    )
                    self.agent.bdi.set_belief(Belief.HEALTH, self.agent.health)
                    self.agent.bdi.set_belief(Belief.AMMO, self.agent.ammo)
                    self.agent.bdi.set_belief(
                        Belief.THRESHOLD_HEALTH, self.agent.threshold.health
                    )
                    self.agent.bdi.set_belief(Belief.THRESHOLD_AMMO, self.agent.threshold.ammo)
                    self.agent.bdi.set_belief(Belief.THRESHOLD_AIM, self.agent.threshold.aim)
                    self.agent.bdi.set_belief(
                        Belief.THRESHOLD_SHOTS, self.agent.threshold.shot
                    )
                    self.agent.bdi.set_belief(
                        Belief.FLAG, tuple((content[Action.X], content[Action.Y], content[Action.Z]))
                    )
                logger.info(
                    "Team: {}, agent: {}, has its objective at {}".format(
                        self.agent.team, self.agent.name, content
                    )
                )
                self.kill()

    # Behaviour to listen to manager if game has finished
    class GameFinishedBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
            if msg:
                logger.info("[" + self.agent.name + "]: Bye!")
                await self.agent.die()
                self.kill()

    # Behaviour to handle Shot messages
    class ShootResponderBehaviour(PeriodicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
            if msg:
                content = json.loads(msg.body)
                health_to_decrease = int(content[Action.DEC_HEALTH])
                # self.agent.health_to_decrease(health_to_decrease)
                logger.info(
                    "Agent {} has been hit by a shot! Loses {} health points ({}).".format(
                        self.agent.name, health_to_decrease, self.agent.health
                    )
                )

                self.agent.perform_injury_action()

    # Behaviour to get from pygomas Manager our position, status, and so on
    class DataFromTroopBehaviour(PeriodicBehaviour):
        async def run(self):
            try:
                if not self.agent.movement:
                    logger.debug(f"[{self.agent.name}]: No movement object")
                    self.agent.movement = Mobile()
                if len(self.agent.destinations) > 0:
                    dest_x, dest_z = self.agent.destinations[0]
                else:
                    dest_x, dest_z = self.agent.movement.position.x, self.agent.movement.position.z
                content = {
                    Belief.NAME: self.agent.name,
                    Action.DEST_X: dest_x,
                    Action.DEST_Y: 0,
                    Action.DEST_Z: dest_z,
                    Action.VEL_X: self.agent.movement.velocity.x,
                    Action.VEL_Y: self.agent.movement.velocity.y,
                    Action.VEL_Z: self.agent.movement.velocity.z,
                    Action.HEAD_X: self.agent.movement.heading.x,
                    Action.HEAD_Y: self.agent.movement.heading.y,
                    Action.HEAD_Z: self.agent.movement.heading.z,
                }
                msg = Message(to=self.agent.manager)
                msg.set_metadata(str(Performative.PERFORMATIVE), str(Performative.DATA))
                msg.body = json.dumps(content)

                if self.agent.is_alive():
                    await self.send(msg)

                info = await self.receive(LONG_RECEIVE_WAIT)
                if info is None:
                    return
                info = json.loads(info.body)

                self.agent.movement.position.x = float(info[Action.X])
                self.agent.movement.position.y = float(info[Action.Y])
                self.agent.movement.position.z = float(info[Action.Z])
                self.agent.bdi.set_belief(
                    Belief.POSITION,
                    tuple(
                        (
                            self.agent.movement.position.x,
                            self.agent.movement.position.y,
                            self.agent.movement.position.z,
                        )
                    ),
                )
                self.agent.movement.velocity.x = float(info[Action.VEL_X])
                self.agent.movement.velocity.y = float(info[Action.VEL_Y])
                self.agent.movement.velocity.z = float(info[Action.VEL_Z])
                self.agent.bdi.set_belief(
                    Belief.VELOCITY,
                    tuple(
                        (
                            self.agent.movement.velocity.x,
                            self.agent.movement.velocity.y,
                            self.agent.movement.velocity.z,
                        )
                    ),
                )

                self.agent.movement.heading.x = float(info[Action.HEAD_X])
                self.agent.movement.heading.y = float(info[Action.HEAD_Y])
                self.agent.movement.heading.z = float(info[Action.HEAD_Z])
                self.agent.bdi.set_belief(
                    Belief.HEADING,
                    tuple(
                        (
                            self.agent.movement.heading.x,
                            self.agent.movement.heading.y,
                            self.agent.movement.heading.z,
                        )
                    ),
                )

                self.agent.update_destination()

                self.agent.health = int(info[Belief.HEALTH])
                if self.agent.health <= 0:
                    await self.pass_away()

                self.agent.bdi.set_belief(Belief.HEALTH, self.agent.health)
                self.agent.ammo = int(info[Belief.AMMO])
                self.agent.bdi.set_belief(Belief.AMMO, self.agent.ammo)

                packs = info[Action.PACKS] if info[Action.PACKS] is not None else []
                for pack in packs:
                    pack = json.loads(pack)
                    quantity = pack[Action.QTY]
                    type_ = pack[Action.TYPE]
                    self.agent.pack_taken(pack_type=type_, quantity=quantity)

                self.agent.fov_objects = []
                fovs = info[Action.FOV] if info[Action.FOV] is not None else []
                if len(fovs) <= 0:
                    self.agent.aimed_agent = None
                else:
                    for idx, obj in enumerate(fovs):
                        s = Sight()
                        s.sight_id = idx
                        s.team = int(obj[Belief.TEAM])
                        s.type = int(obj[Action.TYPE])
                        s.angle = float(obj[Action.ANGLE])
                        s.distance = float(obj[Action.DISTANCE])
                        s.health = int(obj[Belief.HEALTH])
                        s.position.x = float(obj[Action.X])
                        s.position.y = float(obj[Action.Y])
                        s.position.z = float(obj[Action.Z])
                        self.agent.fov_objects.append(s)
                        if s.team == TEAM_NONE:
                            self.agent.bdi.set_belief(
                                Belief.PACKS_IN_FOV,
                                idx,
                                int(obj[Action.TYPE]),
                                float(obj[Action.ANGLE]),
                                float(obj[Action.DISTANCE]),
                                int(obj[Belief.HEALTH]),
                                tuple((float(obj[Action.X]), float(obj[Action.Y]), float(obj[Action.Z]))),
                            )
                        elif s.team == self.agent.team:
                            self.agent.bdi.set_belief(
                                Belief.FRIENDS_IN_FOV,
                                idx,
                                int(obj[Action.TYPE]),
                                float(obj[Action.ANGLE]),
                                float(obj[Action.DISTANCE]),
                                int(obj[Belief.HEALTH]),
                                tuple((float(obj[Action.X]), float(obj[Action.Y]), float(obj[Action.Z]))),
                            )
                        else:
                            self.agent.bdi.set_belief(
                                Belief.ENEMIES_IN_FOV,
                                idx,
                                int(obj[Action.TYPE]),
                                float(obj[Action.ANGLE]),
                                float(obj[Action.DISTANCE]),
                                int(obj[Belief.HEALTH]),
                                tuple((float(obj[Action.X]), float(obj[Action.Y]), float(obj[Action.Z]))),
                            )

            except ZeroDivisionError:
                pass

        async def pass_away(self):
            logger.success(self.agent.name + ": DEAD!!")
            if self.agent.is_objective_carried:
                self.agent.bdi.remove_belief(Belief.FLAG_TAKEN)
                self.agent.is_objective_carried = False
                logger.info(
                    "Agent {} loses the objective.".format(self.agent.name)
                )
            await self.agent.die()

    def update_destination(self):
        # Check if there are any destinations left
        if len(self.destinations) > 0:
            # Check if the agent's current position matches the first destination in the queue
            if (self.movement.position.x == self.destinations[0][0] and
                    self.movement.position.z == self.destinations[0][1]):
                logger.info(f"{self.jid.localpart} reached destination {self.destinations[0]}")

                # If it matches, remove the first destination from the queue
                x, z = self.destinations.popleft()

                # If there are no more destinations left, set the belief that the target has been reached
                if len(self.destinations) == 0:
                    self.bdi.set_belief(
                        Belief.TARGET_REACHED,
                        tuple(
                            (
                                self.movement.destination.x,
                                self.movement.destination.y,
                                self.movement.destination.z,
                            )
                        ),
                    )
                # If there are still destinations left, get the next destination
                else:
                    x, z = self.destinations[0]
                # Update the agent's orientation to face the next destination
                self.compare_orientation(x, z)
        else:
            # logger.info(f"{self.jid.localpart} has no more destinations")
            pass

    def compare_orientation(self, x, z):
        last_velocity = Vector3D(self.movement.velocity)
        last_heading = Vector3D(self.movement.heading)
        self.movement.calculate_new_orientation(Vector3D(x=x, y=0, z=z))
        if last_velocity != self.movement.velocity:
            self.bdi.set_belief(
                Belief.VELOCITY,
                tuple(
                    (
                        self.movement.velocity.x,
                        self.movement.velocity.y,
                        self.movement.velocity.z,
                    )
                ),
            )
        if last_heading != self.movement.heading:
            self.bdi.set_belief(
                Belief.HEADING,
                tuple(
                    (
                        self.movement.heading.x,
                        self.movement.heading.y,
                        self.movement.heading.z,
                    )
                ),
            )

    def pack_taken(self, pack_type, quantity):
        if pack_type == PACK_MEDICPACK:
            self.bdi.set_belief(Belief.PACK_TAKEN, Service.MEDIC, quantity)
        elif pack_type == PACK_AMMOPACK:
            self.bdi.set_belief(Belief.PACK_TAKEN, Service.AMMO, quantity)
        elif pack_type == PACK_OBJPACK and self.team == TEAM_ALLIED:
            self.is_objective_carried = True
            self.bdi.set_belief(Belief.FLAG_TAKEN)

    def get_health(self):
        """
        Get the current health of the agent.

        :returns current value for health
        :rtype int
        """
        return self.health

    def get_ammo(self):
        """
        Get the current ammunition of the agent.

        :returns: current value for ammo
        """
        return self.ammo

    def get_stamina(self):
        """
        Get the current stamina of the agent.

        :returns: current value for stamina bar
        """
        return self.stamina

    def use_stamina(self):
        """
        Use stamina from the stamina bar if possible (there is at least 5 units).
        """
        self.stamina -= STAMINA_UNIT
        if self.stamina <= MIN_STAMINA:
            self.stamina = MIN_STAMINA

    def get_power(self):
        """
        Get the current power of the agent.

        :returns: current value for power bar
        """
        return self.power

    def use_power(self):
        """
        Use power from the power bar if possible (there is at least 25 units).

        Power bar is reduced in 25 units.
        """
        self.power -= POWER_UNIT
        if self.power <= MIN_POWER:
            self.power = MIN_POWER

    def add_service_type(self, service_list):
        """
        Adds a type of service to the service type list.

        This method registers all types of services to offer in a list, excluding repeated services.

        :param service_list
        """

        if not self.service_types:
            self.service_types = []

        if service_list.lower() not in self.service_types:
            self.service_types.append(service_list.lower())

    def perform_aim_action(self):
        """
        Action to do when agent has an enemy at sight.

        This method is called when agent has looked and has found an enemy,
        calculating (in agreement to the enemy position) the new direction where is aiming.
        """

        if self.aimed_agent is None:
            return

        if self.team == self.aimed_agent.get_team():
            logger.warning("Same team in PerformAimAction!")

        self.movement.destination.x = self.aimed_agent.position.x
        self.movement.destination.y = self.aimed_agent.position.y
        self.movement.destination.z = self.aimed_agent.position.z
        self.movement.calculate_new_orientation(self.movement.destination)

    def have_agent_to_shot(self):
        """
        To know if an enemy is aimed.

        This method is called just before agent can shoot.
        If an enemy is aimed, a value of <tt> TRUE</tt> is returned. Otherwise, the return value is <tt> FALSE</tt>.
        The result is used to decide if agent must shoot.

        :returns True(aimed enemy) | False (no aimed enemy)
        :rtype bool
        """
        return self.aimed_agent is not None

    # End of non-overloadable Methods

    # Methods to overload

    def generate_escape_position(self):
        """
        Calculates a new destiny position to escape.
        This method is called before the agent creates a task for escaping.
        It generates a valid random point in a radius of 50 units.
        Once position is calculated, agent updates its destiny to the new position,
        and automatically calculates the new direction.

        It's very useful to overload this method. </em>
        """

        while True:
            self.movement.calculate_new_destination(
                radius_x=ESCAPE_RADIUS, radius_y=ESCAPE_RADIUS
            )
            if self.map.can_walk(
                    self.movement.destination.x, self.movement.destination.z
            ):
                self.movement.calculate_new_orientation(self.movement.destination)
                return

    def perform_escape_action(self):
        """
        Action to do when the agent tries to escape.

        This method is just called before this agent creates a TASK_RUN_AWAY task. By default, the only thing it
        does is to reset its aimed enemy: aimed_agent = null. If it's overloaded, it's convenient to call
        parent's method.

        It's very useful to overload this method.
        """
        self.aimed_agent = None

    def perform_injury_action(self):
        """
        Action to do when an agent is being shot.

        This method is called every time this agent receives a messager from agent Manager informing it is being shot.

        It's very useful to overload this method.
        """
        pass

    def get_agent_to_aim(self):
        """
        Calculates if there is an enemy at sight.

        This method scans the list fov_objects (objects in the Field Of View of the agent) looking for an enemy.
        If an enemy agent is found, a value of True is returned and variable aimed_agent is updated.
        Note that there is no criterion (proximity, etc.) for the enemy found.
        Otherwise, the return value is False.

        It's very useful to overload this method.

        :returns True: enemy found / False: enemy not found
        """

        if not self.fov_objects:
            self.aimed_agent = None
            return False

        for tracked_object in self.fov_objects:
            if tracked_object.get_type() >= PACK_NONE:
                continue

            if self.team == tracked_object.get_team():
                continue

            self.aimed_agent = tracked_object
            return True
        self.aimed_agent = None
        return False

    def perform_look_action(self):
        """
        Action to do when the agent is looking at.

        This method is called just after Look method has ended.

        It's very useful to overload this method.
        """
        pass

    # End of Methods to overload
