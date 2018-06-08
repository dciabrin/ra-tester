#!/usr/bin/env python

'''Resource Agents Tester

Simple test example on the Dummy RA.
 '''

__copyright__ = '''
Copyright (C) 2018 Damien Ciabrini <dciabrin@redhat.com>
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

class DummyCommonTest(ResourceAgentTest):
    def setup_test(self, node):
        '''Common setup for dummy test'''
        # create a dummy resource, without starting it yet
        # the real test will decide what to do with it

        patterns = [r"crmd.*:\s*notice:\sState\stransition\s.*->\sS_IDLE(\s.*origin=notify_crmd)?"]
        if self.Env["bundle"]:
            patterns += [self.ratemplates.build("Pat:RscRemoteOp", "probe", "dummy-bundle-docker-[0-9]", n, 'not running') \
                         for n in self.Env["nodes"]]
        else:
            patterns += [self.ratemplates.build("Pat:RscRemoteOp", "probe", "dummy", n, 'not running') \
                         for n in self.Env["nodes"]]

        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()

        if self.Env["bundle"]:
            # image=self.Env["image"]
            image="docker.io/tripleoupstream/centos-binary-mariadb:latest"
            self.rsh_check(node,
                           "pcs resource bundle create dummy-bundle container docker image=%s network=host options=\"--user=root --log-driver=journald\" run-command=\"/usr/sbin/pacemaker_remoted\" network control-port=3123 storage-map id=map0 source-dir=/dev/log target-dir=/dev/log storage-map id=map1 source-dir=/dev/zero target-dir=/etc/libqb/force-filesystem-sockets options=ro --disabled"%image)

        meta = self.Env["meta"] or ""
        if self.Env["bundle"]:
            meta += "bundle %s"%self.Env["rsc_name"]

        if meta != "":
            meta = "meta %s"%meta
            
        self.rsh_check(node,
                       "pcs resource create dummy ocf:pacemaker:Dummy %s %s" % (
                       meta,
                        "" if self.Env["bundle"] else "--disabled"
                    ))
        # Note: starting in target-role:Stopped first triggers a demote, then a stop
        # Note: adding a resource forces a first probe (INFO: MySQL is not running)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

    def teardown_test(self, node):
        # handy debug hook
        if self.Env.has_key("keep_resources"):
            return 1

        # give back control to pacemaker in case the test disabled it
        self.rsh_check(node, "pcs resource manage %s"%self.Env["rsc_name"])

        # delete the resource created for this test
        # note: deleting a resource triggers an implicit stop, and that
        # implicit delete will fail when ban constraints are set.
        self.rsh_check(node, "pcs resource delete %s"%self.Env["rsc_name"])

    def errorstoignore(self):
        return [
            # docker daemon is quite verbose, but all real errors are reported by pacemaker
            r"dockerd-current.*:\s*This node is not a swarm manager",
            r"dockerd-current.*:\s*No such container",
            r"dockerd-current.*:\s*No such image",
            r"dockerd-current.*Handler for GET.*/.*returned error: (network|plugin).*not found",
            r"dockerd-current.*Handler for GET.*/.*returned error: get.*no such volume",
            # pengine logs spurious error on regular operations
            r"pengine.*error: Could not fix addr for "
        ]


class ClusterStart(DummyCommonTest):
    '''Start a dummy resource'''
    def __init__(self, cm):
        DummyCommonTest.__init__(self,cm)
        self.name = "ClusterStart"

    def test(self, target):
        '''Start an entire dummy resource'''
        # force pacemaker to probe the disable state before starting
        # the test
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe",
                                           "dummy-bundle-docker-[0-9]" if self.Env["bundle"] else "dummy",
                                           n, 'not running') \
                    for n in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource refresh %s"%self.Env["rsc_name"])
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # enable the resource and wait for pacemaker to start it
        target_nodes=self.Env["nodes"]
        ## bundles run resources on container nodes, not host nodes
        if self.Env["bundle"]:
            target_nodes=["dummy-bundle-%d"%x for x in range(len(self.Env["nodes"]))]
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "start", "dummy", n, 'ok') \
                    for n in target_nodes]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "pcs resource enable %s"%self.Env["rsc_name"])
        watch.look()
        assert not watch.unmatched, watch.unmatched

tests.append(ClusterStart)
