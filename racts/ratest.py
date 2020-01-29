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
# from cts.CM_ais import crm_mcp
from cts.CTSscenarios import *
from cts.CTSaudits import *
from cts.CTSvars   import *
from cts.patterns  import PatternSelector
from cts.logging   import LogFactory
from cts.remote    import RemoteFactory
from cts.watcher   import LogWatcher
from cts.environment import EnvFactory
from racts.rapatterns import RATemplates
from racts.raaction import ActionMixin


class ResourceAgentTest(CTSTest, ActionMixin):
    '''Assertion-friendly base class for resource agent tests'''
    def __init__(self, cm):
        CTSTest.__init__(self,cm)
        # self.start_cluster = False
        self.name = "GenericRATest"
        self.bg = {}
        self.verbose = self.Env["verbose"]
        self.ratemplates = RATemplates()

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

    @property
    def resource(self):
        return self.Env["resource"]
        
    def teardown(self, node):
        '''Teardown, cleanup resource after the test'''
        try:
            self.teardown_test(node)
            return self.success()
        except AssertionError as e:
            return self.failure(str(e))

    def resource_probe_pattern(self, resource, node):
        pattern = resource["ocf_name"]
        if resource["bundle"]:
            pattern+='-bundle-%s-[0-9]'%self.Env["distribution"].container_engine().package_name()
        return pattern

    def resource_target_nodes(self, resource, cluster):
        name = resource["ocf_name"]
        if resource["bundle"]:
            target_nodes = ["%s-bundle-%d"%(name, x) for x in range(len(cluster))]
        else:
            target_nodes = cluster
        return target_nodes

    def setup_inactive_resource(self, cluster_nodes, resource=None):
        '''Common resource creation for test setup'''
        if resource is None:
            resource = self.resource

        node = cluster_nodes[0]

        patterns = [r"(crmd|pacemaker-controld).*:\s*notice:\sState\stransition\s.*->\sS_IDLE(\s.*origin=notify_crmd)?"]
        patterns += [self.ratemplates.build("Pat:RscRemoteOp", "probe",
                                            self.resource_probe_pattern(resource, n),
                                            n, 'not running') \
                     for n in cluster_nodes]

        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()

        meta = resource["meta"] or ""

        # create a bundle that will host the resource
        if resource["bundle"]:
            bundle_cmd = self.bundle_command(cluster_nodes, resource)
            bundle_cmd += " storage-map id=pcmk1 source-dir=/var/log/pacemaker target-dir=/var/log/pacemaker options=rw"
            bundle_cmd += " --disabled"
            self.rsh_check(node, bundle_cmd)
            meta += " bundle %s"%resource["name"]

        # create the resource, set it disabled if it is not
        # running in a bundle
        resource_cmd = self.resource_command(cluster_nodes, resource)
        if meta != "": resource_cmd += " meta %s"%meta
        if not resource["bundle"]: resource_cmd += " --disabled"
        self.rsh_check(node, resource_cmd)

        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

    def delete_resource(self, cluster_nodes, resource=None):
        if resource is None:
            resource = self.resource

        # handy debug hook
        if self.Env.has_key("keep_resources"):
            return 1

        node = cluster_nodes[0]

        # give back control to pacemaker in case the test disabled it
        self.rsh_check(node, "pcs resource manage %s"%resource["name"])

        # delete the resource created for this test
        # note: deleting a resource triggers an implicit stop, and that
        # implicit delete will fail when ban constraints are set.
        self.rsh_check(node, "pcs resource delete %s"%resource["name"])

    def errorstoignore(self):
        container_logs = self.Env["distribution"].container_engine().errorstoignore()
        return container_logs + [
            # pengine logs spurious error on regular operations
            r"pengine.*error: Could not fix addr for ",
            # bundle: when associating an ocf resource to a bundle, pengine
            # logs some spurious errors (not fatal)
            r"pengine.*:.*error: Could not determine address for bundle",
            # bundle: pacemaker_remoted logs error when it's deleted
            r"error:.*Connection terminated: Error in the push function",
            r"error:.*Could not send remote message: Software caused connection abort",
            r"error:.*Connection terminated: The specified session has been invalidated for some reason",
            r"error:.*Connection terminated rc = -(53|10)",
            r"error:.*Failed to send remote msg, rc = -(53|10)",
            r"error:.*Failed to send remote lrmd tls msg, rc = -(53|10)"
        ]
