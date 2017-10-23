#!/usr/bin/env python

'''Resource Agents Tester

Regression tests for galera RA
Node-centric test cases, validating behaviour of recovery scenarios.
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

from .galeratests import GaleraTest, ClusterStart

tests = []


class NodeForceStartBootstrap(GaleraTest):
    '''Force-bootstrap Galera on a single node'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeForceStartBootstrap"

    def test(self, node):
        '''Ban all nodes except one, to block promotion to master, and force promote manually on one node.
              . start the resource so that it stays in slave state (because some nodes are baned)
              . unmanage the resource to set it out of pacemaker control
              . manually trigger a promotion operation'''
        target = node
        unwanted_nodes = [x for x in self.Env["nodes"] if x != target]

        # ban unwanted nodes, so that pacemaker won't try to start resource on them
        for n in unwanted_nodes:
            self.rsh_check(n, "pcs resource ban %s %s"%(self.Env["galera_rsc_name"], n))

        # note: this is also needed for bundles because we want the
        # docker resource and the pacemaker remote resource to be
        # started

        target_nodes=self.Env["nodes"]
        ## bundles run resources on container nodes, not host nodes
        if self.Env["galera_bundle"]:
            target_nodes=["galera-bundle-%d"%x for x in range(len(self.Env["nodes"]))]
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "start", "galera", n, 'ok') \
                    for n in target_nodes]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource enable %s"%self.Env["galera_rsc_name"])
        watch.look()

        # set galera management away of pacemaker's control
        self.rsh_check(target, "pcs resource unmanage galera")

        # force status of target node to "bootstrap" and promote it
        # note: in the current RA, once a node is promoted, it forces
        # other nodes to go master. Since the resource is unmanaged,
        # that sets phantom attributes "master-galera:0" in the CIB
        self.crm_attr_set(target, "galera-bootstrap", "true")
        self.crm_attr_set(target, "master-galera", "100")
        promotecmd="crm_resource --force-promote -r galera"
        if self.Env["galera_bundle"]:
            promotecmd="docker exec $(docker ps -f name=galera-bundle -q) /bin/bash -c 'OCF_RESKEY_CRM_meta_container_attribute_target=host OCF_RESKEY_CRM_meta_physical_host=%s %s'"%(target,promotecmd)
        self.rsh_check(target, promotecmd)

        # remove unwanted "master-galera:0" attributes
        for n in self.Env["nodes"]:
            self.rsh_check(n, "crm_attribute -N %s -l reboot --name master-galera:0 -D"%n)

        # time.sleep(30);

        # instruct pacemaker to re-probe the state of the galera resource
        if self.Env["galera_bundle"]:
            # bundles run resource on container node, which may have a
            # name depending on resource allocation, so be generic
            # TODO use real bundle target
            probe_target = '.*'
        else:
            probe_target = target
        pattern = self.ratemplates.build("Pat:RscRemoteOp", "probe", "galera", probe_target, 'master')
        watch = self.create_watch([pattern], self.Env["DeadTime"])

        watch.setwatch()
        self.rsh_check(target, "pcs resource cleanup %s"%self.Env["galera_rsc_name"])
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
        stopcmd="crm_resource --force-stop -r galera"
        if self.Env["galera_bundle"]:
            stopcmd="docker exec $(docker ps -f name=galera-bundle -q) /bin/bash -c 'OCF_RESKEY_CRM_meta_container_attribute_target=host OCF_RESKEY_CRM_meta_physical_host=%s %s'"%(node,stopcmd)
        self.rsh_check(node, stopcmd)

        # the "start" op only tags this node as a joining node.
        # the galera server is started during the "monitor" op (1) and
        # a promotion is triggered after the node has synced to the
        # cluster (2), potentially during the same "monitor" op

        # we want to track (1) and (2).
        # TODO: double check (1) and (2) with attribute "sync-needed"
        if self.Env["galera_bundle"]:
            # bundles run resource on container node, which may have a
            # name depending on resource allocation, so be generic
            # TODO use real bundle target
            probe_target = '.*'
        else:
            probe_target = node
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "promote", "galera", probe_target, 'ok')]
        # newer version of the RA
        # patterns = [r"INFO: Node <%s> is joining the cluster"%(node,),
        #             r"INFO: local node synced with the cluster"]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        # TODO potential race, we should stop the node here
        # to make sure we catch all the logs
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # "promote" op for joining node is almost a no-op, though
        # once a node is running, boot status should be cleared
        self.crm_attr_check(node, "no-grastate", expected = 6)

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
               GaleraTest.errors_after_forced_stop(self)

