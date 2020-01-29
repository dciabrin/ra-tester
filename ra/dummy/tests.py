#!/usr/bin/env python

'''Resource Agents Tester

Simple test example on the Dummy RA.
 '''

__copyright__ = '''
Copyright (C) 2018-2019 Damien Ciabrini <dciabrin@redhat.com>
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

class DummyCommonTest(ResourceAgentTest):
    def bundle_command(self, cluster_nodes, resource):
        engine = self.Env["distribution"].container_engine().package_name()
        name = resource["name"]
        image = resource["container_image"]
        return "pcs resource bundle create %s"\
            " container %s image=%s network=host options=\"--user=root --log-driver=journald\""\
            " run-command=\"/usr/sbin/pacemaker_remoted\" network control-port=3123"\
            " storage-map id=map0 source-dir=/dev/log target-dir=/dev/log"\
            " storage-map id=map1 source-dir=/dev/zero target-dir=/etc/libqb/force-filesystem-sockets options=ro"%\
            (name, engine, image)

    def resource_command(self, cluster_nodes, resource):
        return """pcs resource create dummy ocf:pacemaker:Dummy"""

    def setup_test(self, node):
        self.setup_inactive_resource(self.Env["nodes"])

    def teardown_test(self, node):
        self.delete_resource(self.Env["nodes"])

    def errorstoignore(self):
        return ResourceAgentTest.errorstoignore(self)



class Start(DummyCommonTest):
    '''Start a dummy resource'''
    def __init__(self, cm):
        DummyCommonTest.__init__(self,cm)
        self.name = "Start"

    def test(self, target):
        # setup_test has created the inactive resource

        # force a probe to ensure pacemaker knows that the resource
        # is in disabled state
        rsc = self.Env["resource"]
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe",
                                           self.resource_probe_pattern(rsc, n),
                                           n, 'not running') \
                    for n in self.Env["nodes"]]
        watch = self.make_watch(patterns)
        self.rsh_check(target, "pcs resource refresh %s"%rsc["name"])
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # bundles run OCF resources on bundle nodes, not host nodes
        name = rsc["ocf_name"]
        target_nodes = self.resource_target_nodes(rsc, self.Env["nodes"])
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "start", name, n, 'ok') \
                    for n in target_nodes]
        watch = self.make_watch(patterns)
        self.rsh_check(target, "pcs resource enable %s"%rsc["name"])
        watch.look()
        assert not watch.unmatched, watch.unmatched

        # teardown_test will delete the resource

tests.append(Start)
