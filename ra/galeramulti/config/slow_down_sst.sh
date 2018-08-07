#!/bin/sh
# This file is part of Resource Agents Tester
# Copyright (C) 2016 Damien Ciabrini <dciabrin@redhat.com>
# Licensed under the GNU GPL.

set -e

SPEED=5mbps
NODE=$(hostname)
IFACE=
VERBOSE=

show_help()
{
    echo "Usage: $0 [-i iface] [-n node] on/off"
    echo "Slow down traffic on a specific interface"
    echo "  -h/? help"
    echo "  -i   interface to slow down"
    echo "  -n   ip/name to use for discovering the interface to slow down"
}

while getopts "h?v?n:?" opt; do
    case "$opt" in
    h|\?)
        show_help
        exit 0
        ;;
    v)  VERBOSE=1
        ;;
    n)  NODE=$OPTARG
        ;;
    i)  IFACE=$OPTARG
        ;;
    esac
done

if [ -z "$IFACE" ]; then
    ipnode=$(dig +noall +short $NODE)
    # pick interface matching the ip w/ best metric
    IFACE=$(ip route ls scope link proto kernel src $ipnode | sort -nk5,5 | head -1 | awk '{print $3}')
fi

NW=$(ip route ls scope link proto kernel dev $IFACE | sort -nk5,5 | head -1 | awk '{print $1}')

shift $((OPTIND-1))

case "$1" in
    on)
        tc qdisc add dev $IFACE root handle 1: cbq avpkt 1000 bandwidth 100mbit
        tc class add dev $IFACE parent 1: classid 1:1 cbq rate $SPEED allot 1500 prio 5 bounded isolated
        tc filter add dev $IFACE parent 1: protocol ip prio 16 u32 match ip dst $NW flowid 1:1
        test -n "$VERBOSE" && echo 1>&2 "slowed down $IFACE speed to $SPEED"
        ;;
    off)
        tc qdisc del dev $IFACE root
        test -n "$VERBOSE" && echo 1>&2 "reset $IFACE speed"
        ;;
    *)
        echo 1>&2 "unknown action. -h for help"
        exit 1
esac

exit 0
