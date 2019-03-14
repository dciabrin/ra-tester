#!/usr/bin/env python

'''Resource Agent Tester

ScenarioComponent utilities and base classes, extends Pacemaker's CTS
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
from cts.CTStests import CTSTest
# from cts.CM_ais import crm_mcp
from cts.CTSscenarios import *
from cts.CTSaudits    import *
from cts.CTSvars      import *
from cts.patterns     import PatternSelector
from cts.logging      import LogFactory
from cts.remote       import RemoteFactory
from cts.watcher      import LogWatcher
from cts.environment  import EnvFactory
from racts.cluster    import get_cluster_manager
from racts.container  import get_container_engine
from racts.rapatterns import RATemplates

class RATesterScenarioComponent(ScenarioComponent):
    '''Assertion-friendly base class for scenario setup/teardown.
    '''
    def __init__(self, environment):
        self.rsh = RemoteFactory().getInstance()
        self.logger = LogFactory()
        self.Env = environment
        self.verbose = bool(self.Env["verbose"])
        self.cluster_manager = get_cluster_manager(self.Env)
        self.container_engine = get_container_engine(self.Env)
        self.ratemplates = RATemplates()
        self.dependencies = []

    def node_fqdn(self, node):
        return self.rsh(node, "getent ahosts %s | awk '/STREAM/ {print $3;exit}'"%node, stdout=1).strip()

    def node_fqdn_ipv6(self, node):
        return self.rsh(node, "getent ahosts %s.v6 | awk '/STREAM/ {print $3;exit}'"%node, stdout=1).strip()

    def node_shortname(self, node):
        return self.rsh(node, "hostname", stdout=1).strip()

    def node_ip(self, node):
        return self.rsh(node, "getent ahosts %s | awk '/STREAM/ {print $1;exit}'"%node, stdout=1).strip()

    def node_ipv6(self, node):
        return self.rsh(node, "getent ahosts %s.v6 | awk '/STREAM/ {print $1;exit}'"%node, stdout=1).strip()

    def copy_to_nodes(self, files, create_dir=False, owner=False, perm=False, template=False, nodes=False):
        if nodes == False:
            nodes = self.Env["nodes"]
        for node in self.Env["nodes"]:
            for localfile,remotefile in files:
                if create_dir:
                    remotedir=os.path.dirname(remotefile)
                    rc = self.rsh(node, "mkdir -p %s" % remotedir)
                    assert rc == 0, "create dir \"%s\" on remote node \"%s\"" % (remotedir, node)
                src = os.path.join(os.path.dirname(os.path.abspath(__file__)), localfile)
                with tempfile.NamedTemporaryFile() as tmp:
                    if template:
                        with open(src,"r") as f: template=f.read()
                        tmp.write(template.replace("{{node}}",self.node_fqdn(node)))
                        tmp.flush()
                        cpsrc=tmp.name
                    else:
                        cpsrc=src
                    rc = self.rsh.cp(cpsrc, "root@%s:%s" % (node, remotefile))
                    assert rc == 0, "copy test data \"%s\" on remote node \"%s\"" % (src, node)
                    if owner:
                        rc = self.rsh(node, "chown %s %s" % (owner, remotefile))
                        assert rc == 0, "change ownership of \"%s\" on remote node \"%s\"" % (src, node)
                    if perm:
                        rc = self.rsh(node, "chmod %s %s" % (perm, remotefile))
                        assert rc == 0, "change permission of \"%s\" on remote node \"%s\"" % (src, node)

    def copy_to_node(self, node, files, create_dir=False, owner=False, perm=False, template=False):
        for localfile,remotefile in files:
            if create_dir:
                remotedir=os.path.dirname(remotefile)
                rc = self.rsh(node, "mkdir -p %s" % remotedir)
                assert rc == 0, "create dir \"%s\" on remote node \"%s\"" % (remotedir, node)
            src = os.path.join(os.path.dirname(os.path.abspath(__file__)), localfile)
            with tempfile.NamedTemporaryFile(mode='w') as tmp:
                if template:
                    with open(src,"r") as f: lines=f.readlines()
                    for line in lines:
                        tmpstr = line
                        for k,v in template.items():
                            if k in tmpstr:
                                tmpstr = tmpstr.replace(k,v)
                        tmp.write(tmpstr)
                    tmp.flush()
                    cpsrc=tmp.name
                else:
                    cpsrc=src
                rc = self.rsh.cp(cpsrc, "root@%s:%s" % (node, remotefile))
                assert rc == 0, "copy test data \"%s\" on remote node \"%s\"" % (src, node)
                if owner:
                    rc = self.rsh(node, "chown %s %s" % (owner, remotefile))
                    assert rc == 0, "change ownership of \"%s\" on remote node \"%s\"" % (src, node)
                if perm:
                    rc = self.rsh(node, "chmod %s %s" % (perm, remotefile))
                    assert rc == 0, "change permission of \"%s\" on remote node \"%s\"" % (src, node)

    def get_candidate_path(self, candidates, is_dir=False):
        testopt = "-f" if is_dir is False else "-d"
        target = False
        for candidate in candidates:
            if self.rsh(self.Env["nodes"][0], "test %s %s"%(testopt, candidate)) == 0:
                return candidate
        assert target

    def IsApplicable(self):
        return 1

    def SetUp(self, cluster_manager):
        try:
            self.setup_scenario(cluster_manager)
            return 1
        except AssertionError as e:
            print("Setup of scenario %s failed: %s"%\
                  (self.__class__.__name__,str(e)))
        return 0

    def TearDown(self, cluster_manager):
        try:
            self.teardown_scenario(cluster_manager)
            return 1
        except AssertionError as e:
            print("Teardown of scenario %s failed: %s"%\
                  (self.__class__.__name__,str(e)))
        return 0

    def log(self, args):
        self.logger.log(args)

    def debug(self, args):
        self.logger.debug(args)

    def rsh_check(self, target, command, expected = 0):
        if self.verbose: self.log("> [%s] %s"%(target,command))
        res=self.rsh(target, command+" &>/dev/null")
        assert res == expected, "\"%s\" returned %d"%(command,res)

    def check_package_dependencies(self, target, pkgs):
        if self.Env.has_key("skip_install_dependencies"): return
        # make sure a container runtime is available
        if self.Env.has_key("bundle"):
            self.dependencies.append(self.container_engine.package_name())
        # TODO delegate the install to an implementation class
        # based on the running distro
        for p in pkgs:
            res = self.rsh(target, "rpm -qa --qf '%%{NAME}\n' %s | grep %s"%(p, p))
            if res != 0:
                if self.verbose: self.log("[Installing prerequisite %s on %s]"%(p, target))
                self.rsh_check(target, "yum install -y %s"%p)
            else:
                res = self.rsh(target, "repoquery -a --pkgnarrow=updates --qf 'UPDATE' %s | grep UPDATE"%(p,))
                if res == 0:
                    if self.verbose: self.log("[Updating prerequisite %s on %s]"%(p, target))
                    self.rsh_check(target, "yum update -y %s"%p)

    def setup_scenario(self, cluster_manager):
        # install package pre-requisites
        for node in self.Env["nodes"]:
            self.check_package_dependencies(node, self.dependencies)

        # container setup
        if self.Env.has_key("bundle"):
            self.container_engine.enable_engine(self.Env["nodes"])
            if not self.Env.has_key("skip_container_image_pull"):
                self.container_engine.pull_image(self.Env["nodes"],
                                                 self.Env["container_image"])

        # setup cluster
        if self.Env.has_key("keep_cluster"):
            self.setup_keep_cluster(cluster_manager)
        else:
            self.setup_new_cluster(cluster_manager)


    def setup_configs(self, cluster_nodes):
        pass

    def setup_state(self, cluster_nodes):
        pass

    def setup_new_cluster(self, cluster_manager):
        # stop cluster if previously running, failure is not fatal
        for node in self.Env["nodes"]:
            self.log("destroy any existing cluster on node %s"%node)
            self.rsh(node, "pcs cluster destroy")
            self.rsh(node, "systemctl stop pacemaker_remote")
            self.rsh(node, "systemctl disable pacemaker_remote")

        # cleanup previous galera state on disk
        for cluster in self.Env["clusters"]:
            self.setup_configs(cluster)
            self.setup_state(cluster)

        # create a new cluster
        # note: setting up cluster disable pacemaker service. re-enable it
        for cluster in self.Env["clusters"]:
            self.log("Creating cluster for nodes %s"%cluster)
            node=cluster[0]
            patterns = [r"(crmd|pacemaker-controld).*:\s*notice:\sState\stransition\sS_STARTING(\s->.*origin=do_started)?",
                        r"(crmd|pacemaker-controld).*:\s*notice:\sState\stransition\s.*->\sS_IDLE(\s.*origin=notify_crmd)?"]
            watch = LogWatcher(self.Env["LogFileName"], patterns, None, self.Env["DeadTime"], kind=self.Env["LogWatcher"], hosts=cluster)
            watch.setwatch()
            self.cluster_manager.authenticate_nodes(cluster)
            self.cluster_manager.create_cluster(cluster)
            for n in cluster:
                self.rsh_check(n, "systemctl enable pacemaker")
            self.rsh_check(node, "pcs cluster start --all")
            # Disable STONITH by default. A dedicated ScenarioComponent
            # is in charge of enabling it if requested
            self.rsh_check(node, "pcs property set stonith-enabled=false")
            watch.lookforall()
            assert not watch.unmatched, watch.unmatched

    def setup_keep_cluster(self, cluster_manager):
        for cluster in self.Env["clusters"]:
            cluster_manager.log("Reusing cluster %s"%cluster)
            # Disable STONITH by default. A dedicated ScenarioComponent
            # is in charge of enabling it if requested
            self.rsh_check(cluster[0], "pcs property set stonith-enabled=false")

            # Stop and remove resource if it exists
            # Note1: in order to avoid error when stopping the resource while
            # in unknown state, we first reprobe the resource state.
            # Note2: if you clean and delete before pacemaker had a
            # chance to re-probe state, it will consider resource is stopped
            # and will happily delete the resource from the cib even if
            # galera is still running!
            # Note3: after a cleanup, pacemaker may log a warning log
            # if it finds the resource is still running. This does not
            # count as an error for the CTS test
            target=cluster[0]
            rc = self.rsh(target, "pcs resource unmanage %s"%self.Env["rsc_name"])
            if rc == 0:
                cluster_manager.log("Previous resource exists, delete it")
                # no longer true with pacemaker 1.1.18 and resource refresh
                # patterns = [r"(crmd|pacemaker-controld).*:\s*Initiating action.*: probe_complete probe_complete-%s on %s"%(n,n) \
                #         for n in self.Env["nodes"]]
                resource_pattern = re.sub(r'-(master|clone|bundle)','',self.Env["rsc_name"])
                if self.Env["bundle"]:
                    resource_pattern+='-bundle-%s-[0-9]'%self.Env["container_engine"]

                patterns = [self.ratemplates.build("Pat:RscRemoteOp", "probe", resource_pattern, n, '.*') \
                            for n in cluster]
                watch=LogWatcher(self.Env["LogFileName"], patterns, None, self.Env["DeadTime"], kind=self.Env["LogWatcher"], hosts=cluster)
                watch.setwatch()
                self.rsh(target, "pcs resource refresh %s"%self.Env["rsc_name"])
                watch.lookforall()
                assert not watch.unmatched, watch.unmatched
                self.rsh(target, "pcs resource disable %s"%self.Env["rsc_name"])
                self.rsh(target, "pcs resource manage %s"%self.Env["rsc_name"])
                self.rsh(target, "pcs resource delete %s --wait"%self.Env["rsc_name"])

    def teardown_scenario(self, cluster_manager):
        cluster_manager.log("Leaving cluster running on all nodes")
