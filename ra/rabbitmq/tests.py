#!/usr/bin/env python

'''Resource Agents Tester

Tests for the RabbitMQ resource agent.
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

class RabbitMQCommonTest(ResourceAgentTest):
    def bundle_command(self, cluster_nodes, resource):
        engine = self.Env["container_engine"]
        name = resource["name"]
        image = resource["container_image"]
        return "pcs resource bundle create %s"\
            " container %s image=%s network=host options=\"--user=root --log-driver=journald\""\
            " replicas=3 run-command=\"/usr/sbin/pacemaker_remoted\" network control-port=3123"\
            " storage-map id=map0 source-dir=/dev/log target-dir=/dev/log"\
            " storage-map id=map1 source-dir=/dev/zero target-dir=/etc/libqb/force-filesystem-sockets options=ro"\
            " storage-map id=map2 source-dir=/etc/hosts target-dir=/etc/hosts options=ro"\
            " storage-map id=map3 source-dir=/etc/localtime target-dir=/etc/localtime options=ro"\
            " storage-map id=map4 source-dir=/etc/rabbitmq target-dir=/etc/rabbitmq options=ro"\
            " storage-map id=map5 source-dir=/var/lib/rabbitmq target-dir=/var/lib/rabbitmq options=rw"\
            " storage-map id=map6 source-dir=/var/log/rabbitmq target-dir=/var/log/rabbitmq options=rw"\
            " storage-map id=map7 source-dir=/usr/lib/ocf target-dir=/usr/lib/ocf options=rw"%\
            (name, engine, image)

    def resource_command(self, cluster_nodes, resource):
        name = resource["ocf_name"]
        return """pcs resource create %s ocf:heartbeat:rabbitmq-cluster set_policy='ha-all ^(?!amq\\.).* {"ha-mode":"all"}' op stop interval=0s timeout=200s"""%name

    def setup_test(self, node):
        self.setup_inactive_resource(self.Env["nodes"])

    def teardown_test(self, node):
        self.delete_resource(self.Env["nodes"])

    def errorstoignore(self):
        return ResourceAgentTest.errorstoignore(self) + [
            "ERROR: Failed to forget node rabbit@.* via rabbit@.*"
        ]



class ClusterStart(RabbitMQCommonTest):
    '''Start a rabbitmq cluster'''
    def __init__(self, cm):
        RabbitMQCommonTest.__init__(self,cm)
        self.name = "ClusterStart"

    def test(self, target):
        # setup_test has created the inactive resource
        rsc = self.resource
        # force a probe to ensure pacemaker knows that the resource
        # is in disabled state
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe",
                                           self.resource_probe_pattern(rsc, n),
                                           n, 'not running') \
                    for n in self.Env["nodes"]]
        watch = self.make_watch(patterns)
        self.rsh_check(target, "pcs resource refresh %s"%rsc["name"])
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # bundles run OCF resources on bundle nodes, not host nodes
        name = rsc["name"]
        target_nodes = self.resource_target_nodes(rsc, self.Env["nodes"])
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "start", name, n, 'ok') \
                    for n in target_nodes]
        watch = self.make_watch(patterns)
        self.rsh_check(target, "pcs resource enable %s"%name)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # teardown_test will delete the resource

tests.append(ClusterStart)


class ClusterRebootAllNodes(ClusterStart):
    '''Restart the rabbitmq cluster after all hosts have been rebooted'''
    def __init__(self, cm):
        RabbitMQCommonTest.__init__(self,cm)
        self.name = "ClusterRebootAllNodes"

    def test(self, target):
        # ClusterStart starts all the rabbitmq clones
        ClusterStart.test(self, target)

        # restart all the nodes forcibly
        rsc = self.resource
        name = rsc["name"]
        target_nodes = self.resource_target_nodes(rsc, self.Env["nodes"])
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "start", name, n, 'ok') \
                    for n in target_nodes]
        watch = self.make_watch(patterns)
        self.log("Force-reset nodes "%self.Env["nodes"])
        for n in self.Env["nodes"]:
            self.rsh(n, "echo b > /proc/sysrq-trigger")
        self.log("Wait until all nodes are restarted and reachable over ssh")
        for n in self.Env["nodes"]:
            self.wait_until_restarted(n)
        # wait until pacemaker restart all the rabbitmq clones
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # teardown_test will delete the resource

    def errorstoignore(self):
        return ResourceAgentTest.errorstoignore(self) + [
            # libvirt seems to log warnings when triggering the b sysreq
            "libvirtd.*error : virPCIGetDeviceAddressFromSysfsLink:.*internal error: Failed to parse PCI config address",
            # pengine is not happy if stonith is disabled
            "pengine.*error: ENABLE STONITH TO KEEP YOUR RESOURCES SAFE",
            "pengine.*error: Calculated transition .*(with errors), saving inputs"
        ]

tests.append(ClusterRebootAllNodes)
