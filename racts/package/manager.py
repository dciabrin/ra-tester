from abc import ABC, abstractmethod
import yaml

class PackageManager(ABC):
    def __init__(self, env, pkg_format, flavor):
        self.Env = env
        with open(env["package_mapping"], "r") as f:
            self.mapping = yaml.safe_load(f)
        self.pkg_format = pkg_format
        self.flavor = flavor

    @abstractmethod
    def _is_installed(self, node, pkg):
        pass

    @abstractmethod
    def _install(self, node, pkg):
        pass

    @abstractmethod
    def _can_be_updated(self, node, pkg):
        pass

    @abstractmethod
    def _update(self, node, pkg):
        pass

    def map_package_name(self, pkg):
        ns = self.pkg_format + "-" + self.flavor
        table = self.mapping.get(ns, {})
        mapped = table.get(pkg, False)
        if not mapped:
            ns = self.pkg_format
            table = self.mapping.get(ns, {})
        r = table.get(pkg, pkg)
        return r

    def is_installed(self, node, pkg):
        return self._is_installed(node, self.map_package_name(pkg))

    def install(self, node, pkg):
        return self._install(node, self.map_package_name(pkg))

    def can_be_updated(self, node, pkg):
        return self._can_be_updated(node, self.map_package_name(pkg))

    def update(self, node, pkg):
        return self._update(node, self.map_package_name(pkg))
