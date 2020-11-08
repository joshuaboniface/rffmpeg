#!/usr/bin/env python3

# rffmpeg.py - Remote FFMPEG transcoding for Jellyfin
#
#    Copyright (C) 2019-2020  Joshua M. Boniface <joshua@boniface.me>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
###############################################################################
#
# rffmpeg works as a drop-in replacement to an existing ffmpeg binary. It is
# used to launch ffmpeg commands on a remote machine via SSH, while passing
# in any stdin from the calling environment. Its primary usecase is to enable
# a program such as Jellyfin to distribute its ffmpeg calls to remote machines
# that might be better suited to transcoding or processing ffmpeg.
#
# rffmpeg uses a configuration file, by default at `/etc/rffmpeg/rffmpeg.yml`,
# to specify a number of settings that the processes will use. This includes
# the remote system(s) to connect to, temporary directories, SSH configuration,
# and other settings.
#
###############################################################################

###############################################################################
# Imports and helper functions
###############################################################################

import os
import sys
import re
import yaml
import subprocess
from datetime import datetime

def logger(msg):
    log_to_file = config.get('log_to_file', False)
    logfile  = config.get('logfile', False)

    if log_to_file and logfile:
        with open(logfile, 'a') as logfhd:
            logfhd.write(str(datetime.now()) + ' ' + str(msg) + '\n')

###############################################################################
# Configuration parsing
###############################################################################

# Get configuration file
default_config_file = '/etc/rffmpeg/rffmpeg.yml'
config_file = os.environ.get('RFFMPEG_CONFIG', default_config_file)

# Parse the configuration
with open(config_file, 'r') as cfgfile:
    try:
        o_config = yaml.load(cfgfile, Loader=yaml.BaseLoader)
    except Exception as e:
        logger('ERROR: Failed to parse configuration file: {}'.format(e))
        exit(1)

try:
    config = {
        'state_tempdir':   o_config['rffmpeg']['state']['tempdir'],
        'state_filename':  o_config['rffmpeg']['state']['filename'],
        'state_contents':  o_config['rffmpeg']['state']['contents'],
        'log_to_file':     o_config['rffmpeg']['logging']['file'],
        'logfile':         o_config['rffmpeg']['logging']['logfile'],
        'remote_hosts':    o_config['rffmpeg']['remote']['hosts'],
        'remote_user':     o_config['rffmpeg']['remote']['user'],
        'remote_args':     o_config['rffmpeg']['remote']['args'],
        'pre_commands':    o_config['rffmpeg']['commands']['pre'],
        'ffmpeg_command':  o_config['rffmpeg']['commands']['ffmpeg'],
        'ffprobe_command': o_config['rffmpeg']['commands']['ffprobe']
    }
except Exception as e:
    logger('ERROR: Failed to load configuration: {}'.format(e))
    exit(1)

# Handle the fallback configuration using get() to avoid failing
config['fallback_ffmpeg_command'] = o_config['rffmpeg']['commands'].get('fallback_ffmpeg', config['ffmpeg_command'])
config['fallback_ffprobe_command'] = o_config['rffmpeg']['commands'].get('fallback_ffprobe', config['ffprobe_command'])

# Parse CLI args (ffmpeg command line)
all_args = sys.argv
cli_ffmpeg_args = all_args[1:]

# Get PID
our_pid = os.getpid()
current_statefile = config['state_tempdir'] + '/' + config['state_filename'].format(pid=our_pid)

logger("Starting rffmpeg {}: {}".format(our_pid, ' '.join(all_args)))

