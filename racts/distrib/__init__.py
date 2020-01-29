import re

from cts.remote import RemoteFactory

from .rpm_rhel_7 import RpmRHEL7

def get_distribution(env):
    return env["package_manager"]

def autodetect_distribution(env):
    rsh = RemoteFactory().getInstance()
    # TODO allow rsh to output multiple lines
    output = rsh(env["nodes"][0], "lsb_release -a | tr '\n' '|'", stdout=1)
    values = [s.split(":",1) for s in output.rstrip("\n|").split("|")]
    info = dict([[s.strip() for s in v] for v in values])
    manager = False
    if ((info["Distributor ID"] == "RedHatEnterpriseServer") and
        (info["Release"].startswith("7."))):
        manager = RpmRHEL7(env)

    assert manager is not False
    return manager
