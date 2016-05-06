#!/usr/bin/env python

'''Resource Agent Tester

ScenarioComponent utilities and base classes, extends Pacemaker's CTS
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


class RATesterScenarioComponent(ScenarioComponent):
    '''Assertion-friendly base class for scenario setup/teardown.
    '''
    def __init__(self, environment, verbose=True):
        self.rsh = RemoteFactory().getInstance()
        self.logger = LogFactory()
        self.Env = environment
        self.verbose = verbose

    def IsApplicable(self):
        return 1

    def SetUp(self, cluster_manager):
        try:
            self.setup_scenario(cluster_manager)
            return 1
        except AssertionError as e:
            print("Setup of scenario %s failed: %s"%\
                  (self.__class__.__name__,str(e)))
        return 0

    def TearDown(self, cluster_manager):
        try:
            self.teardown_scenario(cluster_manager)
            return 1
        except AssertionError as e:
            print("Teardown of scenario %s failed: %s"%\
                  (self.__class__.__name__,str(e)))
        return 0

    def log(self, args):
        self.logger.log(args)

    def debug(self, args):
        self.logger.debug(args)

    def rsh_check(self, target, command, expected = 0):
        if self.verbose: self.log("> [%s] %s"%(target,command))
        res=self.rsh(target, command+" &>/dev/null")
        assert res == expected, "\"%s\" returned %d"%(command,res)



class SetupSTONITH(RATesterScenarioComponent):
    def IsApplicable(self):
        return self.Env.has_key("DoFencing")

    def setup_scenario(self, cluster_manager):
        cluster_manager.log("Enabling STONITH in cluster")
        self.rsh_check(self.Env["nodes"][0], "pcs stonith create stonith fence_virsh ipaddr=$(ip route | grep default | awk '{print $3}') secure=1 login=%s identity_file=/root/.ssh/fence-key action=reboot pcmk_host_list=%s"%\
                       (os.environ["USERNAME"], ",".join(self.Env["nodes"])))
        self.rsh_check(self.Env["nodes"][0], "pcs property set stonith-enabled=true")

    def teardown_scenario(self, cluster_manager):
        self.rsh_check(self.Env["nodes"][0], "pcs property set stonith-enabled=false")
        self.rsh_check(self.Env["nodes"][0], "pcs stonith delete stonith")
