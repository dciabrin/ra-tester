from cts.logging import LogFactory
from cts.remote import RemoteFactory
from racts.raaction import ActionMixin

from .engine import ContainerEngine

class Docker(ContainerEngine, ActionMixin):
    def __init__(self, env):
        self.Env = env
        self.verbose = self.Env["verbose"]
        self.logger = LogFactory()
        self.rsh = RemoteFactory().getInstance()

    def is_detected(self):
        return self.rsh(self.Env["nodes"][0], "docker --version") == 0

    def package_name(self):
        return "docker"

    def enable_engine(self, nodes):
        for node in nodes:
            self.rsh_check(node, "systemctl enable docker --now")

    def pull_image(self, nodes, img):
        for node in nodes:
            self.rsh_check(node, "docker pull %s"%img)


