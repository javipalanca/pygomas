import json
import random
from collections import deque

import agentspeak as asp
from agentspeak.stdlib import actions as asp_action
from loguru import logger
from numpy import arctan2, cos, sin
from spade.behaviour import OneShotBehaviour, PeriodicBehaviour, CyclicBehaviour
from spade.message import Message
from spade.template import Template
from spade_bdi.bdi import BDIAgent

from .agent import AbstractAgent, LONG_RECEIVE_WAIT
from .config import (
    Config,
    MIN_POWER,
    MAX_POWER,
    POWER_UNIT,
    MIN_STAMINA,
    MAX_STAMINA,
    STAMINA_UNIT,
    MIN_AMMO,
    MAX_AMMO,
    MIN_HEALTH,
    MAX_HEALTH,
    TEAM_NONE,
    TEAM_ALLIED,
    TEAM_AXIS,
    PRECISION_Z,
    PRECISION_X,
)
from .jps import JPSAlgorithm
from .map import TerrainMap
from .mobile import Mobile
from .ontology import (
    AIM,
    ANGLE,
    DEC_HEALTH,
    DISTANCE,
    FOV,
    HEAD_X,
    HEAD_Y,
    HEAD_Z,
    MAP,
    PACKS,
    QTY,
    SHOTS,
    VEL_X,
    TYPE,
    VEL_Y,
    VEL_Z,
    X,
    Y,
    Z,
    PERFORMATIVE,
    PERFORMATIVE_CFA,
    PERFORMATIVE_CFB,
    PERFORMATIVE_CFM,
    PERFORMATIVE_DATA,
    PERFORMATIVE_GAME,
    PERFORMATIVE_GET,
    PERFORMATIVE_INIT,
    PERFORMATIVE_MOVE,
    PERFORMATIVE_OBJECTIVE,
    PERFORMATIVE_SHOOT,
    AMMO_SERVICE,
    BACKUP_SERVICE,
    MEDIC_SERVICE,
    AMMO,
    BASE,
    CLASS,
    DESTINATION,
    ENEMIES_IN_FOV,
    FRIENDS_IN_FOV,
    FLAG,
    HEADING,
    HEALTH,
    NAME,
    MY_MEDICS,
    MY_FIELDOPS,
    MY_BACKUPS,
    PACKS_IN_FOV,
    PERFORMATIVE_PACK_TAKEN,
    PERFORMATIVE_TARGET_REACHED,
    PERFORMATIVE_FLAG_TAKEN,
    POSITION,
    TEAM,
    THRESHOLD_HEALTH,
    THRESHOLD_AMMO,
    THRESHOLD_AIM,
    THRESHOLD_SHOTS,
    VELOCITY,
)
from .pack import PACK_MEDICPACK, PACK_AMMOPACK, PACK_OBJPACK, PACK_NONE
from .sight import Sight
from .threshold import Threshold
from .vector import Vector3D

DEFAULT_RADIUS = 20
ESCAPE_RADIUS = 50

INTERVAL_TO_MOVE = 0.05

ARG_TEAM = 0

