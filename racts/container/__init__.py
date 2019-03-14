from . import engine

from .docker import Docker
from .podman import Podman

engines = {
        "docker": Docker,
        "podman": Podman
}

priority = ["podman", "docker"]

def get_container_engine(env):
    mapping = {
        "docker": Docker,
        "podman": Podman
    }
    return engines[env["container_engine"]](env)

def autodetect_container_engine(env):
    engine = next(e for e in priority if engines[e](env).is_detected())
    return engine
