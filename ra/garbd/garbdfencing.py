'''Resource Agents Tester

Dedicated 2-node fencing scenario for garbd RA
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

from racts.rafencing import RATesterFencingComponent

class Garbd2NodesDelayedFencing(RATesterFencingComponent):
    def setup_scenario(self, cluster_manager):
        cluster_manager.log("Enabling fencing in cluster")
        delay=0
        for node in self.Env["nodes"]:
            self.rsh_check(self.Env["nodes"][0], "pcs stonith create fence_%s %s %s action=reboot delay=%d pcmk_host_list=%s"%\
                           (node, self.Env["stonith-type"], self.Env["stonith-params"], delay, node))
            delay+=5
        self.rsh_check(self.Env["nodes"][0], "pcs property set stonith-enabled=true")

    def teardown_scenario(self, cluster_manager):
        # handy debug hook
        if self.Env.has_key("keep_resources"): return
        self.rsh_check(self.Env["nodes"][0], "pcs property set stonith-enabled=false")
        for node in self.Env["nodes"]:
            self.rsh_check(self.Env["nodes"][0], "pcs stonith delete fence_%s"%node)

fencing = Garbd2NodesDelayedFencing
