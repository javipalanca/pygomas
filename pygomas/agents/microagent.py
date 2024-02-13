import json
import random

from loguru import logger
from spade.message import Message

from ..config import TEAM_NONE, PRECISION_X, PRECISION_Z, MAX_STAMINA, MAX_POWER, CLASS_MEDIC, MIN_HEALTH, MAX_HEALTH, \
    MAX_AMMO, TEAM_ALLIED
from ..ontology import Action, Belief, Performative
from ..utils.mobile import Mobile
from ..utils.vector import Vector3D


class MicroAgent:
    def __init__(self, map):
        self.jid = ""
        self.team = TEAM_NONE
        self.locate = Mobile()
        self.is_carrying_objective = False
        self.is_shooting = False
        self.health = MAX_HEALTH
        self.ammo = MAX_AMMO
        self.type = 0
        self.is_updated = False
        self.map = map
        self.stamina = MAX_STAMINA
        self.power = MAX_POWER

    def move(self, dt):
        if (self.locate.position.x != self.locate.destination.x or
                self.locate.position.z != self.locate.destination.z):
            new_position = Vector3D(self.locate.calculate_position(dt))
            if not self.map.can_walk(new_position.x, new_position.z):
                logger.info(
                    self.jid
                    + ": Can't walk to {} with velocity {}. It stays at {}".format(
                        new_position, self.locate.velocity, self.locate.position
                    )
                )
                self.escape_barrier()
            else:
                if self.locate.position != new_position:
                    if self.in_destination(new_position):
                        self.locate.position = Vector3D(self.locate.destination)
                    else:
                        self.locate.position = Vector3D(new_position)

                # return MV_OK

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
            x = self.locate.position.x
        if z is None:
            z = self.locate.position.z

        x = int(x)
        z = int(z)
        return self.map.can_walk(x, z)

    def in_destination(self, new_position):
        absx = abs(
            self.locate.destination.x - new_position.x
        )
        absz = abs(
            self.locate.destination.z - new_position.z
        )
        return (absx < PRECISION_X) and (absz < PRECISION_Z)

    def escape_barrier(self):

        """
        Escape a barrier. Sets the agent's velocity vector
        highest component to zero, forcing it to move only
        along the other component.
        """
        gx, gz = random.gauss(0, 0.1), random.gauss(0, 0.1)
        self.locate.velocity.x += gx
        self.locate.velocity.z += gz
        if random.randint(0, 1) == 0:
            self.locate.velocity.x *= -1
        else:
            self.locate.velocity.z *= -1
        logger.trace(
            self.jid
            + ": New velocity is <{},{}>".format(
                self.locate.velocity.x, self.locate.velocity.z
            )
        )

    def restore(self):
        if self.stamina < MAX_STAMINA:
            self.stamina += 1
        if self.power < MAX_POWER:
            self.power += 1
        if self.type == CLASS_MEDIC and self.health > MIN_HEALTH:
            if self.health < MAX_HEALTH:
                self.health = self.health + 1

    def update(self, content):
        self.is_updated = True

        self.locate.destination.x = float(content[Action.DEST_X])
        self.locate.destination.y = float(content[Action.DEST_Y])
        self.locate.destination.z = float(content[Action.DEST_Z])

        logger.error("Update destination[{}]: {}".format(self.jid, self.locate.destination))

        self.locate.velocity.x = float(content[Action.VEL_X])
        self.locate.velocity.y = float(content[Action.VEL_Y])
        self.locate.velocity.z = float(content[Action.VEL_Z])

        self.locate.heading.x = float(content[Action.HEAD_X])
        self.locate.heading.y = float(content[Action.HEAD_Y])
        self.locate.heading.z = float(content[Action.HEAD_Z])

    def get_update_msg(self, packs, fov_objects):
        content = {
            Action.X: self.locate.position.x,
            Action.Y: self.locate.position.y,
            Action.Z: self.locate.position.z,
            Action.VEL_X: self.locate.velocity.x,
            Action.VEL_Y: self.locate.velocity.y,
            Action.VEL_Z: self.locate.velocity.z,
            Action.HEAD_X: self.locate.heading.x,
            Action.HEAD_Y: self.locate.heading.y,
            Action.HEAD_Z: self.locate.heading.z,
            Belief.HEALTH: self.health,
            Belief.AMMO: self.ammo,
            Action.PACKS: packs,
            Action.FOV: fov_objects
        }
        msg = Message(to=self.jid)
        msg.set_metadata(
            str(Performative.PERFORMATIVE), str(Performative.DATA)
        )
        msg.body = json.dumps(content)
        logger.warning("Update message [{}]: {}".format(self.jid, msg.body))
        return msg

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

        logger.info("Spawn position for agent {} is ({}, {})".format(self.jid, x, z))

        self.locate.position.x = x
        self.locate.position.y = 0
        self.locate.position.z = z

    def __str__(self):
        return "<{} Team({}) Health({}) Ammo({}) Obj({})>".format(
            self.jid, self.team, self.health, self.ammo, self.is_carrying_objective
        )
