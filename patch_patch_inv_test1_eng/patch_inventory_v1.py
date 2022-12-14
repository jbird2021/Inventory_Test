from __future__ import print_function
from ansible.plugins.inventory import BaseInventoryPlugin
from ansible.errors import AnsibleError, AnsibleParserError
from pprint import pprint
import json
import os
import stat
import sys
import re

# Ansible, annoyingly, has other modules/files named 'yaml'
# but we need the generic system yaml module here,
# so let's do some magic
def import_non_local(name, custom_name=None):
    import imp, sys

    custom_name = custom_name or name

    f, pathname, desc = imp.find_module(name, sys.path[1:])
    module = imp.load_module(custom_name, f, pathname, desc)
    if (f is not None):
        f.close()

    return module
sys_yaml = import_non_local('yaml','sys_yaml')


class InventoryModule(BaseInventoryPlugin):

    NAME="patch_inventory_v1"
    repo_key_path = None
    repo_checkout_path = None
    repo_source = None
    new_group = None
    def verify_file(self,path):
        # Let's see what we're given
        self.repo_key_path = os.getenv("REPO_SECRET_KEY_FILE")
        if (self.repo_key_path is None):
            print("No REPO_SECRET_KEY_FILE provided",file=sys.stderr)
            raise AnsibleError("No REPO_SECRET_KEY_FILE provided")
        self.repo_checkout_path = os.getenv("AWX_ISOLATED_DATA_DIR",default="")+"/git_checkout"
        self.repo_source = os.getenv("REPO_INVENTORY_SOURCE")
        if (self.repo_source is None):
            print("No REPO_INVENTORY_SOURCE provided",file=sys.stderr)
            raise AnsibleError("No REPO_INVENTORY_SOURCE provided")
        self.repo_directory_suffix = os.getenv("REPO_INVENTORY_DIRECTORY")
        if (self.repo_directory_suffix is None):
            print("No REPO_INVENTORY_DIRECTORY provided",file=sys.stderr)
            raise AnsibleError("No REPO_INVENTORY_DIRECTORY provided")
        self.new_group = os.getenv("INVENTORY_GROUP")
        if (self.new_group is None):
            print("No INVENTORY_GROUP provided",file=sys.stderr)
            raise AnsibleError("No INVENTORY_GROUP provided")


        return True

    def parse(self,inventory,loader,path,cache):
        # Prepare
        super(InventoryModule, self).parse(inventory,loader,path,cache=cache)
        # Check out git
        git_ssh_path=os.getenv("AWX_ISOLATED_DATA_DIR")+"/git_ssh"
        with open(git_ssh_path,'w') as file:
            file.write("#! /bin/sh\nssh -q -i "+self.repo_key_path+" -oStrictHostKeyChecking=False -oUserKnownHostsFile=/dev/null $*")
        os.chmod(git_ssh_path,stat.S_IXUSR|stat.S_IRUSR)
        repo_branch = os.getenv("REPO_INVENTORY_BRANCH")
        branch_option=""
        if (repo_branch is not None):
            branch_option = " --branch "+repo_branch
        os.environ["GIT_SSH"] = git_ssh_path
        os.system("git clone --quiet "+self.repo_source+" "+self.repo_checkout_path+branch_option)
        # open the exclusions file, if any
        basepath=self.repo_checkout_path+"/"+self.repo_directory_suffix
        exclusions=None
        try:
            with open(basepath+"/exclusions.yml") as file:
                    exclusions = sys_yaml.safe_load(file)
        except:
            print("exclusions.yml is missing or unparsable, continuing anyway",file=sys.stderr)
            exclusions=None
        if (exclusions is None):
            exclusions={}
        if ('exclusions' in exclusions):
            exclusions = exclusions['exclusions']
        # Open the inclusions file
        with open(basepath+"/inclusions.yml") as file:
            inclusions = sys_yaml.safe_load(file)
        if (inclusions is None):
            raise AnsibleError("inclusions.yml must not be empty")
        include_all_hosts = False
        if ("include_all_hosts" in inclusions and
                re.match(r'(?i)(true|yes|1)',str(inclusions['include_all_hosts']))):
            if ("inclusions" in inclusions):
                raise AnsibleError("include_all_hosts set to true and inclusion list provided")
            include_all_hosts = True
        else:
            if ("inclusions" not in inclusions):
                raise AnsibleError("Either an inclusions list must be provided or include_all_hosts must be provided and set to true")

        # Open the Inventory file
        with open(basepath+"/hosts.yml") as file:
            hosts = sys_yaml.safe_load(file)
            # these are the groups
        self.inventory.add_group(group=self.new_group)
        # self.inventory.groups[g].set_variable("test","variable")
        for h_dict in hosts:
           h=h_dict['name']
           if ((include_all_hosts or h in inclusions['inclusions']) and h not in exclusions):
              self.inventory.add_host(group=self.new_group,host=h)
              if ('cmdb_people' in h_dict):
                self.inventory.set_variable(h,'cmdb_people',h_dict['cmdb_people'])
        # Add vars(if any) to group
        vars = None
        try:
            with open(basepath+"/vars.yml") as file:
                    vars = sys_yaml.safe_load(file)
        except:
            print("vars.yml is missing or unparsable, continuing anyway",file=sys.stderr)
        if (vars is not None):
            for k,v in vars.items():
                self.inventory.groups[self.new_group].set_variable(k,v)


        return True
