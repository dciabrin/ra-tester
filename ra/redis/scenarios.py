#!/usr/bin/env python

'''Resource Agents Tester

Redis resource setup
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


import os
from racts.rascenario import RATesterScenarioComponent
from racts.raconfig import RAConfig


scenarios = {}


class PrepareCluster(RATesterScenarioComponent):
    def __init__(self, environment):
        RATesterScenarioComponent.__init__(self, environment, scenario_module_name="redis")
        self.dependencies = ["redis", "stunnel"]

    def setup_configs(self, cluster_nodes):
        config = self.Env["config"]
        node = cluster_nodes[0]

        self.log("Setting up redis config files")
        basedir = os.path.dirname(os.path.abspath(__file__))
        configdir = os.path.join(basedir, "config")
        rediscfg = os.path.join(configdir, "redis.conf.in")

        for node in cluster_nodes:
            if bool(config["ipv6"]):
                ip = "["+self.node_ipv6(node)+"]"
                shortname = self.node_fqdn_ipv6(node)
            else:
                ip = self.node_ip(node)
                if bool(config["tls"]):
                    shortname = self.node_fqdn(node)
                else:
                    shortname = self.node_shortname(node)
            self.copy_to_node(node,
                              [(rediscfg, "/etc/redis.conf")],
                              True, "root", "0444", {
                                  "%HOSTIP%": ip,
                                  "%HOSTNAME%": shortname
                              })

    def setup_state(self, cluster_nodes):
        config = self.Env["config"]
        for node in cluster_nodes:
            # blank galera state on disk
            if not bool(config["skip_install_db"]):
                self.log("recreating empty redis database on node %s" % node)
                self.rsh(node, "rm -rf /var/lib/redis /var/log/redis /var/run/redis")
                self.rsh(node, "mkdir -p /var/lib/redis /var/log/redis /var/run/redis")
            self.rsh(node, "chown -R %s:%s /etc/redis /var/log/redis /var/lib/redis /var/run/redis" %
                     (config["user"], config["user"]))
            if bool(self.Env["config"]["bundle"]):
                self.rsh(node, "which chcon && chcon -R -t container_file_t /etc/redis /var/lib/redis /var/log/redis /var/run/redis")
            else:
                self.rsh(node, "which restorecon && restorecon -R /etc/redis /var/lib/redis /var/log/redis /var/run/redis")


# The scenario below set up two basic configuration for the RA tests
#   . SimpleSetup run the bare tests without customization
#   . BundleSetup wraps the dummy resource into a bundle

class SimpleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        cluster = self.cluster_manager
        config = RAConfig(self.Env, self.module_name, {
            "name": cluster.meta_promotable_resource_name("redis"),
            "ocf_name": "redis",
            "user": "redis",
            "meta": cluster.meta_promotable_config(1),
            "bundle": None,
            "skip_install_db": False,
            "tls": False,
            "ipv6": False
        })
        self.Env["config"] = config
        PrepareCluster.setup_scenario(self, cm)


scenarios["SimpleSetup"] = [SimpleSetup]


class BundleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        config = RAConfig(self.Env, self.module_name, {
            "name": "redis-bundle",
            "ocf_name": "redis",
            "meta": "container-attribute-target=host notify=true",
            "user": "42460",
            "bundle": True,
            "container_image": "docker.io/tripleomaster/centos-binary-redis:current-tripleo-rdo",
            "skip_install_db": False,
            "tls": False,
            "ipv6": False,
        })
        self.Env["config"] = config
        PrepareCluster.setup_scenario(self, cm)


scenarios["BundleSetup"] = [BundleSetup]
