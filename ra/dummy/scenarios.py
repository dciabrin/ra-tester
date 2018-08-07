#!/usr/bin/env python

'''Resource Agents Tester

Template scenarios definition for resource agent
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


# The scenario below set up two basic configuration for the RA tests#
#   . SimpleSetup run the bare tests without customization
#   . BundleSetup wraps the dummy resource into a bundle

class SimpleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        self.Env["rsc_name"] = "dummy"
        PrepareCluster.setup_scenario(self,cm)

scenarios["SimpleSetup"]=[SimpleSetup]


class BundleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        self.Env["bundle"] = True
        self.Env["rsc_name"] = "dummy-bundle"
        self.Env["container_image"] = "docker.io/tripleoqueens/centos-binary-rabbitmq:current-tripleo-rdo"
        PrepareCluster.setup_scenario(self,cm)

scenarios["BundleSetup"]=[BundleSetup]
