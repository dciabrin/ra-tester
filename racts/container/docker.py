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
            self.rsh_check(node, "docker pull %s" % img)

    def errorstoignore(self):
        return [
            # pull from an insecure registry logs a warning
            r"docker.*Attempting next endpoint for pull after error",
            # docker daemon is quite verbose, but all real errors are reported by pacemaker
            r"dockerd-current.*:\s*This node is not a swarm manager",
            r"dockerd-current.*:\s*No such container",
            r"dockerd-current.*:\s*No such image",
            r"dockerd-current.*Handler for GET.*/.*returned error: (network|plugin).*not found",
            r"dockerd-current.*Handler for GET.*/.*returned error: get.*no such volume",
        ]
