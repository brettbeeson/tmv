# pylint: disable=dangerous-default-value, logging-fstring-interpolation), import-error

import re
import socket
import sys
import argparse
import logging
from enum import Enum
from pathlib import Path
from getpass import getuser
from subprocess import run, CalledProcessError, PIPE
from os import geteuid, execlp
from signal import signal, SIGTERM, SIGINT
import psutil
from sshconf import read_ssh_config
#from tmv.exceptions import SignalException
#from tmv.util import LOG_FORMAT, LOG_LEVELS, run_and_capture

LOGGER = logging.getLogger(__name__)

PORT_MIN = 1024
PORT_MAX = 65535
SSHD_PROCESS = 'sshd'


class SignalException(Exception):
    """ Signal to exception """


class LOG_LEVELS(Enum):
    """ Convenience for argparse / logging modules """
    DEBUG = 'DEBUG'
    INFO = 'INFO'
    WARNING = 'WARNING'
    ERROR = 'ERROR'
    CRITICAL = 'CRITICAL'

    @staticmethod
    def choices():
        return [l.name for l in list(LOG_LEVELS)]


class SSHTunnel:
    """ Represent a tunnel """

    def __init__(self, port, ip, pid):
        self.port = port
        self.ip = ip
        self.pid = pid
        self.host = None
        self.rip = None
        self.id = None
        self.interrogated = False

    @property
    def valid(self):
        return self.name is not None

    @property
    def name(self):
        if self.id:
            return self.id
        return self.host


class SSHTunnels():
    """ List of SSH tunnels to the localhost """

    def __init__(self, users=None, ports=(PORT_MIN, PORT_MAX), id_rsa=None, local_listeners_only=False):
        self.ssh_options = ["-o", "StrictHostKeyChecking=no", "-o", "PasswordAuthentication=no"]
        # "-o", "ConnectTimeout=5", "-o", "ForwardX11=no",
        if id_rsa:
            if not Path(id_rsa).is_file():
                raise FileNotFoundError(f"id_rsa specified not found: {id_rsa}")
            self.ssh_options += ["-i", id_rsa]

        lc = psutil.net_connections('inet')

        listening_sockets = list(c for c in lc if (c.type == socket.SOCK_STREAM and
                                                   c.status == psutil.CONN_LISTEN)
                                 )
        in_range_sockets = list(c for c in listening_sockets if ports[0] <= c.laddr.port <= ports[1])
        if local_listeners_only:
            in_range_sockets = list(c for c in in_range_sockets if c.laddr.ip == "127.0.0.1")

        self._tunnels = []

        for s in in_range_sockets:
            if s.pid is None or (psutil.Process(s.pid).name() == SSHD_PROCESS):
                if len([t for t in self._tunnels if t.port == s.laddr.port]) == 0:
                    tunnel = SSHTunnel(s.laddr.port, s.laddr.ip, s.pid)
                    if s.pid is not None:
                        tunnel.process = SSHD_PROCESS
                    else:
                        tunnel.process = None

                    self._tunnels.append(tunnel)

        self.users = users or [getuser()]

        self.interrogate()

        self._tunnels = list(t for t in self._tunnels if t.valid)

    def find_ssh_user(self, port):
        for user in self.users:
            the_call = ['ssh'] + self.ssh_options + ['-l', user, '-p', str(port), "localhost", "echo test-user"]
            LOGGER.debug(f"Trying {user} at {port}:{the_call}")
            proc = run(the_call, check=False, stderr=PIPE, stdout=PIPE)
            if proc.returncode == 0:
                LOGGER.debug(f"Succeeded {user} at {port}")
                return user
            else:
                LOGGER.debug(f"{user} at {port} failed: stdout={proc.stdout} stderr={proc.stderr}")
        raise ConnectionRefusedError(f"None of {self.users} are valid for {port}")

    def interrogate(self):
        """ Connect to each localhost:port and get details  """

        # 8.8.8.8 via 172.17.44.225 dev eth0 src 172.17.44.237 uid 1000 \    cache
        #                                     ^   ^   ^  ^  ^
        ip_cmd = "ip -o route get to 8.8.8.8"
        ip_regex = re.compile(r".*src (\d+.\d+.\d+.\d+).*")
        id_cmd = "head -1 ~/.id"

        for t in self._tunnels:
            if not t.interrogated:
                try:
                    t.interrogated = True
                    t.user = self.find_ssh_user(t.port)

                    the_call = ['ssh'] + self.ssh_options + ['-l', t.user, '-p', str(t.port), "localhost", 'hostname']
                    host_output, _ = run_and_capture(the_call)
                    t.host = host_output.strip()

                    the_call = ['ssh'] + self.ssh_options + ['-l', t.user, '-p', str(t.port), "localhost", ip_cmd]
                    ip_output, _ = run_and_capture(the_call)
                    t.rip = ip_regex.search(ip_output).groups()[0]

                    the_call = ['ssh'] + self.ssh_options + ['-l', t.user, '-p', str(t.port), "localhost", id_cmd]
                    id_output, _ = run_and_capture(the_call)
                    t.id = id_output.strip()

                except CalledProcessError as exc:
                    print(exc, file=sys.stderr)
                    #LOGGER.debug(exc, exc_info=exc)
                    LOGGER.debug(exc)
                except ConnectionRefusedError as exc:
                    #LOGGER.debug(exc, exc_info=exc)
                    LOGGER.debug(exc)

    def connect(self, tunnel):
        """ ssh to the port """
        the_call = ['ssh'] + self.ssh_options + ['-l', tunnel.user, '-p', str(tunnel.port), "localhost"]
        sys.stdout.flush()
        sys.stderr.flush()
        execlp("ssh", *the_call)
        # the abyss: ssh process has replaced us

    def connect_to(self, remote):
        """ find the host with any attribute matching remote, and connect """
        t = self.get_tunnel(remote)
        LOGGER.info(f"Connecting to {self.tunnel2str(t)}")
        self.connect(t)

    def get_tunnel(self, remote):
        for t in self._tunnels:
            #LOGGER.debug(f"Checking for {remote} in {self.tunnel2str(t)}")
            #LOGGER.debug( (t.host, t.rip, t.id))
            if remote in (t.host, t.rip, t.id):
                return t
        raise ConnectionError(f"No tunnels match {remote}.")

    def update_config(self, config_file):
        """ Update config_file with our tunnels and return as string """
        # https://github.com/sorend/sshconf
        """
        # Typical entry:
        Host lunchbox
	        HostName localhost
	        Port 40991
	        User pi

        """
        c = read_ssh_config(str(config_file))
        hosts = c.hosts()
        for t in self._tunnels:
            if not t.name in hosts:
                LOGGER.info(f"Adding unit: name:{t.name} host:{t.host} id:{t.id}")
                c.add(t.name)
            LOGGER.info(f"Updating host: {t.user}@{t.name}:{t.port} via {t.ip} (host:{t.host} id:{t.id})")
            #c.set(t.name, Hostname=t.ip, Port=t.port, User=t.user)
            c.set(t.name, Hostname="127.0.0.1", Port=t.port, User=t.user)

        return c.config()

    @property
    def tunnels(self):
        return list(t for t in self._tunnels if t.valid)

    @staticmethod
    def tunnel2str(t):
        return f"port={t.port} lip={t.ip} pid={t.pid} process={t.process} host={t.host} id={t.id} rip={t.rip}"

    def __str__(self):
        s = []
        for t in self._tunnels:
            s.append(self.tunnel2str(t))
        return "\n".join(s)


