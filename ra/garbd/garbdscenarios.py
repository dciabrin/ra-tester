'''Resource Agents Tester

Regression scenarios for garbd RA
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

scenarios = {}

class GarbdRemote(Sequence):
    pass

scenarios[GarbdRemote]=[]

class GarbdRemoteNewCluster(RATesterScenarioComponent):
    def __init__(self, environment, verbose=False):
        RATesterScenarioComponent.__init__(self, environment, verbose)

    def IsApplicable(self):
        return not self.Env.has_key("keep_cluster")

    def copy_to_nodes(self, files, create_dir=False, owner=False, perm=False):
        for node in self.Env["nodes"]:
            for localfile,remotefile in files:
                if create_dir:
                    remotedir=os.path.dirname(remotefile)
                    rc = self.rsh(node, "mkdir -p %s" % remotedir)
                    assert rc == 0, "create dir \"%s\" on remote node \"%s\"" % (remotedir, node)
                src = os.path.join(os.path.dirname(os.path.abspath(__file__)), localfile)
                rc = self.rsh.cp(src, "root@%s:%s" % (node, remotefile))
                assert rc == 0, "copy test data \"%s\" on remote node \"%s\"" % (src, node)
                if owner:
                    rc = self.rsh(node, "chown %s %s" % (owner, remotefile))
                    assert rc == 0, "change ownership of \"%s\" on remote node \"%s\"" % (src, node)
                if perm:
                    rc = self.rsh(node, "chmod %s %s" % (perm, remotefile))
                    assert rc == 0, "change permission of \"%s\" on remote node \"%s\"" % (src, node)


    def setup_scenario(self, cluster_manager):
        # galera-specific data
        self.log("Copy test-specific galera config")
        with tempfile.NamedTemporaryFile() as tmp:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "galera.cnf.in"),"r") as f: template=f.read()
            tmp.write(template.replace("{{nodes}}",",".join(self.Env["nodes"])))
            tmp.flush()
            galera_config_files = [(tmp.name,"/etc/my.cnf.d/galera.cnf")]
            self.copy_to_nodes(galera_config_files)

        remote_authkey = "/etc/pacemaker/authkey"
        if not self.rsh.exists_on_all(remote_authkey, self.Env["nodes"]):
            self.log("Creating auth key for communication with pacemaker remote")
            with tempfile.NamedTemporaryFile() as tmp:
                tmp.write(os.urandom(4096))
                tmp.flush()
                self.copy_to_nodes([(tmp.name, remote_authkey)], True, "root:haclient", "440")

        # cluster_manager.prepare()

        # stop cluster if previously running, failure is not fatal
        for node in self.Env["nodes"]:
            self.rsh(node, "pcs cluster destroy")
            self.rsh(node, "systemctl stop pacemaker_remote")
            self.rsh(node, "systemctl enable pacemaker")

        # reconfigure cluster for 2-nodes + one remote arbitrator
        self.Env["arb"]=self.Env["nodes"][-1]
        self.Env["nodes"]=self.Env["nodes"][:-1]
        self.rsh_check(self.Env["nodes"][0], "pcs cluster setup --force --name ratester %s %s" % \
                       (self.Env["nodes"][0],self.Env["nodes"][1]))
        self.rsh_check(self.Env["nodes"][0], "pcs cluster start --all")

        # TODO: better way to wait until cluster is started
        time.sleep(8)

        # Disable STONITH by default. A dedicated ScenarioComponent
        # is in charge of enabling it if requested
        self.rsh_check(self.Env["nodes"][0], "pcs property set stonith-enabled=false")

        for node in self.Env["nodes"]:
            self.rsh_check(node, "pcs property set --node %s osprole=controller"%node)

        # cluster_manager.prepare()

        # pacemaker remote to host garbd
        res=self.rsh_check(self.Env["arb"], "systemctl disable pacemaker")
        res=self.rsh_check(self.Env["arb"], "systemctl enable pacemaker_remote")
        res=self.rsh_check(self.Env["arb"], "systemctl start pacemaker_remote")

        remote_ok_pat = r"crmd.*:\s*Operation %s_start.*:\s*ok \(node=.*,\s*confirmed=true\)"%("arb",)
        watch=LogWatcher(self.Env["LogFileName"], [remote_ok_pat], None, self.Env["DeadTime"], kind=self.Env["LogWatcher"], hosts=self.Env["nodes"])
        # watch = self.create_watch([remote_ok_pat], self.Env["DeadTime"])
        watch.setwatch()
        res=self.rsh_check(self.Env["nodes"][0], "pcs resource create arb ocf:pacemaker:remote server=%s reconnect_interval=60 op monitor interval=20"%self.Env["arb"])
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        self.rsh_check(self.Env["nodes"][0], "pcs property set --node arb osprole=arbitrator")

        # there's no selinux context for garbd currently
        res=self.rsh_check(self.Env["arb"], "setenforce 0")


    def TearDown(self, cluster_manager):
        cluster_manager.log("Leaving Cluster running on all nodes")
        return 1

scenarios[GarbdRemote].append(GarbdRemoteNewCluster)


class GarbdRemoteKeepCluster(RATesterScenarioComponent):
    def __init__(self, environment, verbose=False):
        RATesterScenarioComponent.__init__(self, environment, verbose)

    def IsApplicable(self):
        return self.Env.has_key("keep_cluster")

    def setup_scenario(self, cluster_manager):
        # consider cluster has 2-nodes + one remote arbitrator
        cluster_manager.log("Reusing cluster")
        target=self.Env["nodes"][0]

        self.Env["arb"]=self.Env["nodes"][-1]
        self.rsh_check(target, "pcs property set --node arb osprole=arbitrator")

        # attempt at cleaning up and remove garbd if it exists
        rc = self.rsh(target, "pcs resource unmanage garbd")
        if rc == 0:
            self.rsh(target, "pcs resource cleanup garbd")
            self.rsh(target, "pcs resource disable garbd")
            self.rsh(target, "pcs resource manage garbd")
            self.rsh(target, "pcs resource delete garbd --wait")

        self.Env["nodes"]=self.Env["nodes"][:-1]
        for node in self.Env["nodes"]:
            self.rsh_check(node, "pcs property set --node %s osprole=controller"%node)

        # attempt at cleaning up and remove galera if it exists
        # try to avoid cluster error when we stop the resource because
        # we don't know in which state it was left.
        # => tell pacemaker that we're going to stop galera, cleanup
        # any error that could prevent the stop, and let pacemaker
        # know the current state of the resource before processing
        # Note: if you clean and delete before pacemaker had a
        # chance to re-probe state, it will consider resource is stopped
        # and will happily delete the resource from the cib even if
        # galera is still running!
        # Note2: after a cleanup, pacemaker may log a warning log
        # if it finds the resource is still running. This does not
        # count as an error for the CTS test
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

    def teardown_scenario(self, cluster_manager):
        cluster_manager.log("Leaving cluster running on all nodes")

scenarios[GarbdRemote].append(GarbdRemoteKeepCluster)
