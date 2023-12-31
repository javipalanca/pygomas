import datetime

from pygomas.packs.pack import PACK_MEDICPACK, PACK_AMMOPACK, PACK_OBJPACK
from .config import TEAM_ALLIED, TEAM_AXIS


class PackStatistic:
    def __init__(self):
        self.delivered = 0
        self.team_taken = 0
        self.enemy_taken = 0
        self.not_taken = 0

    def __str__(self):
        ret = "\t\t* Delivered:   \t" + str(self.delivered) + "\n"
        ret += "\t\t* Team Taken:  \t" + str(self.team_taken) + "\n"
        ret += "\t\t* Enemy Taken: \t" + str(self.enemy_taken) + "\n"
        ret += "\t\t* Not Taken:   \t" + str(self.not_taken) + "\n"
        return ret


class TeamStatistic:
    def __init__(self):

        self.packs = {PACK_MEDICPACK: PackStatistic(), PACK_AMMOPACK: PackStatistic()}

        self.total_shots = 0
        self.enemy_hit_shots = 0
        self.team_hit_shots = 0
        self.failed_shots = 0

        self.total_objective_taken = 0
        self.total_objective_lost = 0

        self.medic_efficiency = 0
        self.fieldops_efficiency = 0
        self.army_efficiency = 0

        self.medic_anti_efficiency = 0
        self.fieldops_anti_efficiency = 0
        self.army_anti_efficiency = 0

        self.alive_players = 0
        self.average_health = 0.0

    def calculate_efficiency(self, alive_enemies):

        if self.packs[PACK_MEDICPACK].delivered <= 0:
            self.medic_efficiency = 0
        else:
            not_taken = self.packs[PACK_MEDICPACK].not_taken
            delivered = self.packs[PACK_MEDICPACK].delivered
            self.medic_efficiency = 1.0 - (not_taken * 1.0) / delivered

        if self.packs[PACK_AMMOPACK].delivered <= 0:
            self.fieldops_efficiency = 0
        else:
            not_taken = self.packs[PACK_AMMOPACK].not_taken
            delivered = self.packs[PACK_AMMOPACK].delivered
            self.fieldops_efficiency = 1.0 - (not_taken * 1.0) / delivered

        if self.total_shots <= 0:
            self.army_efficiency = 0
        else:
            self.army_efficiency = 1.0 - (alive_enemies * 1.0) / self.total_shots

    def calculate_anti_efficiency(self):

        if self.packs[PACK_MEDICPACK].delivered <= 0:
            self.medic_anti_efficiency = 0
        else:
            enemy_taken = self.packs[PACK_MEDICPACK].enemy_taken
            delivered = self.packs[PACK_MEDICPACK].delivered
            self.medic_anti_efficiency = (enemy_taken * 1.0) / delivered

        if self.packs[PACK_AMMOPACK].delivered <= 0:
            self.fieldops_anti_efficiency = 0
        else:
            enemy_taken = self.packs[PACK_AMMOPACK].enemy_taken
            delivered = self.packs[PACK_AMMOPACK].delivered
            self.fieldops_anti_efficiency = (enemy_taken * 1.0) / delivered

        if self.team_hit_shots <= 0:
            self.army_anti_efficiency = 0
        else:
            self.army_anti_efficiency = (self.alive_players * 1.0) / self.team_hit_shots

    def __str__(self):

        ret = "\t-GENERAL:\n"
        ret += "\t\t* Alive:       \t" + str(self.alive_players) + "\n"
        ret += "\t\t* Avrg. Health:\t" + str(self.average_health) + "\n"

        ret += "\t-OBJECTIVE:\n"
        ret += "\t\t* Times Taken: \t" + str(self.total_objective_taken) + "\n"
        ret += "\t\t* Times Lost:  \t" + str(self.total_objective_lost) + "\n"

        ret += "\t-SHOTS:\n"
        ret += "\t\t* EnemyHit:    \t" + str(self.enemy_hit_shots) + "\n"
        ret += "\t\t* TeamHit:     \t" + str(self.team_hit_shots) + "\n"
        ret += "\t\t* FailedHit:   \t" + str(self.failed_shots) + "\n"
        ret += "\t\t* TOTAL:       \t" + str(self.total_shots) + "\n"

        ret += "\t-MEDIC PACKS:\n"
        ret += str(self.packs[PACK_MEDICPACK]) + "\n"

        ret += "\t-AMMO PACKS:\n"
        ret += str(self.packs[PACK_AMMOPACK]) + "\n"

        ret += "\t-EFICIENCY:\n"
        ret += "\t\t* Medic:       \t" + str(self.medic_efficiency) + "\n"
        ret += "\t\t* FieldOps:    \t" + str(self.fieldops_efficiency) + "\n"
        ret += "\t\t* Army:        \t" + str(self.army_efficiency) + "\n"

        ret += "\t-ANTI-EFICIENCY:" + "\n"
        ret += "\t\t* Medic:       \t" + str(self.medic_anti_efficiency) + "\n"
        ret += "\t\t* FieldOps:    \t" + str(self.fieldops_anti_efficiency) + "\n"
        ret += "\t\t* Army:        \t" + str(self.army_anti_efficiency) + "\n"

        return ret


