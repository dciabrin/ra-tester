#!/usr/bin/env python

'''Resource Agents Tester

Various tests on the Redis RA.
 '''

__copyright__ = '''
Copyright (C) 2020 Damien Ciabrini <dciabrin@redhat.com>
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


from racts.ratest import ResourceAgentTest

tests = []


class RedisCommonTest(ResourceAgentTest):
    def bundle_command(self, cluster_nodes, config):
        engine = self.Env["distribution"].container_engine().package_name()
        name = config["name"]
        image = config["container_image"]
        return "pcs resource bundle create %s"\
            " container %s image=%s network=host options=\"--user=root --log-driver=journald\""\
            " replicas=3 masters=1 run-command=\"/usr/sbin/pacemaker_remoted\" network control-port=3123"\
            " storage-map id=map0 source-dir=/dev/log target-dir=/dev/log"\
            " storage-map id=map1 source-dir=/dev/zero target-dir=/etc/libqb/force-filesystem-sockets options=ro"\
            " storage-map id=map2 source-dir=/etc/hosts target-dir=/etc/hosts options=ro"\
            " storage-map id=map3 source-dir=/etc/localtime target-dir=/etc/localtime options=ro"\
            " storage-map id=map4 source-dir=/etc/redis.conf target-dir=/etc/redis.conf options=ro"\
            " storage-map id=map6 source-dir=/var/lib/redis target-dir=/var/lib/redis options=rw"\
            " storage-map id=map7 source-dir=/var/log target-dir=/var/log options=rw"\
            " storage-map id=map8 source-dir=/var/run/redis target-dir=/var/run/redis options=rw" %\
            (name, engine, image)

    def resource_command(self, cluster_nodes, config):
        name = config["ocf_name"]
        opts = ""
        return "pcs resource create %s ocf:heartbeat:redis %s" %\
            (name, opts)

    def setup_test(self, node):
        self.setup_inactive_resource(self.Env["nodes"])

    def teardown_test(self, node):
        self.delete_resource(self.Env["nodes"])

    def errorstoignore(self):
        return ResourceAgentTest.errorstoignore(self)


class ClusterStart(RedisCommonTest):
    '''Start a redis cluster'''
    def __init__(self, cm):
        RedisCommonTest.__init__(self, cm)
        self.name = "ClusterStart"

    def test(self, target):
        # setup_test has created the inactive resource

        # force a probe to ensure pacemaker knows that the resource
        # is in disabled state
        rsc = self.Env["config"]
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe",
                                           self.resource_probe_pattern(rsc, n),
                                           n, 'not running')
                    for n in self.Env["nodes"]]
        watch = self.make_watch(patterns)
        self.rsh_check(target, "pcs resource refresh %s" % rsc["name"])
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # bundles run OCF resources on bundle nodes, not host nodes
        name = rsc["ocf_name"]
        target_nodes = self.resource_target_nodes(rsc, self.Env["nodes"])
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "promote", name, n, 'ok')
                    for n in target_nodes]
        watch = self.make_watch(patterns)
        self.rsh_check(target, "pcs resource enable %s" % rsc["name"])
        watch.look()
        assert not watch.unmatched, watch.unmatched

        # There's only one master in pacemaker due to master-max=1, but
        # the master score is computed for every node (a computation
        # using number of incoming connections to redis)
        output = self.rsh(target, """cibadmin -Q --scope=status | xmllint --xpath "count(//instance_attributes/nvpair[@name='master-redis'])" -""", stdout=1)
        assert int(output) == len(self.Env["nodes"])

        # There should be only one master in pacemaker, and the redis
        # server running on that node should be in master state
        output = self.rsh(target, """pcs property show redis_REPL_INFO | awk '/redis_REPL_INFO/ {print $2}'""", stdout=1)
        master = output.strip()
        assert master != ''

        output = self.rsh(master, """REDISCLI_AUTH=ratester redis-cli -s /var/run/redis/redis.sock info | grep role""", stdout=1)
        role = output.strip().split(':')
        assert len(role) == 2
        assert role[1] == "master"

        # teardown_test will delete the resource


tests.append(ClusterStart)


class ClusterStop(ClusterStart):
    '''Stop a redis cluster'''
    def __init__(self, cm):
        ClusterStart.__init__(self, cm)
        self.name = "ClusterStop"

    def test(self, target):
        # start cluster
        ClusterStart.test(self, target)
        cluster = self.cluster_manager
        config = self.Env["config"]
        name = config["name"]
        ocf_name = config["ocf_name"]

        target_nodes = self.resource_target_nodes(config, self.Env["nodes"])
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "stop", ocf_name, n, 'ok')
                    for n in target_nodes]
        watch = self.make_watch(patterns)
        self.rsh_check(target, "pcs resource disable %s" % name)
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched
        watch = self.make_watch(patterns)

        # ensure all things are cleaned up after stop
        for target in self.Env["nodes"]:
            self.crm_attr_check(target, "master-redis", expected=cluster.attribute_absent_errno)


tests.append(ClusterStop)
