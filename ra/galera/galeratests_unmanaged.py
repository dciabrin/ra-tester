#!/usr/bin/env python

'''Resource Agents Tester

Regression tests for galera RA
Test cases for when the resource is unmanged
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
from .galeratests_sst import SSTTest

tests = []


class UnmanagedNoMonitorWhenStopped(ClusterStart):
    '''
    When the last known state of an unmanaged resource is "Stopped",
    pacemaker shouldn't trigger recurring monitor op at all.
    So status shouldn't change even if a mysqld is started manually
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "UnmanagedNoMonitorWhenStopped"

    def is_applicable(self):
        return True

    def test(self, target):
        # start cluster
        ClusterStart.test(self, target)

        # start cluster and wait for our joiner to fail in SST
        patterns = [r"pengine.*:\s+warning:.*Processing failed op %s for %s(:[0-9]*)? on %s: %s"%\
                    ("monitor", "galera", target, '(not running|unknown error)')
        ]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource unmanage galera")
        self.rsh_check(target, "mysqladmin shutdown")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe", "galera", target, 'not running')]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource cleanup galera --node %s"%target)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe", "galera", target, '.*')]
        watch = self.create_watch(patterns, 10)
        watch.setwatch()
        self.rsh_check(target, "nohup mysqld_safe --defaults-file=/etc/my.cnf --pid-file=/var/run/mysql/mysqld.pid --socket=/var/lib/mysql/mysql.sock --datadir=/var/lib/mysql --log-error=/var/log/mysqld.log --user=mysql --wsrep-cluster-address=gcomm://%s </dev/null &>/dev/null &"%(",".join(self.Env["nodes"]),))
        self.rsh_until([target], "mysqladmin status &>/dev/null", timeout=20)
        watch.lookforall()
        assert watch.unmatched, watch.unmatched

        # since it's cleared, we shouldn't have any attribute
        self.crm_attr_check(target, "galera-sync-needed",expected=6)
        self.crm_attr_check(target, "master-galera",expected=6)

    def teardown_test(self, target):
        self.rsh_check(target, "pcs resource cleanup galera --node %s"%target)
        ClusterStart.teardown_test(self, target)

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
               GaleraTest.errors_after_forced_stop(self)

tests.append(UnmanagedNoMonitorWhenStopped)


