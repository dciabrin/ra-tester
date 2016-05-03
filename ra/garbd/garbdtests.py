'''Resource Agents Tester

Regression tests for garbd RA
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

from racts.ratest import ResourceAgentTest, ReuseCluster

tests = []

class GarbdRemoteTest(ResourceAgentTest):
    '''Base class for garbd tests on pacemaker remote node.
    Setup creates galera resource, and garbd running on remote node,
    both unstarted (target-state:disabled)
    Teardown deletes the resource'''
    def __init__(self, cm, verbose=False):
        ResourceAgentTest.__init__(self,cm)
        # self.start_cluster = False
        self.verbose = verbose

    def setup_test(self, node):
        '''Setup the given test'''
        # create galera and garbd resources, without starting them yet

        self.rsh_check(node, "pcs cluster cib galera.xml")
        self.rsh_check(node, "pcs -f galera.xml resource create galera galera enable_creation=true wsrep_cluster_address='gcomm://%s' meta master-max=2 ordered=true --master --disabled"% \
                       ",".join(self.Env["nodes"]))
        self.rsh_check(node, "pcs -f galera.xml constraint location galera-master rule resource-discovery=exclusive score=0 osprole eq controller")
        # TODO: clean wait for cib push completion
        self.rsh_check(node, "pcs cluster cib-push galera.xml && sleep 2")
        # Note: starting in target-role:Stopped first triggers a demote, then a stop
        # Note: adding a resource forces a first probe (INFO: MySQL is not running)

        self.rsh_check(node, "pcs cluster cib garbd.xml")
        self.rsh_check(node,
                       "pcs -f garbd.xml resource create garbd garbd wsrep_cluster_name='ratester' wsrep_cluster_address='gcomm://%s' op start timeout=30"% \
                       ",".join([x+":4567" for x in self.Env["nodes"]]))
        self.rsh_check(node, "pcs -f garbd.xml constraint location garbd rule resource-discovery=exclusive score=0 osprole eq arbitrator")
        self.rsh_check(node, "pcs -f garbd.xml constraint order start galera-master then start garbd")
        # TODO: clean wait for cib push completion
        self.rsh_check(node, "pcs cluster cib-push garbd.xml && sleep 2")

    def teardown_test(self, node):
        # delete garbd first
        self.rsh_check(node, "pcs resource delete garbd --wait")

        # delete galera
        # try to avoid cluster error when we stop the resource because
        # we don't know in which state it was left.
        # => tell pacemaker that we're going to stop galera, cleanup
        # any error that could prevent the stop, and let pacemaker
        # know the current state of the resource before processing
        # Note: if you clean and delete before pacemaker had a
        # chance to re-probe state, it will consider resource is stopped
        # and will happily delete the resource from the cib even if
        # galera is still running!
        # Note2: after a cleanup, pacemaker may log a warning log
        # if it finds the resource is still running. This does not
        # count as an error for the CTS test
        self.rsh_check(node, "pcs resource unmanage galera")
        patterns = [r"crmd.*:\s*Initiating action.*: probe_complete probe_complete-%s on %s"%(n,n) \
                    for n in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(node, "pcs resource cleanup galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched
        self.rsh_check(node, "pcs resource disable galera")
        self.rsh_check(node, "pcs resource manage galera")
        self.rsh_check(node, "pcs resource delete galera --wait")

    def errorstoignore(self):
        return [
            # currently, ERROR is logged before mysqld is started...
            r"ERROR:\s*MySQL is not running",
            # every SST finishes by killing rsynd on the joiner side...
            r"rsyncd.*:\s*rsync error: received SIGINT, SIGTERM, or SIGHUP"
        ]

class ClusterStart(GarbdRemoteTest):
    '''Start the galera cluster on all the nodes'''
    def __init__(self, cm):
        GarbdRemoteTest.__init__(self,cm)
        self.name = "ClusterStart"

    def test(self, target):
        '''Start an entire Garbd cluster'''
        # clean errors and force probe current state
        # this is my way of ensuring pacemaker will "promote" nodes
        # rather than just "monitoring" and finding "Master" state
        patterns = [r"crmd.*:\s*Operation %s_monitor.*:\s*%s \(node=%s,.*,\s*confirmed=true\)"%("galera", "not running", n) \
                    for n in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource cleanup galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        patterns = [r"crmd.*:\s*Operation %s_monitor.*:\s*%s \(node=%s,.*,\s*confirmed=true\)"%("garbd", "not running", "arb")]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource cleanup garbd")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # need to enable galera-master because of how we created the resource
        patterns = [self.templates["Pat:RscRemoteOpOK"] %("galera", "promote", n) \
                    for n in self.Env["nodes"]]
        patterns += [self.templates["Pat:RscRemoteOpOK"] %("garbd", "start", "arb")]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource enable galera-master")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

tests.append(ClusterStart)

class ClusterStop(ClusterStart):
    '''Ensure that Garbd is stopped when the galera cluster stop'''
    def __init__(self, cm):
        ClusterStart.__init__(self,cm)
        self.name = "ClusterStop"

    def test(self, target):
        # start cluster
        ClusterStart.test(self,target)

        patterns = [self.templates["Pat:RscRemoteOpOK"] %("galera", "stop", n) \
                    for n in self.Env["nodes"]]
        patterns += [self.templates["Pat:RscRemoteOpOK"] %("garbd", "stop", "arb")]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource disable galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

tests.append(ClusterStop)

class StopWhenDemotingLastGaleraNode(ClusterStart):
    '''Ensure garbd is stopped before the last galera node gracefully
    exits the galera cluster.

    This ensures that garbd will reconnect on next cluster bootstrap
    '''
    def __init__(self, cm):
        ClusterStart.__init__(self,cm)
        self.name = "StopWhenDemotingLastGaleraNode"

    def test(self, target):
        '''Ensure that Garbd is stopped when the galera cluster stop'''
        # start cluster
        ClusterStart.test(self,target)

        for ban_node in self.Env["nodes"]:
            patterns = [self.templates["Pat:RscRemoteOpOK"] %("galera", "stop", ban_node)]
            # last node? ensure garbd stops before galera,
            # to prevent garbd "monitor" failures
            if ban_node == self.Env["nodes"][-1]:
                patterns += [self.templates["Pat:RscRemoteOpOK"] %("garbd", "stop", "arb")]
            watch = self.create_watch(patterns, self.Env["DeadTime"])
            watch.setwatch()
            self.rsh_check(target, "pcs resource ban galera %s"%ban_node)
            watch.lookforall()
            assert not watch.unmatched, watch.unmatched

    def teardown_test(self, target):
        self.rsh_check(target, "pcs resource disable galera")
        for n in self.Env["nodes"]:
            self.rsh_check(target, "pcs constraint remove cli-ban-galera-on-%s"%n)
        ClusterStart.teardown_test(self, target)


tests.append(StopWhenDemotingLastGaleraNode)

class ErrorIfDisconnectFromAllNodes(ClusterStart):
    '''Ensure garbd is stopped before the last galera node gracefully
    exits the galera cluster.

    This ensures that garbd will reconnect on next cluster bootstrap
    '''
    def __init__(self, cm):
        ClusterStart.__init__(self,cm)
        self.name = "ErrorIfDisconnectFromAllNodes"

    def test(self, target):
        '''Ensure that Garbd is stopped when the galera cluster stop'''
        # start cluster
        ClusterStart.test(self,target)

        # make sure galera is not restarted by pacemaker
        self.rsh_check(target, "pcs resource unmanage galera")

        patterns=["notice:\s*(Stop|Recover)\s*%s\s*\(Started %s\)"%("garbd","arb")]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        for node in self.Env["nodes"]:
            self.rsh_check(node, "kill -9 $(cat /var/run/mysql/mysqld.pid)")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

    def teardown_test(self, target):
        self.rsh_check(target, "pcs resource disable galera")
        ClusterStart.teardown_test(self, target)

    def errorstoignore(self):
        return [
            # currently, ERROR is logged before mysqld is started...
            r"ERROR: MySQL is not running",
            # expected after we force-killed the galera servers
            r"ERROR: MySQL not running: removing old PID file",
            # garbd will complain that it lost connection w/ galera cluster
            r"ERROR: garbd disconnected from cluster \".*\""
        ]

tests.append(ErrorIfDisconnectFromAllNodes)

class DontRestartBeforeGaleraIsRestarted(ErrorIfDisconnectFromAllNodes):
    '''Ensure garbd is stopped before the last galera node gracefully
    exits the galera cluster.

    This ensures that garbd will reconnect on next cluster bootstrap
    '''
    def __init__(self, cm):
        ClusterStart.__init__(self,cm)
        self.name = "DontRestartBeforeGaleraIsRestarted"

    def test(self, target):
        '''Ensure that Garbd is stopped when the galera cluster stop'''
        # start cluster
        ErrorIfDisconnectFromAllNodes.test(self,target)

        patterns=["notice:\s*Start\s*%s\s*\(%s - blocked\)"%("garbd","arb")]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource cleanup garbd")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

tests.append(DontRestartBeforeGaleraIsRestarted)