def sig_handler(signal_received, frame):
    raise SignalException


def run_and_capture(cl: list, log_filename=None, timeout=None):
    """
    Only for python <=3.6. Use "capture" keyword for >3.6
    cl: list of parameters, or str (will be split on " "; quotes are respected
    log_filename: on process error (i.e. runs but fails), log it's output.
    """
    if isinstance(cl, str):
        cl = cl.split(" ")  # shlex
    try:
        proc = run(cl, encoding="UTF-8", stdout=PIPE, stderr=PIPE, check=False, timeout=timeout)
    except OSError as e:
        raise OSError("Subprocess failed to even run: {}. Cause: {}".format(' '.join(cl), str(e)))

    if proc.returncode != 0:
        if log_filename:
            Path(log_filename).write_text(f"*** command ***\n{cl}\n{' '.join(cl)}\n*** returned ***\n{proc.returncode}\n" +
                                          f"*** stdout ***\n{proc.stdout}\n*** stderr ***\n{proc.stderr}\n")
        raise CalledProcessError(proc.returncode, cl, proc.stdout, proc.stderr)

    return str(proc.stdout), str(proc.stderr)


def shun_jumpy_console(cl=sys.argv[1:]):
    try:
        signal(SIGINT, sig_handler)
        signal(SIGTERM, sig_handler)

        parser = argparse.ArgumentParser("shun_jumpy", description="Reverse of autossh: find local ports which are tunnels to remote ssh hosts")
        parser.add_argument('--log-level', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
        parser.add_argument("--user", action='append', help="Remote user/s to try. Multiple flags allowed.")
        parser.add_argument("--ports", type=int, nargs=2, metavar=('first', 'last'), default=(PORT_MIN, PORT_MAX))
        parser.add_argument("--id-rsa", type=str, help="Filename of private key if non-standard.")
        parser.add_argument("--dry-run", action='store_true', help="Don't connect, just print connection we would have used")

        args = parser.parse_args(cl)
        logging.basicConfig(format='%(levelname)-8s %(filename)-8s: %(message)s')
        LOGGER.setLevel(args.log_level)

        if not geteuid() == 0:
            LOGGER.info("Running as non-root: functionality restricted")
        else:
            if args.user is None:
                raise RuntimeError("Running as root: please specify --users to use for connections")
            if args.id_rsa is None:
                raise RuntimeError("Running as root: please specify --id_rsa to use for connections")

        ssh_tunnels = SSHTunnels(users=args.user, ports=args.ports, id_rsa=args.id_rsa)  # users=args.users, ports=args.ports)

        if args.remote:
            # connect
            if not args.dry_run:
                ssh_tunnels.connect_to(args.remote)
                sys.exit(3)  # never 'ere normally
            else:
                print(ssh_tunnels.get_tunnel(args.remote))
                sys.exit(0)
        elif args.config:
            # update ssh config
            print(ssh_tunnels.update_config(args.config))
        else:
            # list all valid
            print(ssh_tunnels)
            sys.exit(0)

    except SignalException:
        print("Exiting gracefully.")
        LOGGER.info("Exiting gracefully.")
        sys.exit(0)
    except Exception as exc:
        LOGGER.debug(exc, exc_info=exc)
        print(exc, file=sys.stderr)
        sys.exit(2)


def shun_find_console(cl=sys.argv[1:]):
    try:
        signal(SIGINT, sig_handler)
        signal(SIGTERM, sig_handler)

        parser = argparse.ArgumentParser("SSHAuto", description="Reverse of autossh: find local ports which are tunnels to remote ssh hosts")
        parser.add_argument('--log-level', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
        parser.add_argument("--user", action='append', help="Remote user/s to try. Multiple flags allowed.")
        parser.add_argument("--ports", type=int, nargs=2, metavar=('first', 'last'), default=(PORT_MIN, PORT_MAX))
        parser.add_argument("--id-rsa", type=str, help="Filename of private key if non-standard.")
        parser.add_argument("--dry-run", action='store_true', help="Don't connect, just print connection we would have used")

        args = parser.parse_args(cl)
        logging.basicConfig(format='%(levelname)-8s %(filename)-8s: %(message)s')
        LOGGER.setLevel(args.log_level)

        if not geteuid() == 0:
            LOGGER.info("Running as non-root: functionality restricted")
        else:
            if args.user is None:
                raise RuntimeError("Running as root: please specify --users to use for connections")
            if args.id_rsa is None:
                raise RuntimeError("Running as root: please specify --id_rsa to use for connections")

        ssh_tunnels = SSHTunnels(users=args.user, ports=args.ports, id_rsa=args.id_rsa)  # users=args.users, ports=args.ports)

        if args.remote:
            # connect
            if not args.dry_run:
                ssh_tunnels.connect_to(args.remote)
                sys.exit(3)  # never 'ere normally
            else:
                print(ssh_tunnels.get_tunnel(args.remote))
                sys.exit(0)
        elif args.config:
            # update ssh config
            print(ssh_tunnels.update_config(args.config))
        else:
            # list all valid
            print(ssh_tunnels)
            sys.exit(0)

    except SignalException:
        print("Exiting gracefully.")
        LOGGER.info("Exiting gracefully.")
        sys.exit(0)
    except Exception as exc:
        LOGGER.debug(exc, exc_info=exc)
        print(exc, file=sys.stderr)
        sys.exit(2)


def shun_connect_console(cl=sys.argv[1:]):
    try:
        signal(SIGINT, sig_handler)
        signal(SIGTERM, sig_handler)

        parser = argparse.ArgumentParser("SSHAuto", description="Reverse of autossh: find local ports which are tunnels to remote ssh hosts")
        parser.add_argument("remote", nargs="?", help="Remote hostname, ip or id (contents of ~/.id)")
        parser.add_argument('--log-level', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
        parser.add_argument("--user", action='append', help="Remote user/s to try. Multiple flags allowed.")
        parser.add_argument("--ports", type=int, nargs=2, metavar=('first', 'last'), default=(PORT_MIN, PORT_MAX))
        parser.add_argument("--id-rsa", type=str, help="Filename of private key if non-standard.")
        parser.add_argument("--dry-run", action='store_true', help="Don't connect, just print connection we would have used")
        parser.add_argument("--config", type=str, help="Add found remote hosts to ssh config and print it.")

        args = parser.parse_args(cl)
        logging.basicConfig(format='%(levelname)-8s %(filename)-8s: %(message)s')
        LOGGER.setLevel(args.log_level)

        if not geteuid() == 0:
            LOGGER.info("Running as non-root: functionality restricted")
        else:
            if args.user is None:
                raise RuntimeError("Running as root: please specify --users to use for connections")
            if args.id_rsa is None:
                raise RuntimeError("Running as root: please specify --id_rsa to use for connections")

        ssh_tunnels = SSHTunnels(users=args.user, ports=args.ports, id_rsa=args.id_rsa)  # users=args.users, ports=args.ports)

        if args.remote:
            # connect
            if not args.dry_run:
                ssh_tunnels.connect_to(args.remote)
                sys.exit(3)  # never 'ere normally
            else:
                print(ssh_tunnels.get_tunnel(args.remote))
                sys.exit(0)
        elif args.config:
            # update ssh config
            print(ssh_tunnels.update_config(args.config))
        else:
            # list all valid
            print(ssh_tunnels)
            sys.exit(0)

    except SignalException:
        print("Exiting gracefully.")
        LOGGER.info("Exiting gracefully.")
        sys.exit(0)
    except Exception as exc:
        LOGGER.debug(exc, exc_info=exc)
        print(exc, file=sys.stderr)
        sys.exit(2)
