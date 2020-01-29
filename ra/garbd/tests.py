'''Resource Agents Tester

Regression tests for garbd RA
 '''

__copyright__ = '''
Copyright (C) 2015-2019 Damien Ciabrini <dciabrin@redhat.com>
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
from ra.galera.tests import GaleraCommonTest

tests = []

class GarbdCommonTest(GaleraCommonTest):
    '''Base class for garbd tests on pacemaker remote node.
    Setup creates galera resource, and garbd running on remote node,
    both unstarted (target-state:disabled)
    Teardown deletes the resource'''
    # TODO fix the bundle use case
    def bundle_command(self, cluster_nodes, config):
        engine = self.Env["container_engine"]
        name = config["name"]
        image = config["container_image"]
        return "pcs resource bundle create %s"\
            " container %s image=%s network=host options=\"--user=root --log-driver=journald\""\
            " replicas=2 masters=2 run-command=\"/usr/sbin/pacemaker_remoted\" network control-port=3123"\
            " storage-map id=map0 source-dir=/dev/log target-dir=/dev/log"\
            " storage-map id=map1 source-dir=/dev/zero target-dir=/etc/libqb/force-filesystem-sockets options=ro"\
            " storage-map id=map2 source-dir=/etc/hosts target-dir=/etc/hosts options=ro"\
            " storage-map id=map3 source-dir=/etc/localtime target-dir=/etc/localtime options=ro"\
            " storage-map id=map4 source-dir=/etc/my.cnf.d target-dir=/etc/my.cnf.d options=ro"\
            " storage-map id=map5 source-dir=/var/lib/mysql target-dir=/var/lib/mysql options=rw"\
            " storage-map id=map6 source-dir=/var/log/mysql target-dir=/var/log/mysql options=rw"%\
            (name, engine, image)

    def resource_command(self, cluster_nodes, config):
        name = config["ocf_name"]
        if name == "garbd":
            nodes = ",".join([n+":4567" for n in cluster_nodes])
            return "pcs resource create %s ocf:heartbeat:garbd"\
                " wsrep_cluster_name='ratester'"\
                " wsrep_cluster_address='gcomm://%s'"\
                " options='pc.announce_timeout=PT30s'"\
                " op start timeout=30"%\
                (name, nodes)
        else:
            nodes = ",".join(cluster_nodes)
            return "pcs resource create %s ocf:heartbeat:galera"\
                " wsrep_cluster_address='gcomm://%s'"\
                " log=/var/log/mysql/mysqld.log"\
                " op promote timeout=60 on-fail=block"%\
                (name, nodes)

    def setup_test(self, node):
        cluster_nodes = self.Env["clusters"][0]
        self.setup_inactive_resource(cluster_nodes, self.Env["config"])
        self.setup_inactive_resource(cluster_nodes, self.Env["config-garbd"])
        self.rsh_check(cluster_nodes[0], "pcs constraint location %s rule"\
                       " resource-discovery=exclusive score=0 osprole eq galera"%\
                       self.Env["config"]["name"])
        self.rsh_check(cluster_nodes[0], "pcs constraint location %s rule"\
                       " resource-discovery=exclusive score=0 osprole eq garbd"%\
                       self.Env["config-garbd"]["name"])
        self.rsh_check(cluster_nodes[0], "pcs constraint order start %s then start %s"%\
                       (self.Env["config"]["name"],self.Env["config-garbd"]["name"]))
            
    def teardown_test(self, node):
        cluster_nodes = self.Env["clusters"][0]
        self.delete_resource(self.Env["nodes"])


class ClusterStart(GarbdCommonTest):
    '''Start the galera cluster on all the nodes'''
    def __init__(self, cm):
        GarbdCommonTest.__init__(self,cm)
        self.name = "ClusterStart"

    def test(self, target):
        '''Start an entire Galera cluster'''
        # setup_test has created the inactive resource
        # force a probe to ensure pacemaker knows that the resource
        # is in disabled state
        galera_rsc = self.Env["config"]
        garbd_rsc = self.Env["config-garbd"]
        galera_name = galera_rsc["name"]
        garbd_name = garbd_rsc["name"]
        cluster_nodes = self.Env["clusters"][0]
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe",
                                           self.resource_probe_pattern(galera_rsc,n),
                                           n, 'not running') \
                    for n in cluster_nodes]
        watch = self.make_watch(patterns)
        self.rsh_check(cluster_nodes[0], "pcs resource refresh %s"%galera_name)
        watch.lookforall()

        # TODO: shooting two 'resource refresh in a row' is too fast and
        # prevents us from seeing all probe logs?
        # FIXME: we probably want to check the pattern on the arb node only
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe",
                                            self.resource_probe_pattern(garbd_rsc,n),
                                            n, 'not running') \
                     for n in cluster_nodes]
        watch = self.make_watch(patterns)
        assert not watch.unmatched, watch.unmatched
        self.rsh_check(cluster_nodes[0], "pcs resource refresh %s"%garbd_name)
        watch.lookforall()

        # bundles run OCF resources on bundle nodes, not host nodes
        galera_ocf_name = self.Env["config"]["ocf_name"]
        galera_target_nodes = self.resource_target_nodes(galera_rsc, cluster_nodes)
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "promote", galera_ocf_name, n, 'ok') \
                    for n in galera_target_nodes]
        garbd_target_node = self.resource_target_nodes(garbd_rsc, self.Env["arb"])
        patterns += [self.ratemplates.build("Pat:RscRemoteOp", "start", garbd_name, garbd_target_node, 'ok')]
        watch = self.make_watch(patterns)
        self.rsh_check(cluster_nodes[0], "pcs resource enable %s"%garbd_name)
        self.rsh_check(cluster_nodes[0], "pcs resource enable %s"%galera_name)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        pass

tests.append(ClusterStart)

# TODO port all tests below

# class ClusterStop(ClusterStart):
#     '''Ensure that Garbd is stopped when the galera cluster stop'''
#     def __init__(self, cm):
#         ClusterStart.__init__(self,cm)
#         self.name = "ClusterStop"

#     def test(self, target):
#         # start cluster
#         ClusterStart.test(self,target)

#         patterns = [self.ratemplates.build("Pat:RscRemoteOp", "stop", "galera", n, 'ok') \
#                     for n in self.Env["nodes"]]
#         patterns += [self.ratemplates.build("Pat:RscRemoteOp", "stop", "garbd", "arb", 'ok')]
#         watch = self.create_watch(patterns, self.Env["DeadTime"])
#         watch.setwatch()
#         self.rsh_check(target, "pcs resource disable galera")
#         watch.lookforall()
#         assert not watch.unmatched, watch.unmatched

# tests.append(ClusterStop)

# class StopWhenDemotingLastGaleraNode(ClusterStart):
#     '''Ensure garbd is stopped before the last galera node gracefully
#     exits the galera cluster.

