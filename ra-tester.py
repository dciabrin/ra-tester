#!/usr/bin/env python

'''Resource Agents Tester

A automated test shooter to validate the behaviour of OCF
resource agents.

Relies on Pacemaker's Cluster Test Suite
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

from cts.CTS import CtsLab
from cts.CM_ais import crm_mcp
from cts.CTSaudits import AuditList, LogAudit
from cts.CTSscenarios import Sequence
from cts.logging   import LogFactory
from racts.ratest import ReuseCluster

# TODO: dynamic test loading
import ra.galera


# These are globals so they can be used by the signal handler.
cluster_manager = None
scenario = None

def sig_handler(signum, frame) :
    LogFactory().log("Interrupted by signal %d"%signum)
    if scenario: scenario.summarize()
    if signum == 15 :
        if scenario: scenario.TearDown()
        sys.exit(1)


def build_test_list(cluster_manager, all_audits):
    result = []
    # TODO: dynamic test loading
    for testclass in ra.galera.tests:
        bound_test = testclass(cluster_manager)
        if bound_test.is_applicable():
            bound_test.Audits = all_audits
            result.append(bound_test)
    return result


if __name__ == '__main__':

    env = CtsLab(sys.argv[1:])
    cluster_manager = crm_mcp(env)
    log=LogFactory()
    log.add_stderr()

    all_audits = AuditList(cluster_manager)
    all_tests = []
    
    # Set the signal handler
    signal.signal(15, sig_handler)
    signal.signal(10, sig_handler)

    for i in [x for x in all_audits if isinstance(x,LogAudit)]:
        i.kinds = [ "journal", "remote" ]

    if env["ListTests"] == 1:
        all_tests = build_test_list(cluster_manager, all_audits)
        log.log("Total %d tests"%len(all_tests))
        for test in all_tests :
            log.log(str(test.name));
        sys.exit(0)

    elif len(env["tests"]) == 0:
        all_tests = build_test_list(cluster_manager, all_audits)

    else:
        Chosen = env["tests"]
        for TestCase in Chosen:
           match = None

           for test in build_test_list(cluster_manager, all_audits):
               if test.name == TestCase:
                   match = test

           if not match:
               log.log("--choose: No applicable/valid tests chosen")
               sys.exit(1)
           else:
               all_tests.append(match)

    if env.has_key("verbose"):
        for t in all_tests:
            t.verbose = True

    num_tests=len(all_tests)
    scenario = Sequence(
        cluster_manager, # reified cluster manager
        [x(env) for x in ra.galera.scenarios], # global setup/teardown
        all_audits, # systemic checks (logs, files, disk...)
        all_tests # our galera RA tests
    )

    log.log(">>>>>>>>>>>>>>>> BEGINNING " + repr(num_tests) + " TESTS ")
    log.log("Scenario:               %s" % scenario.__doc__)
    log.log("CTS Master:             %s" % env["cts-master"])
    log.log("CTS Logfile:            %s" % env["OutputFile"])
    log.log("Random Seed:            %s" % env["RandSeed"])
    log.log("Syslog variant:         %s" % env["syslogd"].strip())
    log.log("System log files:       %s" % env["LogFileName"])
    if env.has_key("IPBase"):
        log.log("Base IP for resources:  %s" % env["IPBase"])
    log.log("Cluster starts at boot: %d" % env["at-boot"])
    if env.has_key("verbose"):
        log.log("verbose mode will log cluster actions")

    env.dump()
    rc = env.run(scenario, num_tests)
    sys.exit(rc)
