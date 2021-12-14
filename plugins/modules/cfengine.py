#!/usr/bin/python

# Copyright: (c) 2021, Vratislav Podzimek <vratislav.podzimek@northern.tech>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
---
module: cfengine

short_description: Module for putting machines under a CFEngine umbrella

# If this is part of a collection, you need to use semantic versioning,
# i.e. the version is of the form "2.5.0" and not "2.4".
version_added: "1.0.0"

description: The 'cfengine' module provides an easy way to make sure CFEngine
             is installed on the targeted hosts and that they are bootstrapped
             to the right CFEngine hub.

options:
    policy_server:
        description: The CFEngine policy server that the host should be bootstrapped to.
        required: true
        type: str
    version:
        description:
          - Version of CFEngine that should be installed.
          - If CFEngine is installed already, this is ignored.
        required: false
        type: str
# Specify this value according to your collection
# in format of namespace.collection.doc_fragment_name
# extends_documentation_fragment:
#     - vpodzime.cfengine.my_doc_fragment_name

author:
    - Vratislav Podzimek (@vpodzime)
'''

EXAMPLES = r'''
- name: Make sure the host is part of the CFEngine-managed infra
  vpodzime.cfengine.cfengine:
    policy_server: 10.0.0.1

# host name can be used instead of IP
- name: Make sure the host is part of the CFEngine-managed infra
  vpodzime.cfengine.cfengine:
    policy_server: hub.example.com

# specific version can be requested (if CFEngine is not installed already)
- name: Make sure the host is part of the CFEngine-managed infra
  vpodzime.cfengine.cfengine:
    policy_server: hub.example.com
    version: 3.18.1

# version series can be requested (if CFEngine is not installed already)
- name: Make sure the host is part of the CFEngine-managed infra
  vpodzime.cfengine.cfengine:
    policy_server: hub.example.com
    version: 3.18.x
'''

RETURN = r'''
cfengine_policy_server:
    description: The CFEngine policy server the host is bootstrapped to
    type: str
    returned: always
    sample: 'hub.example.com'
cfengine_role:
    description: CFEngine role of the host ('hub' or 'agent')
    type: str
    returned: always
    sample: 'agent'
state:
    description: Description of the current state of the host
    type: str
    returned: if the host has CFEngine installed and is bootstrapped
    sample: 'CFEngine installed and bootstrapped to hub.example.com'