class GameStatistic:
    def __init__(self):
        self.team_statistic = {TEAM_ALLIED: TeamStatistic(), TEAM_AXIS: TeamStatistic()}

        self.match_duration = 0

    def pack_taken(self, pack, team):
        pack_team = TEAM_ALLIED if pack.team == TEAM_ALLIED else TEAM_AXIS

        if pack.type == PACK_OBJPACK:
            if team == TEAM_ALLIED:
                self.team_statistic[TEAM_ALLIED].total_objective_taken += 1
                self.team_statistic[TEAM_AXIS].total_objective_lost += 1
            elif team == TEAM_AXIS:
                self.team_statistic[TEAM_AXIS].total_objective_taken += 1
        else:
            if pack.team == team:
                self.team_statistic[pack_team].packs[pack.type].team_taken += 1
            else:
                self.team_statistic[pack_team].packs[pack.type].enemy_taken += 1

    def shoot(self, victim, team):
        team = TEAM_ALLIED if team == TEAM_ALLIED else TEAM_AXIS
        self.team_statistic[team].total_shots += 1

        if victim is None:
            self.team_statistic[team].failed_shots += 1
        elif team == victim.team:
            self.team_statistic[team].team_hit_shots += 1
        else:
            self.team_statistic[team].enemy_hit_shots += 1

    def objective_lost(self, team):
        team = TEAM_ALLIED if team == TEAM_ALLIED else TEAM_AXIS
        self.team_statistic[team].total_objective_lost += 1

    def pack_destroyed(self, din_object):
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
            self.team_statistic[pack_team].packs[pack_type].not_taken += 1

    def pack_created(self, din_object, team):
        pack_team = TEAM_ALLIED if team == TEAM_ALLIED else TEAM_AXIS
        pack_type = -1
        if din_object.type == PACK_MEDICPACK:
            pack_type = PACK_MEDICPACK
        elif din_object.type == PACK_AMMOPACK:
            pack_type = PACK_AMMOPACK

        if pack_type >= 0:
            self.team_statistic[pack_team].packs[pack_type].delivered += 1

    def calculate_data(
        self, allied_alive_players, axis_alive_players, allied_health, axis_health
    ):

        self.team_statistic[TEAM_ALLIED].alive_players = allied_alive_players
        if allied_alive_players > 0:
            self.team_statistic[TEAM_ALLIED].average_health = (
                allied_health * 1.0
            ) / allied_alive_players
        else:
            self.team_statistic[TEAM_ALLIED].average_health = 0

        self.team_statistic[TEAM_AXIS].alive_players = axis_alive_players
        if axis_alive_players > 0:
            self.team_statistic[TEAM_AXIS].average_health = (
                axis_health * 1.0
            ) / axis_alive_players
        else:
            self.team_statistic[TEAM_AXIS].average_health = 0

        self.team_statistic[TEAM_ALLIED].calculate_efficiency(axis_alive_players)
        self.team_statistic[TEAM_ALLIED].calculate_anti_efficiency()

        self.team_statistic[TEAM_AXIS].calculate_efficiency(allied_alive_players)
        self.team_statistic[TEAM_AXIS].calculate_anti_efficiency()

    def dumps(self, winner_team=""):

        ret = "Winner Team: " + winner_team + "\n"
        ret += (
            "Duration: ["
            + str(str(datetime.timedelta(seconds=self.match_duration)))
            + "]\n"
        )
        ret += "Statistics for ALLIED TEAM\n"
        ret += str(self.team_statistic[TEAM_ALLIED])

        ret += "\n"
        ret += "Statistics for AXIS TEAM\n"
        ret += str(self.team_statistic[TEAM_AXIS])

        ret = ret + "\n"
        return ret
