from .pcmk1 import Pacemaker1
from .pcmk2 import Pacemaker2
from . import manager

def get_cluster_manager(env, verbose):
    mapping = {
        "pcmk1": Pacemaker1,
        "pcmk2": Pacemaker2
    }
    return mapping[env["cluster_manager"]](env, verbose)
