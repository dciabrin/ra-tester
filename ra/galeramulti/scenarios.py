#!/usr/bin/env python

'''Resource Agents Tester

Regression scenarios for galera RA - multicluster variant
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

from racts.rascenario import RATesterScenarioComponent



scenarios = {}

class PrepareCluster(RATesterScenarioComponent):
    def __init__(self, environment, verbose=False):
        RATesterScenarioComponent.__init__(self, environment, verbose)
        self.dependencies = ["mariadb-server-galera"]

    def setup_configs(self, cluster_nodes):
        self.log("Setting up galera config files")
        basedir=os.path.dirname(os.path.abspath(__file__))
        configdir=os.path.join(basedir, "config")
        galeracfg=os.path.join(configdir, "galera.cnf.in")
        killgdb=os.path.join(configdir, "kill-during-txn.gdb")
        slowsst=os.path.join(configdir, "slow_down_sst.sh")
        gcomm="gcomm://"+(",".join(cluster_nodes))

        for node in cluster_nodes:
            ip=self.node_ip(node)
            shortname=self.node_shortname(node)
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
        for node in cluster_nodes:
            # blank galera state on disk
            if not self.Env.has_key("galera_skip_install_db"):
                self.rsh(node, "rm -rf /var/lib/mysql")
                self.rsh(node, "mkdir -p /var/lib/mysql")
            self.rsh(node, "chown -R %s:%s /var/log/mysql /var/lib/mysql"%\
                     (self.Env["galera_user"],self.Env["galera_user"]))
            if not self.Env.has_key("galera_skip_install_db"):
                self.log("recreating empty mysql database on node %s"%node)
                self.rsh(node, "sudo -u mysql mysql_install_db")



# The scenario below set up various configuration of the galera tests

class SimpleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        self.Env["rsc_name"] = "galera-master"
        self.Env["meta"] = "master-max=3 --master"
        self.Env["galera_user"] = "mysql"
        PrepareCluster.setup_scenario(self,cm)

scenarios["SimpleSetup"]=[SimpleSetup]


class BundleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        self.Env["bundle"] = True
        self.Env["rsc_name"] = "galera-bundle"
        self.Env["meta"] = "container-attribute-target=host notify=true"
        self.Env["galera_user"] = "42434" # galera user uid in kolla image
        self.Env["container_image"] = "docker.io/tripleoqueens/centos-binary-mariadb:current-tripleo-rdo"
        PrepareCluster.setup_scenario(self,cm)

scenarios["BundleSetup"]=[BundleSetup]



# class HostMapSetup(GaleraPrepareCluster):

#     def setup_scenario(self, cm):
#         target=self.Env["nodes"][0]
#         pcmk_nodes=self.Env["nodes"]
#         nodes_ip=[self.rsh(target,"getent ahostsv4 %s | grep STREAM | cut -d' ' -f1"%n,
#                            stdout=1).strip() for n in pcmk_nodes]
#         pcmk_host_map=";".join(["%s:%s"%(a,b) for a,b in zip(pcmk_nodes,nodes_ip)])
#         self.Env["galera_gcomm"]=",".join(nodes_ip)
#         self.Env["galera_opts"] = "cluster_host_map='%s'"%pcmk_host_map
#         self.Env["galera_rsc_name"] = "galera-master"
#         self.Env["galera_user"] = "mysql"
#         self.Env["galera_meta"] = "master-max=3 --master"
#         GaleraPrepareCluster.setup_scenario(self,cm)

# scenarios["HostMapSetup"]=[HostMapSetup]
