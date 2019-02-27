from cts.logging import LogFactory
from cts.remote import RemoteFactory
from racts.raaction import ActionMixin
from . import manager

class Pacemaker1(manager.ClusterManager, ActionMixin):
    def __init__(self, env, verbose=True):
        self.Env = env
        self.verbose = verbose
        self.logger = LogFactory()
        self.rsh = RemoteFactory().getInstance()

    def authenticate_nodes(self, nodes):
        self.rsh_check(nodes[0], "pcs cluster auth -u hacluster -p ratester %s" % \
                       " ".join(nodes))

    def create_cluster(self, nodes):
        self.rsh_check(nodes[0], 
                       "pcs cluster setup --force --name ratester %s" % \
                       " ".join(nodes))

    def add_remote_node(self, cluster_nodes, node):
        self.rsh_check(cluster_nodes[0], 
                       "pcs cluster node add-remote %s %s reconnect_interval=60 op monitor interval=20" % \
                       (node, node) )
