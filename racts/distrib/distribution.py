from abc import ABC, abstractmethod
import yaml


class Distribution(ABC):
    def __init__(self, env):
        self.Env = env

    @abstractmethod
    def cluster_manager(self):
        pass

    @abstractmethod
    def package_manager(self):
        pass

    @abstractmethod
    def container_engine(self):
        pass

    @abstractmethod
    def add_insecure_container_registry(self, node, uri):
        pass
