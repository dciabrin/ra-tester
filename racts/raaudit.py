#!/usr/bin/env python

'''Resource Agent Tester

Resource Agent audit classes, extends Pacemaker's CTS
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
from cts.CTSaudits import ClusterAudit, AuditList, LogAudit, FileAudit

AllRAAuditClasses = [ ]


class SHMAudit(ClusterAudit):

    def name(self):
        return "SHMAudit"

    def __init__(self, cm):
        self.CM = cm
        self.known = []

    def __call__(self):
        result = 1
        self.CM.ns.WaitForAllNodesToComeUp(self.CM.Env["nodes"])
        for node in self.CM.Env["nodes"]:

            if node in self.CM.ShouldBeStatus and self.CM.ShouldBeStatus[node] == "down":
                clean = 0
                (rc, lsout) = self.CM.rsh(node, "ls -al /dev/shm | grep qb-", None)
                for line in lsout:
                    result = 0
                    clean = 1

                if clean:
                    (rc, lsout) = self.CM.rsh(node, "ps axf | grep -e pacemaker -e corosync", None)
                    for line in lsout:
                        self.CM.debug("ps[%s]: %s" % (node, line))

                    self.CM.rsh(node, "rm -f /dev/shm/qb-*")

            else:
                self.CM.debug("Skipping %s" % node)

        return result
    
    def is_applicable(self):
        return 1

# AllRAAuditClasses.append(SHMAudit)


# Replace CTS' FileAudit because we do not want reporting on
# cluster-based warning such as "stale SHM"
def RATesterAuditList(cm):
    tmp = AuditList(cm)
    result = [a for a in tmp if a.__class__ is not FileAudit]
    for auditclass in AllRAAuditClasses:
        a = auditclass(cm)
        if a.is_applicable():
            result.append(a)
    return result
