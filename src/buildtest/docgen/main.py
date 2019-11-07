"""
This file is used for generating documentation tests.
"""
import os, sys
sys.path.insert(0, os.path.join(os.getenv("BUILDTEST_ROOT"), 'src'))

from buildtest.tools.system import BuildTestCommand
from buildtest.tools.file import create_dir

docgen=os.path.join(os.getenv("BUILDTEST_ROOT"),"docs","docgen")

def build_helper():
    help_cmds = [
     "buildtest -h",
     "buildtest list -h",
     "buildtest show -h",
     "buildtest testconfigs -h",
     "buildtest testconfigs maintainer -h",
     "buildtest build -h",
     "buildtest build bsub -h",
     "buildtest benchmark -h",
     "buildtest benchmark osu -h",
     "buildtest module -h",
     "buildtest module tree -h",
     "buildtest module collection -h",
     "buildtest config -h",
     "buildtest system -h"
    ]
    for cmd in help_cmds:
        out = run(cmd)
        tmp_fname = cmd.replace(" ","_") + ".txt"
        fname = os.path.join(docgen,tmp_fname)

        writer(fname,out,cmd)

def run(query):
    print (f"Executing Command: {query}")
    cmd = BuildTestCommand()
    cmd.execute(query)
    out = cmd.get_output()
    return out

def introspection_cmds():

    queries = [
        "buildtest list --software",
        "buildtest list --modules",
        "buildtest list --easyconfigs",
        "buildtest show -k singlesource",
        "buildtest show --config",
        "buildtest config view",
        "buildtest config restore",
        "buildtest system view",
        "buildtest system fetch",
        "buildtest testconfigs list",
        "buildtest testconfigs view compilers.helloworld.args.c.yml",
        "buildtest benchmark osu --list",
        "buildtest benchmark osu --info",
        "buildtest module collection --clear",
        "buildtest module tree -l"
    ]
    for cmd in queries:
        out = run(cmd)
        tmp_fname = cmd.replace(" ", "_") + ".txt"
        fname = os.path.join(docgen, tmp_fname)

        writer(fname, out, cmd)


def module_cmds():
    module_dict = {
        "add_module_tree.txt" : "buildtest module tree -a /usr/share/lmod/lmod/modulefiles/Core",
        "remove_module_tree.txt": "buildtest module tree -r /usr/share/lmod/lmod/modulefiles/Core",
        "default_module_tree.txt": "buildtest module tree -l",
        "set_module_tree.txt": "buildtest module tree -s /usr/share/lmod/lmod/modulefiles/Core",
        "set_module_tree_view.txt": "buildtest module tree -l"
    }
    for k,v in module_dict.items():
        out = run(v)
        fname = os.path.join(docgen,k)
        writer(fname, out, v)

    run("buildtest module tree -s /mxg-hpc/users/ssi29/spack/modules/linux-rhel7-x86_64/Core")
    out = run("buildtest module --spack")
    writer(os.path.join(docgen,"spack_modules.txt"),out,"buildtest module --spack")

    run("buildtest module tree -s /mxg-hpc/users/ssi29/easybuild-HMNS/modules/all/Core")
    out = run("buildtest module --easybuild")
    writer(os.path.join(docgen, "easybuild_modules.txt"), out, "buildtest module --easybuild")

    out = run ("buildtest module -d GCCcore/8.1.0")
    writer(os.path.join(docgen, "parent_modules.txt"), out, "buildtest module -d GCCcore/8.1.0")
def writer(fname,out,query):
    fd = open(fname,"w")
    fd.write(f"$ {query}\n")
    fd.write(out)
    fd.close()
    print (f"Writing file: {fname}")

def main():
    create_dir(docgen)
    build_helper()
    introspection_cmds()
    module_cmds()

if __name__ == "__main__":
    """Entry Point, invoking main() method"""
    main()