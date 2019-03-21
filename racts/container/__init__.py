from cts.remote import RemoteFactory

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
    try:
        engine = next(e for e in priority if engines[e](env).is_detected())
        return engine
    except StopIteration:
        # RHEL 8 uses podman instead of docker
        rsh = RemoteFactory().getInstance()
        node = env["nodes"][0]
        inspect = rsh(node, "/usr/bin/hostnamectl | grep CPE", stdout=True).rstrip()
        if inspect:
            items=inspect.split(":")
            # ['       CPE OS Name', ' cpe', '/o', 'redhat', 'enterprise_linux', '8.0', 'GA']
            if items[5].startswith('8.'):
                return "podman"
        return "docker"
