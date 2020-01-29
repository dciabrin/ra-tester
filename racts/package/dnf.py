from cts.logging import LogFactory
from cts.remote import RemoteFactory
from .manager import PackageManager
from .rpm import Rpm


class Dnf(Rpm):
    def __init__(self, env, pkg_format, flavor):
        PackageManager.__init__(self, env, pkg_format, flavor)
        self.verbose = self.Env["verbose"]
        self.logger = LogFactory()
        self.rsh = RemoteFactory().getInstance()

    def _install(self, node, pkg):
        self.rsh_check(node, "dnf install -y %s" % pkg)

    def _update(self, node, pkg):
        self.rsh_check(node, "dnf update -y %s" % pkg)

