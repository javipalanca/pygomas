from .vector import Vector3D


class Sight(object):
    def __init__(self):
        self.position = Vector3D()
        self.sight_id = 0
        self.team = 0
        self.type = 0
        self.distance = 0.0
        self.angle = 0.0
        self.health = 0

    def get_angle(self):
        return self.angle

    def get_distance(self):
        return self.distance

    def get_team(self):
        return self.team

    def get_type(self):
        return self.type

    def get_health(self):
        return self.health

    def get_position(self):
        return self.position