class UnmanagedDoNotPromoteSlave(SSTTest):
    '''
    It last known state of an unmanaged resource is "Slave",
    pacemaker may trigger monitor op, but it is not allowed
    to promote a resource.
    Ensure the resource agent doesn't try to trigger promotion
    during unmanaged state.
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "UnmanagedDoNotPromoteSlave"

    def is_applicable(self):
        return True

    def setup_test(self, target):
        ClusterStart.setup_test(self, target)

    def test(self, target):
        # start cluster
        ClusterStart.test(self, target)

        # tmp hack: make first node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        target = self.Env["nodes"][1]

        # start cluster and wait for our joiner to fail in SST
        patterns = [r"pengine.*:\s+warning:.*Processing failed op %s for %s(:[0-9]*)? on %s: %s"%\
                    ("monitor", "galera", target, '(not running|unknown error)')
        ]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource unmanage galera")
        self.rsh_check(target, "mysqladmin shutdown")
        self.prepare_node_for_sst(target)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe", "galera", target, 'not running')]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource cleanup galera --node %s"%target)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # start a server manually and wait for a SST to kick in
        # and proceed slooowly
        for node in self.Env["nodes"]:
            self.rsh_check(node, "/tmp/slow_down_sst.sh -n %s on"%node)
            # create big file on potential donor nodes
            if node != target:
                self.create_big_file(node,sizekb=20000)
        self.prepare_node_for_sst(target)
        self.rsh_check(target, "nohup mysqld_safe --defaults-file=/etc/my.cnf --pid-file=/var/run/mysql/mysqld.pid --socket=/var/lib/mysql/mysql.sock --datadir=/var/lib/mysql --log-error=/var/log/mysqld.log --user=mysql --wsrep-cluster-address=gcomm://%s </dev/null &>/dev/null &"%(",".join(self.Env["nodes"]),))
        self.rsh_until([target], "ps -ef | grep -e 'wsrep_sst_rsync --role joiner' | grep -v grep")

        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe", "galera", target, 'ok')]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        # at this stage we should be in slave state
        self.rsh_check(target, "pcs resource cleanup galera --node %s"%target)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # since it's slave we should still have sync-needed, and not be master
        self.crm_attr_check(target, "galera-sync-needed")
        self.crm_attr_check(target, "master-galera",expected=6)

        # wait until the mysqld has fully joined the galera cluster...
        self.rsh_until([target], "mysqladmin status &>/dev/null")

        # and ensure we're still slave for pacemaker (i.e. there
        # are no master monitor op for the next master interval seconds)
        # and that the attributes are set accordingly
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe", "galera", target, '.*')]
        watch = self.create_watch(patterns, 10)
        watch.setwatch()
        watch.lookforall()
        assert watch.unmatched, watch.unmatched
        self.crm_attr_check(target, "galera-sync-needed")
        self.crm_attr_check(target, "master-galera",expected=6)

    def teardown_test(self, target):
        self.rsh_check(target, "pcs resource cleanup galera --node %s"%target)
        self.crm_attr_del(target, "galera-no-grastate")
        self.crm_attr_del(target, "galera-sync-needed")
        SSTTest.teardown_test(self, target)

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
               GaleraTest.errors_after_forced_stop(self)

tests.append(UnmanagedDoNotPromoteSlave)


class UnmanagedRecoverAfterErrorWhenMaster(ClusterStart):
    '''
    When a unmanaged Master resource goes in error, pacemaker reports
    a "FAILED" flag but keeps monitoring like it was in Master (due
    to unmanage). Next time the monitor action succeeds, the FAILED
    flag should be removed and pacemaker should proceed with passive
    monitoring of the unmanged Master.
    '''

    def __init__(self, cm):
        GaleraTest.__init__(self,cm)
        self.name = "UnmanagedRecoverAfterErrorWhenMaster"

    def is_applicable(self):
        return True

    def test(self, target):
        # start cluster
        ClusterStart.test(self, target)

        # tmp hack: make first node the target, it can be
        # any node when we integrate "prevent bootstrapping w/ recovered"
        target = self.Env["nodes"][1]

        # start cluster and wait for poacemaker to report failure on
        # the manually stopped node
        patterns = [r"pengine.*:\s+warning:.*Processing failed op %s for %s(:[0-9]*)? on %s: %s"%\
                    ("monitor", "galera", target, '(not running|unknown error)')
        ]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource unmanage galera")
        self.rsh_check(target, "mysqladmin shutdown")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # restart manually and wait for pacemaker to update status
        patterns = [r"pengine.*:\s+warning:.*Processing failed op %s for %s(:[0-9]*)? on %s: %s"%\
                    ("monitor", "galera", target, '(not running|unknown error)')
        ]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "nohup mysqld_safe --defaults-file=/etc/my.cnf --pid-file=/var/run/mysql/mysqld.pid --socket=/var/lib/mysql/mysql.sock --datadir=/var/lib/mysql --log-error=/var/log/mysqld.log --user=mysql --wsrep-cluster-address=gcomm://%s </dev/null &>/dev/null &"%(",".join(self.Env["nodes"]),))
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # the latest monitor action should report 'Master' again
        self.rsh_check(target, "pcs cluster cib | xmllint --xpath \"//lrm_rsc_op[@on_node='%s' and @operation_key='%s_monitor_10000' and @rc-code='8']\" - &>/dev/null"%(target,"galera"))
        self.crm_attr_check(target, "master-galera")

    def errorstoignore(self):
        return GaleraTest.errorstoignore(self) + \
               GaleraTest.errors_after_forced_stop(self)

tests.append(UnmanagedRecoverAfterErrorWhenMaster)
