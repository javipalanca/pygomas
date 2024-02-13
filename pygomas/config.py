import os

this_dir, _ = os.path.split(__file__)
DEFAULT_DATA_PATH = f"{this_dir}{os.sep}maps{os.sep}"


class Config(object):
    def __init__(self, data_path=None):
        self.data_path = data_path if data_path else DEFAULT_DATA_PATH
        if not self.data_path.endswith(os.sep):
            self.data_path += os.sep

    def set_data_path(self, data_path):
        self.data_path = data_path
        if not self.data_path.endswith(os.sep):
            self.data_path += os.sep


MIN_POWER: int = 0
MAX_POWER: int = 100
POWER_UNIT: int = 25
MIN_STAMINA: int = 0
MAX_STAMINA: int = 100
STAMINA_UNIT: int = 5
MIN_AMMO: int = 0
MAX_AMMO: int = 100
MIN_HEALTH: int = 0
MAX_HEALTH: int = 100
TEAM_NONE: int = 0
TEAM_ALLIED: int = 100
TEAM_AXIS: int = 200
PRECISION_Z: float = 0.5
PRECISION_X: float = 0.5
MISSING_SHOT_PROBABILITY: float = 0.1
CLASS_NONE = 0
CLASS_SOLDIER = 1
CLASS_MEDIC = 2
CLASS_ENGINEER = 3
CLASS_FIELDOPS = 4
INTERVAL_TO_MOVE = 0.05
