# Resource Agent Tester

Shoot automated tests to validate the behaviour of resource agents
in Pacemaker-based clusters.

The tests are built on Pacemaker's Cluster Test Suite framework.
We use CTS for setup, cluster communication, audit, reporting...
and add our own RA scenarios on top of that.


## Prerequisites

The automated test script `ra-tester.py` must be run from a
machine which is not part of the cluster, and where the CTS python
modules are installed and in sync with the version of pacemaker
running on the cluster. Usually it's as simple as:

    yum install -y pacemaker-cts

On the cluster machine, you will need various packages for the tests
to run correctly:

    yum install -y gdb screen

In order to run the tests, cluster must be up and running;
we do not try to setup a cluster from scratch (yet). Also, we make
the assumption that there won't be resource conflicts, so please
backup your cluster's resource and delete them before running the
automated tests:

    pcs cluster cib > saved-cluster-state.xml


## Instructions

You can list available tests with:

    ./ra-tester.py --nodes 'node1 node2 node3' --list
    
Command-line options are akin to CTS. You can run the whole series of
tests with:

    ./ra-tester.py --nodes 'node1 node2 node3' --stonith xvm

Alternately, you can shoot a single test, and raise verbosity to
see the pcs commands ran during the test with:

    ./ra-tester.py --nodes 'node1 node2 node3' --choose ClusterStart --set verbose=1


## License

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Lesser General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public
License along with this program. If not, see
<http://www.gnu.org/licenses/>.