#     This ensures that garbd will reconnect on next cluster bootstrap
#     '''
#     def __init__(self, cm):
#         ClusterStart.__init__(self,cm)
#         self.name = "StopWhenDemotingLastGaleraNode"

#     def test(self, target):
#         '''Ensure that Garbd is stopped when the galera cluster stop'''
#         # start cluster
#         ClusterStart.test(self,target)

#         for ban_node in self.Env["nodes"]:
#             patterns = [self.ratemplates.build("Pat:RscRemoteOp", "stop", "galera", ban_node, 'ok')]
#             # last node? ensure garbd stops before galera,
#             # to prevent garbd "monitor" failures
#             if ban_node == self.Env["nodes"][-1]:
#                 patterns += [self.ratemplates.build("Pat:RscRemoteOp", "stop", "garbd", "arb", 'ok')]
#             watch = self.create_watch(patterns, self.Env["DeadTime"])
#             watch.setwatch()
#             self.rsh_check(target, "pcs resource ban galera-master %s"%ban_node)
#             watch.lookforall()
#             assert not watch.unmatched, watch.unmatched

#     def teardown_test(self, target):
#         self.rsh_check(target, "pcs resource disable galera")
#         self.rsh_check(target, "pcs resource disable garbd")
#         for n in self.Env["nodes"]:
#             self.rsh_check(target, "pcs constraint remove cli-ban-galera-master-on-%s"%n)
#         ClusterStart.teardown_test(self, target)


# tests.append(StopWhenDemotingLastGaleraNode)

# class ErrorIfDisconnectFromAllNodes(ClusterStart):
#     '''Ensure garbd monitor errors if it is disconnected from all galera
#     nodes.

#     This ensures that garbd won't go into split-brain when galera cluster reforms
#     '''
#     def __init__(self, cm):
#         ClusterStart.__init__(self,cm)
#         self.name = "ErrorIfDisconnectFromAllNodes"

#     def test(self, target):
#         '''Ensure that Garbd is stopped when the galera cluster stop'''
#         # start cluster
#         ClusterStart.test(self,target)

#         # make sure galera is not restarted by pacemaker
#         self.rsh_check(target, "pcs resource unmanage galera")

#         patterns=["notice:\s*(Stop|Recover)\s*%s\s*\(Started %s\)"%("garbd","arb")]
#         watch = self.create_watch(patterns, self.Env["DeadTime"])
#         watch.setwatch()
#         for node in self.Env["nodes"]:
#             self.rsh_check(node, "kill -9 $(cat /var/run/mysql/mysqld.pid)")
#         watch.lookforall()
#         assert not watch.unmatched, watch.unmatched

