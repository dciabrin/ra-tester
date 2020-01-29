#!/usr/bin/env python

'''Resource Agent Tester

Runner class sets up a run before executing a scenario component
 '''

__copyright__ = '''
Copyright (C) 2019 Damien Ciabrini <dciabrin@redhat.com>
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

from cts.logging      import LogFactory
from cts.remote       import RemoteFactory
from cts.CTSscenarios import Sequence


class RARunner(Sequence):
    def __init__(self, ClusterManager, Components, Audits, Tests):
        Sequence.__init__(self, ClusterManager, Components, Audits, Tests)
        self.rsh = RemoteFactory().getInstance()
        self.logger = LogFactory()
        self.Env = ClusterManager.Env

    def SetUp(self):
        # stop cluster if previously running, failure is not fatal
        for node in self.Env["nodes"]:
            self.logger.log("destroy any existing cluster on node %s" % node)
            self.rsh(node, "pcs cluster destroy")
            self.rsh(node, "systemctl stop pacemaker_remote")
            self.rsh(node, "systemctl disable pacemaker_remote")

        self.logger.log("Prepare log directories on all cluster nodes")
        for node in self.Env["nodes"]:
            self.rsh(node, "mkdir -p /var/log/pacemaker")

        return Sequence.SetUp(self)
