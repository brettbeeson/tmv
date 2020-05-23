# pylint: disable=dangerous-default-value, logging-fstring-interpolation), import-error

import re
import socket
import sys
import argparse
import logging
from pathlib import Path
from getpass import getuser
from subprocess import run, CalledProcessError, PIPE
from collections import namedtuple
from os import geteuid, execlp
from signal import signal, SIGTERM, SIGINT
import psutil
from tmv.exceptions import SignalException
from tmv.util import LOG_FORMAT, LOG_LEVELS, run_and_capture

LOGGER = logging.getLogger(__name__)

PORT_MIN = 1024
PORT_MAX = 65535
SSHD_PROCESS = 'sshd'


class SSHTunnels():
    """ List of SSH tunnels to the localhost """

    def __init__(self, users=None, ports=(PORT_MIN, PORT_MAX), id_rsa=None, local_listeners_only=True):
        self.ssh_options = ["-o", "ForwardX11=no", "-o", "StrictHostKeyChecking=no", "-o", "PasswordAuthentication=no"]
        if id_rsa:
            if not Path(id_rsa).is_file():
                raise FileNotFoundError(f"id_rsa specified not found: {id_rsa}")
            self.ssh_options += ["-i", id_rsa]

        lc = psutil.net_connections('inet')
        # self.ports = namedtuple('socket',['ip','port'],default=ports[0],ports[1])

        listening_sockets = list(c for c in lc if (c.type == socket.SOCK_STREAM and
                                                   c.status == psutil.CONN_LISTEN)
                                 )
        # c.laddr = (ip,port)
        in_range_sockets = list(c for c in listening_sockets if ports[0] <= c.laddr.port <= ports[1])
        if local_listeners_only:
            in_range_sockets = list(c for c in in_range_sockets if c.laddr.ip == "127.0.0.1")

        self._tunnels = []

        for s in in_range_sockets:
            if s.pid is None or (psutil.Process(s.pid).name() == SSHD_PROCESS):
                tunnel = namedtuple("tunnel", ['port', 'ip', 'pid', 'process', 'host', 'rip', 'id', 'interrogated'])
                tunnel.port = s.laddr.port
                tunnel.ip = s.laddr.ip
                tunnel.pid = s.pid
                tunnel.host = None
                tunnel.rip = None
                tunnel.id = None
                tunnel.interrogated = False
                tunnel.works = False

                if s.pid is not None:
                    tunnel.process = SSHD_PROCESS
                else:
                    tunnel.process = None
                self._tunnels.append(tunnel)

        if users is None:
            self.users = [getuser()]
        else:
            self.users = users

        self.interrogate()

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
                    t.works = True

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

    @property
    def tunnels(self):
        return list(t for t in self._tunnels if t.works)

    @staticmethod
    def tunnel2str(t):
        return f"port={t.port} lip={t.ip} pid={t.pid} process={t.process} host={t.host} id={t.id} rip={t.rip}"

    def __str__(self):

        s = []
        for t in self._tunnels:
            if t.works:
                s.append(self.tunnel2str(t))
        return "\n".join(s)


def sig_handler(signal_received, frame):
    raise SignalException


def sshauto_console(cl=sys.argv[1:]):
    # pylint: disable=broad-except

    try:
        signal(SIGINT, sig_handler)
        signal(SIGTERM, sig_handler)

        parser = argparse.ArgumentParser("SSHAuto")
        parser.add_argument('--log-level', '-ll', default='WARNING', type=lambda s: LOG_LEVELS(s).name, nargs='?', choices=LOG_LEVELS.choices())
        parser.add_argument("remote", nargs="?", help="Remote host, ip or id")
        parser.add_argument("--users", nargs="+", help="Remote user/s to try.")
        parser.add_argument("--ports", type=int, nargs=2, metavar=('first', 'last'), default=(PORT_MIN, PORT_MAX))
        parser.add_argument("--id-rsa", type=str)
        parser.add_argument("--dry-run", action='store_true', help="Don't connect, just print connection we would have used")

        args = parser.parse_args(cl)
        logging.basicConfig(format=LOG_FORMAT)
        LOGGER.setLevel(args.log_level)

        if not geteuid() == 0:
            print("Running as non-root: functionality restricted", file=sys.stderr)
        else:
            if args.users is None:
                raise RuntimeError("Running as root: please specify --users to use for connections")
            if args.id_rsa is None:
                raise RuntimeError("Running as root: please specify --id_rsa to use for connections")

        ssh_tunnels = SSHTunnels(users=args.users, ports=args.ports, id_rsa=args.id_rsa)  # users=args.users, ports=args.ports)

        if args.remote:
            # connect
            if not args.dry_run:
                ssh_tunnels.connect_to(args.remote)
                sys.exit(3) # never 'ere normally
            else:
                print(ssh_tunnels.get_tunnel(args.remote))
                sys.exit(0)
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


if __name__ == '__main__':
    sshauto_console()
