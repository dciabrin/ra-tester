from cts.logging import LogFactory
from cts.remote import RemoteFactory
from racts.raaction import ActionMixin
from racts.distrib.rpm_rhel_7 import RpmRHEL7
from racts.cluster.pcmk2 import Pacemaker2
from racts.package.dnf import Dnf
from racts.container.podman import Podman


class RpmRHEL8(RpmRHEL7):
    def __init__(self, env):
        self.verbose = env["verbose"]
        self.logger = LogFactory()
        self.rsh = RemoteFactory().getInstance()
        self.pkg_mgr = Dnf(env, "rpm", "rhel")
        self.cluster_mgr = Pacemaker2(env)
        self.container_eng = Podman(env)
