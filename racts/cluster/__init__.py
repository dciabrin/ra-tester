from . import manager

from .pcmk1 import Pacemaker1
from .pcmk2 import Pacemaker2

managers = {
        "pcmk1": Pacemaker1,
        "pcmk2": Pacemaker2
}

priority = ["pcmk2", "pcmk1"]

def get_cluster_manager(env):
    return managers[env["cluster_manager"]](env)

def autodetect_cluster_manager(env):
    target = env["nodes"][0]
    manager = next(m for m in priority if managers[m](env).is_detected())
    return manager
