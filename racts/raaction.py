#!/usr/bin/env python

'''Resource Agent Tester

Mixin class holding various common actions to run on cluster nodes
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


import time

class ActionMixin(object):
    def crm_attr_set(self, target, attribute, value, expected = 0):
        command="crm_attribute -N %s -l reboot --name %s -v %s"% \
                     (target, attribute, value)
        if self.verbose: self.logger.log("> [%s] %s"%(target,command))
        res=self.rsh(target, command+" &>/dev/null")
        assert res == expected, "set crm attribute \"%s\" returned %d (expected %d)"% \
            (attribute,res,expected)

    def crm_attr_check(self, target, attribute, expected = 0, expected_value = 0):
        command="crm_attribute -N %s -l reboot --name %s -Q"% \
                     (target, attribute)
        if self.verbose: self.logger.log("> [%s] %s"%(target,command))
        res=self.rsh(target, command+" &>/dev/null")
        assert res == expected, "get crm attribute \"%s\" returned %d (expected %d)"% \
            (attribute,res,expected)

    def crm_attr_del(self, target, attribute, expected = 0, expected_value = 0):
        command="crm_attribute -N %s -l reboot --name %s -D"% \
                     (target, attribute)
        if self.verbose: self.logger.log("> [%s] %s"%(target,command))
        res=self.rsh(target, command+" &>/dev/null")
        assert res == expected, "del crm attribute \"%s\" returned %d (expected %d)"% \
            (attribute,res,expected)

    def rsh_check(self, target, command, expected = 0):
        if self.verbose: self.logger.log("> [%s] %s"%(target,command))
        temp="ratester-tmp%f"%time.time()
        res=self.rsh(target, command+" &>"+temp)
        if res != expected:
            if type(res) is list: res = res[0]
            self.rsh(target, "mv %s '%s-%s-%d'"%(temp, temp, command, res))
        else:
            self.rsh(target, "rm -f %s"%temp)
        assert res == expected, "\"%s\" returned %d"%(command,res)

    def rsh_bg(self, target, command, expected = 0):
        # TODO: multiple bg jobs per target
        # if target not in self.bg:
        #     self.rsh_check(target, "screen -S %s -d -m"%self.name)
        #     self.bg[target]=True
        # self.rsh_check(target, "screen -S %s -X stuff '%s\r'"%(self.name,command) )
        self.rsh_check(target, "screen -S %s -d -m %s"%(self.name,command) )

    def rsh_until(self, targets, command, timeout=1000, expected = 0):
        if self.verbose: self.logger.log("> [%s] %s -> UNTIL $? == %d"%(",".join(targets),command, expected))
        while timeout > 0:
            for t in targets:
                res=self.rsh(t, command)
                if res == expected: return
            time.sleep(2)
            timeout-=2

    def wait_until_restarted(self, node, timeout=300):
        start=time.time()
        alive = False
        while not alive:
            time.sleep(3)
            assert time.time()-start < timeout, "Restart timeout exceeded"
            res = self.rsh(node, "true")
            if res == 0: alive = True

    def make_watch(self, patterns):
        watch = self.create_watch(patterns, self.Env["DeadTime"])
        watch.setwatch()
        return watch
