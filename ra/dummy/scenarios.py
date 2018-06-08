#!/usr/bin/env python

'''Resource Agents Tester

Template scenarios definition for resource agent
 '''

__copyright__ = '''
Copyright (C) 2018 Damien Ciabrini <dciabrin@redhat.com>
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

class PrepareCluster(RATesterScenarioComponent):
    def __init__(self, environment, verbose=False):
        RATesterScenarioComponent.__init__(self, environment, verbose)

    def pull_container_image(self, img):
        for node in self.Env["nodes"]:
            self.log("pulling container image %s on %s"%(img,node))
            rc = self.rsh(node, "docker pull %s"%img)
            assert rc == 0, \
                "failed to pull container image on remote node \"%s\"" % \
                (node,)

    def check_prerequisite(self, prerequisite):
        missing_reqs = False
        for req in prerequisite:
            if not self.rsh.exists_on_all(req, self.Env["nodes"]):
                self.log("error: %s could not be found on remote nodes. "
                         "Please install the necessary package to run the tests"%  req)
                missing_reqs = True
        assert not missing_reqs

    def setup_scenario(self, cluster_manager):
        # install package pre-requisites
        # todo pre-req hook

        # container setup
        if self.Env["bundle"]:
            for node in self.Env["nodes"]:
                self.rsh(node, "systemctl enable docker")
                self.rsh(node, "systemctl start docker")
            self.pull_container_image(self.Env["container_image"])


        # stop cluster if previously running, failure is not fatal
        for node in self.Env["nodes"]:
            self.rsh(node, "pcs cluster destroy")
            self.rsh(node, "systemctl enable pacemaker")
            self.rsh(node, "systemctl stop pacemaker_remote")
            self.rsh(node, "systemctl disable pacemaker_remote")

        # create a new cluster
        # note: setting up cluster disable pacemaker service. re-enable it
        patterns = [r"crmd.*:\s*notice:\sState\stransition\sS_STARTING(\s->.*origin=do_started)?",
                    r"crmd.*:\s*notice:\sState\stransition\s.*->\sS_IDLE(\s.*origin=notify_crmd)?"]
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
        assert not watch.unmatched, watch.unmatched

    def teardown_scenario(self, cluster_manager):
        cluster_manager.log("Leaving cluster running on all nodes")



# The scenario below set up two basic configuration for the RA tests
#   . BundleSetup will hint tests to wrap the Dummy resource into a
#     bundle (container)
#   . SimpleSetup doesn't change the tests' original behaviour

class SimpleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        self.Env["rsc_name"] = "dummy"
        PrepareCluster.setup_scenario(self,cm)

scenarios["SimpleSetup"]=[SimpleSetup]


class BundleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        self.Env["bundle"] = True
        self.Env["rsc_name"] = "dummy-bundle"
        self.Env["container_image"] = "docker.io/tripleoupstream/centos-binary-mariadb:latest"
        PrepareCluster.setup_scenario(self,cm)

scenarios["BundleSetup"]=[BundleSetup]
