from .galerascenarios import scenarios
import galeratests
import galeratests_node
import galeratests_sst
# import galeratests_unmanaged

__all__ = [ "tests", "scenarios", "name" ]
tests = galeratests.tests + \
        galeratests_node.tests + \
        galeratests_sst.tests # + \
        # galeratests_unmanaged.tests
name = "Galera"
