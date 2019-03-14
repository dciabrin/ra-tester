#!/usr/bin/env python

'''Resource Agents Tester

Regression scenarios for galera RA
 '''

__copyright__ = '''
Copyright (C) 2015-2018 Damien Ciabrini <dciabrin@redhat.com>
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

from racts.rascenario import RATesterScenarioComponent


                
# class GaleraSetupMixin(object):
#     def mysql_etc_dir(self):
#         target_dir = self.get_candidate_path(["/etc/my.cnf.d", "/etc/mysql/conf.d"],
#                                              is_dir=True)
#         return target_dir

#     def init_and_setup_mysql_defaults(self):
#         self.log("Ensuring minimal mysql configuration")
#         for node in self.Env["nodes"]:
#             rc = self.rsh(node,
#                           "if [ ! -d /var/lib/mysql ]; then "
#                           "mkdir /var/lib/mysql; fi")
#             assert rc == 0, "could not create dir on remote node %s" % node
#             rc = self.rsh(node,
#                           "chown -R %s:%s /var/lib/mysql"%\
#                           (self.Env["galera_user"],self.Env["galera_user"]) )
#             assert rc == 0, "could not set permission of galera directory remote node %s" % node
#             etc_dir = self.mysql_etc_dir()
#             rc = self.rsh(node,
#                           "if ! `my_print_defaults --mysqld | grep -q socket`; then "
#                           "echo -e '[mysqld]\nsocket=/var/lib/mysql/mysql.sock\n"
#                           "[client]\nsocket=/var/lib/mysql/mysql.sock'"
#                           ">%s/ratester.cnf; fi" %etc_dir)
#             assert rc == 0, "could not override mysql settings on node %s" % node

#     def setup_galera_config(self):
#         self.log("Copying test-specific galera config")
#         with tempfile.NamedTemporaryFile() as tmp:
#             targetlib = self.get_candidate_path(["/usr/lib64/galera/libgalera_smm.so",
#                                                  "/usr/lib/galera/libgalera_smm.so",
#                                                  "/usr/lib64/galera-3/libgalera_smm.so"])
#             with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "galera.cnf.in"),"r") as f: template=f.read()
#             nodes_fqdn=[self.node_fqdn(x) for x in self.Env["nodes"]]
#             tmp.write(template.replace("{{nodes}}",",".join(nodes_fqdn))\
#                               .replace("{{libpath}}",targetlib))
#             tmp.flush()
#             target_dir = self.mysql_etc_dir()
#             galera_config_files = [(tmp.name,os.path.join(target_dir,"galera.cnf"))]
#             self.copy_to_nodes(galera_config_files,template=True)


scenarios = {}


class PrepareCluster(RATesterScenarioComponent):
    def __init__(self, environment):
        RATesterScenarioComponent.__init__(self, environment)
        self.dependencies = ["mariadb-server-galera"]

    def setup_configs(self, cluster_nodes):
        self.log("Setting up galera config files")
        basedir=os.path.dirname(os.path.abspath(__file__))
        configdir=os.path.join(basedir, "config")
        galeracfg=os.path.join(configdir, "galera.cnf.in")
        killgdb=os.path.join(configdir, "kill-during-txn.gdb")
        slowsst=os.path.join(configdir, "slow_down_sst.sh")
        if self.Env.has_key("use_ipv6"):
            gcomm="gcomm://"+(",".join([self.node_fqdn_ipv6(n) for n in cluster_nodes]))
        else:
            gcomm="gcomm://"+(",".join(cluster_nodes))

        for node in cluster_nodes:
            if self.Env.has_key("use_ipv6"):
                ip = "["+self.node_ipv6(node)+"]"
                shortname = self.node_fqdn_ipv6(node)
            else:
                ip = self.node_ip(node)
                shortname = self.node_shortname(node)
            self.copy_to_node(node,
                              [(galeracfg, "/etc/my.cnf.d/galera.cnf"),
                               (killgdb,   "/tmp/kill-during-txn.gdb"),
                               (slowsst,   "/tmp/slow_down_sst.sh")],
                              True, "root", "0444", {
                                  "%HOSTIP%": ip,
                                  "%GCOMM%": gcomm,
                                  "%HOSTNAME%": shortname,
                                  "%GALERALIBPATH%": "/usr/lib64/galera/libgalera_smm.so"
                              })

    def setup_state(self, cluster_nodes):
        resource=self.Env["resource"]
        for node in cluster_nodes:
            # blank galera state on disk
            if not self.Env.has_key("galera_skip_install_db"):
                self.log("recreating empty mysql database on node %s"%node)
                self.rsh(node, "rm -rf /var/lib/mysql /var/log/mysql")
                self.rsh(node, "mkdir -p /var/lib/mysql /var/log/mysql")
                self.rsh(node, "sudo mysql_install_db")
            self.rsh(node, "chown -R %s:%s /var/log/mysql /var/lib/mysql"%\
                     (resource["user"],resource["user"]))




# The scenario below set up various configuration of the galera tests

class SimpleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        resource = {
            "name": "galera-clone",
            "ocf_name": "galera",
            "alt_node_names": {},
            "meta": "promotable master-max=3",
            "user": "mysql",
            "bundle": None
        }
        if self.Env.has_key("use_ipv6"):
            nodes = self.Env["nodes"]
            nodes_fqdn_ipv6 = [self.node_fqdn_ipv6(n) for n in nodes]
            resource["alt_node_names"] = dict(zip(nodes,nodes_fqdn_ipv6))
        self.Env["resource"] = resource
        PrepareCluster.setup_scenario(self,cm)

scenarios["SimpleSetup"]=[SimpleSetup]


class BundleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        resource = {
            "name": "galera-bundle",
            "ocf_name": "galera",
            "alt_node_names": {},
            "meta": "container-attribute-target=host notify=true",
            "user": "42434",
            "bundle": True,
            "container_image": self.Env["galera_container_image"] or \
                "docker.io/tripleoqueens/centos-binary-mariadb:current-tripleo-rdo"
        }
        if self.Env.has_key("use_ipv6"):
            nodes = self.Env["nodes"]
            nodes_fqdn_ipv6 = [self.node_fqdn_ipv6(n) for n in nodes]
            resource["alt_node_names"] = zip(nodes,nodes_fqdn_ipv6)
        self.Env["resource"] = resource
        PrepareCluster.setup_scenario(self,cm)

scenarios["BundleSetup"]=[BundleSetup]


# class HostMapSetup(PrepareCluster):

#     def setup_scenario(self, cm):
#         target=self.Env["nodes"][0]
#         pcmk_nodes=self.Env["nodes"]
#         nodes_ip=[self.rsh(target,"getent ahostsv4 %s | grep STREAM | cut -d' ' -f1"%n,
#                            stdout=1).strip() for n in pcmk_nodes]
#         pcmk_host_map=";".join(["%s:%s"%(a,b) for a,b in zip(pcmk_nodes,nodes_ip)])
#         self.Env["galera_opts"] = "cluster_host_map='%s'"%pcmk_host_map
#         self.Env["galera_gcomm"]=",".join(nodes_ip)
#         self.Env["galera_rsc_name"] = "galera-master"
#         self.Env["galera_user"] = "mysql"
#         self.Env["galera_meta"] = "master-max=3 --master"
#         PrepareCluster.setup_scenario(self,cm)

# # scenarios["HostMapSetup"]=[HostMapSetup]


# class KollaSetup(PrepareCluster):

#     def setup_scenario(self, cm):
#         target=self.Env["nodes"][0]
#         pcmk_nodes=self.Env["nodes"]
#         pcmk_host_map=";".join(["%s:%s"%(a,b) for a,b in zip(pcmk_nodes,pcmk_nodes)])
#         self.Env["galera_gcomm"] = ",".join(pcmk_nodes)
#         self.Env["galera_opts"] = "cluster_host_map='%s'"%pcmk_host_map
#         self.Env["galera_rsc_name"] = "galera-bundle"
#         self.Env["galera_meta"] = "container-attribute-target=host bundle galera-bundle"
#         self.Env["galera_bundle"] = True
#         self.Env["galera_user"] = "42434" # mysql uid in kolla image
#         PrepareCluster.setup_scenario(self,cm)
# # scenarios["KollaSetup"]=[KollaSetup]
