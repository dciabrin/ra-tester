from .scenarios import scenarios
from . import tests as t
# import .tests_node
# import .tests_sst
# import galeratests_unmanaged

__all__ = [ "tests", "scenarios", "name" ]
tests = t.tests
# + \
#         tests_node.tests + \
#         tests_sst.tests # + \
        # galeratests_unmanaged.tests
name = "Galera"
