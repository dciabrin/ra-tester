#!/usr/bin/env python

'''Resource Agent Tester

Remote execution and watch utilities, extends Pacemaker's CTS
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
from subprocess import Popen,PIPE
from cts.remote    import AsyncRemoteCmd, RemoteExec, RemoteFactory
from cts.watcher   import LogWatcher
from cts.environment import Environment
from cts.CTS import NodeStatus

def ratester___get_lines(self, timeout):
    count=0
    if not len(self.file_list):
        raise ValueError("No sources to read from")

    pending = []
    for f in self.file_list:
        t = f.harvest_async(self)
        if t:
            pending.append(t)

    for t in pending:
        t.join(8.0)
        if t.is_alive():
            self.debug("%s: %s did not returned after 8s." % (self.name, repr(t)))
            self.debug("%s: forgetting node %s." % (self.name, t.node))
            self.hosts=[x for x in self.hosts if x != t.node]
            self.file_list=[x for x in self.file_list if x.host != t.node]

def ratester_ensure_control_master(self, node):
    # SSH control master: at start of after a node is fenced, the
    # master socket might not be present. If so, we cannot 'readlines'
    # stderr after the next remote call completion, due to ssh master
    # pid leaking a dup'd fd.
    # Force the creation of the master socket here, without reading
    # output to avoid dead locking on the next remote call
    proc =  Popen(self._cmd([node, "true"]),
                 stdout = PIPE, stderr = PIPE, close_fds = True, shell = True)
    rc = proc.wait()
    proc.stdout.close()
    proc.stderr.close()
    return (proc, rc)

def ratester_call_async(self, node, command, completionDelegate=None):
    proc, rc = self.ensure_control_master(node)
    if rc != 0:
        self.debug("Connection check to %s failed. Node went inaccessible."%node)
        if completionDelegate:
            completionDelegate.async_complete(proc.pid, rc, [], [])
        return 0
    else:
        return self.orig_call_async(node, command, completionDelegate)

def ratester___call__(self, node, command, stdout=0, synchronous=1, silent=False, blocking=True, completionDelegate=None):
    proc, rc = self.ensure_control_master(node)
    if rc != 0:
        self.debug("Connection check to %s failed. Node went inaccessible."%node)
        if not synchronous:
            if completionDelegate:
                completionDelegate.async_complete(proc.pid, rc, [], [])
            return 0
        return (rc, "" if stdout == 1 else [])
    else:
        return self.orig___call__(node, command, stdout, synchronous,
                                  silent, blocking, completionDelegate)

def ratester_environment__setitem__(self, key, value):
    if key == "nodes":
        self.Nodes = []
        for node in value:
            self.Nodes.append(node.strip())
        self.filter_nodes()
    else:
        self.orig___setitem__(key, value)

def ratester_is_node_booted(self, node):
    '''Return TRUE if the given node is booted (responds to pings)'''
    return RemoteFactory().getInstance()(node, "/bin/true", silent=True) == 0

def monkey_patch_cts_log_watcher():
    # continue watching when a node gets unresponsive (fencing)
    LogWatcher._LogWatcher__get_lines = ratester___get_lines

def monkey_patch_cts_remote_commands():
    # prevent deadlock with SSH + control master
    # when polling stderr after process ended
    RemoteExec.orig___call__ = RemoteExec.__call__
    RemoteExec.orig_call_async = RemoteExec.call_async
    RemoteExec.ensure_control_master = ratester_ensure_control_master
    RemoteExec.__call__ = ratester___call__
    RemoteExec.call_async = ratester_call_async

def monkey_patch_cts_env_node_setup():
    Environment.orig___setitem__ = Environment.__setitem__
    Environment.__setitem__ = ratester_environment__setitem__

def monkey_patch_node_state():
    NodeStatus.IsNodeBooted = ratester_is_node_booted
