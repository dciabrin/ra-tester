from cts.logging import LogFactory
from cts.remote import RemoteFactory
from racts.raaction import ActionMixin
from racts.distrib.distribution import Distribution
from racts.cluster.pcmk1 import Pacemaker1
from racts.package.rpm import Rpm
from racts.container.docker import Docker


class RpmRHEL7(Distribution, ActionMixin):
    def __init__(self, env):
        self.verbose = env["verbose"]
        self.logger = LogFactory()
        self.rsh = RemoteFactory().getInstance()
        self.pkg_mgr = Rpm(env, "rpm", "rhel")
        self.cluster_mgr = Pacemaker1(env)
        self.container_eng = Docker(env)

    def cluster_manager(self):
        return self.cluster_mgr

    def package_manager(self):
        return self.pkg_mgr

    def container_engine(self):
        return self.container_eng

    def add_insecure_container_registry(self, node, uri):
        res = self.rsh(node,
                       "if grep -v -w '%s' /etc/containers/registries.conf; then (echo -e \"[registries.insecure]\nregistries = ['%s']\" | crudini --merge /etc/containers/registries.conf registries.insecure); systemctl restart registries docker; fi" % (uri, uri))
        return res == 0
