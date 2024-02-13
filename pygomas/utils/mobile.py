import math
import random

from .vector import Vector3D

MAP_SCALE = 1


class Mobile(object):
    def __init__(self, velocity_value=2):
        self.position = Vector3D()
        self.destination = Vector3D()
        self.velocity = Vector3D()
        self.heading = Vector3D()
        self.view_radius = 50.0
        self.angle = 1.0
        self.min_x = self.min_z = self.max_x = self.max_z = 0
        self.velocity_value = velocity_value

    def set_size(self, max_x, max_z):
        self.min_x = MAP_SCALE
        self.min_z = MAP_SCALE
        self.max_x = (max_x * MAP_SCALE) - MAP_SCALE
        self.max_z = (max_z * MAP_SCALE) - MAP_SCALE

    def calculate_position(self, dt):
        position = Vector3D()
        position.x = self.position.x + (self.velocity.x * dt)
        position.y = self.position.y + (self.velocity.y * dt)  # + (0.5f * t2)
        position.z = self.position.z + (self.velocity.z * dt)
        return position

    def calculate_new_orientation(self, destination):
        dx = float(destination.x - self.position.x)
        dy = float(destination.y - self.position.y)
        dz = float(destination.z - self.position.z)
        f2_norma = math.sqrt((dx * dx + dy * dy + dz * dz))

        if f2_norma > 0:
            self.velocity.x = float(dx / f2_norma)
            self.velocity.y = float(dy / f2_norma)
            self.velocity.z = float(dz / f2_norma)
        else:
            self.velocity.x = 0.0
            self.velocity.y = 0.0
            self.velocity.z = 0.0

        if self.velocity.length() > 0.0001:
            self.heading.x = self.velocity.x
            self.heading.y = self.velocity.y
            self.heading.z = self.velocity.z

        self.velocity.x *= self.velocity_value
        self.velocity.y *= self.velocity_value
        self.velocity.z *= self.velocity_value

    def calculate_new_destination(self, radius_x, radius_y):
        x = self.position.x + ((random.random() * (radius_x * 2)) - radius_x)
        z = self.position.z + ((random.random() * (radius_y * 2)) - radius_y)

        x = min(x, self.min_x)
        x = max(x, self.max_x)
        z = min(z, self.min_z)
        z = max(z, self.max_z)

        return Vector3D(x=x, y=0.0, z=z)

    def get_destination(self):
        return self.destination

    def set_destination(self, destination):
        self.destination = destination

    def get_position(self):
        return self.position

    def get_angle(self):
        return self.angle

    def get_view_radius(self):
        return self.view_radius

    def get_heading(self):
        return self.heading

    def get_velocity(self):
        return self.velocity
