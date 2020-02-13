#!/usr/bin/env python

'''Resource Agents Tester

Regression scenarios for galera RA
 '''

__copyright__ = '''
Copyright (C) 2015-2018 Damien Ciabrini <dciabrin@redhat.com>
Licensed under the GNU GPL.
'''

#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA.


import sys, signal, time, os, re, string, subprocess, tempfile
from stat import *
from cts import CTS
from cts.CTS import CtsLab
from cts.CTStests import CTSTest
# from cts.CM_ais import crm_mcp
from cts.CTSscenarios import *
from cts.CTSaudits import *
from cts.CTSvars   import *
from cts.patterns  import PatternSelector
from cts.logging   import LogFactory
from cts.remote    import RemoteFactory
from cts.watcher   import LogWatcher
from cts.environment import EnvFactory

from racts.rascenario import RATesterScenarioComponent
from racts.raconfig import RAConfig

scenarios = {}


class PrepareCluster(RATesterScenarioComponent):
    def __init__(self, environment):
        RATesterScenarioComponent.__init__(self, environment, scenario_module_name="galera")
        self.dependencies = ["mariadb-server-galera"]

    def setup_configs(self, cluster_nodes):
        config = self.Env["config"]

        self.log("Discovering galera paths for config")
        node = cluster_nodes[0]
        mysqld = self.rsh(node, "for i in /usr/{libexec,sbin}/mysqld; "
                          "do if test -x $i; then echo $i; break; fi; done", stdout=1).strip()
        assert mysqld, "could not determine mysqld path"
        mysql_etc_file = self.rsh(node, "for i in $(%s --verbose --help 2>/dev/null | grep /etc/my.cnf); "
                                  "do if test -f $i; then echo $i; break; fi; done" % mysqld, stdout=1).strip()
        mysql_etc_file, "could not determine default mysql config file"
        mysql_etc_dir = self.rsh(node, "for i in $(grep includedir %s | cut -d' ' -f2); "
                                 "do if test -d $i; then echo $i; break; fi; done" % mysql_etc_file, stdout=1).strip()
        mysql_etc_dir, "could not determine default mysql extra config directory"
        galera_libpath = self.rsh(node, "for i in /usr/{lib64,lib}/galera/libgalera_smm.so; "
                                  "do if test -f $i; then echo $i; break; fi; done", stdout=1).strip()
        galera_libpath, "could not determine galera library path"
        ratester_mysqlcfg = os.path.join(mysql_etc_dir, "galera.cnf")

        self.log("Setting up galera config files")
        basedir=os.path.dirname(os.path.abspath(__file__))
        configdir=os.path.join(basedir, "config")
        galeracfg=os.path.join(configdir, "galera.cnf.in")
        killgdb=os.path.join(configdir, "kill-during-txn.gdb")
        slowsst=os.path.join(configdir, "slow_down_sst.sh")
        if bool(config["tls"]):
            tlstunnel="[sst]\ntca=/tls/all-mysql.crt\ntcert=/tls/mysql.pem\nsockopt=\"verify=1\""
            tls="socket.ssl_key=/tls/mysql.key;socket.ssl_cert=/tls/mysql.crt;socket.ssl_ca=/tls/all-mysql.crt;"
            rsync="rsync_tunnel"
        else:
            tlstunnel=""
            tls=""
            rsync="rsync"
        if bool(config["ipv6"]):
            gcomm="gcomm://"+(",".join([self.node_fqdn_ipv6(n) for n in cluster_nodes]))
        elif bool(config["tls"]):
            gcomm="gcomm://"+(",".join([self.node_fqdn(n) for n in cluster_nodes]))
        else:
            gcomm="gcomm://"+(",".join(cluster_nodes))

        for node in cluster_nodes:
            if bool(config["ipv6"]):
                ip = "["+self.node_ipv6(node)+"]"
                shortname = self.node_fqdn_ipv6(node)
            else:
                ip = self.node_ip(node)
                if bool(config["tls"]):
                    shortname = self.node_fqdn(node)
                else:
                    shortname = self.node_shortname(node)
            self.copy_to_node(node,
                              [(galeracfg, ratester_mysqlcfg),
                               (killgdb,   "/tmp/kill-during-txn.gdb"),
                               (slowsst,   "/tmp/slow_down_sst.sh")],
                              True, "root", "0444", {
                                  # mariadb 10.3.11 has a buggy galera with ipv6
                                  # force listen to all interface
                                  "%HOSTIP%": ip if not bool(config["ipv6"]) else "[::]",
                                  "%GCOMM%": gcomm,
                                  "%HOSTNAME%": shortname,
                                  "%GALERALIBPATH%": galera_libpath,
                                  "%TLS%": tls,
                                  "%RSYNC%": rsync,
                                  "%TLSTUNNEL%": tlstunnel
                              })
        if bool(config["tls"]):
            self.log("Generating certificates for TLS")
            for node in cluster_nodes:
                if bool(config["ipv6"]):
                    ca_node = self.node_fqdn_ipv6(node)
                else:
                    ca_node = self.node_fqdn(node)
                self.rsh(node, "rm -rf /tls && mkdir /tls")
                self.rsh_check(node, "openssl genrsa -out /tls/mysql.key 2048")
                self.rsh_check(node, "openssl req -new -key /tls/mysql.key -x509 -days 365000"
                               " -subj \"/CN=%s\" -out /tls/mysql.crt -batch"%ca_node)
                self.rsh_check(node, "sh -c 'cat /tls/mysql.key /tls/mysql.crt > /tls/mysql.pem'")
            self.log("Generating a common CA file for TLS")
            if bool(config["ipv6"]):
                ca_nodes = " ".join([self.node_fqdn_ipv6(n) for n in cluster_nodes])
            else:
                ca_nodes = " ".join([self.node_fqdn(n) for n in cluster_nodes])
            for node in cluster_nodes:
                self.rsh_check(node, "for n in %s; do ssh -o StrictHostKeyChecking=no $n 'cat /tls/mysql.crt'"
                               ">> /tls/all-mysql.crt; done"%\
                               ca_nodes)
            for node in cluster_nodes:
                self.rsh(node, "chown -R %s:%s /tls"%\
                         (config["user"],config["user"]))

    def setup_state(self, cluster_nodes):
        config=self.Env["config"]
        for node in cluster_nodes:
            # blank galera state on disk
            if not bool(config["skip_install_db"]):
                self.log("recreating empty mysql database on node %s"%node)
                self.rsh(node, "rm -rf /var/lib/mysql /var/log/mysql")
                self.rsh(node, "mkdir -p /var/lib/mysql /var/log/mysql")
                self.rsh(node, "sudo mysql_install_db")
            self.rsh(node, "chown -R %s:%s /var/log/mysql /var/lib/mysql"%\
                     (config["user"],config["user"]))
            if bool(self.Env["config"]["bundle"]):
                self.rsh(node, "which chcon && chcon -R -t container_file_t /var/lib/mysql /var/log/mysql")
            else:
                self.rsh(node, "which restorecon && restorecon -R /var/lib/mysql /var/log/mysql")


