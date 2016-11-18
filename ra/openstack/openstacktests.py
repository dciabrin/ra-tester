#!/usr/bin/env python

'''Resource Agents Tester

Regression test for OpenStack HA
 '''

__copyright__ = '''
Copyright (C) 2016 Damien Ciabrini <dciabrin@redhat.com>
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

from racts.ratest import ResourceAgentTest, ReuseCluster

tests = []


class OpenStackTest(ResourceAgentTest):
    '''Base class for OpenStack HA tests.
    It is assumed that a galera resource is up and running in the
    pacemaker cluster. Teardown asserts that galera is up and the
    end of the test.
    '''
    def __init__(self, cm, verbose=False):
        ResourceAgentTest.__init__(self,cm)
        # self.start_cluster = False
        self.verbose = verbose

    def setup_test(self, node):
        '''Setup the given test'''
        pass

    def teardown_test(self, node):
        pass

    def errorstoignore(self):
        return [
            # currently, ERROR is logged before mysqld is started...
            r"ERROR:\s*MySQL is not running",
            # every SST finished by killing rsynd on the joiner side...
            r"rsyncd.*:\s*rsync error: received SIGINT, SIGTERM, or SIGHUP",
            # recent version of pacemaker complain about galera's metadata output
            r"crmd.*:\s*error: Failed to receive meta-data for ocf:heartbeat:galera",
            r"crmd.*:\s*error: No metadata for ocf::heartbeat:galera"
        ]

    def errors_after_forced_stop(self):
        # after the node has been force-stopped, monitor op will fail and log
        return [
            r"ERROR: Unable to retrieve wsrep_cluster_status, verify check_user",
            r"ERROR: local node <.*> is started, but not in primary mode. Unknown state.",
            r"ERROR: MySQL not running: removing old PID file",
            r"notice:\s.*galera_monitor_.*:.*\s\[\sERROR\s.*\s\(HY000\): Lost\sconnection\sto\sMySQL\sserver"
        ]


class ServicesReconnectAfterGaleraIsRestarted(OpenStackTest):
    '''Start the galera cluster on all the nodes'''
    def __init__(self, cm):
        OpenStackTest.__init__(self,cm)
        self.name = "ServicesReconnectAfterGaleraIsRestarted"

    def test(self, target):
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "stop", "galera", n, 'ok') \
                    for n in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])

        watch.setwatch()
        self.rsh_check(target, "sudo pcs resource disable galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        # need to enable galera-master because of how we created the resource
        patterns = [self.ratemplates.build("Pat:RscRemoteOp", "promote", "galera", n, 'ok') \
                    for n in self.Env["nodes"]]
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        self.rsh_check(target, "sudo pcs resource enable galera")
        watch.lookforall()
        assert not watch.unmatched, watch.unmatched

        for n in self.Env["nodes"]:
            # self.log("Waiting for all OpenStack services to come up on node %s"%n)
            self.rsh_until_check([n], "systemctl list-units openstack\* --state=failed | grep \.service")

tests.append(ServicesReconnectAfterGaleraIsRestarted)
