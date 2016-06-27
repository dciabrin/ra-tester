#!/bin/bash

# This file is part of ratester.
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

VM_NAME_PREFIX=
SESSION=
SSH_ARGS=

check_ssh()
{
    local location=$1
    local i=1
    tmux set-window-option -t $SESSION:$location synchronize-panes off
    tmux list-pane -F '#D:#{pane_pid}' -t $SESSION:$location | while IFS=: read pane pid
    do
        # if pid is a shell and it has no children, we can ssh into the target node
        if cat /proc/$pid/cmdline | grep -qe '-.*sh'; then
            if ! (ps axfo ppid | grep -q $pid); then
                echo "ssh ${SSH_ARGS} ${VM_NAME_PREFIX}$i" in $location - $pane
                tmux send-key -t $pane "ssh ${SSH_ARGS} ${VM_NAME_PREFIX}$i" Enter
            fi
        fi
        ((i++))
    done
}

create_window()
{
    local name=$1
    local location=$2
    tmux new-window -dk -n $name -t $SESSION:$location
    tmux split-window -v -t $SESSION:$location
    tmux split-window -v -t $SESSION:$location
    tmux select-layout -t $SESSION:$location even-vertical
}

# force create a ssh control master.
# controlpersist makes the magic work
ensure_control_master()
{
    ssh ${SSH_ARGS} ${VM_NAME_PREFIX}1 true&
    local pid1=$!
    ssh ${SSH_ARGS} ${VM_NAME_PREFIX}2 true&
    local pid2=$!
    ssh ${SSH_ARGS} ${VM_NAME_PREFIX}3 true&
    local pid3=$!
    wait $pid1
    wait $pid2
    wait $pid3
}


usage()
{
    cat <<EOF
Create a tmux session for monitoring cluster nodes
Usage: $(basename $0) VM_NAME_PREFIX [options ...]

Options:
   --ssh CONFIG    Use config file CONFIG to ssh to cluster nodes
   --force         Re-create the tmux session if it already exists

Exemple:
   # Connect to cluster nodes centos1,centos2,centos3
   $(basename $0) centos --ssh ssh_config_centos
EOF
}

CREATE=0

while [ "$1" != "" ]; do
    case "$1" in
        --ssh ) SSH_ARGS="-F$2"; shift 2;;
        --force ) CREATE=1; shift;;
        -h|--help ) usage; exit 0;;
        * )
            if [ "x$VM_NAME_PREFIX" = "x" ]; then
                VM_NAME_PREFIX=$1
                shift
            else
                echo "ERROR: unknown parameter \"$1\"" >&2
                usage
                exit 1
            fi
            ;;
    esac
done

SESSION=$VM_NAME_PREFIX-ra

if [ $CREATE -ne 1 ]; then
    tmux -q has-session -t $SESSION 2>/dev/null || CREATE=1
fi

if [ $CREATE -eq 1 ]; then
    tmux kill-session -t $SESSION 2>/dev/null
    tmux new-session -d -s $SESSION
    create_window shell 1
    create_window agent 2
    create_window journal 3
fi

ensure_control_master
for i in 1 2 3; do check_ssh $i; done

if [ $CREATE -eq 1 ]; then
    exec tmux a -t $SESSION
fi