tests.append(NodeForceStartJoining)


class NodeCheckDemoteCleanUp(GaleraTest):
    '''Ensure that a "demote" op cleans up galera attributes in the CIB'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeCheckDemoteCleanUp"

    def test(self, node):
        # note: for bundle we need to start the galera resource up to
        # 'Slave' resource, for the container resource to be started
        target = node
        unwanted_nodes = [x for x in self.Env["nodes"] if x != target]

        # ban unwanted nodes, so that pacemaker won't try to start resource on them
        for n in unwanted_nodes:
            self.rsh_check(n, "pcs resource ban %s %s"%(self.Env["galera_rsc_name"], n))

        # note: this is also needed for bundles because we want the
        # docker resource and the pacemaker remote resource to be
        # started

        target_nodes=self.Env["nodes"]
        ## bundles run resources on container nodes, not host nodes
        if self.Env["galera_bundle"]:
            target_nodes=["galera-bundle-%d"%x for x in range(len(self.Env["nodes"]))]
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "start", "galera", n, 'ok') \
                    for n in target_nodes]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource enable %s"%self.Env["galera_rsc_name"])
        watch.look()

        # set galera management away of pacemaker's control.
        # note: resource is stopped, so pacemaker will also disable
        # regular monitoring that could mess with the test
        self.rsh_check(node, "pcs resource unmanage galera")

        # first promote the node
        self.crm_attr_set(node, "galera-bootstrap", "true")
        self.crm_attr_set(node, "master-galera", "100")
        promotecmd="crm_resource --force-promote -r galera"
        if self.Env["galera_bundle"]:
            promotecmd="docker exec $(docker ps -f name=galera-bundle -q) /bin/bash -c 'OCF_RESKEY_CRM_meta_container_attribute_target=host OCF_RESKEY_CRM_meta_physical_host=%s %s'"%(node,promotecmd)
        self.rsh_check(node, promotecmd)

        # remove unwanted "master-galera:0" attributes
        for n in self.Env["nodes"]:
            self.rsh_check(n, "crm_attribute -N %s -l reboot --name master-galera:0 -D"%n)

        # ensure things are cleaned up after a demote
        demotecmd="crm_resource --force-demote -r galera"
        if self.Env["galera_bundle"]:
            demotecmd="docker exec $(docker ps -f name=galera-bundle -q) /bin/bash -c 'OCF_RESKEY_CRM_meta_container_attribute_target=host OCF_RESKEY_CRM_meta_physical_host=%s %s'"%(node,demotecmd)
        self.rsh_check(node, demotecmd)
        self.crm_attr_check(node, "galera-bootstrap", expected = 6)
        self.crm_attr_check(node, "galera-sync-needed", expected = 6)

        # last-committed is not cleaned automatically by a "demote" op
        # because it is useful for subsequent bootstraps
        self.crm_attr_del(node, "galera-last-committed")

        # note: master score is cleaned automatically only when
        # pacemaker manages the resource
        self.crm_attr_del(node, "master-galera")

tests.append(NodeCheckDemoteCleanUp)


class NodeRestartOnErrorIfMaster(ClusterStart):
    '''Trigger an error condition during Master state (stop the node),
    Ensure that the node is restarted automatically at next restart
    Expected flow:
      * stop the node
      * monitor detects a failure (during master) ->
        - pcmk calls demote
        - pcmk calls stop
      * pcmk calls start -> node will be a joiner
      * monitor restart a galera node
      * sync monitor sets master score when ist is over
      * pcmk calls promote
    '''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeRestartOnErrorIfMaster"

    def test(self, target):
        # start cluster, prepare nodes to be killed
        ClusterStart.test(self,target)

        # check whether master stops the resource as expected and
        # does not respawn galera yet
        target_nodes=[target]
        ## bundles run resources on container nodes, not host nodes
        if self.Env["galera_bundle"]:
            target_nodes=["galera-bundle-%d"%x for x in range(len(self.Env["nodes"]))]
        patterns = [r"galera\(%s\).*INFO:\s+Galera started"]
        patterns += [self.ratemplates.build("Pat:RscRemoteOp", "stop", "galera", t, 'ok')
                     for t in target_nodes]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "mysqladmin shutdown")
        matched = watch.look()
        assert "Galera started" not in matched, matched

        # galera should get respawn during a monitor operation and
        # resource should go to master
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "promote", "galera", t, 'ok')
                     for t in target_nodes]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        watch.look()
        assert not watch.unmatched, watch.unmatched

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
               GaleraTest.errors_after_forced_stop(self)

tests.append(NodeRestartOnErrorIfMaster)


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

    def is_applicable(self):
        # mariadb 10.1+ seems to be immune to pending XA
        return self.rsh(self.Env["nodes"][0],
                        "mysql --version | awk '{print $5}' | awk -F. '$1==5 && $2==5 {print 1}' | grep 1") == 0

    def test(self, target):
        # start cluster, prepare nodes to be killed
        ClusterStart.test(self,target)

        # prepare data to trigger a kill
        self.rsh_check(target, "mysql -e 'drop database if exists racts; drop table if exists racts.break; create database racts; create table racts.break (i int) engine=innodb;'");
        self.rsh_bg(target, "gdb -x /tmp/kill-during-txn.gdb -p `cat /var/run/mysql/mysqld.pid`")

        # racy sleep to allow gdb to engage
        time.sleep(3)

        patterns = [r"local node.*was not shutdown properly. Rollback stuck transaction with --tc-heuristic-recover",
                    self.ratemplates.build("Pat:RscRemoteOp", "promote", "galera", target, 'ok')]
        # newer version of the RA
        # patterns += [r"Node <%s> is joining the cluster"%(target,),
        #              r"INFO: local node synced with the cluster"]

        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        triggernode=[x for x in self.Env["nodes"] if x != target][0]
        self.rsh_check(triggernode, "mysql -e 'insert into racts.break values (42);'")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
               GaleraTest.errors_after_forced_stop(self)

tests.append(NodeRecoverWhileClusterIsRunning)


class NodeDontChooseForBootstrappingCluster(ClusterStart):
    '''Ensure that a node which is missing grastate.dat will
    not be choosing if other node can bootstrap the cluster.
    '''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeDontChooseForBootstrappingCluster"

    def is_applicable(self):
        return self.rsh(self.Env["nodes"][0],
                        "grep no-grastate /usr/lib/ocf/resource.d/heartbeat/galera") == 0

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




class NodeRecoverWhileStartingCluster(ClusterStart):
    '''Ensure that a node killed during a transaction does not block cluster bootstrap'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeRecoverWhileStartingCluster"

    def is_applicable(self):
        # mariadb 10.1+ seems to be immune to pending XA
        return self.rsh(self.Env["nodes"][0],
                        "mysql --version | awk '{print $5}' | awk -F. '$1==5 && $2==5 {print 1}' | grep 1") == 0

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
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "stop", "galera", n, 'ok') \
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
        return GaleraTest.errorstoignore(self) + \
               GaleraTest.errors_after_forced_stop(self)

tests.append(NodeRecoverWhileStartingCluster)


class NodeSyncFailureEnsureSSTAtNextRestart(ClusterStart):
    '''Ensure that if a node failed to join the cluster while being in
       sync-needed state, the next restart will catch it and request a SST.
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "NodeSyncFailureEnsureSSTAtNextRestart"

    def is_applicable(self):
        return self.rsh(self.Env["nodes"][0],
                        "grep sync-needed /usr/lib/ocf/resource.d/heartbeat/galera") == 0

    def setup_test(self, target):
        # tmp hack: make first node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        target = self.Env["nodes"][1]

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
        target = self.Env["nodes"][1]
        self.crm_attr_set(target, "galera-sync-needed", "true")

        # todo: ensure that target's SST syncs for a long enough time
        # for a monitor op to see it and log appropriately
        patterns = [r"%s.*rsyncd.*listening on port 4444"%target,
                    r"%s.*INFO: local node syncing"%target,
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

tests.append(NodeSyncFailureEnsureSSTAtNextRestart)
