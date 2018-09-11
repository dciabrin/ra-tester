#!/usr/bin/env python

'''Resource Agents Tester

Regression scenarios for galera RA
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

class GaleraSetupMixin(object):
    def mysql_etc_dir(self):
        target_dir = self.get_candidate_path(["/etc/my.cnf.d", "/etc/mysql/conf.d"],
                                             is_dir=True)
        return target_dir

    def init_and_setup_mysql_defaults(self):
        self.log("Ensuring minimal mysql configuration")
        for node in self.Env["nodes"]:
            rc = self.rsh(node,
                          "if [ ! -d /var/lib/mysql ]; then "
                          "mkdir /var/lib/mysql; fi")
            assert rc == 0, "could not create dir on remote node %s" % node
            rc = self.rsh(node,
                          "chown -R %s:%s /var/lib/mysql"%\
                          (self.Env["galera_user"],self.Env["galera_user"]) )
            assert rc == 0, "could not set permission of galera directory remote node %s" % node
            etc_dir = self.mysql_etc_dir()
            rc = self.rsh(node,
                          "if ! `my_print_defaults --mysqld | grep -q socket`; then "
                          "echo -e '[mysqld]\nsocket=/var/lib/mysql/mysql.sock\n"
                          "[client]\nsocket=/var/lib/mysql/mysql.sock'"
                          ">%s/ratester.cnf; fi" %etc_dir)
            assert rc == 0, "could not override mysql settings on node %s" % node

    def setup_galera_config(self):
        self.log("Copying test-specific galera config")
        with tempfile.NamedTemporaryFile() as tmp:
            targetlib = self.get_candidate_path(["/usr/lib64/galera/libgalera_smm.so",
                                                 "/usr/lib/galera/libgalera_smm.so",
                                                 "/usr/lib64/galera-3/libgalera_smm.so"])
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "galera.cnf.in"),"r") as f: template=f.read()
            nodes_fqdn=[self.node_fqdn(x) for x in self.Env["nodes"]]
            tmp.write(template.replace("{{nodes}}",",".join(nodes_fqdn))\
                              .replace("{{libpath}}",targetlib))
            tmp.flush()
            target_dir = self.mysql_etc_dir()
            galera_config_files = [(tmp.name,os.path.join(target_dir,"galera.cnf"))]
            self.copy_to_nodes(galera_config_files,template=True)


scenarios = {}

class GaleraPrepareCluster(RATesterScenarioComponent, GaleraSetupMixin):
    def __init__(self, environment):
        RATesterScenarioComponent.__init__(self, environment)

    def setup_scenario(self, cluster_manager):
        if self.Env.has_key("keep_cluster"):
            self.setup_keep_cluster(cluster_manager)
        else:
            self.setup_new_cluster(cluster_manager)

    def teardown_scenario(self, cluster_manager):
        if self.Env.has_key("keep_cluster"):
            self.teardown_keep_cluster(cluster_manager)
        else:
            self.teardown_new_cluster(cluster_manager)


    def pull_galera_container_image(self):
        for node in self.Env["nodes"]:
            self.log("pulling galera container image on %s"%node)
            rc = self.rsh(node, "docker pull docker.io/tripleoupstream/centos-binary-mariadb:latest")
            assert rc == 0, \
                "failed to pull galera container image on remote node \"%s\"" % \
                (node,)

    def check_prerequisite(self, prerequisite):
        missing_reqs = False
        for req in prerequisite:
            if not self.rsh.exists_on_all(req, self.Env["nodes"]):
                self.log("error: %s could not be found on remote nodes. "
                         "Please install the necessary package to run the tests"%  req)
                missing_reqs = True
        assert not missing_reqs

    def setup_new_cluster(self, cluster_manager):
        # pre-requisites
        self.check_prerequisite(["/usr/bin/gdb", "/usr/bin/screen", "/usr/bin/dig"])
        if self.Env["galera_bundle"]:
            self.check_prerequisite(["/usr/bin/docker"])

        # galera-specific data
        test_scripts = ["kill-during-txn.gdb", "slow_down_sst.sh"]
        for node in self.Env["nodes"]:
            for script in test_scripts:
                src = os.path.join(os.path.dirname(os.path.abspath(__file__)), script)
                rc = self.rsh.cp(src, "root@%s:/tmp/%s" % (node, script))
                assert rc == 0, \
                    "failed to copy data \"%s\" on remote node \"%s\"" % \
                    (src, node)

        # container setup
        if self.Env["galera_bundle"]:
            self.rsh(node, "systemctl enable docker")
            self.rsh(node, "systemctl start docker")
            self.pull_galera_container_image()

        # mysql setup
        self.init_and_setup_mysql_defaults()
        self.setup_galera_config()

        # clean up any traffic control on target network interface
        for node in self.Env["nodes"]:
            self.rsh(node, "/tmp/slow_down_sst.sh -n %s off"%node)

        # stop cluster if previously running, failure is not fatal
        for node in self.Env["nodes"]:
            self.rsh(node, "pcs cluster destroy")
            self.rsh(node, "systemctl enable pacemaker")
            self.rsh(node, "systemctl stop pacemaker_remote")
            self.rsh(node, "systemctl disable pacemaker_remote")

        # create a new cluster
        # note: setting up cluster disable pacemaker service. re-enable it
        patterns = [r"crmd.*:\s*notice:\sState\stransition\sS_STARTING(\s->.*origin=do_started)?",
                    r"crmd.*:\s*notice:\sState\stransition\s.*->\sS_IDLE(\s.*origin=notify_crmd)?"]
        watch = LogWatcher(self.Env["LogFileName"], patterns, None, self.Env["DeadTime"], kind=self.Env["LogWatcher"], hosts=self.Env["nodes"])
        watch.setwatch()
        self.rsh_check(self.Env["nodes"][0], "pcs cluster setup --force --name ratester %s" % \
                       " ".join(self.Env["nodes"]))
        self.rsh_check(self.Env["nodes"][0], "systemctl enable pacemaker")
        self.rsh_check(self.Env["nodes"][0], "pcs cluster start --all")
        # Disable STONITH by default. A dedicated ScenarioComponent
        # is in charge of enabling it if requested
        self.rsh_check(self.Env["nodes"][0], "pcs property set stonith-enabled=false")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

    def teardown_new_cluster(self, cluster_manager):
        cluster_manager.log("Leaving cluster running on all nodes")

    def setup_keep_cluster(self, cluster_manager):
        cluster_manager.log("Reusing cluster")

        # Disable STONITH by default. A dedicated ScenarioComponent
        # is in charge of enabling it if requested
        self.rsh_check(self.Env["nodes"][0], "pcs property set stonith-enabled=false")

        # Stop and remove galera if it exists
        # Note1: in order to avoid error when stopping the resource while
        # in unknown state, we first reprobe the resource state.
        # Note2: if you clean and delete before pacemaker had a
        # chance to re-probe state, it will consider resource is stopped
        # and will happily delete the resource from the cib even if
        # galera is still running!
        # Note3: after a cleanup, pacemaker may log a warning log
        # if it finds the resource is still running. This does not
        # count as an error for the CTS test
        target=self.Env["nodes"][0]
        rc = self.rsh(target, "pcs resource unmanage galera")
        if rc == 0:
            patterns = [r"crmd.*:\s*Initiating action.*: probe_complete probe_complete-%s on %s"%(n,n) \
                    for n in self.Env["nodes"]]
            watch=LogWatcher(self.Env["LogFileName"], patterns, None, self.Env["DeadTime"], kind=self.Env["LogWatcher"], hosts=self.Env["nodes"])
            watch.setwatch()
            self.rsh(target, "pcs resource cleanup galera")
            watch.lookforall()
            assert not watch.unmatched, watch.unmatched
            self.rsh(target, "pcs resource disable galera")
            self.rsh(target, "pcs resource manage galera")
            self.rsh(target, "pcs resource delete galera --wait")

    def teardown_keep_cluster(self, cluster_manager):
        cluster_manager.log("Leaving cluster running on all nodes")


# The scenario below set up various configuration of the galera tests

class SimpleSetup(GaleraPrepareCluster):

    def setup_scenario(self, cm):
        self.Env["galera_gcomm"]=",".join(self.Env["nodes"])
        self.Env["galera_rsc_name"] = "galera-master"
        self.Env["galera_opts"] = ""
        self.Env["galera_user"] = "mysql"
        self.Env["galera_meta"] = "master-max=3 --master"
        GaleraPrepareCluster.setup_scenario(self,cm)

scenarios["SimpleSetup"]=[SimpleSetup]

class HostMapSetup(GaleraPrepareCluster):

    def setup_scenario(self, cm):
        target=self.Env["nodes"][0]
        pcmk_nodes=self.Env["nodes"]
        nodes_ip=[self.rsh(target,"getent ahostsv4 %s | grep STREAM | cut -d' ' -f1"%n,
                           stdout=1).strip() for n in pcmk_nodes]
        pcmk_host_map=";".join(["%s:%s"%(a,b) for a,b in zip(pcmk_nodes,nodes_ip)])
        self.Env["galera_gcomm"]=",".join(nodes_ip)
        self.Env["galera_opts"] = "cluster_host_map='%s'"%pcmk_host_map
        self.Env["galera_rsc_name"] = "galera-master"
        self.Env["galera_user"] = "mysql"
        self.Env["galera_meta"] = "master-max=3 --master"
        GaleraPrepareCluster.setup_scenario(self,cm)

scenarios["HostMapSetup"]=[HostMapSetup]

class KollaSetup(GaleraPrepareCluster):

    def setup_scenario(self, cm):
        target=self.Env["nodes"][0]
        pcmk_nodes=self.Env["nodes"]
        pcmk_host_map=";".join(["%s:%s"%(a,b) for a,b in zip(pcmk_nodes,pcmk_nodes)])
        self.Env["galera_gcomm"] = ",".join(pcmk_nodes)
        self.Env["galera_opts"] = "cluster_host_map='%s'"%pcmk_host_map
        self.Env["galera_rsc_name"] = "galera-bundle"
        self.Env["galera_meta"] = "container-attribute-target=host bundle galera-bundle"
        self.Env["galera_bundle"] = True
        self.Env["galera_user"] = "42434" # mysql uid in kolla image
        GaleraPrepareCluster.setup_scenario(self,cm)
scenarios["KollaSetup"]=[KollaSetup]
