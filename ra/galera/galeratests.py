#!/usr/bin/env python

'''Resource Agents Tester

Regression tests for galera RA.
Cluster-wide test cases, validating general start/stop conditions.
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
        self.bundle_map_sst_script = False

    def create_big_file(self, node, sizekb=100000):
        self.rsh_check(node, "mkdir -p /var/lib/mysql/big_file && dd if=/dev/urandom bs=1024 count=%d of=/var/lib/mysql/big_file/for_sst && chown -R mysql. /var/lib/mysql/big_file"%sizekb)

    def prepare_node_for_sst(self, node):
        # force SST at restart for the target, and ensure
        # node won't be chosen as a the bootstrap node,
        # this is correct as per test `NodeDontChooseForBootstrappingCluster`
        self.rsh_check(node, "rm -f /var/lib/mysql/grastate.dat")

    def isolate_sst_script(self, node):
        cmd = "cp /usr/bin/wsrep_sst_rsync /usr/bin/wsrep_sst_rsync.ratester && truncate -s 0 /usr/bin/wsrep_sst_rsync"
        self.rsh_check(node, cmd)
        # if self.Env["galera_bundle"]:
        #     # in case the bundle has already started, isolate the
        #     # script in the running container
        #     cmd = "a=$(docker ps -f name=galera-bundle -q); test -n \"$a\" && docker run \"$a\" /bin/bash -c '" + cmd + "'"
        #     self.rsh_check(node, cmd)

    def restore_sst_script(self, node):
        self.rsh_check(node, "if [ -f /usr/bin/wsrep_sst_rsync.ratester ]; then mv -f /usr/bin/wsrep_sst_rsync.ratester /usr/bin/wsrep_sst_rsync; fi")

    def setup_test(self, node):
        '''Setup the given test'''
        # ensure the cluster is clean before starting the test
        for node in self.Env["nodes"]:
            self.rsh(node,
                     "if [ -f /usr/bin/wsrep_sst_rsync.ratester ]; then " \
                     "cp /usr/bin/wsrep_sst_rsync.ratester /usr/bin/wsrep_sst_rsync &&" \
                     "rm -f /usr/bin/wsrep_sst_rsync.ratester; fi")

        # create a galera resource, without starting it yet
        patterns = [r"crmd.*:\s*notice:\sState\stransition\s.*->\sS_IDLE(\s.*origin=notify_crmd)?"]
        if self.Env["galera_bundle"]:
            patterns += [self.ratemplates.build("Pat:RscRemoteOp", "probe", "galera-bundle-docker-[0-9]", n, 'not running') \
                         for n in self.Env["nodes"]]
        else:
            patterns += [self.ratemplates.build("Pat:RscRemoteOp", "probe", "galera", n, 'not running') \
                         for n in self.Env["nodes"]]

        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()

        if self.Env["galera_bundle"]:
            if self.bundle_map_sst_script:
                sst_map = "storage-map id=mapsst source-dir=/usr/bin/wsrep_sst_rsync target-dir=/usr/bin/wsrep_sst_rsync options=ro"
            else:
                sst_map = ""
            self.rsh_check(node,
                           "pcs resource bundle create galera-bundle container docker image=docker.io/tripleoupstream/centos-binary-mariadb:latest replicas=3 masters=3 network=host options=\"--user=root --log-driver=journald\" run-command=\"/usr/sbin/pacemaker_remoted\" network control-port=3123 storage-map id=map0 source-dir=/dev/log target-dir=/dev/log storage-map id=map1 source-dir=/dev/zero target-dir=/etc/libqb/force-filesystem-sockets options=ro storage-map id=map2 source-dir=/etc/my.cnf.d/galera.cnf target-dir=/etc/my.cnf.d/galera.cnf options=ro storage-map id=map3 source-dir=/var/lib/mysql target-dir=/var/lib/mysql options=rw %s --disabled"%sst_map)

        self.rsh_check(node,
                       "pcs resource create galera galera enable_creation=true wsrep_cluster_address='gcomm://%s' %s op promote timeout=60 on-fail=block meta %s %s" % \
                       (self.Env["galera_gcomm"],
                        self.Env["galera_opts"],
                        self.Env["galera_meta"],
                        "" if self.Env["galera_bundle"] else "--disabled"))
        # Note: starting in target-role:Stopped first triggers a demote, then a stop
        # Note: adding a resource forces a first probe (INFO: MySQL is not running)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

    def teardown_test(self, node):
        # handy debug hook
        if self.Env.has_key("keep_resources"):
            return 1

        # give back control to pacemaker in case the test disabled it
        self.rsh_check(node, "pcs resource manage %s"%self.Env["galera_rsc_name"])

        # delete the galera resource create for this test
        # note: deleting a resource triggers an implicit stop, and that
        # implicit delete will fail when ban constraints are set.
        self.rsh_check(node, "pcs resource delete %s"%self.Env["galera_rsc_name"])

    def errorstoignore(self):
        return [
            # currently, ERROR is logged before mysqld is started...
            r"ERROR:\s*MySQL is not running",
            # every SST finished by killing rsynd on the joiner side...
            r"rsyncd.*:\s*rsync error: received SIGINT, SIGTERM, or SIGHUP",
            # docker daemon is quite verbose, but all real errors are reported by pacemaker
            r"dockerd-current.*:\s*This node is not a swarm manager",
            r"dockerd-current.*:\s*No such container",
            r"dockerd-current.*:\s*No such image",
            # the bundle's pacemaker remote docker daemon logs error when it's deleted
            # TODO check whether it's the remote or the connection to the remote
            r"error: Connection terminated rc = -(53|10)",
            r"error: Failed to send remote msg, rc = -(53|10)",
            r"error: Failed to send remote lrmd tls msg, rc = -(53|10)"
        ]

    def errors_after_forced_stop(self):
        # after the node has been force-stopped, monitor op will fail and log
        return [
            r"ERROR: Unable to retrieve wsrep_cluster_status, verify check_user",
            r"ERROR: local node <.*> is started, but not in primary mode. Unknown state.",
            r"ERROR: MySQL not running: removing old PID file",
            r"notice:\s.*galera_monitor_.*:.*\s\[\sERROR\s.*\s\(HY000\): Lost\sconnection\sto\sMySQL\sserver"
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
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe",
                                           "galera-bundle-docker-[0-9]" if self.Env["galera_bundle"] else "galera",
                                           n, 'not running') \
                    for n in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource cleanup %s"%self.Env["galera_rsc_name"])
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # need to enable galera-master because of how we created the resource
        target_nodes=self.Env["nodes"]
        ## bundles run resources on container nodes, not host nodes
        if self.Env["galera_bundle"]:
            target_nodes=["galera-bundle-%d"%x for x in range(len(self.Env["nodes"]))]
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "promote", "galera", n, 'ok') \
                    for n in target_nodes]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource enable %s"%self.Env["galera_rsc_name"])
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

        target_nodes=self.Env["nodes"]
        ## bundles run resources on container nodes, not host nodes
        if self.Env["galera_bundle"]:
            target_nodes=["galera-bundle-%d"%x for x in range(len(self.Env["nodes"]))]
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "stop", "galera", n, 'ok') \
                    for n in target_nodes]
        watch = self.create_watch(patterns, self.Env["DeadTime"])

        watch.setwatch()
        self.rsh_check(self.Env["nodes"][0], "pcs resource disable %s"%self.Env["galera_rsc_name"])
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


class ClusterRestartAfter2RecoveredNodes(ClusterStart):
    '''Ensure cluster recovers after several nodes killed during a transaction'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "ClusterRestartAfter2RecoveredNodes"

    def is_applicable(self):
        # mariadb 10.1+ seems to be immune to pending XA
       return self.rsh(self.Env["nodes"][0],
                        "mysql --version | awk '{print $5}' | awk -F. '$1==5 && $2==5 {print 1}' | grep 1") == 0

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
        self.rsh_check(target, "pcs resource unmanage galera")

        # kill two nodes died, the remaining will go Non-Primary
        # due to loss of quorum. pacemaker will stop it
        patterns = [r"local node <%s> is started, but not in primary mode. Unknown state." % target,
        ]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "mysql -e 'insert into racts.break values (42);'")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        self.rsh_check(target, "mysqladmin shutdown")
        self.rsh_check(target, "pcs resource cleanup galera")

        # restart all the cluster -> bootstrap
        # ensure the bootstrap node is not a recovered one
        patterns = [r"Node <%s> is bootstrapping the cluster" % target] + \
                   [r"local node <%s> was not shutdown properly. Rollback stuck transaction with --tc-heuristic-recover"%node for node in to_break] + \
                   [self.ratemplates.build("Pat:RscRemoteOp", "promote", "galera", node, 'ok') for node in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource manage galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # ensure recovered state is cleaned up
        for node in to_break:
            self.crm_attr_check(node, "galera-no-grastate", expected = 6)

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
               GaleraTest.errors_after_forced_stop(self)

tests.append(ClusterRestartAfter2RecoveredNodes)


class ClusterRestartAfterAllNodesRecovered(ClusterStart):
    '''Ensure cluster recovers after all nodes killed during a transaction!'''
    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "ClusterRestartAfterAllNodesRecovered"

    def is_applicable(self):
        # mariadb 10.1+ seems to be immune to pending XA
        return self.rsh(self.Env["nodes"][0],
                        "mysql --version | awk '{print $5}' | awk -F. '$1==5 && $2==5 {print 1}' | grep 1") == 0

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
                   [self.ratemplates.build("Pat:RscRemoteOp", "promote", "galera", node, 'ok') for node in all_nodes]

        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "mysql -e 'insert into racts.break values (42);'", expected=1)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # ensure recovered state is cleaned up
        for node in all_nodes:
            self.crm_attr_check(node, "galera-no-grastate", expected = 6)

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
               GaleraTest.errors_after_forced_stop(self)


tests.append(ClusterRestartAfterAllNodesRecovered)


class ClusterStartWithLongRunningSST(ClusterStart):
    '''Ensure that a long running SST can finish without being killed by
       start or promote timeout
       It is assumed nodes are in sync prior to this test
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "ClusterStartWithLongRunningSST"

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

tests.append(ClusterStartWithLongRunningSST)


class ClusterStartWith2LongRunningSST(ClusterStartWithLongRunningSST):
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

    def is_applicable(self):
        return self.rsh(self.Env["nodes"][0],
                        "grep sync-needed /usr/lib/ocf/resource.d/heartbeat/galera") == 0

    def setup_test(self, target):
        # tmp hack: make last node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        target = self.Env["nodes"][-1]

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
        target = self.Env["nodes"][-1]

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
