from cts.logging import LogFactory
from cts.remote import RemoteFactory
from racts.raaction import ActionMixin
from .manager import ClusterManager


class Pacemaker2(ClusterManager, ActionMixin):
    def __init__(self, env):
        self.Env = env
        self.verbose = self.Env["verbose"]
        self.logger = LogFactory()
        self.rsh = RemoteFactory().getInstance()

    def is_detected(self):
        return self.rsh(self.Env["nodes"][0], "pacemakerd --version | grep -q 'Pacemaker 2.'") == 0

    def authenticate_nodes(self, nodes):
        for n in nodes:
            self.rsh_check(n, "pcs host auth -u hacluster -p ratester %s" %
                           " ".join(nodes))

    def create_cluster(self, nodes):
        self.rsh_check(nodes[0],
                       "pcs cluster setup ratester --force %s" %
                       " ".join(nodes))

    def set_node_property(self, nodes, node, name, value):
        self.rsh_check(node,
                       "pcs node attribute %s %s=%s" % (node, name, value))

    def add_remote_node(self, cluster_nodes, node):
        self.rsh_check(cluster_nodes[0],
                       "pcs cluster node add-remote %s %s reconnect_interval=60 op monitor interval=20" %
                       (node, node))

    def meta_promotable_resource_name(self, ocf_name):
        return "%s-clone" % ocf_name
        pass

    def meta_promotable_config(self, max_clones=None):
        res = "promotable"
        if max_clones:
            res += " master-max=%d" % max_clones
        return res

    def errorstoignore(self):
        return [
            # during cluster setup, prior to configuring fencing, pacemaker logs harmless errors
            r"pacemaker-schedulerd.*:\s*error: Resource start-up disabled since no STONITH resources have been defined",
            r"pacemaker-schedulerd.*:\s*error: Either configure some or disable STONITH with the stonith-enabled option",
            r"pacemaker-schedulerd.*:\s*error: NOTE: Clusters with shared data need STONITH to ensure data integrity"
        ]

    @property
    def attribute_absent_errno(self):
        return 105