# The scenario below set up various configuration of the galera tests

class SimpleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        cluster = self.cluster_manager
        config = RAConfig(self.Env, self.module_name, {
            "name": cluster.meta_promotable_resource_name("galera"),
            "ocf_name": "galera",
            "alt_node_names": {},
            "meta": cluster.meta_promotable_config(len(self.Env["nodes"])),
            "user": "mysql",
            "bundle": None,
            "skip_install_db": False,
            "tls": False,
            "ipv6": False,
        })
        if bool(config["ipv6"]):
            nodes = self.Env["nodes"]
            nodes_fqdn_ipv6 = [self.node_fqdn_ipv6(n) for n in nodes]
            config["alt_node_names"] = dict(zip(nodes,nodes_fqdn_ipv6))
        self.Env["config"] = config
        PrepareCluster.setup_scenario(self,cm)

scenarios["SimpleSetup"]=[SimpleSetup]


class BundleSetup(PrepareCluster):

    def setup_scenario(self, cm):
        config = RAConfig(self.Env, self.module_name, {
            "name": "galera-bundle",
            "ocf_name": "galera",
            "alt_node_names": {},
            "meta": "container-attribute-target=host notify=true",
            "user": "42434",
            "bundle": True,
            "container_image": "docker.io/tripleoqueens/centos-binary-mariadb:current-tripleo-rdo",
            "skip_install_db": False,
            "tls": False,
            "ipv6": False,
        })
        if bool(config["ipv6"]):
            nodes = self.Env["nodes"]
            nodes_fqdn_ipv6 = [self.node_fqdn_ipv6(n) for n in nodes]
            # TODO implement setting config key name with prefix?
            config["alt_node_names"] = dict(zip(nodes,nodes_fqdn_ipv6))
        self.Env["config"] = config
        PrepareCluster.setup_scenario(self,cm)

scenarios["BundleSetup"]=[BundleSetup]


class TLSSetup(PrepareCluster):

    def setup_scenario(self, cm):
        cluster = self.cluster_manager
        config = RAConfig(self.Env, self.module_name, {
            "name": cluster.meta_promotable_resource_name("galera"),
            "ocf_name": "galera",
            "alt_node_names": {},
            "meta": cluster.meta_promotable_config(len(self.Env["nodes"])),
            "user": "mysql",
            "bundle": None,
            "skip_install_db": False,
            "tls": True,
            "ipv6": False,
        })
        nodes = self.Env["nodes"]
        if bool(config["ipv6"]):
            ca_nodes = [self.node_fqdn_ipv6(n) for n in nodes]
        else:
            ca_nodes = [self.node_fqdn(n) for n in nodes]
        config["alt_node_names"] = dict(zip(nodes,ca_nodes))
        self.Env["config"] = config
        PrepareCluster.setup_scenario(self,cm)

scenarios["TLSSetup"]=[TLSSetup]
