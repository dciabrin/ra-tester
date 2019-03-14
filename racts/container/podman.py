from cts.logging import LogFactory
from cts.remote import RemoteFactory
from racts.raaction import ActionMixin

from .engine import ContainerEngine

class Podman(ContainerEngine, ActionMixin):
    def __init__(self, env):
        self.Env = env
        self.verbose = self.Env["verbose"]
        self.logger = LogFactory()
        self.rsh = RemoteFactory().getInstance()

    def is_detected(self):
        return self.rsh(self.Env["nodes"][0], "podman --version") == 0

    def package_name(self):
        return "podman"

    def enable_engine(self, nodes):
        # podman has no daemon, so it's a noop
        pass

    def pull_image(self, nodes, img):
        for node in nodes:
            self.rsh_check(node, "podman pull %s"%img)

