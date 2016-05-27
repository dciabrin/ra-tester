#!/usr/bin/env python

'''Resource Agent Tester

Test utilities and base classes, extends Pacemaker's CTS
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



class ReuseCluster(ScenarioComponent):
    '''Use an existing cluster for running tests.
    This assumes the cluster is in good shape, and that
    it does not contain any resource conflicting with the tests'''

    def IsApplicable(self):
        return 1

    def SetUp(self, cluster_manager):
        return 1

    def TearDown(self, cluster_manager):
        return 1


class ResourceAgentTest(CTSTest):
    '''Assertion-friendly base class for resource agent tests'''
    def __init__(self, cm, verbose=False):
        CTSTest.__init__(self,cm)
        # self.start_cluster = False
        self.name = "GenericRATest"
        self.bg = {}
        self.verbose = verbose

    def setup(self, node):
        '''Setup test before execution'''
        try:
            self.setup_test(node)
            return self.success()
        except AssertionError as e:
            return self.failure(str(e))
        return self.success()

    def __call__(self, node):
        '''Execute the test'''
        # called only once for all nodes
        self.incr("calls")
        try:
            self.test(node)
            return self.success()
        except AssertionError as e:
            return self.failure(str(e))

    def teardown(self, node):
        '''Teardown, cleanup resource after the test'''
        try:
            self.teardown_test(node)
            return self.success()
        except AssertionError as e:
            return self.failure(str(e))

    def crm_attr_set(self, target, attribute, value, expected = 0):
        command="crm_attribute -N %s -l reboot --name %s -v %s"% \
                     (target, attribute, value)
        if self.verbose: self.log("> [%s] %s"%(target,command))
        res=self.rsh(target, command+" &>/dev/null")
        assert res == expected, "set crm attribute \"%s\" returned %d (expected %d)"% \
            (attribute,res,expected)

    def crm_attr_check(self, target, attribute, expected = 0, expected_value = 0):
        command="crm_attribute -N %s -l reboot --name %s -Q"% \
                     (target, attribute)
        if self.verbose: self.log("> [%s] %s"%(target,command))
        res=self.rsh(target, command+" &>/dev/null")
        assert res == expected, "get crm attribute \"%s\" returned %d (expected %d)"% \
            (attribute,res,expected)

    def crm_attr_del(self, target, attribute, expected = 0, expected_value = 0):
        command="crm_attribute -N %s -l reboot --name %s -D"% \
                     (target, attribute)
        if self.verbose: self.log("> [%s] %s"%(target,command))
        res=self.rsh(target, command+" &>/dev/null")
        assert res == expected, "del crm attribute \"%s\" returned %d (expected %d)"% \
            (attribute,res,expected)

    def rsh_check(self, target, command, expected = 0):
        if self.verbose: self.log("> [%s] %s"%(target,command))
        temp="ratester-tmp%f"%time.time()
        res=self.rsh(target, command+" &>"+temp)
        if res != expected:
            self.rsh(target, "mv %s '%s-%s-%d'"%(temp, temp, command, res))
        else:
            self.rsh(target, "rm -f %s"%temp)
        assert res == expected, "\"%s\" returned %d"%(command,res)

    def rsh_bg(self, target, command, expected = 0):
        # TODO: multiple bg jobs per target
        # if target not in self.bg:
        #     self.rsh_check(target, "screen -S %s -d -m"%self.name)
        #     self.bg[target]=True
        # self.rsh_check(target, "screen -S %s -X stuff '%s\r'"%(self.name,command) )
        self.rsh_check(target, "screen -S %s -d -m %s"%(self.name,command) )

    def wait_until_restarted(self, node, timeout=60):
        start=time.time()
        alive = False
        while not alive:
            time.sleep(3)
            assert time.time()-start < timeout, "Restart timeout exceeded"
            res = self.rsh(node, "true")
            if res == 0: alive = True
