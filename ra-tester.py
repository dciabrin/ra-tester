#!/usr/bin/env python2

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

# TODO: dynamic test loading
# from racts.ratest import ReuseCluster
import ra.galera
import ra.garbd


# These are globals so they can be used by the signal handler.
cluster_manager = None
scenario = None


def sig_handler(signum, frame) :
    LogFactory().log("Interrupted by signal %d"%signum)
    if scenario: scenario.summarize()
    if signum == 15 :
        if scenario: scenario.TearDown()
        sys.exit(1)


def build_test_list(cluster_manager, ra_modules, all_audits):
    result = {}
    for module in ra_modules:
        result[module]=[]
        for testclass in module.tests:
            bound_test = testclass(cluster_manager)
            if bound_test.is_applicable():
                bound_test.Audits = all_audits
                result[module].append(bound_test)
    return result

def build_scenario_list(env, ra_modules):
    result = {}
    for module in ra_modules:
        result[module]={}
        for scenario in module.scenarios.keys():
            result[module][scenario]=[]
            for componentclass in module.scenarios[scenario]:
                bound_component = componentclass(env)
                if bound_component.IsApplicable():
                    result[module][scenario].append(bound_component)
    return result

def count_all_tests(scenarios, tests):
    modules = scenarios.keys()
    scenarios_per_module = [len(scenarios[m]) for m in modules]
    tests_per_module = [len(tests[m]) for m in modules]
    return sum([a*b for a,b in zip(scenarios_per_module, tests_per_module)])



if __name__ == '__main__':
    env = CtsLab(sys.argv[1:])
    cluster_manager = crm_mcp(env)
    log=LogFactory()
    log.add_stderr()

    # TODO: dynamic test loading
    all_ra_modules = [ra.garbd]
    all_audits = AuditList(cluster_manager)

    for i in [x for x in all_audits if isinstance(x,LogAudit)]:
        i.kinds = [ "journal", "remote" ]

    if env["ListTests"] == 1:
        all_scenarios = build_scenario_list(env, all_ra_modules)
        all_tests = build_test_list(cluster_manager, all_ra_modules, all_audits)
        count = count_all_tests(all_scenarios, all_tests)
        log.log("Total %d tests"%count)
        for m in all_ra_modules:
            for s in all_scenarios[m]:
                log.log(s.__name__+":")
                for t in all_tests[m]:
                    log.log("   - "+str(t.name));
        exit(0)

    # sort tests by scenario
    all_scenarios = build_scenario_list(env, all_ra_modules)
    all_tests = build_test_list(cluster_manager, all_ra_modules, all_audits)
    selected = {}
    for m in all_ra_modules:
        dict_component = all_scenarios[m]
        for sclass in dict_component.keys():
            selected[sclass.__name__] = {
                "scenario": sclass,
                "components": all_scenarios[m][sclass],
                "tests": all_tests[m]
                }

    # --choose scenario1:test1,scenario2:test4,scenario1:test2
    if len(env["tests"]) != 0:
        match = None
        chosen={}
        for name in env["tests"]:
            if ':' not in name:
                log.log("Skipping invalid test name: %s"%name)
                continue
            scenario, test = name.split(":",1)
            oldtests = chosen.get(scenario,[])
            chosen[scenario] = oldtests+[test]

        selected_filtered = {}
        for scenario in selected:
            if scenario in chosen:
                selected_filtered[scenario] = {
                    "scenario": selected[scenario]["scenario"],
                    "components": selected[scenario]["components"]
                    }
                tests_filtered=[]
                for t in selected[scenario]["tests"]:
                    if t.name in chosen[scenario]:
                        tests_filtered.append(t)
                selected_filtered[scenario]["tests"] = tests_filtered

        if len(selected_filtered.keys()) == 0:
            log.log("--choose: No applicable/valid tests chosen")
            log.log("format: --choose Scenario:Test")
            sys.exit(1)
        else:
            selected = selected_filtered


    if env.has_key("verbose"):
        for scenario in selected.values():
            for t in scenario['tests']:
                t.verbose = True
            for c in scenario['components']:
                c.verbose = True

    # Set the signal handler
    signal.signal(15, sig_handler)
    signal.signal(10, sig_handler)


    for s in selected:
        desc=selected[s]
        num_tests = len(desc['tests'])
        log.log(">>>>>>>>>>>>>>>> Starting scenario %s (%d tests)"%(s, num_tests))
        log.log("Documentation:          %s" % desc['scenario'].__doc__)
        log.log("CTS Master:             %s" % env["cts-master"])
        log.log("CTS Logfile:            %s" % env["OutputFile"])
        log.log("Random Seed:            %s" % env["RandSeed"])
        log.log("Syslog variant:         %s" % env["syslogd"].strip())
        log.log("System log files:       %s" % env["LogFileName"])
        if env.has_key("verbose"):
            log.log("verbose mode will log cluster actions")

        scenario = desc['scenario'](cluster_manager,
                                    desc['components'],
                                    all_audits,
                                    desc['tests'])
        env.dump()
        env.run(scenario, num_tests)
