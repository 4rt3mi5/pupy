#!/usr/bin/env python2

import argparse
import subprocess
import os
import sys
import errno

default_local_bin_location = os.path.expanduser('~/.local/bin/')
ROOT = os.path.abspath(os.path.dirname(__file__))

parser = argparse.ArgumentParser(prog="create-workspace.py")
parser.add_argument('-P', '--pupy-git-folder', default=ROOT, help='Path to pupy git')
parser.add_argument('-NC', '--do-not-compile-templates',
                    action='store_true', default=False, help='Do not compile payload templates')
parser.add_argument('-R', '--docker-repo',
                    help='Use non-default toolchains repo (Use "local" to build all the things on your PC')
parser.add_argument('-B', '--bin-path', default=default_local_bin_location,
                    help='Store pupy launch wrapper to this folder (default={})'.format(
                        default_local_bin_location))
parser.add_argument('-NI', '--no-pip-install-deps', action='store_true', default=False,
                    help='Do not install missing python deps (virtualenv, python-docker) using pip')
parser.add_argument('workdir', help='Location of workdir')

args = parser.parse_args()

try:
    with open('/dev/null', 'w') as devnull:
        subprocess.check_call(['git', '--help'], stdout=devnull)
except:
    sys.exit("Install git (example: sudo apt-get install git)")

if not args.do_not_compile_templates:
    try:
        with open('/dev/null', 'w') as devnull:
            subprocess.check_call(['docker', '--help'], stdout=devnull)
    except:
        sys.exit("Install docker: https://docs.docker.com/install/")

    vsc = '/proc/sys/abi/vsyscall32'
    if os.path.isfile(vsc):
        vsyscall = int(open(vsc).read())
        if not vsyscall:
            sys.exit('You need to have vsyscall enabled:\n~> sudo sysctl -w abi.vsyscall32=1\n~> sudo reboot')

try:
    import virtualenv
except:
    if args.NI:
        sys.exit('virtualenv missing: pip install --user virtualenv')
    else:
        subprocess.call('pip install --user virtualenv')

    import virtualenv

if not os.path.isfile(os.path.join(args.pupy_git_folder, 'create-workspace.py')):
    sys.exit('{} is not pupy project folder'.format(args.pupy_git_folder))

if os.path.isdir(args.workdir) and os.listdir(args.workdir):
    sys.exit('{} is not empty'.format(args.workdir))

pupy = os.path.abspath(args.pupy_git_folder)

print "[+] Pupy at {}".format(pupy)

if not args.do_not_compile_templates:
    pwd = os.getcwd()
    print "[+] Compile common templates"
    os.chdir(os.path.join(args.pupy_git_folder, 'client'))
    env = os.environ.copy()
    if args.docker_repo:
        env['REPO'] = args.docker_repo

    subprocess.check_call(['build-docker.sh'], env=env)

print "[+] Create VirtualEnv environment"

try:
    os.makedirs(args.workdir)
except OSError, e:
    if e.errno == errno.EEXIST:
        pass

virtualenv.create_environment(args.workdir)

print "[+] Install dependencies"
subprocess.check_call([
    os.path.join(args.workdir, 'bin', 'pip'),
    'install',
    '-r', 'requirements.txt'
], cwd=os.path.join(pupy, 'pupy'))

print "[+] Create pupysh wrapper"
pupysh_path = os.path.join(args.workdir, 'bin', 'pupysh')
pupysh_update_path = os.path.join(args.workdir, 'bin', 'pupysh-update')

with open(pupysh_path, 'w') as pupysh:
    wa = os.path.abspath(args.workdir)
    print >>pupysh, '#!/bin/sh'
    print >>pupysh, 'cd {}'.format(wa)
    print >>pupysh, 'exec bin/python -B {} "$@"'.format(
        os.path.join(pupy, 'pupy', 'pupysh.py'))

os.chmod(pupysh_path, 0755)

with open(pupysh_update_path, 'w') as pupysh_update:
    wa = os.path.abspath(args.workdir)
    print >>pupysh_update, '#!/bin/sh'
    print >>pupysh_update, 'set -e'
    print >>pupysh_update, 'echo "[+] Update pupy repo"'
    print >>pupysh_update, 'cd {}; git pull --recurse-submodules'.format(pupy)
    print >>pupysh_update, 'echo "[+] Update python dependencies"'
    print >>pupysh_update, 'source {}/bin/activate; cd pupy; pip install --upgrade -r requirements.txt'.format(
        args.workdir)
    if not args.do_not_compile_templates:
        print >>pupysh_update, 'echo "[+] Recompile templates"'
        for target in ( 'windows', 'linux32', 'linux64' ):
            print >>pupysh_update, 'echo "[+] Build {}"'.format(target)
            print >>pupysh_update, 'docker start -a build-pupy-{}'.format(target)
    print >>pupysh_update, 'echo "[+] Update completed"'

os.chmod(pupysh_update_path, 0755)

if args.bin_path:
    bin_path = os.path.abspath(args.bin_path)
    print "[+] Store symlink to pupysh to {}".format(bin_path)

    if not os.path.isdir(bin_path):
        os.makedirs(bin_path)

    for src, sympath in ((pupysh_path, 'pupysh'), (pupysh_update_path, 'pupysh-update')):
        sympath = os.path.join(bin_path, sympath)

        if os.path.islink(sympath):
            os.unlink(sympath)

        elif os.path.exists(sympath):
            sys.exit("[-] File at {} already exists and not symlink".format(sympath))

        os.symlink(src, sympath)

    if not bin_path in os.environ['PATH']:
        print "[-] {} is not in your PATH!".format(bin_path)
    else:
        print "[I] To execute pupysh:"
        print "~ > pupysh"
        print "[I] To update:"
        print "~ > pupysh-update"

else:
    print "[I] To execute pupysh:"
    print "~ > {}".format(pupysh_path)
    print "[I] To update:"
    print "~ > {}".format(pupysh_update_path)
