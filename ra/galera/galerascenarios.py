#!/usr/bin/env python

'''Resource Agents Tester

Regression scenarios for galera RA
 '''

__copyright__ = '''
Copyright (C) 2015-2016 Damien Ciabrini <dciabrin@redhat.com>
Licensed under the GNU GPL.
'''

#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA.


import sys, signal, time, os, re, string, subprocess, tempfile
from stat import *
from cts import CTS
from cts.CTS import CtsLab
from cts.CTStests import CTSTest
from cts.CM_ais import crm_mcp
from cts.CTSscenarios import *
from cts.CTSaudits import *
from cts.CTSvars   import *
from cts.patterns  import PatternSelector
from cts.logging   import LogFactory
from cts.remote    import RemoteFactory
from cts.watcher   import LogWatcher
from cts.environment import EnvFactory

from racts.rascenario import RATesterScenarioComponent

scenarios = {}

class Galera(Sequence):
    pass

scenarios[Galera]=[]

class GaleraNewCluster(RATesterScenarioComponent):
    def __init__(self, environment, verbose=False):
        RATesterScenarioComponent.__init__(self, environment, verbose)

    def IsApplicable(self):
        return not self.Env.has_key("keep_cluster")

    def setup_scenario(self, cluster_manager):
        # pre-requisites
        prerequisite = ["/usr/bin/gdb", "/usr/bin/screen", "/usr/bin/dig"]
        missing_reqs = False
        for req in prerequisite:
            if not self.rsh.exists_on_all(req, self.Env["nodes"]):
                self.log("error: %s could not be found on remote nodes. "
                         "Please install the necessary package to run the tests"%  req)
                missing_reqs = True
        assert not missing_reqs

        # galera-specific data
        test_scripts = ["kill-during-txn.gdb", "slow_down_sst.sh"]
        for node in self.Env["nodes"]:
            for script in test_scripts:
                src = os.path.join(os.path.dirname(os.path.abspath(__file__)), script)
                rc = self.rsh.cp(src, "root@%s:/tmp/%s" % (node, script))
                assert rc == 0, \
                    "failed to copy data \"%s\" on remote node \"%s\"" % \
                    (src, node)

        # clean up any traffic control on target network interface
        for node in self.Env["nodes"]:
            self.rsh(node, "/tmp/slow_down_sst.sh -n %s off"%node)

        # stop cluster if previously running, failure is not fatal
        for node in self.Env["nodes"]:
            self.rsh(node, "pcs cluster destroy")
            self.rsh(node, "systemctl enable pacemaker")
            self.rsh(node, "systemctl stop pacemaker_remote")
            self.rsh(node, "systemctl disable pacemaker_remote")

        # create a new cluster
        # note: setting up cluster disable pacemaker service. re-enable it
        patterns = [r"crmd.*:\s*notice:\sState\stransition\sS_STARTING\s->.*origin=do_started",
                    r"crmd.*:\s*notice:\sState\stransition\s.*->\sS_IDLE\s.*origin=notify_crmd"]
        watch = LogWatcher(self.Env["LogFileName"], patterns, None, self.Env["DeadTime"], kind=self.Env["LogWatcher"], hosts=self.Env["nodes"])
        watch.setwatch()
        self.rsh_check(self.Env["nodes"][0], "pcs cluster setup --force --name ratester %s" % \
                       " ".join(self.Env["nodes"]))
        self.rsh_check(self.Env["nodes"][0], "systemctl enable pacemaker")
        self.rsh_check(self.Env["nodes"][0], "pcs cluster start --all")
        # Disable STONITH by default. A dedicated ScenarioComponent
        # is in charge of enabling it if requested
        self.rsh_check(self.Env["nodes"][0], "pcs property set stonith-enabled=false")
        watch.lookforall()

    def teardown_scenario(self, cluster_manager):
        cluster_manager.log("Leaving cluster running on all nodes")

scenarios[Galera].append(GaleraNewCluster)


class GaleraKeepCluster(RATesterScenarioComponent):
    def __init__(self, environment, verbose=False):
        RATesterScenarioComponent.__init__(self, environment, verbose)

    def IsApplicable(self):
        return self.Env.has_key("keep_cluster")

    def setup_scenario(self, cluster_manager):
        cluster_manager.log("Reusing cluster")

        # Disable STONITH by default. A dedicated ScenarioComponent
        # is in charge of enabling it if requested
        self.rsh_check(self.Env["nodes"][0], "pcs property set stonith-enabled=false")

        # Stop and remove galera if it exists
        # Note1: in order to avoid error when stopping the resource while
        # in unknown state, we first reprobe the resource state.
        # Note2: if you clean and delete before pacemaker had a
        # chance to re-probe state, it will consider resource is stopped
        # and will happily delete the resource from the cib even if
        # galera is still running!
        # Note3: after a cleanup, pacemaker may log a warning log
        # if it finds the resource is still running. This does not
        # count as an error for the CTS test
        target=self.Env["nodes"][0]
        rc = self.rsh(target, "pcs resource unmanage galera")
        if rc == 0:
            patterns = [r"crmd.*:\s*Initiating action.*: probe_complete probe_complete-%s on %s"%(n,n) \
                    for n in self.Env["nodes"]]
            watch=LogWatcher(self.Env["LogFileName"], patterns, None, self.Env["DeadTime"], kind=self.Env["LogWatcher"], hosts=self.Env["nodes"])
            watch.setwatch()
            self.rsh(target, "pcs resource cleanup galera")
            watch.lookforall()
            assert not watch.unmatched, watch.unmatched
            self.rsh(target, "pcs resource disable galera")
            self.rsh(target, "pcs resource manage galera")
            self.rsh(target, "pcs resource delete galera --wait")

    def teardown_scenario(self, cluster_manager):
        cluster_manager.log("Leaving cluster running on all nodes")

scenarios[Galera].append(GaleraKeepCluster)
