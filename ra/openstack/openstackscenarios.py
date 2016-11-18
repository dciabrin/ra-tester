#!/usr/bin/env python

'''Resource Agents Tester

Regression scenarios for OpenStack HA
 '''

__copyright__ = '''
Copyright (C) 2016 Damien Ciabrini <dciabrin@redhat.com>
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
from racts.rapatterns import RATemplates

from racts.rascenario import RATesterScenarioComponent


scenarios = {}

class OpenStack(Sequence):
    pass

scenarios[OpenStack]=[]


class OpenStackReuseOvercloud(RATesterScenarioComponent):
    def __init__(self, environment, verbose=False):
        RATesterScenarioComponent.__init__(self, environment, verbose)
        self.ratemplates = RATemplates()

    def IsApplicable(self):
        return True

    def setup_scenario(self, cluster_manager):
        cluster_manager.log("Reusing cluster")

        # Make sure that a galera resource exist and is Master
        target=self.Env["nodes"][0]
        rc = self.rsh(target, "sudo pcs resource unmanage galera")
        assert rc == 0, "Unable to unmanage galera resource"
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe", "galera", n, 'master')
                    for n in self.Env["nodes"]]
        watch=LogWatcher(self.Env["LogFileName"], patterns, None, self.Env["DeadTime"], kind=self.Env["LogWatcher"], hosts=self.Env["nodes"])
        watch.setwatch()
        self.rsh(target, "sudo pcs resource cleanup galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched
        rc = self.rsh(target, "sudo pcs resource manage galera")
        assert rc == 0, "Unable to manage resource galera"

    def teardown_scenario(self, cluster_manager):
        cluster_manager.log("Leaving cluster running on all nodes")

scenarios[OpenStack].append(OpenStackReuseOvercloud)
