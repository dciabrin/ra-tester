import setuptools.command.build_py
from setuptools import setup
import glob

class BuildPyCommand(setuptools.command.build_py.build_py):
    def run(self):
        rules = {
            '@PYTHON@': '/usr/bin/env python',
            '@BASH_PATH@': '/usr/bin/env bash',
            '@datadir@': '/usr/share',
            '@PACKAGE@': 'pacemaker',
            '@CRM_CONFIG_DIR@': '/var/lib/pacemaker/cib',
            '@CRM_LOG_DIR@': '/var/log/pacemaker',
            '@CRM_DAEMON_USER@': 'hacluster',
            '@CRM_DAEMON_DIR@': '/usr/libexec/pacemaker',
            '@OCF_ROOT_DIR@': '/usr/lib/ocf'
        }
        for i in glob.glob("cts/lab/*.py.in"):
            with open(i, 'r') as inf, open(i[:-3], 'w') as outf:
                for l in inf.readlines():
                    for k,v in rules.items():
                        l = l.replace(k, v)
                    outf.write(l)
        setuptools.command.build_py.build_py.run(self)


setup(name = 'cts',
      version = '0.1',
      description = 'Pacemaker Cluster Test Suite',
      url = 'http://github.com/ClusterLabs/pacemaker',
      author = 'Pacemaker project contributors',
      license = 'GPLv2',
      packages = ['cts'],
      package_dir = {'cts': 'cts/lab'},
      cmdclass = {
          'build_py': BuildPyCommand,
      },
      zip_safe = False)
