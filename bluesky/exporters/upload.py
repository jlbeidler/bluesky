"""bluesky.exporters.upload"""

__author__ = "Joel Dubowy"

import copy
import getpass
import logging
import os
import re
import shutil
import tempfile

from bluesky import io
from bluesky.exceptions import BlueSkyConfigurationError
from . import ExporterBase

__all__ = [
    'UploadExporter'
]

__version__ = "0.1.0"


class UploadExporter(ExporterBase):

    EXPORT_KEY = 'upload'

    def __init__(self, extra_exports):
        super(UploadExporter, self).__init__(extra_exports)
        self._upload_options = {}
        self._current_user = getpass.getuser()

        # TODO: don't assume scp? maybe look for 'scp' > 'host' & 'user' & ...,
        #  and/or 'ftp' > ..., etc., and upload to all specified
        self._read_scp_config()

        # TODO: other upload options
        if not self._upload_options:
            raise BlueSkyConfigurationError(
                "Specify at least one mode of uploads")

    def _read_scp_config(self):
        scp_config = self.config('scp')
        if scp_config:
            if isinstance(scp_config, list):
                for c in scp_config:
                    self._read_one_scp_dest_config(c)
            else:
                self._read_one_scp_dest_config(scp_config)

    def _read_one_scp_dest_config(self, c):
        if any([not c.get(k) for k in ['host', 'dest_dir']]):
            raise BlueSkyConfigurationError(
                "Specify host and dest_dir for scp'ing")
        if 'scp' not in self._upload_options:
            self._upload_options['scp'] = []
        self._upload_options['scp'].append(copy.deepcopy(c))
        if not self._upload_options['scp'][-1].get('user'):
            self._upload_options['scp'][-1]['user'] = self._current_user
        if not self._upload_options['scp'][-1].get('port'):
            self._upload_options['scp'][-1]['port'] = self.config(
                'scp_defaults', 'port')

    LOCAL_HOSTS = set(['localhost', '127.0.0.1'])
    PORT_IN_HOSTNAME_MATCHER = re.compile(':\d+')
    def _is_same_host(self, upload_user, upload_host):
        """Checks if the upload user and host are the same as the local user
        and server.

        If they are local, the run status and output APIS can carry out their
        checks more efficiently and quickly.

        This function is a complete hack, but it works, at least some of the time.
        (And when it fails, it should only result in false negatives, which
        don't affect the correctness of the calling APIs - it just means they
        don't take advantage of working with local files.)
        """
        # If different users, then
        if upload_user and upload_user != self._current_user:
            return False

        # if host matches loopback address ('localhost', 127.0.0.1, etc.),
        # assume local server (though this should never really happen except
        # maybe in dev test)
        # Note: This logic breaks if forwarding ports to a vm, ssh tunneling,
        #  etc.
        if upload_host in self.LOCAL_HOSTS:
            return True

        # check if same hostname
        try:
            this_server = socket.gethostbyaddr(socket.gethostname())[0]
            if upload_host == this_server:
                return True
        except:
            pass

        # TODO: determine ip address of upload host and this server and
        #   check if ip addresses match
        # TODO: some other means?

        return False

    ##
    ## Host is Local
    ##

    def _local_cp(self, tarball, dest_dir):
        if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir)

        # TODO: do we need to copy tarball too?
        shutil.copy(tarball, dest_dir)

        # TODO: use tarfile module
        io.SubprocessExecutor().execute(['tar', 'xzf', tarball, '-C', dest_dir])

    ##
    ## SCP
    ##

    def _scp_upload(self, options, tarball):
        # TODO: check if host is in fact this server; if so,
        #   simply move tarball and unpack it rather than scp it;
        port = str(options['port'])
        remote_server = "{}@{}".format(options['user'], options['host'])
        destination = "{}:{}".format(remote_server, options['dest_dir'])

        # Note: there are various ways of doing this: a) call scp directly,
        #  b) use paramiko, c) use fabric, d) etc.....
        #  See http://stackoverflow.com/questions/68335/how-do-i-copy-a-file-to-a-remote-server-in-python-using-scp-or-ssh
        #  for examples
        # Note: ssh/scp error output (ex.
        #    'ssh: connect to host 127.0.0.1 port 2222: Connection refused')
        #   is captured by piping stderr to stdout in each check_output call
        logging.info("Creating remote destination {}".format(
            options['dest_dir']))
        io.SubprocessExecutor().execute(['ssh', '-o', 'StrictHostKeyChecking=no',
            remote_server, '-p', port, 'mkdir', '-p', options['dest_dir']])
        logging.info("Uploading {} via scp".format(tarball))
        io.SubprocessExecutor().execute(['scp', '-o', 'StrictHostKeyChecking=no',
            '-P', port, tarball, destination])

        return {
            "destination": destination,
            "tarball": os.path.basename(tarball)
        }

    def _scp_unpack(self, options, tarball):
        remote_server = "{}@{}".format(options['user'], options['host'])
        port = str(options['port'])
        tarball_filename = os.path.basename(tarball)
        logging.info("Extracting {} on {} in {}".format(tarball,
            remote_server, options['dest_dir']))

        cmd = "ssh {} -p {} 'cd {} && tar xzf {}'".format(remote_server,
            port, options['dest_dir'], tarball_filename)
        io.SubprocessExecutor().execute(cmd)

    def _scp(self, options, tarball):
        # Note: don't catch and exceptions here. Let calling method, 'export',
        #  handle exceptions
        r = self._scp_upload(options, tarball)

        # Note: we do, however, want to catch exceptions here; failuer to
        #  extract shouldn't cause use to lose information about successful scp
        # TODO: move extraction code to separate method, to share with other
        #  future upload modes
        try:
            self._scp_unpack(options, tarball)
            r["directory"] = self._output_dir_name
        except:
            r["error"] = "failed to extract {}".format(tarball)

        return r

    ##
    ## Public Interface
    ##

    def export(self, fires_manager):
        # Note: tempfile.TemporaryDirectory() isn't available until python
        #  3.5, so we need to use tempfile.mkdtemp and delete it manually
        # TODO: create context manager with __enter__/__exit__ to create
        #  and cleanup tempdir;  put in common module (maybe even pyairfire?)
        temp_dir = tempfile.mkdtemp()
        fires_manager.export = fires_manager.export or {}
        fires_manager.export['upload'] = {}
        try:
            tarball = self._bundle(fires_manager, temp_dir, create_tarball=True)

            # TODO: implement and call other upload options
            # TODO: detect if upload host is local here, rather than in
            #   scp, etc. specific methods (to centralize logic and avoid
            #   repetitive/redundant code)
            for u in ['scp']:
                if self._upload_options.get(u):
                    fires_manager.export['upload'][u] = []
                    for options in self._upload_options[u]:
                        fires_manager.export['upload'][u].append({
                            'options': options
                        })
                        is_local = self._is_same_host(
                            options['user'], options['host'])
                        try:
                            if is_local:
                                r = self._local_cp(tarball,
                                    options['dest_dir'])
                            else:
                                r = getattr(self,'_{}'.format(u))(options, tarball)
                            if r:
                                # Only include upload if it actually happened
                                fires_manager.export['upload'][u][-1].update(r)
                        except Exception as e:
                            msg = "Failed to {} tarball - {}".format(
                                'cp' if is_local else u, str(e))
                            fires_manager.export['upload'][u][-1]["error"] = msg
                            logging.error(msg)
                else:
                    logging.warning("Missing configuration for %s export", u)

        finally:
            shutil.rmtree(temp_dir)
