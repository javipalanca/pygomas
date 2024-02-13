class Threshold(object):
    def __init__(self):
        self.health = 50
        self.ammo = 50
        self.aim = 1
        self.shot = 1
        self.look = 1

    def get_health(self):
        """
        Get the stablished limit of health. Agent can perform some actions if
        its health is lower than this value.

        Returns:
                health: current threshold for health
        """
        return self.health

    def get_ammo(self):
        """
        Get the stablished limit of ammunition. Agent can perform some actions if its ammo is lower than this value.

        Returns:
                ammo: current threshold for ammo

        """
        return self.ammo

    def get_aim(self):
        """
        Get the stablished number of times that the agent must aim the enemy
        before to shoot.

        Returns:
                aim: current threshold for aim
        """
        return self.aim

    def get_shot(self):
        """
        Get the stablished number of times that the agent must shoot
        consecutively before doing other action.

        Returns:
                shot: current threshold for shot
        """
        return self.shot

    def get_look(self):
        """
        Get the stablished number of times (cycles) that the agent must wait
        (moving blindly) before looking again.

        Returns:
                look: current threshold for look

        """
        return self.look

    def set_health(self, health):
        """
        Stablish the limit of health. Agent can perform some actions if its
        health is lower than this value.
        Rank is [0..100].

        Args:
                health (int):health desired threshold for health
        """
        if health > 100:
            health = 100
        if health < 0:
            health = 0
        self.health = health

    def set_ammo(self, ammo):
        """
        Stablish the limit of ammunition. Agent can perform some actions if its
        ammo is lower than this value.
        Rank is [0..100].

        Args:
                ammo desired threshold for ammo
        """
        if ammo > 100:
            ammo = 100
        if ammo < 0:
            ammo = 0
        self.ammo = ammo

    def set_aim(self, aim):
        """
        Stablish the number of times that the agent must aim the enemy before
        to shoot. Rank is [1..20].

        Args:
                aim: desired threshold for aim
        """
        if aim > 20:
            aim = 20
        if aim < 1:
            aim = 1
        self.aim = aim

    def set_shot(self, shot):
        """
        Stablish the number of times that the agent must shoot consecutively
        before doing other action. Rank is [1..20].

        Args:
                shot:  desired threshold for shot
        """
        if shot > 20:
            shot = 20
        if shot < 1:
            shot = 1
        self.shot = shot

    def set_look(self, look):
        """
        Stablish the number of times (cycles) that the agent must wait (moving
        blindly) before looking again. Rank is [0..100].

        Args:
                look: desired threshold for look
        """
        if look > 100:
            look = 100
        if look < 0:
            look = 0
        self.look = look