def local_ffmpeg_fallback():
    """
    Fallback call to local ffmpeg
    """
    rffmpeg_command = list()

    # Prepare our default stdin/stdout/stderr (normally, stdout to stderr)
    stdin = sys.stdin
    stdout = sys.stderr
    stderr = sys.stderr

    # Verify if we're in ffmpeg or ffprobe mode
    if 'ffprobe' in all_args[0]:
        rffmpeg_command.append(config['fallback_ffprobe_command'])
        stdout = sys.stdout
    else:
        rffmpeg_command.append(config['fallback_ffmpeg_command'])

    # Determine if version, encorders, or decoders is an argument; if so, we output stdout to stdout
    # Weird workaround for something Jellyfin requires...
    if '-version' in cli_ffmpeg_args or '-encoders' in cli_ffmpeg_args or '-decoders' in cli_ffmpeg_args:
        stdout = sys.stdout

    # Parse and re-quote any problematic arguments
    for arg in cli_ffmpeg_args:
        rffmpeg_command.append('{}'.format(arg))

    p = subprocess.run(rffmpeg_command,
                     shell=False,
                     bufsize=0,
                     universal_newlines=True,
                     stdin=stdin,
                     stderr=stderr,
                     stdout=stdout)
    returncode = p.returncode

    try:
        os.remove(current_statefile)
    except FileNotFoundError:
        pass

    logger("Finished rffmpeg {} (local failover mode) with return code {}".format(our_pid, returncode))
    exit(returncode)

def get_target_host():
    """
    Determine the optimal target host
    """
    logger("Determining target host")

    # Ensure the state directory exists or create it
    if not os.path.exists(config['state_tempdir']):
        os.makedirs(config['state_tempdir'])

    # Check for existing state files
    state_files = os.listdir(config['state_tempdir'])

    # Read each statefile to determine which hosts are bad or in use
    bad_hosts = list()
    active_hosts = list()
    for state_file in state_files:
        with open(config['state_tempdir'] + '/' + state_file, 'r') as statefile:
            contents = statefile.readlines()
            for line in contents:
                if re.match('^badhost', line):
                    bad_hosts.append(line.split()[1])
                else:
                    active_hosts.append(line.split()[0])

    # Get the remote hosts list from the config
    remote_hosts = config['remote_hosts']

    # Remove any bad hosts from the remote_hosts list
    for host in bad_hosts:
        if host in remote_hosts:
            remote_hosts.remove(host)

    # Find out which active hosts are in use
    host_counts = dict()
    for host in remote_hosts:
        # Determine process counts in active_hosts
        count = 0
        for ahost in active_hosts:
            if host == ahost:
                count += 1
        host_counts[host] = count

    # Select the host with the lowest count (first host is parsed last)
    lowest_count = 999
    target_host = None
    for host in remote_hosts:
        if host_counts[host] < lowest_count:
            lowest_count = host_counts[host]
            target_host = host

    # Write to our state file
    with open(current_statefile, 'a') as statefile:
        statefile.write(config['state_contents'].format(host=target_host) + '\n')

    if not target_host:
        logger('Failed to find a valid target host - using local fallback instead')
        local_ffmpeg_fallback()

    return target_host

def bad_host(target_host):
    logger("Setting bad host {}".format(target_host))

    # Rewrite the statefile, removing all instances of the target_host that were added before
    with open(current_statefile, 'r+') as statefile:
        new_statefile = statefile.readlines()
        statefile.seek(0)
        for line in new_statefile:
            if target_host not in line:
                statefile.write(line)
        statefile.truncate()

    # Add the bad host to the statefile
    # This will affect this run, as well as any runs that start while this one is active; once
    # this run is finished and its statefile removed, however, the host will be retried again
    with open(current_statefile, 'a') as statefile:
        statefile.write("badhost " + config['state_contents'].format(host=target_host) + '\n')