'''

import os
import re
import json
import sys
import socket
from os.path import basename, splitext, expanduser, abspath
from collections import OrderedDict
from datetime import datetime
from tempfile import mkstemp

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import open_url
from ansible.module_utils.facts.network.linux import LinuxNetwork


log = None

def get_json(url):
    try:
        url_f = open_url(url)
    except:
        return None

    data = url_f.read()
    url_f.close()
    return json.loads(data)

class LoggerToAnsible:
    def __init__(self, module):
        self._module = module

    def _log_msg(self, msg):
        self._module.log(msg)

    def debug(self, msg, *args):
        formatted_msg = msg % args
        self._log_msg("[debug] %s" % formatted_msg)

    def info(self, msg, *args):
        formatted_msg = msg % args
        self._log_msg("[info] %s" % formatted_msg)

    def error(self, msg, *args):
        formatted_msg = msg % args
        self._log_msg("[error] %s" % formatted_msg)

    def warning(self, msg, *args):
        formatted_msg = msg % args
        self._log_msg("[warning] %s" % formatted_msg)

    def critical(self, msg, *args):
        formatted_msg = msg % args
        self._log_msg("[CRITICAL] %s" % formatted_msg)

# ======================= BEGIN code taken as-is from cf-remote =======================

def is_in_past(date):
    now = datetime.now()
    date = datetime.strptime(date, "%Y-%m-%d")
    return now > date

def canonify(string):
    legal = "abcdefghijklmnopqrstuvwxyz0123456789-_"
    string = string.strip()
    string = string.lower()
    string = string.replace(".", "_")
    string = string.replace(" ", "_")
    results = []
    for c in string:
        if c in legal:
            results.append(c)
    return "".join(results)

def os_release(inp):
    if not inp:
        log.debug("Cannot parse os-release file (empty)")
        return None
    d = OrderedDict()
    for line in inp.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, sep, value = line.partition("=")
        assert "=" not in key
        if len(value) > 1 and value[0] == value[-1] and value[0] in ["'", '"']:
            value = value[1:-1]
        d[key] = value
    return d

class Artifact:
    def __init__(self, data, filename=None):
        if filename and not data:
            data = {}
            data["URL"] = abspath(expanduser(filename))
            data["Title"] = ""
            data["Arch"] = None
            if "sparc" in filename.lower():
                data["Arch"] = "spar"
        self.data = data
        self.url = data["URL"]
        self.title = data["Title"]
        self.arch = canonify(data["Arch"]) if data["Arch"] else None

        self.filename = basename(self.url)
        self.extension = splitext(self.filename)[1]

        self.tags = ["any"]
        self.create_tags()

    def create_tags(self):
        if self.arch:
            self.add_tag(self.arch)
        self.add_tag(self.extension[1:])

        look_for_tags = [
            "Windows", "CentOS", "Red Hat", "Debian", "Ubuntu", "SLES", "Solaris", "AIX", "HPUX",
            "HP-UX", "nova", "community", "masterfiles", "OSX", "OS X", "OS-X"
        ]
        for tag in look_for_tags:
            tag = tag.lower()
            filename = self.filename
            if tag in filename:
                self.add_tag(tag)
        if "hp-ux" in self.tags:
            self.add_tag("hpux")
            self.tags.remove("hp-ux")
        if "os-x" in self.tags:
            self.add_tag("osx")
            self.tags.remove("os-x")
        if "os_x" in self.tags:
            self.add_tag("osx")
            self.tags.remove("os_x")
        if "x86" in self.tags:
            self.add_tag("32")
        if "x86_64" in self.tags:
            self.add_tag("64")
        if "i686" in self.tags:
            self.add_tag("32")

        self.add_tags_from_filename(self.filename)

    def add_tag(self, string):
        if sys.version_info[0] == 2:
            assert type(string) in (str, unicode)
        else:
            assert type(string) is str

        canonified = canonify(string)
        if canonified not in self.tags:
            self.tags.append(canonified)

    def add_tags_from_filename(self, filename):
        parts = re.split(r"[-_.]", filename)
        #parts = self.filename.split("-_.")
        for part in parts:
            part = part.strip()
            if part == "x86":
                continue
            if part == "amd64" or part == "x86_64":
                self.add_tag("64")
            try:
                _ = int(part)
            except ValueError:
                self.add_tag(part)
        if "hub" in self.tags:
            self.add_tag("policy_server")
        else:
            self.add_tag("client")
            self.add_tag("agent")
        parts = filename.split(".")
        if "x86_64" in parts:
            self.add_tag("x86_64")
            self.add_tag("64")
        if "amd64" in parts:
            self.add_tag("amd64")
            self.add_tag("64")

    def __str__(self):
        return self.filename + " ({})".format(" ".join(self.tags))

    def __repr__(self):
        return str(self)

def filter_artifacts(artifacts, tags, extension):
    if extension:
        artifacts = [a for a in artifacts if a.extension == extension]
    log.debug("Looking for tags: {}".format(tags))
    log.debug("In artifacts: {}".format(artifacts))
    for tag in tags or []:
        tag = canonify(tag)
        new_artifacts = [a for a in artifacts if tag in a.tags]
        # Have to force evaluation using list comprehension,
        # since we are overwriting artifacts
        if len(new_artifacts) > 0:
            artifacts = new_artifacts

    log.debug("Found artifacts: {}".format(artifacts))
    return artifacts

class Release:
    def __init__(self, data):
        self.data = data
        self.version = data["version"]
        self.url = data["URL"]
        self.lts = data["lts_branch"] if "lts_branch" in data else None
        self.extended_data = None
        self.artifacts = None
        self.default = False

    def init_download(self):
        self.extended_data = get_json(self.url)
        artifacts = self.extended_data["artifacts"]
        self.artifacts = []
        for header in artifacts:
            for blob in artifacts[header]:
                artifact = Artifact(blob)
                artifact.add_tag(header)
                self.artifacts.append(artifact)

    def find(self, tags, extension=None):
        if not self.extended_data:
            self.init_download()
        return filter_artifacts(self.artifacts, tags, extension)

    def __str__(self):
        string = self.version
        if self.lts:
            string += " LTS"
        # string = "{}: {}".format(version, self.url)
        if self.default:
            string += " (default)"
        return string


class Releases:
    def __init__(self, edition="enterprise"):
        assert edition in ["community", "enterprise"]
        self.url = "https://cfengine.com/release-data/{}/releases.json".format(edition)
        self.data = get_json(self.url)
        self.supported_branches = []
        for branch in self.data["lts_branches"]:
            expires = branch["supported_until"]
            expires += "-25"
            # Branch expires 25th day of month
            # This is exact enough and avoids problems with leap years
            if not is_in_past(expires):
                self.supported_branches.append(branch["branch_name"])
            else:
                log.info("LTS branch {} expired on {}".format(branch["branch_name"], expires))

        self.releases = []
        for release in self.data["releases"]:
            rel = Release(release)
            if "status" in release and release["status"] == "unsupported":
                continue
            if (
                (release["version"] != "master")
                and ("lts_branch" not in release)
                and ("latest_stable" not in release)
            ):
                continue
            if "lts_branch" in release and release["lts_branch"] not in self.supported_branches:
                continue
            if "latestLTS" in release and release["latestLTS"] == True:
                self.default = rel
                rel.default = True
            self.releases.append(rel)

    def pick_version(self, version):
        for release in self.data["releases"]:
            if "version" in release and version == release["version"]:
                return Release(release)
            if "lts_branch" in release and version == release["lts_branch"]:
                return Release(release)
        return None

    def __str__(self):
        return ", ".join(str(x.version) for x in self.releases)

def _package_from_list(tags, extension, packages):
    artifacts = [Artifact(None, p) for p in packages]
    artifact = filter_artifacts(artifacts, tags, extension)[-1]
    return artifact.url

def _package_from_releases(tags, extension, version, edition, remote_download):
    releases = Releases(edition)
    release = releases.default
    if version:
        release = releases.pick_version(version)

    release.init_download()

    if not release.artifacts:
        log.error("The {} {} release is empty, visit tracker.mender.io to file a bug report".format(
            version, edition))
        return None

    artifacts = release.find(tags, extension)
    if not artifacts:
        log.error(
            "Could not find an appropriate package for host, please use --{}-package".format(
                "hub" if "hub" in tags else "client"))
        return None
    artifact = artifacts[-1]
    if remote_download:
        return artifact.url
    else:
        return download_package(artifact.url)

def get_package_tags(os_release=None, redhat_release=None):
    tags = []
    if os_release is not None:
        distro = os_release["ID"]
        major = os_release["VERSION_ID"].split(".")[0]
        platform_tag = distro + major

        # Add tags with version number first, to filter by them first:
        tags.append(platform_tag) # Example: ubuntu16
        if distro == "centos" or distro == "rhel":
            tags.append("el" + major)

        # Then add more generic tags (lower priority):
        tags.append(distro) # Example: ubuntu
        if distro == "centos":
            tags.append("rhel")

        if distro == "centos" or distro == "rhel":
            tags.append("el")
    elif redhat_release is not None:
        # Examples:
        # CentOS release 6.10 (Final)
        # Red Hat Enterprise Linux release 8.0 (Ootpa)
        before, after = redhat_release.split(" release ")
        distro = "rhel"
        if before.lower().startswith("centos"):
            distro = "centos"
        major = after.split(".")[0]
        tags.append(distro + major)
        tags.append("el" + major)
        if "rhel" not in tags:
            tags.append("rhel" + major)

        tags.append(distro)
        if "rhel" not in tags:
            tags.append("rhel")
        tags.append("el")

    return tags

def get_package_from_host_info(package_tags, pkg_binary, arch, version=None,
                               hub=False, edition="enterprise", packages=None,
                               remote_download=False):
    tags = []
    if edition == "enterprise":
        tags.append("hub" if hub else "agent")

    tags.append("64" if arch in ("x86_64", "amd64") else arch)
    if arch in ("i386", "i486", "i586", "i686"):
        tags.append("32")

    extension = None
    if package_tags is not None and "msi" in package_tags:
        extension = ".msi"
    elif "dpkg" in pkg_binary:
        extension = ".deb"
    elif "rpm" in pkg_binary:
        extension = ".rpm"

    if package_tags is not None:
        tags.extend(tag for tag in package_tags if tag != "msi")

    if packages is None: # No commandd line argument given
        package = _package_from_releases(tags, extension, version, edition, remote_download)
    else:
        package = _package_from_list(tags, extension, packages)

    return package

# ======================== END code taken as-is from cf-remote ========================


def get_package_url_for_this_host(module, version=None, hub=False):
    os_release_data = None
    if os.access("/etc/os-release", os.R_OK):
        with open("/etc/os-release") as osr:
            os_release_data = osr.read()

    redhat_release_data = None
    if os_release_data is not None:
        os_release_data = os_release(os_release_data)
    else:
        if os.access("/etc/redhat-release", os.R_OK):
            with open("/etc/rehat-release") as rhr:
                redhat_release_data = rhr.read()

    if not any((os_release_data, redhat_release_data)):
        log.error("Failed to get information about host OS")
        return None

    package_tags = get_package_tags(os_release_data, redhat_release_data)
    log.debug("Package tags: %s" % package_tags)

    arch = os.uname()[4]

    pkg_binaries = dict()
    for pkg_binary in ["dpkg", "rpm", "yum", "apt", "pkg"]:
        path = module.get_bin_path(pkg_binary)
        if path is not None:
            pkg_binaries[pkg_binary] = path

    package = get_package_from_host_info(package_tags, pkg_binaries, arch,
                                         version, hub, remote_download=True)
    return (package, pkg_binaries)


def get_cfengine_role(module, result):
    network_facts = LinuxNetwork(module).populate()
    local_ips = network_facts["all_ipv4_addresses"] + network_facts["all_ipv6_addresses"]

    # os.uname()[1] == nodename
    hub = module.params["policy_server"] in (local_ips + [os.uname()[1]])

    looks_like_ip = re.match(r'^([0-9]{1,3}\.){3}[0-9]{1,3}$', module.params["policy_server"])
    if not hub and not looks_like_ip:
        try:
            ip = socket.gethostbyname(module.params["policy_server"])
        except socket.gaierror:
            pass
        else:
            hub = ip in local_ips

    result["cfengine_role"] = "hub" if hub else "agent"


def install_cfengine(module, result):
    version = module.params.get("version")
    hub = result["cfengine_role"] == "hub"
    url, pkg_binaries = get_package_url_for_this_host(module, version, hub)
    extension = splitext(url)[1]

    result["cfengine_package"] = url

    fd, fpath = mkstemp(prefix="ansible-cfengine-pkg", suffix=extension)
    log.debug("Downloading %s to %s" % (url, fpath))
    try:
        url_f = open_url(url)
    except:
        os.close(fd)
        try:
            os.unlink(fpath)
        except:
            pass
        return False

    with os.fdopen(fd, "wb") as pkg_file:
        done = False
        while not done:
            data = url_f.read(512 * 1024)
            done = not bool(data)
            if data:
                pkg_file.write(data)
    url_f.close()

    command = None
    if extension == ".rpm":
        command = pkg_binaries.get("yum") or pkg_binaries.get("zypper") or pkg_binaries.get("rpm")
    elif extension == ".deb":
        command = pkg_binaries.get("dpkg")

    if command is None:
        try:
            os.unlink(fpath)
        except:
            pass
        module.fail_json(msg="Installation of %s not supported" % url, **result)

    if "rpm" in command or "dpkg" in command:
        sub_command = "-i"
    else:
        sub_command = "install -y"

    command_str = " ".join([command, sub_command, fpath])
    log.info("Installing %s with %s" % (url, command_str))
    rc, _out, _err = module.run_command(command_str)

    try:
        os.unlink(fpath)
    except:
        pass

    if rc != 0:
        module.fail_json(msg="Installation of %s failed" % url, **result)

    result["changed"] = True


def bootstrap(host, module, result):
    rc, _out, _err = module.run_command("/var/cfengine/bin/cf-agent --bootstrap %s" % host)
    if rc != 0:
        module.fail_json(msg="Failed to bootstrap to %s" % host, **result)


def run_module():
    # define available arguments/parameters a user can pass to the module
    module_args = dict(
        policy_server=dict(type='str', required=True),
        version=dict(type='str', required=False),
        # hub=dict(type='bool', required=False, default=False)
    )

    # seed the result dict in the object
    result = dict(
        changed=False,
    )

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    # if the user is working with this module in only check mode we do not
    # want to make any changes to the environment, just return the current
    # state with no modifications
    if module.check_mode:
        if not os.access("/var/cfengine/bin/cf-agent", os.X_OK):
            module.fail_json(msg="CFEngine not installed", **result)

        policy_server_fpath = "/var/cfengine/policy_server.dat"
        if not os.path.exists(policy_server_fpath):
            module.fail_json(msg="Not bootstrapped", **result)

        get_cfengine_role(module, result)
        with open(policy_server_fpath) as psf:
            policy_server = psf.read().strip()

        if policy_server != module.params["policy_server"]:
            module.fail_json(msg="Bootstrapped to a different target: %s" % policy_server,
                             **result)

        result["state"] = "CFEngine installed and bootstrapped to %s" % policy_server
        module.exit_json(**result)


    # XXX: this is a little hacky, but it's to make simple 'log.debug()' and
    #      similar work in the functions above taken from cf-remote
    global log
    log = LoggerToAnsible(module)

    if not os.access("/var/cfengine/bin/cf-agent", os.X_OK):
        get_cfengine_role(module, result)
        install_cfengine(module, result)

    policy_server_fpath = "/var/cfengine/policy_server.dat"
    if not os.path.exists(policy_server_fpath):
        bootstrap(module.params["policy_server"], module, result)
    else:
        with open(policy_server_fpath) as psf:
            policy_server = psf.read().strip()

        if policy_server != module.params["policy_server"]:
            # Rebootstrap
            bootstrap(module.params["policy_server"], module, result)

    if "cfengine_role" not in result:
        get_cfengine_role(module, result)
    result["cfengine_policy_server"] = module.params["policy_server"]
    result["state"] = "CFEngine installed and bootstrapped to %s" % module.params["policy_server"]

    module.exit_json(**result)


def main():
    run_module()


if __name__ == '__main__':
    main()
