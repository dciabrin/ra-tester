from cts.logging import LogFactory
from cts.remote import RemoteFactory
from racts.raaction import ActionMixin
from .manager import PackageManager

class Rpm(PackageManager, ActionMixin):
    def __init__(self, env, pkg_format, flavor):
        PackageManager.__init__(self, env, pkg_format, flavor)
        self.verbose = self.Env["verbose"]
        self.logger = LogFactory()
        self.rsh = RemoteFactory().getInstance()

    def _is_installed(self, node, pkg):
        res = self.rsh(node,
                       "rpm -qa --qf '%%{NAME}\n' %s | grep %s" % (pkg, pkg))
        return res == 0

    def _install(self, node, pkg):
        self.rsh_check(node, "yum install -y %s" % pkg)

    def _can_be_updated(self, node, pkg):
        res = self.rsh(node,
                       "repoquery -a --pkgnarrow=updates"
                       "--qf 'UPDATE' %s | grep UPDATE" % pkg)
        return res == 0

    def _update(self, node, pkg):
        self.rsh_check(node, "yum update -y %s" % pkg)