def setup_command(target_host):
    """
    Craft the target command
    """
    logger("Crafting remote command string")

    rffmpeg_command = list()

    # Add SSH component
    rffmpeg_command.append('ssh')
    rffmpeg_command.append('-q')

    # Set our connection timeouts, in case one of several remote machines is offline
    rffmpeg_command.append('-o')
    rffmpeg_command.append('ConnectTimeout=1')
    rffmpeg_command.append('-o')
    rffmpeg_command.append('ConnectionAttempts=1')

    for arg in config['remote_args']:
        if arg:
            rffmpeg_command.append(arg)

    # Add user+host string
    rffmpeg_command.append('{}@{}'.format(config['remote_user'], target_host))
    logger("Running rffmpeg {} on {}@{}".format(our_pid, config['remote_user'], target_host))

    # Add EOSSH escape start
    rffmpeg_command.append('-T')
    rffmpeg_command.append('<<EOSSH')

    # First part of EOSSH encapsulation
    rffmpeg_cli = ' '.join(rffmpeg_command)
    rffmpeg_cli += '\n'
    rffmpeg_command = []

    # Add any pre command
    for cmd in config['pre_commands']:
        if cmd:
            rffmpeg_command.append(cmd)

    # Prepare our default stdin/stdout/stderr (normally, stdout to stderr)
    stdin = sys.stdin
    stdout = sys.stderr
    stderr = sys.stderr

    # Verify if we're in ffmpeg or ffprobe mode
    if 'ffprobe' in all_args[0]:
        rffmpeg_command.append(config['ffprobe_command'])
        stdout = sys.stdout
    else:
        rffmpeg_command.append(config['ffmpeg_command'])

    # Determine if version, encorders, or decoders is an argument; if so, we output stdout to stdout
    # Weird workaround for something Jellyfin requires...
    if '-version' in cli_ffmpeg_args or '-encoders' in cli_ffmpeg_args or '-decoders' in cli_ffmpeg_args:
        stdout = sys.stdout

    # Parse and re-quote any problematic arguments
    for arg in cli_ffmpeg_args:
        # Match bad shell characters: * ( ) whitespace
        if re.search('[*()\s|\[\]]', arg):
            rffmpeg_command.append('"{}"'.format(arg))
        else:
            rffmpeg_command.append('{}'.format(arg))

    # Inner/second part of EOSSH encapsulation
    rffmpeg_cli += ' '.join(rffmpeg_command)

    # Final part of EOSSH encapsulation
    rffmpeg_cli += '\nEOSSH\n\n'

    return rffmpeg_cli, stdin, stdout, stderr

def prepare_command():
    logger("Preparing remote command")

    target_host = get_target_host()
    rffmpeg_cli, stdin, stdout, stderr = setup_command(target_host)
    logger("Remote command for rffmpeg {}: {}".format(our_pid, rffmpeg_cli))

    return rffmpeg_cli, target_host, stdin, stdout, stderr

def run_command(rffmpeg_command, stdin, stdout, stderr):
    """
    Execute the remote command using subprocess
    """
    logger("Running remote command")

    p = subprocess.run(rffmpeg_command,
                         shell=True,
                         bufsize=0,
                         universal_newlines=True,
                         stdin=stdin,
                         stderr=stderr,
                         stdout=stdout)
    returncode = p.returncode

    return returncode


# Main process loop; executes until the ffmpeg command actually runs on a reachable host
while True:
    logger("Starting process loop")

    # Set up and execute our command
    rffmpeg_command, target_host, stdin, stdout, stderr = prepare_command()
    returncode = run_command(rffmpeg_command, stdin, stdout, stderr)

    # A returncode of 255 means that the SSH process failed; ffmpeg does not throw this return code (https://ffmpeg.org/pipermail/ffmpeg-user/2013-July/016245.html)
    if returncode == 255:
        logger("SSH failed to host {} with retcode {}: marking this host as bad and retrying".format(target_host, returncode))
        bad_host(target_host)
    else:
        # The SSH succeeded, so we can abort the loop
        break

# Remove the current statefile
try:
    os.remove(current_statefile)
except FileNotFoundError:
    pass

logger("Finished rffmpeg {} with return code {}".format(our_pid, returncode))
exit(returncode)
