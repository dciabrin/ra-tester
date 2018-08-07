#!/usr/bin/env python

'''Resource Agents Tester

Various scenarios setups for the RabbitMQ resource agent
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
        self.dependencies = ["rabbitmq-server"]

    def setup_configs(self, cluster_nodes):
        self.log("Setting up rabbitmq config files")
        basedir=os.path.dirname(os.path.abspath(__file__))
        configdir=os.path.join(basedir, "config")
        rmqconfig=os.path.join(configdir, "rabbitmq.config.in")
        rmqenv=os.path.join(configdir, "rabbitmq-env.conf.in")
        rmqadmin=os.path.join(configdir, "rabbitmqadmin.conf")
        erlcookie=os.path.join(configdir, "cookie")

        for node in cluster_nodes:
            ip=self.node_ip(node)
            ipcomma=ip.replace(".",",")
            shortname=self.node_shortname(node)
            self.copy_to_node(node,
                              [(rmqconfig,   "/etc/rabbitmq/rabbitmq.config"),
                               (rmqenv,      "/etc/rabbitmq/rabbitmq-env.conf"),
                               (rmqadmin,    "/etc/rabbitmq/rabbitmqadmin.conf"),
                               ("/dev/null", "/etc/rabbitmq/inetrc")],
                              True, "root", "0444", {
                                  "%HOSTIP%": ip,
                                  "%HOSTIPCOMMA%": ipcomma,
                                  "%HOSTNAME%": shortname
                              })

    def setup_state(self, cluster_nodes):
        for node in cluster_nodes:
            # blank rabbitmq state on disk
            self.rsh(node, "rm -rf /var/lib/rabbitmq")
            basedir=os.path.dirname(os.path.abspath(__file__))
            configdir=os.path.join(basedir, "config")
            erlcookie=os.path.join(configdir, "cookie")
            self.copy_to_node(node,
                              [(erlcookie,   "/var/lib/rabbitmq/.erlang.cookie")],
                              True, self.Env["rabbitmq_user"], "0600")
            # chown log file
            self.rsh(node, "chown -R %s:%s /var/log/rabbitmq /var/lib/rabbitmq"%\
                     (self.Env["rabbitmq_user"],self.Env["rabbitmq_user"]))




# The scenarios below set up two basic configuration for the RA tests
#   . SimpleSetup runs the test in a rabbitmq clone resource
#   . BundleSetup wraps the rabbitmq resource into a bundle

class SimpleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        self.Env["rsc_name"] = "rabbitmq-clone"
        self.Env["meta"] = "notify=true clone interleave=true ordered=true"
        self.Env["rabbitmq_user"] = "rabbitmq"
        PrepareCluster.setup_scenario(self,cm)

scenarios["SimpleSetup"]=[SimpleSetup]


class BundleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        self.Env["bundle"] = True
        self.Env["rsc_name"] = "rabbitmq-bundle"
        self.Env["meta"] = "container-attribute-target=host notify=true"
        self.Env["rabbitmq_user"] = "42439" # rabbitmq user uid in kolla image
        self.Env["container_image"] = "docker.io/tripleoqueens/centos-binary-rabbitmq:current-tripleo-rdo"
        PrepareCluster.setup_scenario(self,cm)

scenarios["BundleSetup"]=[BundleSetup]