CLASS_NONE = 0
CLASS_SOLDIER = 1
CLASS_MEDIC = 2
CLASS_ENGINEER = 3
CLASS_FIELDOPS = 4

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
            """Sets the PyGomas destination. Expects args to be (x,y,z)"""
            args = asp.grounded(term.args, intention.scope)
            self.movement.destination.x = args[0][0]
            self.movement.destination.y = args[0][1]
            self.movement.destination.z = args[0][2]
            start = (self.movement.position.x, self.movement.position.z)
            end = (self.movement.destination.x, self.movement.destination.z)

            if self.check_static_position(x=end[0], z=end[1]):
                path = self.path_finder.get_path(start, end)
                if path:
                    self.destinations = deque(path)
                    x, z = path[0]
                    self.movement.calculate_new_orientation(Vector3D(x=x, y=0, z=z))
                    self.bdi.set_belief(
                        DESTINATION, tuple((args[0][0], args[0][1], args[0][2]))
                    )
                    self.bdi.set_belief(
                        VELOCITY,
                        tuple(
                            (
                                self.movement.velocity.x,
                                self.movement.velocity.y,
                                self.movement.velocity.z,
                            )
                        ),
                    )
                    self.bdi.set_belief(
                        HEADING,
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
                    msg.set_metadata(PERFORMATIVE, PERFORMATIVE_SHOOT)
                    content = {
                        NAME: self.agent.name,
                        AIM: self.agent.threshold.get_aim(),
                        SHOTS: shots,
                        X: victim_x,
                        Y: victim_y,
                        Z: victim_z,
                    }
                    logger.info("{} shot!".format(content[NAME]))
                    msg.body = json.dumps(content)
                    if self.agent.is_alive():
                        await self.send(msg)

                    self.agent.decrease_ammo(shots)
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
                    msg.set_metadata(PERFORMATIVE, PERFORMATIVE_GET)
                    msg.to = self.agent.service_jid
                    msg.body = json.dumps({NAME: service, TEAM: self.agent.team})
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
            t.set_metadata(PERFORMATIVE, service)
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
                    msg.set_metadata(PERFORMATIVE, PERFORMATIVE_GET)
                    msg.to = self.agent.service_jid
                    msg.body = json.dumps({NAME: MEDIC_SERVICE, TEAM: self.agent.team})
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
                        self.agent.bdi.set_belief(MY_MEDICS, tuple(result))
                    else:
                        self.agent.bdi.set_belief(MY_MEDICS, tuple())
                        self.agent.medics_count = 0

            t = Template()
            t.set_metadata(PERFORMATIVE, PERFORMATIVE_CFM)
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
                    msg.set_metadata(PERFORMATIVE, PERFORMATIVE_GET)
                    msg.to = self.agent.service_jid
                    msg.body = json.dumps({NAME: AMMO_SERVICE, TEAM: self.agent.team})
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
                        self.agent.bdi.set_belief(MY_FIELDOPS, tuple(result))
                    else:
                        self.agent.bdi.set_belief(MY_FIELDOPS, tuple())
                        self.agent.fieldops_count = 0

            t = Template()
            t.set_metadata(PERFORMATIVE, PERFORMATIVE_CFA)
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
                    msg.set_metadata(PERFORMATIVE, PERFORMATIVE_GET)
                    msg.to = self.agent.service_jid
                    msg.body = json.dumps({NAME: BACKUP_SERVICE, TEAM: self.agent.team})
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
                        self.agent.bdi.set_belief(MY_BACKUPS, tuple(result))
                    else:
                        self.agent.bdi.set_belief(MY_BACKUPS, tuple())
                        self.agent.soldiers_count = 0

            t = Template()
            t.set_metadata(PERFORMATIVE, PERFORMATIVE_CFB)
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
                HEADING,
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
                HEADING,
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
            """Stops the PyGomas agent. """
            self.destinations = deque()
            self.movement.destination.x = self.movement.position.x
            self.movement.destination.y = self.movement.position.y
            self.movement.destination.z = self.movement.position.z
            yield

        @actions.add_function(".delete", (int, tuple, ))
        def _delete(index, tuple_):
            if index == 0:
                return tuple_[1:]
            elif index == len(tuple_) - 1:
                return tuple_[:index]
            else:
                return tuple_[0:index] + tuple_[index + 1:]

        super().add_custom_actions(actions)

    def start(self, auto_register=True):
        self.health = MAX_HEALTH
        self.protection = 25
        self.stamina = MAX_STAMINA
        self.power = MAX_POWER
        self.ammo = MAX_AMMO

        # Send a welcome message, and wait for the beginning of match
        self.add_behaviour(self.CreateBasicTroopBehaviour())

        # Behaviour to get the objective of the game, to create the corresponding task
        t = Template()
        t.set_metadata(PERFORMATIVE, PERFORMATIVE_OBJECTIVE)
        self.add_behaviour(self.ObjectiveBehaviour(), t)

        t = Template()
        t.set_metadata(PERFORMATIVE, PERFORMATIVE_INIT)
        self.add_behaviour(self.InitResponderBehaviour(), t)

        # Behaviour to listen to manager if game has finished
        t = Template()
        t.set_metadata(PERFORMATIVE, PERFORMATIVE_GAME)
        self.add_behaviour(self.GameFinishedBehaviour(), t)

        # Behaviour to handle Shot messages
        t = Template()
        t.set_metadata(PERFORMATIVE, PERFORMATIVE_SHOOT)
        self.add_behaviour(self.ShootResponderBehaviour(period=0), t)

        # Behaviour to inform manager our position, status, and so on
        t = Template()
        t.set_metadata(PERFORMATIVE, PERFORMATIVE_DATA)
        self.add_behaviour(self.DataFromTroopBehaviour(period=INTERVAL_TO_MOVE), t)

        # Behaviour to increment inner variables (Power, Stamina and Health Bars)
        # self.agent.Launch_BarsAddOn_InnerBehaviour()
        self.add_behaviour(self.RestoreBehaviour(period=1))

        future = super().start(auto_register)
        return future

    class CreateBasicTroopBehaviour(OneShotBehaviour):
        async def run(self):
            if self.agent.service_types is not None:
                for service in self.agent.service_types:
                    self.agent.register_service(str(service))
            if self.agent.team == TEAM_ALLIED:
                self.agent.register_service("allied")
            else:
                self.agent.register_service("axis")

            msg = Message(to=self.agent.manager)
            msg.set_metadata(PERFORMATIVE, PERFORMATIVE_INIT)
            msg.body = json.dumps(
                {
                    NAME: self.agent.name,
                    TYPE: str(self.agent.eclass),
                    TEAM: str(self.agent.team),
                }
            )
            await self.send(msg)

    class MoveBehaviour(PeriodicBehaviour):
        async def run(self):
            if len(self.agent.destinations) > 0:
                absx = abs(
                    self.agent.destinations[0][0] - self.agent.movement.position.x
                )
                absz = abs(
                    self.agent.destinations[0][1] - self.agent.movement.position.z
                )
                if (absx < PRECISION_X) and (absz < PRECISION_Z):
                    x, z = self.agent.destinations.popleft()
                    self.agent.movement.position = Vector3D(x=x, y=0, z=z)
                    self.agent.bdi.set_belief(
                        POSITION,
                        tuple(
                            (
                                self.agent.movement.position.x,
                                self.agent.movement.position.y,
                                self.agent.movement.position.z,
                            )
                        ),
                    )

                    if len(self.agent.destinations) == 0:
                        self.agent.bdi.set_belief(
                            PERFORMATIVE_TARGET_REACHED,
                            tuple(
                                (
                                    self.agent.movement.destination.x,
                                    self.agent.movement.destination.y,
                                    self.agent.movement.destination.z,
                                )
                            ),
                        )
                    else:
                        x, z = self.agent.destinations[0]
                    self.agent.compare_orientation(x, z)
                else:
                    move_result = self.agent.move(INTERVAL_TO_MOVE)
                    if move_result == MV_CANNOT_GET_POSITION:
                        self.agent.escape_barrier()

    class InitResponderBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
            if msg:
                map_name = json.loads(msg.body)[MAP]
                logger.info("[" + self.agent.name + "]: Beginning to fight")
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
                self.agent.generate_spawn_position()

                t = Template()
                t.set_metadata(PERFORMATIVE, PERFORMATIVE_MOVE)
                self.agent.add_behaviour(
                    self.agent.MoveBehaviour(period=INTERVAL_TO_MOVE), t
                )

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
                        x = (
                            (
                                self.agent.map.allied_base.get_end_x()
                                - self.agent.map.allied_base.get_init_x()
                            )
                            / 2
                        ) + self.agent.map.allied_base.get_init_x()
                        y = (
                            (
                                self.agent.map.allied_base.get_end_y()
                                - self.agent.map.allied_base.get_init_y()
                            )
                            / 2
                        ) + self.agent.map.allied_base.get_init_y()
                        z = (
                            (
                                self.agent.map.allied_base.get_end_z()
                                - self.agent.map.allied_base.get_init_z()
                            )
                            / 2
                        ) + self.agent.map.allied_base.get_init_z()
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
                    self.agent.bdi.set_belief(NAME, self.agent.name)
                    self.agent.bdi.set_belief(TEAM, self.agent.team)
                    self.agent.bdi.set_belief(CLASS, self.agent.eclass)
                    self.agent.bdi.set_belief(BASE, tuple((x, y, z)))
                    self.agent.bdi.set_belief(
                        POSITION,
                        tuple(
                            (
                                self.agent.movement.position.x,
                                self.agent.movement.position.y,
                                self.agent.movement.position.z,
                            )
                        ),
                    )
                    self.agent.bdi.set_belief(HEALTH, self.agent.health)
                    self.agent.bdi.set_belief(AMMO, self.agent.ammo)
                    self.agent.bdi.set_belief(
                        THRESHOLD_HEALTH, self.agent.threshold.health
                    )
                    self.agent.bdi.set_belief(THRESHOLD_AMMO, self.agent.threshold.ammo)
                    self.agent.bdi.set_belief(THRESHOLD_AIM, self.agent.threshold.aim)
                    self.agent.bdi.set_belief(
                        THRESHOLD_SHOTS, self.agent.threshold.shot
                    )
                    self.agent.bdi.set_belief(
                        FLAG, tuple((content[X], content[Y], content[Z]))
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
                decrease_health = int(content[DEC_HEALTH])
                self.agent.decrease_health(decrease_health)
                logger.info(
                    "Agent {} has been hit by a shot! Loses {} health points ({}).".format(
                        self.agent.name, decrease_health, self.agent.health
                    )
                )

                if self.agent.health <= 0:
                    logger.success(self.agent.name + ": DEAD!!")
                    if self.agent.is_objective_carried:
                        self.agent.bdi.remove_belief(PERFORMATIVE_FLAG_TAKEN)
                        self.agent.is_objective_carried = False
                        logger.info(
                            "Agent {} loses the objective.".format(self.agent.name)
                        )
                    await self.agent.die()

                self.agent.perform_injury_action()

    # Behaviour to inform JGomasManager our position, status, and so on
    class DataFromTroopBehaviour(PeriodicBehaviour):
        async def run(self):
            try:
                if not self.agent.movement:
                    return
                content = {
                    NAME: self.agent.name,
                    X: self.agent.movement.position.x,
                    Y: self.agent.movement.position.y,
                    Z: self.agent.movement.position.z,
                    VEL_X: self.agent.movement.velocity.x,
                    VEL_Y: self.agent.movement.velocity.y,
                    VEL_Z: self.agent.movement.velocity.z,
                    HEAD_X: self.agent.movement.heading.x,
                    HEAD_Y: self.agent.movement.heading.y,
                    HEAD_Z: self.agent.movement.heading.z,
                    HEALTH: self.agent.health,
                    AMMO: self.agent.ammo,
                }
                msg = Message(to=self.agent.manager)
                msg.set_metadata(PERFORMATIVE, PERFORMATIVE_DATA)
                msg.body = json.dumps(content)

                if self.agent.is_alive():
                    await self.send(msg)

                info = await self.receive(LONG_RECEIVE_WAIT)
                if info is None:
                    return
                info = json.loads(info.body)

                packs = info[PACKS] if info[PACKS] is not None else []
                for pack in packs:
                    pack = json.loads(pack)
                    quantity = pack[QTY]
                    type_ = pack[TYPE]
                    self.agent.pack_taken(pack_type=type_, quantity=quantity)

                self.agent.fov_objects = []
                fovs = info[FOV] if info[FOV] is not None else []
                if len(fovs) <= 0:
                    self.agent.aimed_agent = None
                else:
                    for idx, obj in enumerate(fovs):
                        s = Sight()
                        s.sight_id = idx
                        s.team = int(obj[TEAM])
                        s.type = int(obj[TYPE])
                        s.angle = float(obj[ANGLE])
                        s.distance = float(obj[DISTANCE])
                        s.health = int(obj[HEALTH])
                        s.position.x = float(obj[X])
                        s.position.y = float(obj[Y])
                        s.position.z = float(obj[Z])
                        self.agent.fov_objects.append(s)
                        if s.team == TEAM_NONE:
                            self.agent.bdi.set_belief(
                                PACKS_IN_FOV,
                                idx,
                                int(obj[TYPE]),
                                float(obj[ANGLE]),
                                float(obj[DISTANCE]),
                                int(obj[HEALTH]),
                                tuple((float(obj[X]), float(obj[Y]), float(obj[Z]))),
                            )
                        elif s.team == self.agent.team:
                            self.agent.bdi.set_belief(
                                FRIENDS_IN_FOV,
                                idx,
                                int(obj[TYPE]),
                                float(obj[ANGLE]),
                                float(obj[DISTANCE]),
                                int(obj[HEALTH]),
                                tuple((float(obj[X]), float(obj[Y]), float(obj[Z]))),
                            )
                        else:
                            self.agent.bdi.set_belief(
                                ENEMIES_IN_FOV,
                                idx,
                                int(obj[TYPE]),
                                float(obj[ANGLE]),
                                float(obj[DISTANCE]),
                                int(obj[HEALTH]),
                                tuple((float(obj[X]), float(obj[Y]), float(obj[Z]))),
                            )

            except ZeroDivisionError:
                pass

    # Behaviour to increment inner variables (Power, Stamina and Health Bars)
    class RestoreBehaviour(PeriodicBehaviour):
        async def run(self):
            if self.agent.stamina < MAX_STAMINA:
                self.agent.stamina = self.agent.stamina + 1

            if self.agent.power < MAX_POWER:
                self.agent.power = self.agent.power + 1

            if self.agent.eclass == CLASS_MEDIC and self.agent.health > MIN_HEALTH:
                if self.agent.health < MAX_HEALTH:
                    self.agent.health = self.agent.health + 1

    def generate_spawn_position(self):

        if self.team == TEAM_ALLIED:
            w = self.map.allied_base.end.x - self.map.allied_base.init.x
            h = self.map.allied_base.end.z - self.map.allied_base.init.z
            offset_x = self.map.allied_base.init.x
            offset_z = self.map.allied_base.init.z

        else:
            w = self.map.axis_base.end.x - self.map.axis_base.init.x
            h = self.map.axis_base.end.z - self.map.axis_base.init.z
            offset_x = self.map.axis_base.init.x
            offset_z = self.map.axis_base.init.z

        x = int((random.random() * w) + offset_x)
        z = int((random.random() * h) + offset_z)

        logger.info("Spawn position for agent {} is ({}, {})".format(self.name, x, z))

        self.movement.position.x = x
        self.movement.position.y = 0
        self.movement.position.z = z

    def move(self, dt):
        new_position = Vector3D(self.movement.calculate_position(dt))
        if not self.check_static_position(new_position.x, new_position.z):
            logger.info(
                self.name
                + ": Can't walk to {} with velocity {}. I stay at {}".format(
                    new_position, self.movement.velocity, self.movement.position
                )
            )
            return MV_CANNOT_GET_POSITION
        else:
            if self.movement.position != new_position:
                self.movement.position = Vector3D(new_position)
                self.bdi.set_belief(
                    POSITION,
                    tuple(
                        (
                            self.movement.position.x,
                            self.movement.position.y,
                            self.movement.position.z,
                        )
                    ),
                )
            x, z = self.destinations[0]
            self.compare_orientation(x, z)
            return MV_OK

    def compare_orientation(self, x, z):
        last_velocity = Vector3D(self.movement.velocity)
        last_heading = Vector3D(self.movement.heading)
        self.movement.calculate_new_orientation(Vector3D(x=x, y=0, z=z))
        if last_velocity != self.movement.velocity:
            self.bdi.set_belief(
                VELOCITY,
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
                HEADING,
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
            self.bdi.set_belief(PERFORMATIVE_PACK_TAKEN, MEDIC_SERVICE, quantity)
            self.increase_health(quantity)
        elif pack_type == PACK_AMMOPACK:
            self.bdi.set_belief(PERFORMATIVE_PACK_TAKEN, AMMO_SERVICE, quantity)
            self.increase_ammo(quantity)
        elif pack_type == PACK_OBJPACK and self.team == TEAM_ALLIED:
            self.is_objective_carried = True
            self.bdi.set_belief(PERFORMATIVE_FLAG_TAKEN)

    def get_health(self):
        """
         Get the current health of the agent.

         :returns current value for health
         :rtype int
         """
        return self.health

    def increase_health(self, quantity):
        """
        Increments the current health of the agent.

        :param quantity: positive quantity to increment
        """
        self.health += quantity
        if self.health > MAX_HEALTH:
            self.health = MAX_HEALTH
        self.bdi.set_belief(HEALTH, self.health)

    def decrease_health(self, quantity):
        """
        Decrements the current health of the agent.

        :param quantity: negative quantity to decrement
        """
        self.health -= quantity
        if self.health < MIN_HEALTH:
            self.health = MIN_HEALTH
        self.bdi.set_belief(HEALTH, self.health)

    def get_ammo(self):
        """
        Get the current ammunition of the agent.

        :returns: current value for ammo
        """
        return self.ammo

    def increase_ammo(self, quantity):
        """
        Increments the current ammunition of the agent.

        :param quantity: positive quantity to increment
        """
        self.ammo += quantity
        if self.ammo > MAX_AMMO:
            self.ammo = MAX_AMMO
        self.bdi.set_belief(AMMO, self.ammo)

    def decrease_ammo(self, quantity):
        """
        Decrements the current ammunition of the agent.

        :param quantity: negative quantity to decrement
        """
        self.ammo -= quantity
        if self.ammo < MIN_AMMO:
            self.ammo = MIN_AMMO
        self.bdi.set_belief(AMMO, self.ammo)

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

    def check_static_position(self, x=None, z=None):
        """
        Checks a position on the static map.

        This method checks if a position on the static map is valid to walk on, and returns the result.

        :param x:
        :param z:
        :returns True (agent can walk on) | False (agent cannot walk on)
        :rtype bool
        """
        if x is None:
            x = self.movement.position.x
        if z is None:
            z = self.movement.position.z

        x = int(x)
        z = int(z)
        return self.map.can_walk(x, z)

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
        This method is called before the agent creates a task for escaping. It generates a valid random point in a radius of 50 units.
        Once position is calculated, agent updates its destiny to the new position, and automatically calculates the new direction.

        It's very useful to overload this method. </em>
        """

        while True:
            self.movement.calculate_new_destination(
                radius_x=ESCAPE_RADIUS, radius_y=ESCAPE_RADIUS
            )
            if self.check_static_position(
                self.movement.destination.x, self.movement.destination.z
            ):
                self.movement.calculate_new_orientation(self.movement.destination)
                return

    def escape_barrier(self):
        """
        Escape a barrier. Sets the agent's velocity vector
        highest component to zero, forcing it to move only
        along the other component.
        """
        """
        if abs(self.movement.velocity.x) == abs(self.movement.velocity.z):
            self.movement.velocity.x += random.gauss(0, 0.1)
            self.movement.velocity.z += random.gauss(0, 0.1)
        elif abs(self.movement.velocity.x) > abs(self.movement.velocity.z):
            self.movement.velocity.x = 0.0
            self.movement.velocity.z = float(1 * sign(self.movement.velocity.z))
        elif abs(self.movement.velocity.x) < abs(self.movement.velocity.z):
            self.movement.velocity.z = 0.0
            self.movement.velocity.x = float(1 * sign(self.movement.velocity.x))
        """
        gx, gz = random.gauss(0, 0.1), random.gauss(0, 0.1)
        self.movement.velocity.x += gx
        self.movement.velocity.z += gz
        if random.randint(0, 1) == 0:
            self.movement.velocity.x *= -1
        else:
            self.movement.velocity.z *= -1
        logger.trace(
            self.name
            + ": New velocity is <{},{}>".format(
                self.movement.velocity.x, self.movement.velocity.z
            )
        )

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
