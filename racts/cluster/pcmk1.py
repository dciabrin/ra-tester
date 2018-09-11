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
