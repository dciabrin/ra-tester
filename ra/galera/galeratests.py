#!/usr/bin/env python

'''Resource Agents Tester

Regression tests for galera RA
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


class GaleraTest(ResourceAgentTest):
    '''Base class for galera tests.
    Setup creates a galera resource, unstarted (target-state:disabled)
    Teardown deletes the resource'''
    def __init__(self, cm, verbose=False):
        ResourceAgentTest.__init__(self,cm)
        # self.start_cluster = False
        self.verbose = verbose

    def setup_test(self, node):
        '''Setup the given test'''
        # create a galera resource, without starting it yet
        self.rsh_check(node,
                       "pcs resource create galera galera enable_creation=true wsrep_cluster_address='gcomm://%s' meta master-max=3 ordered=true --master --disabled"% \
                       ",".join(self.Env["nodes"]))
        # Note: starting in target-role:Stopped first triggers a demote, then a stop
        # Note: adding a resource forces a first probe (INFO: MySQL is not running)

    def teardown_test(self, node):
        # give back control to pacemaker in case the test disabled it
        self.rsh_check(node, "pcs resource manage galera")

        # delete the galera resource create for this test
        # note: deleting a resource triggers an implicit stop, and that
        # implicit delete will fail when ban constraints are set.
        self.rsh_check(node, "pcs resource delete galera")

    def errorstoignore(self):
        return [
            # currently, ERROR is logged before mysqld is started...
            r"ERROR:\s*MySQL is not running",
            # every SST finished by killing rsynd on the joiner side...
            r"rsyncd.*:\s*rsync error: received SIGINT, SIGTERM, or SIGHUP"
        ]


class ClusterStart(GaleraTest):
    '''Start the galera cluster on all the nodes'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "ClusterStart"

    def test(self, target):
        '''Start an entire Galera cluster'''
        # clean errors and force probe current state
        # this is my way of ensure pacemaker will "promote" nodes
        # rather than just "monitoring" and finding "Master" state
        patterns = [r"crmd.*:\s*Operation %s_monitor.*:\s*%s \(node=%s,.*,\s*confirmed=true\)"%("galera", "not running", n) \
                    for n in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource cleanup galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # need to enable galera-master because of how we created the resource
        patterns = [self.templates["Pat:RscRemoteOpOK"] %("galera", "promote", n) \
                    for n in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource enable galera-master")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

tests.append(ClusterStart)


class ClusterStop(ClusterStart):
    '''Stop the galera cluster'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "ClusterStop"

    def test(self, dummy):
        # start cluster
        ClusterStart.test(self,dummy)

        patterns = [self.templates["Pat:RscRemoteOpOK"] %("galera", "stop", n) \
                    for n in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])

        watch.setwatch()
        self.rsh_check(self.Env["nodes"][0], "pcs resource disable galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # ensure all things are cleaned up after stop
        for target in self.Env["nodes"]:
            self.crm_attr_check(target, "master-galera", expected = 6)
            self.crm_attr_check(target, "galera-last-committed", expected = 6)
            self.crm_attr_check(target, "galera-bootstrap", expected = 6)
            self.crm_attr_check(target, "galera-sync-needed", expected = 6)
            self.crm_attr_check(target, "galera-no-grastate", expected = 6)

tests.append(ClusterStop)


class NodeForceStartBootstrap(GaleraTest):
    '''Force-bootstrap Galera on a single node'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeForceStartBootstrap"

    def test(self, node):
        '''Ban all nodes except one, to block promotion to master, and force promote manually on one node.'''
        target = node
        unwanted_nodes = [x for x in self.Env["nodes"] if x != target]

        # ban unwanted nodes, so that pacemaker won't try to start resource on them
        for n in unwanted_nodes:
            self.rsh_check(n, "pcs resource ban galera-master %s"%n)

        # set galera management away of pacemaker's control
        self.rsh_check(target, "pcs resource unmanage galera")

        # due to how we created the resource, we must reset
        # target-role to master, to prevent pacemaker to demote
        # after manual override
        self.rsh_check(target, "pcs resource enable galera-master")

        # force status of target node to "bootstrap" and promote it
        self.crm_attr_set(target, "galera-bootstrap", "true")
        self.crm_attr_set(target, "master-galera", "100")
        self.rsh_check(target, "crm_resource --force-promote -r galera")

        # instruct pacemaker to redetect the state of the galera resource
        # note: it seems patterns "galera_monitor_0:" are only logged
        # for probe actions, not on regular monitor timers...
        pattern = r"crmd.*:\s*Operation %s_monitor.*:\s*%s \(node=%s,.*,\s*confirmed=true\)"%("galera", "master", target)
        watch = self.create_watch([pattern], self.Env["DeadTime"])

        watch.setwatch()
        self.rsh_check(target, "pcs resource cleanup galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # once a node is started, last-committed should be removed
        self.crm_attr_check(target, "galera-last-committed", expected = 6)

        # once a bootstrap node promoted, bootstrap should be removed
        self.crm_attr_check(target, "galera-bootstrap", expected = 6)

        # a bootstrap node never requires sync-ing
        self.crm_attr_check(target, "sync-needed", expected = 6)

        # once a node is running, boot status should be cleared
        self.crm_attr_check(target, "no-grastate", expected = 6)

tests.append(NodeForceStartBootstrap)


class NodeForceStartJoining(ClusterStart):
    '''Force a node to join a Galera cluster'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeForceStartJoining"

    def test(self, node):
        '''TODO'''
        # start cluster
        ClusterStart.test(self,node)

        # stop a node so that pacemaker restart it from the "start" op
        # note: by test "ClusterStop", we know sync-needed is unset
        self.rsh_check(node, "crm_resource --force-stop -r galera")

        # the "start" op only tags this node as a joining node.
        # the galera server is started during the "monitor" op (1) and
        # a promotion is triggered after the node has synced to the
        # cluster (2), potentially during the same "monitor" op

        # we want to track (1) and (2).
        # TODO: double check (1) and (2) with attribute "sync-needed"
        patterns = [r"INFO: Node <%s> is joining the cluster"%(node,),
                    r"INFO: local node synced with the cluster",
                    self.templates["Pat:RscRemoteOpOK"] %("galera", "promote", node)]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        # TODO potential race, we should stop the node here
        # to make sure we catch all the logs
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # "promote" op for joining node is almost a no-op, though
        # once a node is running, boot status should be cleared
        self.crm_attr_check(node, "no-grastate", expected = 6)

tests.append(NodeForceStartJoining)


class NodeCheckDemoteCleanUp(GaleraTest):
    '''Ensure that a "demote" op cleans up galera attributes in the CIB'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeCheckDemoteCleanUp"

    def test(self, node):
        # set galera management away of pacemaker's control.
        # note: resource is stopped, so pacemaker will also disable
        # regular monitoring that could mess with the test
        self.rsh_check(node, "pcs resource unmanage galera")

        # first promote the node
        self.crm_attr_set(node, "galera-bootstrap", "true")
        self.crm_attr_set(node, "master-galera", "100")
        self.rsh_check(node, "crm_resource --force-promote -r galera")

        # ensure things are cleaned up after a demote
        self.rsh_check(node, "crm_resource --force-demote -r galera")
        self.crm_attr_check(node, "galera-bootstrap", expected = 6)
        self.crm_attr_check(node, "galera-sync-needed", expected = 6)

        # last-committed is not cleaned automatically by a "demote" op
        # because it is useful for subsequent bootstraps
        self.crm_attr_del(node, "galera-last-committed")

        # note: master score is cleaned automatically only when
        # pacemaker manages the resource
        self.crm_attr_del(node, "master-galera")

tests.append(NodeCheckDemoteCleanUp)


class NodeRecoverWhileClusterIsRunning(ClusterStart):
    '''Kill a node during a transaction, ensure it is restarted
    Expected flow:
      * kill a node
      * pcmk monitor detects that -> pcmk calls demote
        - demote calls detect_last_commit
      * pcmk calls stop
      * pcmk calls start -> node will be a joiner
      * monitor -> galera started as joiner

    Note: recovery happens in demote, as it tries to recover last-commit
    '''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeRecoverWhileClusterIsRunning"

    def test(self, target):
        # start cluster, prepare nodes to be killed
        ClusterStart.test(self,target)

        # prepare data to trigger a kill
        self.rsh_check(target, "mysql -e 'drop database if exists racts; drop table if exists racts.break; create database racts; create table racts.break (i int) engine=innodb;'");
        self.rsh_bg(target, "gdb -x /tmp/kill-during-txn.gdb -p `cat /var/run/mysql/mysqld.pid`")

        # racy sleep to allow gdb to engage
        time.sleep(3)

        patterns = [r"local node.*was not shutdown properly. Rollback stuck transaction with --tc-heuristic-recover",
                    r"Node <%s> is joining the cluster"%(target,),
                    r"INFO: local node synced with the cluster",
                    self.templates["Pat:RscRemoteOpOK"] %("galera", "promote", target)]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        triggernode=[x for x in self.Env["nodes"] if x != target][0]
        self.rsh_check(triggernode, "mysql -e 'insert into racts.break values (42);'")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + [
            r"ERROR: MySQL not running: removing old PID file",
        ]

tests.append(NodeRecoverWhileClusterIsRunning)


class NodeDontChooseForBootstrappingCluster(ClusterStart):
    '''Ensure that a node which is missing grastate.dat will
    not be choosing if other node can bootstrap the cluster.
    '''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeDontChooseForBootstrappingCluster"

    def test(self, target):
        # The bootstrap node selection is an ordered process,
        # if all nodes are in sync, node3 shall be selected.
        # removing grastate from node3 will have the effect
        # of selecting node2 to bootstrap
        target = self.Env["nodes"][-1]
        self.rsh_check(target, "rm -f /var/lib/mysql/grastate.dat")

        target_bootstrap = self.Env["nodes"][-2]
        # start cluster and ensure that target wait sufficiently
        # long that a monitor op catched it during sync
        patterns = [r".*INFO: Node <%s> is bootstrapping the cluster"%target_bootstrap]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        ClusterStart.test(self, target)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched
        # the transient boot state tracking attribute should be cleared
        # once node3 is running as Master
        self.crm_attr_check(target, "galera-no-grastate", expected = 6)

tests.append(NodeDontChooseForBootstrappingCluster)


class ClusterBootWithoutGrastateOnDisk(ClusterStart):
    '''Ensure that the cluster will boot even if no grastate.dat can
    be found on any of the nodes.
    '''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "ClusterBootWithoutGrastateOnDisk"

    def test(self, target):
        for n in self.Env["nodes"]:
            self.rsh_check(n, "rm -f /var/lib/mysql/grastate.dat")

        # The bootstrap node selection is an ordered process,
        # if all nodes are in sync, node3 shall be selected.
        target_bootstrap = self.Env["nodes"][-1]
        patterns = [r".*INFO: Node <%s> is bootstrapping the cluster"%target_bootstrap]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        ClusterStart.test(self, target)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched
        # the transient boot state tracking attribute should be cleared
        for n in self.Env["nodes"]:
            self.crm_attr_check(n, "galera-no-grastate", expected = 6)

tests.append(ClusterBootWithoutGrastateOnDisk)


class NodeRecoverWhileStartingCluster(ClusterStart):
    '''Ensure that a node killed during a transaction does not block cluster bootstrap'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeRecoverWhileStartingCluster"

    def test(self, target):
        # start cluster, prepare nodes to be killed
        ClusterStart.test(self, target)

        # prepare data to trigger a kill
        self.rsh_check(target, "mysql -e 'drop database if exists racts; drop table if exists racts.break; create database racts; create table racts.break (i int) engine=innodb;'");
        self.rsh_bg(target, "gdb -x /tmp/kill-during-txn.gdb -p `cat /var/run/mysql/mysqld.pid`")

        # set galera management away of pacemaker's control
        self.rsh_check(target, "pcs resource unmanage galera")

        # set target-role to stopped, to prevent pacemaker to
        # restart the to-be-killed node
        self.rsh_check(target, "pcs resource disable galera-master")

        # racy sleep to allow gdb to engage
        time.sleep(3)

        patterns = [r"ERROR: MySQL not running: removing old PID file"]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        triggernode=[x for x in self.Env["nodes"] if x != target][0]
        self.rsh_check(triggernode, "mysql -e 'insert into racts.break values (42);'")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # there might be error due to loss of quorum, as
        # we'll ask for stop before killed target has been flagged
        # as out of cluster in galera.
        # clean up errors in cib before re-enabling pacemaker,
        # this will also prevent pacemaker to try to restart the
        # killed node before stop. (TODO: am i correct here?)
        patterns = [self.templates["Pat:RscRemoteOpOK"] %("galera", "stop", n) \
                    for n in self.Env["nodes"] if n != target]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource cleanup galera")
        self.rsh_check(target, "pcs resource manage galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # restart cluster, ensure recovered node was not selected as
        # bootstrap. TODO: ensure it joined cluster via SST
        patterns = [r"Node (?!<%s>).*is bootstrapping the cluster"%target,
                    r"local node.*was not shutdown properly. Rollback stuck transaction with --tc-heuristic-recover"]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        ClusterStart.test(self,target)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched
        self.crm_attr_check(target, "galera-no-grastate", expected = 6)

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + [
            r"ERROR: MySQL not running: removing old PID file",
        ]

tests.append(NodeRecoverWhileStartingCluster)


class ClusterRestartAfter2RecoveredNodes(ClusterStart):
    '''Ensure cluster recovers after several nodes killed during a transaction'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "ClusterRestartAfter2RecoveredNodes"

    def test(self, target):
        to_break = [x for x in self.Env["nodes"] if x != target]

        # start cluster, prepare nodes to be killed
        ClusterStart.test(self, target)

        # prepare data to trigger a kill
        self.rsh_check(target, "mysql -e 'drop database if exists racts; drop table if exists racts.break; create database racts; create table racts.break (i int) engine=innodb;'");
        for node in to_break:
            self.rsh_bg(node, "gdb -x /tmp/kill-during-txn.gdb -p `cat /var/run/mysql/mysqld.pid`")

        # racy sleep to allow gdb to engage
        time.sleep(3)

        # kill two nodes died, the remaining will go Non-Primary
        # due to loss of quorum. pacemaker will stop it and restart
        # all the cluster -> bootstrap
        # ensure the bootstrap node is not a recovered one
        patterns = [r"local node <%s> is started, but not in primary mode. Unknown state." % target,
                   r"Node <%s> is bootstrapping the cluster" % target] + \
                   [r"local node <%s> was not shutdown properly. Rollback stuck transaction with --tc-heuristic-recover"%node for node in to_break] + \
                   [self.templates["Pat:RscRemoteOpOK"] %("galera", "promote", node) for node in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "mysql -e 'insert into racts.break values (42);'")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # ensure recovered state is cleaned up
        for node in to_break:
            self.crm_attr_check(node, "galera-no-grastate", expected = 6)

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + [
            r"ERROR: MySQL not running: removing old PID file",
            r"local node <.*> is started, but not in primary mode. Unknown state."
        ]

tests.append(ClusterRestartAfter2RecoveredNodes)


class ClusterRestartAfterAllNodesRecovered(ClusterStart):
    '''Ensure cluster recovers after all nodes killed during a transaction!'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "ClusterRestartAfterAllNodesRecovered"

    def test(self, target):
        all_nodes = self.Env["nodes"]

        # start cluster, prepare nodes to be killed
        ClusterStart.test(self, target)

        # prepare data to trigger a kill
        self.rsh_check(target, "mysql -e 'drop database if exists racts; drop table if exists racts.break; create database racts; create table racts.break (i int) engine=innodb;'");
        for node in all_nodes:
            self.rsh_bg(node, "gdb -x /tmp/kill-during-txn.gdb -p `cat /var/run/mysql/mysqld.pid`")

        # racy sleep to allow gdb to engage
        time.sleep(3)

        # Oh my! all the nodes broke in the middle of a transaction
        # this will make the SQL statement fail, and the bootstrap
        # node will be a recovered one.
        # NOTE: bootstrapping a node which doesn't have grastate.dat
        # will result in the cluster's seqno to restart from 0
        patterns = [r"local node <%s> was not shutdown properly. Rollback stuck transaction with --tc-heuristic-recover"%node for node in all_nodes] + \
                   [self.templates["Pat:RscRemoteOpOK"] %("galera", "promote", node) for node in all_nodes]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "mysql -e 'insert into racts.break values (42);'", expected=1)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # ensure recovered state is cleaned up
        for node in all_nodes:
            self.crm_attr_check(node, "galera-no-grastate", expected = 6)

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + [
            r"ERROR: MySQL not running: removing old PID file"
        ]


tests.append(ClusterRestartAfterAllNodesRecovered)


class NodeLongRunningSST(ClusterStart):
    '''Ensure that a long running SST can finish without being killed by
       start or promote timeout
       It is assumed nodes are in sync prior to this test
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeLongRunningSST"

    def create_big_file(self, node):
        self.rsh_check(node, "mkdir -p /var/lib/mysql/big_file && dd if=/dev/urandom bs=1024 count=200000 of=/var/lib/mysql/big_file/for_sst && chown -R mysql. /var/lib/mysql/big_file")

    def prepare_node_for_sst(self, node):
        # force SST at restart for the target, and ensure
        # node won't be chosen as a the bootstrap node,
        # this is correct as per test `NodeDontChooseForBootstrappingCluster`
        self.rsh_check(node, "rm -f /var/lib/mysql/grastate.dat")

    def setup_test(self, target):
        # tmp hack: make first node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        # target = self.Env["nodes"][0]

        ClusterStart.setup_test(self, target)
        # TODO: ensure all nodes are in sync (same wsrep seqno)

        # in this test, target is the joiner
        for node in self.Env["nodes"]:
            self.rsh_check(node, "/tmp/slow_down_sst.sh -n %s on"%node)
            # create big file on potential donor nodes
            if node != target:
                self.create_big_file(node)

        self.prepare_node_for_sst(target)

    def test(self, target):
        # tmp hack: make first node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        # target = self.Env["nodes"][0]

        # start cluster and ensure that target wait sufficiently
        # long that a monitor op catched it during sync
        patterns = [r"%s.*INFO: local node syncing"%target,
                    r"%s.*INFO: local node synced with the cluster"%target]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        ClusterStart.test(self, target)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

    def teardown_test(self, target):
        for node in self.Env["nodes"]:
            self.rsh_check(node, "/tmp/slow_down_sst.sh -n %s off || true"%node)
            self.rsh_check(node, "rm -rf /var/lib/mysql/big_file")
        ClusterStart.teardown_test(self, target)

tests.append(NodeLongRunningSST)


class ClusterStartWith2LongRunningSST(NodeLongRunningSST):
    '''Ensure that all joiner can finish long running SST without being killed by
       start or promote timeout or wsrep protocol itself

       Having only one donor available (the bootstrap node), SST will
       be sequential: one joiner will fail to get an available donor, and retry
       every second until donor is available again.
       It is assumed nodes are in sync prior to this test
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "ClusterStartWith2LongRunningSST"

    def setup_test(self, target):
        # tmp hack: make last node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        # target = self.Env["nodes"][-1]

        ClusterStart.setup_test(self, target)

        # TODO: ensure all nodes are in sync (same wsrep seqno)

        # in this test, target is the donor
        for node in self.Env["nodes"]:
            self.rsh_check(node, "/tmp/slow_down_sst.sh -n %s on"%node)
            if node == target:
                self.create_big_file(node)
            else:
                self.prepare_node_for_sst(node)

    def test(self, target):
        # tmp hack: make last node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        # target = self.Env["nodes"][-1]

        patterns = []
        # start cluster and ensure that all joiners run SST
        for joiner in [n for n in self.Env["nodes"] if n != target]:
            patterns.extend([r"%s.*INFO: local node syncing"%joiner,
                             r"%s.*INFO: local node synced with the cluster"%joiner])
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        ClusterStart.test(self, target)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # TODO: check log "wait for available donor" in mysqld.log

    def teardown_test(self, target):
        for node in self.Env["nodes"]:
            self.rsh_check(node, "/tmp/slow_down_sst.sh -n %s off || true"%node)
            self.rsh_check(node, "rm -rf /var/lib/mysql/big_file")
        ClusterStart.teardown_test(self, target)

tests.append(ClusterStartWith2LongRunningSST)
