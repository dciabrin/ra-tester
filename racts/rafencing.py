#!/usr/bin/env python

'''Resource Agent Tester

ScenarioComponent utilities and base classes, extends Pacemaker's CTS
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
from cts.CTStests import CTSTest
# from cts.CM_ais import crm_mcp
from cts.CTSscenarios import *
from cts.CTSaudits import *
from cts.CTSvars   import *
from cts.patterns  import PatternSelector
from cts.logging   import LogFactory
from cts.remote    import RemoteFactory
from cts.watcher   import LogWatcher
from cts.environment import EnvFactory

from racts.rascenario import RATesterScenarioComponent


class RATesterFencingComponent(RATesterScenarioComponent):
    def get_user_name(self):
        return os.environ.get("USERNAME", os.environ.get("USER"))

    def __init__(self, env):
        RATesterScenarioComponent.__init__(self, env)
        # we re-use the CTS' stonith-* params as configuration
        # of fencing. Only, we adapt the content to our needs.
        if self.Env["stonith-type"] == "fence_xvm":
            self.Env["stonith-params"] = ""
        elif self.Env["stonith-type"] == "external/ssh":
            self.Env["stonith-type"] = "fence_virsh"
            self.Env["stonith-params"] = "ipaddr=$(ip route | grep default | awk '{print $3}') secure=1 login=%s identity_file=/root/.ssh/fence-key " % self.get_user_name()

    def IsApplicable(self):
        return self.Env["stonith"] == True


class RATesterDefaultFencing(RATesterFencingComponent):
    def setup_scenario(self, cluster_manager):
        cluster_manager.log("Enabling fencing in cluster")
        self.rsh_check(self.Env["nodes"][0], "pcs stonith create fence %s %s action=reboot" % \
                       (self.Env["stonith-type"],
                        self.Env["stonith-params"]))
        self.rsh_check(self.Env["nodes"][0], "pcs property set stonith-enabled=true")

    def teardown_scenario(self, cluster_manager):
        # handy debug hook
        if self.Env.has_key("keep_resources"): return
        self.rsh_check(self.Env["nodes"][0], "pcs property set stonith-enabled=false")
        self.rsh_check(self.Env["nodes"][0], "pcs stonith delete fence")

default_fencing = RATesterDefaultFencing
