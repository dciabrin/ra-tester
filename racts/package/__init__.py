import re

from cts.remote import RemoteFactory

from .rpm import Rpm

managers = {
        "rpm": Rpm
}


def get_package_manager(env):
    # TODO: check whether we can create an instance instead of
    # doing a relying on a singleton
    return env["package_manager"]


def autodetect_package_manager(env):
    rsh = RemoteFactory().getInstance()
    distrib = rsh(env["nodes"][0], "lsb_release -i", stdout=1)
    distro_flavor = ""
    manager = False
    if re.search("RedHatEnterpriseServer", distrib):
        manager = managers["rpm"](env, "rpm", "rhel")

    assert manager is not False
    return manager
