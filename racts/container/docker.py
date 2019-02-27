from cts.logging import LogFactory
from cts.remote import RemoteFactory
from racts.raaction import ActionMixin
from .engine import ContainerEngine

class Docker(ContainerEngine, ActionMixin):
    def __init__(self, env, verbose):
        self.Env = env
        self.verbose = verbose
        self.logger = LogFactory()
        self.rsh = RemoteFactory().getInstance()

    def package_name(self):
        return "docker"

    def enable_engine(self, nodes):
        for node in nodes:
            self.rsh_check(node, "systemctl enable docker --now")

    def pull_image(self, nodes, img):
        for node in nodes:
            self.rsh_check(node, "docker pull %s"%img)


