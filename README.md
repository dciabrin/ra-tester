# Resource Agent Tester

Shoot automated and repeatable tests to validate the behaviour of
resource agents in Pacemaker-based clusters.

The tests are built on Pacemaker's Cluster Test Suite framework.
We use CTS for setup, cluster communication, audit, reporting...
and add our own RA scenarios on top of that.


## Prerequisites

`ra-tester` is meant to be run from a host which is not part of the
cluster. It uses [pipenv](https://github.com/pypa/pipenv) to install
dependencies into an isolated virtual env from where you can run the
resource agents' tests. It also relies on CTS, which requires some
additional steps to set up due to it being unavailable in PyPI yet.

    pip install pipenv
    PIPENV_VENV_IN_PROJECT=1 pipenv --three install
    pipenv run setup/install-cts.py

Once the setup is complete, you can run `pipenv shell` to jump
on the create virtualenv and run the `ra-tester` command.

On the cluster nodes, `ra-tester` will automatically install the
required packages based on the tests that you want to run, so no
particular setup is required.

If you want to host your cluster on VMs, a helper script
`ra-tester-build-vms` is available and its usage is explained below.


## Hardware requirements

`ra-tester` has fairly small hardware requirements, a 3-node setup
with 1 CPU and 2GB of RAM per machine is sufficient to run the majority
of the test cases.

It is expected that the pacemaker cluster run on a network without
DHCP, to prevent any network issue caused by lease renewal.

To run the entire test suite, a fencing device must be available so
that pacemaker can shutdown or restart nodes as expected in the face
of resource monitoring failures or network conditions.

A helper script `ra-tester-build-vms` is provided so that you can
bootstrap a VM-based 3-nodes cluster from any Linux distribution:

    pipenv run ./ra-tester-build-vms --img ./CentOS-7-x86_64-GenericCloud.qcow2 --name ratester

The example above will create three CentOS-based VM `ratester1`,
`ratester2` and `ratester3`, with networking and fencing set up
according to `ra-tester` requirements.

## Impact on running cluster

The tests which are run by `ra-tester` are meant to be repeatable,
so they need to re-create an entire cluster and all its resources
at every run. Consequently, be aware any existing pacemaker cluster
running on the target nodes that you provide will be destroyed and
replaced by a cluster suitable for `ra-tester`.

Alternatively, in order to ease development, it is still possible
to configure `ra-tester` to re-use an existing pacemaker cluster.
Still, the resource running on the cluster will be destroyed and
recreated from scratch at every run.

## Instructions

List available tests with:

    ./ra-tester --nodes 'node1 node2 node3' --list
    
Run the whole series of tests with:

    ./ra-tester --nodes 'node1 node2 node3'

Shoot specific tests and raise `ra-tester` verbosity to see the
cluster commands ran during the test with:

    ./ra-tester --nodes 'node1 node2 node3' --choose Galera:SimpleSetup:ClusterStart,Galera:SimpleSetup:ClusterStop --set verbose=1

Keep existing pacemaker cluster when shooting tests:

    ./ra-tester --nodes 'node1 node2 node3' --set verbose=1 --set keep_cluster=1

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
