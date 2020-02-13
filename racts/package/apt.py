from cts.logging import LogFactory
from cts.remote import RemoteFactory
from racts.raaction import ActionMixin
from .manager import PackageManager


class Apt(PackageManager, ActionMixin):
    def __init__(self, env, pkg_format, flavor):
        PackageManager.__init__(self, env, pkg_format, flavor)
        self.verbose = self.Env["verbose"]
        self.logger = LogFactory()
        self.rsh = RemoteFactory().getInstance()

    def _is_installed(self, node, pkg):
        res = self.rsh(node,
                       "dpkg -s %s | grep -q 'Status:.*installed'" % pkg)
        return res == 0

    def _install(self, node, pkg):
        self.rsh_check(node, "apt-get install -y %s" % pkg)

    def _can_be_updated(self, node, pkg):
        res = self.rsh(node,
                       "apt-cache policy %s | "
                       "awk '/Installed:/ {I=$2} /Candidate:/ {C=$2} END {exit(I==C)}'" % pkg)
        return res == 0

    def _update(self, node, pkg):
        self.rsh_check(node, "apt-get install -y %s" % pkg)

