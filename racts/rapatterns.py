#!/usr/bin/env python

'''Resource Agent Tester

Log templates used by ScenarioComponent and CTSTests, extends Pacemaker's CTS
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


class RATemplates(object):
    def __init__(self):
        self.fun_patterns = {
            "Pat:RscRemoteOp": self.pat_rsc_remote_op,
            "Pat:InitRemoteOp": self.pat_init_remote_op
        }

    def build(self, template, *args):
        if template in self.fun_patterns:
            fun = self.fun_patterns[template]
            pat = fun(*args)
            return pat
        else:
            raise KeyError(template)

    def pat_rsc_remote_op(self, operation, resource, node, status):
        return r"crmd.*:\s*(Result\sof\s%s\soperation\sfor\s%s\son\s%s.*\(%s\)|"\
               r"Operation %s_%s.*:\s*%s \(node=%s,.*,\s*confirmed=true\))"%\
            (operation, resource, node, status, resource,
             "monitor" if operation == "probe" else operation, status, node)

    def pat_init_remote_op(self, operation, resource, node):
        return r"crmd.*:\s*.*(Initiating %s operation %s_%s_0 locally on %s|"\
               r"Initiating action.*:.*%s.*%s_%s.*%s)"%\
               (operation, resource, operation, node,
                operation, resource, operation, node)