#     def teardown_test(self, target):
#         self.rsh_check(target, "pcs resource disable galera")
#         ClusterStart.teardown_test(self, target)

#     def errorstoignore(self):
#         return ClusterStart.errorstoignore(self)+[
#             # expected after we force-killed the galera servers
#             r"ERROR: MySQL not running: removing old PID file",
#             # garbd will complain that it lost connection w/ galera cluster
#             r"ERROR: garbd disconnected from cluster \".*\""
#         ]

# tests.append(ErrorIfDisconnectFromAllNodes)

# class DontRestartBeforeGaleraIsRestarted(ErrorIfDisconnectFromAllNodes):
#     '''Ensure garbd is stopped before the last galera node gracefully
#     exits the galera cluster.

#     This ensures that garbd will reconnect on next cluster bootstrap
#     '''
#     def __init__(self, cm):
#         ClusterStart.__init__(self,cm)
#         self.name = "DontRestartBeforeGaleraIsRestarted"

#     def test(self, target):
#         '''Ensure that Garbd is stopped when the galera cluster stop'''
#         # start cluster
#         ErrorIfDisconnectFromAllNodes.test(self,target)

#         patterns=["notice:\s*Start\s*%s\s*\(%s - blocked\)"%("garbd","arb")]
#         watch = self.create_watch(patterns, self.Env["DeadTime"])
#         watch.setwatch()
#         self.rsh_check(target, "pcs resource cleanup garbd")
#         watch.lookforall()
#         assert not watch.unmatched, watch.unmatched

# tests.append(DontRestartBeforeGaleraIsRestarted)

# class FenceNodeAfterNetworkDisconnection(ClusterStart):
#     '''On cluster partition, ensure one galera node is fenced, the other
#     survives and garbd is not stopped.  After the fencing, the galera
#     cluster should survive with 2 component: one galera + one garbd.

#     This ensures that there is no interruption of service for galera
#     should half of the cluster gets fenced.
#     '''
#     def __init__(self, cm):
#         ClusterStart.__init__(self,cm)
#         self.name = "FenceNodeAfterNetworkDisconnection"

#     def is_applicable(self):
#         return self.Env["stonith"] == True

#     def create_mysql_user(self, target):
#         self.rsh_check(target,"mysql -nNEe \"drop user 'ratester'@'localhost';\" &>/dev/null || true")
#         self.rsh_check(target,"mysql -nNEe \"create user 'ratester'@'localhost' identified by 'ratester';\"")

#     def test(self, target):
#         '''Trigger a node fence and ensure garbd is still running'''
#         # start cluster
#         ClusterStart.test(self,target)

#         self.create_mysql_user(target)

#         # prevent fenced node to restart at reboot. disable
#         # both node for fencing can kill any one of those
#         for node in self.Env["nodes"]:
#             self.rsh_check(node, "systemctl disable pacemaker")

#         # cause network disruption, node0 cannot receive message from
#         # node1 (will block both corosync and galera cluster)
#         reboot_pattern="notice:\s*Peer\s*(.*)\swas\s*terminated\s*.reboot..*:\s*OK"
#         watch = self.create_watch([reboot_pattern], self.Env["DeadTime"])
#         watch.setwatch()
#         self.rsh_check(self.Env["nodes"][0],"iptables -A INPUT -j DROP -s %s"% \
#                        self.Env["nodes"][1])
#         watch.lookforall()
#         assert not watch.unmatched, watch.unmatched

#         # there should be 2 nodes left in the galera cluster
#         # assert that on the remaining node
#         fenced_node = re.search(reboot_pattern, watch.matched[0]).group(1)
#         surviving_node = [n for n in self.Env["nodes"] if n != fenced_node][0]
#         self.rsh_check(surviving_node, "test $(mysql -uratester -pratester -nNEe \"show status like '%wsrep_cluster_size';\" | tail -1) = 2")

#         self.wait_until_restarted(fenced_node)

#         # restart pacemaker on the fenced node, and wait for galera to
#         # come up on that node
#         patterns = [self.ratemplates.build("Pat:RscRemoteOp", "promote", "galera", fenced_node, 'ok')]
#         watch = self.create_watch(patterns, self.Env["DeadTime"])
#         watch.setwatch()
#         self.rsh_check(fenced_node, "systemctl enable pacemaker")
#         self.rsh_check(fenced_node, "systemctl start pacemaker")
#         watch.lookforall()


# tests.append(FenceNodeAfterNetworkDisconnection)
