from abc import ABC, abstractmethod

class ClusterManager(ABC):
    def __init__(self, env):
        self.Env = env

    @abstractmethod
    def is_detected(self):
        pass

    @abstractmethod
    def authenticate_nodes(self, nodes):
        pass

    @abstractmethod
    def create_cluster(self, nodes):
        pass

    @abstractmethod
    def set_node_property(self, nodes, node, name, value):
        pass

    @abstractmethod
    def add_remote_node(self, cluster_nodes, node):
        pass

    @abstractmethod
    def meta_promotable_resource_name(self, ocf_name):
        pass

    @abstractmethod
    def meta_promotable_config(self, max_clones=None):
        pass

