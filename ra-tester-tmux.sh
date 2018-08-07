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
ROWS=3
COLUMNS=1

pane_to_node()
{
    local pane=$1
    local panezero row col pos_in_col node

    panezero=$((pane-1))
    row=$((panezero/COLUMNS))
    col=$((panezero%COLUMNS))
    pos_in_col=$(((ROWS*col)+row))
    node=$((pos_in_col+1))
    echo $node
}

check_ssh()
{
    local location=$1
    local node
    tmux set-window-option -t $SESSION:$location synchronize-panes off
    tmux list-pane -F '#D:#{pane_pid}:#P' -t $SESSION:$location | while IFS=: read pane pid idx
    do
        # if pid is a shell and it has no children, we can ssh into the target node
        if cat /proc/$pid/cmdline | grep -qe '-.*sh'; then
            children=$(ps --forest -g $pid)
            if ! $(echo $children | grep -q ssh); then
                node=$(pane_to_node $idx)
                # echo "ssh ${SSH_ARGS} ${VM_NAME_PREFIX}$node" in $location - $pane
                tmux send-key -t $pane "ssh ${SSH_ARGS} ${VM_NAME_PREFIX}$node" Enter
            fi
        fi
    done
}

create_window()
{
    local name=$1
    local location=$2
    local layout

    tmux new-window -dk -n $name -t $SESSION:$location

    for ir in `seq $((ROWS-1))`; do
         tmux split-window -v -t $SESSION:$location
    done

    for c in `seq $((COLUMNS-1))`; do
        for r in `seq $ROWS -1 1`; do
            tmux split-window -h -t $SESSION:$location.$r
        done
    done

    if [ $COLUMNS -gt 1 ]; then
        layout=tiled
    else
        layout=even-vertical
    fi

    tmux select-layout -t $SESSION:$location $layout
}

# force create a ssh control master.
# controlpersist makes the magic work
ensure_control_master()
{
    for i in `seq $((ROW*COLUMNS))`; do
        ssh ${SSH_ARGS} ${VM_NAME_PREFIX}1 true&
        local pid=$!
        wait $pid
    done
}


usage()
{
    cat <<EOF
Create a tmux session for monitoring cluster nodes
Usage: $(basename $0) VM_NAME_PREFIX [options ...]

Options:
   --ssh CONFIG   Use config file CONFIG to ssh to cluster nodes
   --rows R       Split tmux sessions in R rows, laid out vertically
   --columns C    Split tmux sessions in R rows and C columns, tiled
   --force        Re-create the tmux session if it already exists

Exemple:
   # Connect to cluster nodes centos1,centos2,centos3
   $(basename $0) centos --ssh ssh_config_centos
EOF
}

CREATE=0

while [ "$1" != "" ]; do
    case "$1" in
        --ssh ) SSH_ARGS="-F$2"; shift 2;;
        --rows ) ROWS="$2"; shift 2;;
        --columns ) COLUMNS="$2"; shift 2;;
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

if [ "x$VM_NAME_PREFIX" = "x" ]; then
    echo "ERROR: missing parameter VM_NAME_PREFIX" >&2
    usage
    exit 1
fi

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
