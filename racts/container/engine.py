from abc import ABC, abstractmethod

class ContainerEngine(object):
    def __init__(self, env):
        self.Env = env
        self.verbose = verbose

    @abstractmethod
    def is_detected(self):
        pass

    @abstractmethod
    def package_name(self):
        pass

    @abstractmethod
    def enable_engine(self, nodes):
        pass

    @abstractmethod
    def pull_image(self, nodes, img):
        pass


