#!/usr/bin/env python

'''Resource Agents Tester

Simple test example on the Galera RA.
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

from racts.ratest import ResourceAgentTest

tests = []

class GaleraCommonTest(ResourceAgentTest):
    def bundle_command(self, cluster_nodes):
        engine = self.Env["container_engine"]
        name = self.Env["rsc_name"]
        image = self.Env["container_image"]
        return "pcs resource bundle create %s"\
            " container %s image=%s network=host options=\"--user=root --log-driver=journald\""\
            " replicas=3 masters=3 run-command=\"/usr/sbin/pacemaker_remoted\" network control-port=3123"\
            " storage-map id=map0 source-dir=/dev/log target-dir=/dev/log"\
            " storage-map id=map1 source-dir=/dev/zero target-dir=/etc/libqb/force-filesystem-sockets options=ro"\
            " storage-map id=map2 source-dir=/etc/hosts target-dir=/etc/hosts options=ro"\
            " storage-map id=map3 source-dir=/etc/localtime target-dir=/etc/localtime options=ro"\
            " storage-map id=map4 source-dir=/etc/my.cnf.d target-dir=/etc/my.cnf.d options=ro"\
            " storage-map id=map5 source-dir=/var/lib/mysql target-dir=/var/lib/mysql options=rw"\
            " storage-map id=map6 source-dir=/var/log/mysql target-dir=/var/log/mysql options=rw"%\
            (name, engine, image)

    def resource_command(self, cluster_nodes):
        return """pcs resource create galera ocf:heartbeat:galera wsrep_cluster_address='gcomm://%s' op promote timeout=60 on-fail=block"""%(",".join(cluster_nodes),)


    def setup_test(self, node):
        for c in self.Env["clusters"]:
            self.setup_inactive_resource(c)

    def teardown_test(self, node):
        for c in self.Env["clusters"]:
            self.delete_resource(c)

    def errorstoignore(self):
        return ResourceAgentTest.errorstoignore(self) + [
                # currently, ERROR is logged before mysqld is started...
                r"ERROR:\s*MySQL is not running"
            ]

    

class ClusterStart(GaleraCommonTest):
    '''Start a dummy resource'''
    def __init__(self, cm):
        GaleraCommonTest.__init__(self, cm)
        self.name = "ClusterStart"

    def test(self, target):
        '''Start an entire dummy resource'''
        # setup_test has created the inactive resource

        # force a probe to ensure pacemaker knows that the resource
        # is in disabled state

        probe_pattern = self.resource_name_probe_pattern()
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe",
                                           probe_pattern, n, 'not running') \
                    for n in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        for cluster in self.Env["clusters"]:
            self.rsh_check(cluster[0], "pcs resource refresh %s"%self.Env["rsc_name"])
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # enable the resource and wait for pacemaker to start it
        name_pattern = self.resource_name_pattern()
        if self.Env["bundle"]:
            # bundles run resources on container nodes, not host nodes
            target_nodes=["%s-bundle-%d"%(name_pattern,x) for x in range(len(self.Env["nodes"]))]
        else:
            target_nodes=self.Env["nodes"]
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "start", name_pattern, n, 'ok') \
                    for n in target_nodes]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        for cluster in self.Env["clusters"]:
            self.rsh_check(cluster[0], "pcs resource enable %s"%self.Env["rsc_name"])
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

tests.append(ClusterStart)
