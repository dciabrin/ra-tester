from .docker import Docker
from .podman import Podman
from . import engine

def get_container_engine(env, verbose):
    mapping = {
        "docker": Docker,
        "podman": Podman
    }
    return mapping[env["container_engine"]](env, verbose)
