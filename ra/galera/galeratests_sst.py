#!/usr/bin/env python

'''Resource Agents Tester

Regression tests for galera RA. SST recovery edge cases.
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

class SSTTest(ClusterStart):
    '''Base class for test that require SST and slow network transfer
    '''

    def is_applicable(self):
        return self.rsh(self.Env["nodes"][0],
                        "grep sync-needed /usr/lib/ocf/resource.d/heartbeat/galera") == 0

    def start_galera_no_wait(self, target):
        # clean errors and force probe current state
        # this is my way of ensure pacemaker will "promote" nodes
        # rather than just "monitoring" and finding "Master" state
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe", "galera", n, 'not running') \
                    for n in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource cleanup galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        self.rsh_check(target, "pcs resource enable galera-master")

    def setup_test(self, target):
        # tmp hack: make first node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        target = self.Env["nodes"][1]

        ClusterStart.setup_test(self, target)
        # TODO: ensure all nodes are in sync (same wsrep seqno)

        self.setup_slow_sst(target)

    def setup_slow_sst(self, target):
        # in this test, target is the joiner
        for node in self.Env["nodes"]:
            self.rsh_check(node, "/tmp/slow_down_sst.sh -n %s on"%node)
            # create big file on potential donor nodes
            if node != target:
                self.create_big_file(node)

        self.prepare_node_for_sst(target)

    def teardown_test(self, target):
        for node in self.Env["nodes"]:
            self.rsh_check(node, "/tmp/slow_down_sst.sh -n %s off || true"%node)
            self.rsh_check(node, "rm -rf /var/lib/mysql/big_file")
        ClusterStart.teardown_test(self, target)


class SSTFailureTest(SSTTest):
    '''Abstract class which setups test for SST failure
    '''

    def setup_test(self, target):
        # tmp hack: make first node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        target = self.Env["nodes"][1]

        ClusterStart.setup_test(self, target)
        # TODO: ensure all nodes are in sync (same wsrep seqno)

    def test(self, target):
        # tmp hack: make first node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        target = self.Env["nodes"][1]
        self.target = target

        # start all nodes we don't care about, so we're sure
        # we only mess with our target
        ClusterStart.test(self, target)
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "stop", "galera",
                                           "galera-bundle-[0-9]" if self.Env["galera_bundle"] else target,
                                           'ok')]
        watch = self.create_watch(patterns, 10) # self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource ban %s %s"%(self.Env["galera_rsc_name"], target))
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # slow down network and create big files for long sst
        self.setup_slow_sst(target)

        # Wait for generic break action to break the target
        fail_target="galera-bundle-[0-9]" if self.Env["galera_bundle"] else target
        # long-running sst requires op = "monitor"
        op = "promote"
        patterns = [r"pengine.*:\s+warning:.*Processing failed op %s for %s(:[0-9]*)? on %s: %s"%\
                    (op, "galera", fail_target, '(not running|unknown error)')
        ]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource clear %s %s"%(self.Env["galera_rsc_name"], target))
        self.break_action(target)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched
        if self.Env["galera_bundle"]:
            # extract the exact bundle clone where the resource ran
            fail_target = re.sub(r'^.*\W(galera-bundle-[0-9])\W.*$',r'\1',
                                 watch.matched[0].rstrip('\n'))

        # the target resource should be in failed state, and also blocked from restarting
        self.rsh_check(target, "pcs resource failcount show %s %s | grep %s:"%("galera", fail_target, fail_target))
        # note: bundles have the same output in pcs status than regular resource
        self.rsh_check(target, "pcs status | grep %s | grep 'FAILED\W.*\W%s' | grep blocked"%("galera", target))

        # the sync flag should still be set in the CIB for the failed target
        # only with the long-running sst patch
        # self.crm_attr_check(target, "galera-sync-needed")

        # Donor will fail the SST transfer on its side and go back to SYNC state
        # transparently, i.e. no failure
        target_nodes=self.Env["nodes"]
        ## bundles run resources on container nodes, not host nodes
        if self.Env["galera_bundle"]:
            target_nodes=["galera-bundle-%d"%x for x in range(len(self.Env["nodes"]))]
        for node in [x for x in target_nodes if x != fail_target]:
            self.rsh_check(target, "pcs resource failcount show galera %s | grep 'No failcount'"%(node))

    def teardown_test(self, target):
        # tmp hack: make first node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        target = self.Env["nodes"][1]
        self.crm_attr_del(target, "galera-no-grastate")
        self.crm_attr_del(target, "galera-sync-needed")
        # long running sst doesn't need that
        self.crm_attr_del(target, "master-galera")
        SSTTest.teardown_test(self, target)

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
               GaleraTest.errors_after_forced_stop(self) + \
               [r"%s.*rsyncd.*rsync error: error in rsync protocol data stream"%self.target,
                r"MySQL server failed to start.*please check your installation"]


class SSTFailureNoScriptOnJoinerNode(SSTTest):
    '''
    Trigger a failure early on joiner side, during SST set up.
    Donor should start his side of the SST.
    Joiner should be blocked from restarting after the failed sync
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "SSTFailureNoScriptOnJoinerNode"
        self.bundle_map_sst_script = True

    def is_applicable(self):
        return True

    def setup_test(self, target):
        ClusterStart.setup_test(self, target)

    def test(self, target):
        # start all nodes we don't care about, so we're sure
        # we only mess with our target
        ClusterStart.test(self, target)

        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "stop", "galera",
                                           "galera-bundle-[0-9]" if self.Env["galera_bundle"] else target,
                                           'ok')]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource ban %s %s"%(self.Env["galera_rsc_name"], target))
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # force SST at next start
        self.isolate_sst_script(target)
        self.prepare_node_for_sst(target)

        # start joiner and wait for it to fail in SST
        fail_target="galera-bundle-[0-9]" if self.Env["galera_bundle"] else target
        # long-running sst requires op = "monitor"
        op = "promote"
        patterns = [r"pengine.*:\s+warning:.*Processing failed op %s for %s(:[0-9]*)? on %s: %s"%\
                    (op, "galera", fail_target, '(not running|unknown error)')
                    ]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource clear %s %s"%(self.Env["galera_rsc_name"], target))
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched
        if self.Env["galera_bundle"]:
            # extract the exact bundle clone where the resource ran
            fail_target = re.sub(r'^.*\W(galera-bundle-[0-9])\W.*$',r'\1',
                                 watch.matched[0].rstrip('\n'))

        # The resource should be in failed state, and also blocked from restarting
        self.rsh_check(target, "pcs resource failcount show %s %s | grep %s:"%("galera", fail_target, fail_target))
        # note: bundles have the same output in pcs status than regular resource
        self.rsh_check(target, "pcs status | grep %s | grep 'FAILED\W.*\W%s' | grep blocked"%("galera", target))

        # the sync flag should still be set in the CIB for the failed target
        # only with the long-running sst patch
        # self.crm_attr_check(target, "galera-sync-needed")

        # Donor should not have received the SST request, and thus
        # should not be impacted
        target_nodes=self.Env["nodes"]
        ## bundles run resources on container nodes, not host nodes
        if self.Env["galera_bundle"]:
            target_nodes=["galera-bundle-%d"%x for x in range(len(self.Env["nodes"]))]
        for node in [x for x in target_nodes if x != fail_target]:
            self.rsh_check(target, "pcs resource failcount show galera %s | grep 'No failcount'"%(node))

    def teardown_test(self, target):
        self.restore_sst_script(target)
        self.crm_attr_del(target, "galera-no-grastate")
        self.crm_attr_del(target, "galera-sync-needed")
        # long running sst doesn't need that
        self.crm_attr_del(target, "master-galera")
        ClusterStart.teardown_test(self, target)

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
            [r"MySQL server failed to start.*please check your installation"]

tests.append(SSTFailureNoScriptOnJoinerNode)


class SSTFailureNoScriptOnDonorNode(SSTFailureNoScriptOnJoinerNode):
    '''
    Trigger a failure on donor node at SST start.
    This should not be fatal for donor, it should recover and rejoin cluster.
    Joiner should be blocked from restarting after the failed sync
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.bundle_map_sst_script = True
        self.name = "SSTFailureNoScriptOnDonorNode"

    def is_applicable(self):
        return True

    def isolate_sst_script(self, target):
        for node in [x for x in self.Env["nodes"] if x != target]:
            SSTFailureNoScriptOnJoinerNode.isolate_sst_script(self, node)

    def test(self, target):
        # Donor will fail the SST transfer on its side and go back to SYNC state
        # transparently, i.e. no failure
        # Joiner will receive the failed state transfer request, and stop
        # Outcome is the same as SSTNoScriptOnJoinerNode, so reuse it
        SSTFailureNoScriptOnJoinerNode.test(self, target)

    def teardown_test(self, target):
        SSTFailureNoScriptOnJoinerNode.teardown_test(self, target)

tests.append(SSTFailureNoScriptOnDonorNode)


class SSTFailureRSyncKilledOnDonorNode(SSTFailureTest):
    '''
    Donor failure: rsync subprocess killed while transferring data to the joiner
    This should not be fatal for donor, it should recover and rejoin cluster.
    Joiner should be blocked from restarting after the failed sync
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "SSTFailureRSyncKilledOnDonorNode"

    def is_applicable(self):
        return True

    def break_action(self, target):
        self.rsh_until([n for n in self.Env["nodes"] if n != target], "killall -9 rsync")

tests.append(SSTFailureRSyncKilledOnDonorNode)


class SSTFailureRSyncdKilledOnJoinerNode(SSTTest):
    '''
    Joiner failure: rsync subprocess killed while receiving data from donor
    Joiner should be blocked from restarting after the failed sync
    This should not be fatal for donor, it should recover and rejoin cluster.
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "SSTFailureRSyncdKilledOnJoinerNode"

    def is_applicable(self):
        return True

    def break_action(self, target):
        self.rsh_until([target], "killall -9 rsync")

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
            [r"MySQL server failed to start.*please check your installation"]

tests.append(SSTFailureRSyncdKilledOnJoinerNode)


class SSTFailureSSTScriptKilledOnJoinerNode(SSTTest):
    '''
    Joiner failure: wsrep_sst_{method} controller script killed during transfer
    Joiner should be blocked from restarting after the failed sync
    This should not be fatal for donor, it should recover and rejoin cluster.
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "SSTFailureSSTScriptKilledOnJoinerNode"

    def is_applicable(self):
        return True

    def break_action(self, target):
        self.rsh_until([target], "killall -ILL wsrep_sst_rsync")

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
            [r"MySQL server failed to start.*please check your installation"]

tests.append(SSTFailureSSTScriptKilledOnJoinerNode)


class SSTFailureMysqldKilledOnJoinerNode(SSTTest):
    '''
    Joiner failure: mysqld server killed during transfer, other
    member of the galera cluster should notice that event.
    This should not be fatal for donor, it should recover and rejoin cluster.
    Joiner should be blocked from restarting after the failed sync
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "SSTFailureMysqldKilledOnJoinerNode"

    def is_applicable(self):
        return True

    def break_action(self, target):
        self.rsh_until([target], "ps -ef | grep -e 'wsrep_sst_rsync --role joiner' | grep -v grep")
        self.rsh_until([target], "killall -9 /usr/libexec/mysqld")

tests.append(SSTFailureMysqldKilledOnJoinerNode)
