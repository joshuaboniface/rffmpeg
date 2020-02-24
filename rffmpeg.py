#!/usr/bin/env python3

# rffmpeg.py - Remote FFMPEG transcoding for Jellyfin
#
#    Copyright (C) 2019  Joshua M. Boniface <joshua@boniface.me>
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

def debug(msg):
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
        o_config = yaml.load(cfgfile)
    except Exception as e:
        print('ERROR: Failed ot parse configuration file: {}'.format(e))
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
    print('ERROR: Failed to load configuration: {}'.format(e))
    exit(1)

# Parse CLI args (ffmpeg command line)
all_args = sys.argv
cli_ffmpeg_args = all_args[1:]

# Get PID
our_pid = os.getpid()

debug("Starting rffmpeg {}: {}".format(our_pid, ' '.join(all_args)))

###############################################################################
# State parsing and target determination
###############################################################################

# Ensure the state directory exists or create it
if not os.path.exists(config['state_tempdir']):
    os.makedirs(config['state_tempdir'])

# Check for existing state files
state_files = os.listdir(config['state_tempdir'])

# Read each statefile to determine which hosts are in use
active_hosts = list()
for state_file in state_files:
    with open(config['state_tempdir'] + '/' + state_file, 'r') as statefile:
        contents = statefile.readlines()
        active_hosts.append(contents[0])

# Find out which active hosts are in use
host_counts = dict()
for host in config['remote_hosts']:
    count = 0
    for ahost in active_hosts:
        if host == ahost:
            count += 1
    host_counts[host] = count

# Select the host with the lowest count (first host is parsed last)
lowest_count = 999
target_host = None
for host in config['remote_hosts']:
    if host_counts[host] < lowest_count:
        lowest_count = host_counts[host]
        target_host = host

if not target_host:
    debug('ERROR: Failed to find a valid target host')
    exit(1)

# Set up our state file
our_statefile = config['state_tempdir'] + '/' + config['state_filename'].format(pid=our_pid)
with open(our_statefile, 'w') as statefile:
    statefile.write(config['state_contents'].format(host=target_host))

###############################################################################
# Set up our remote command
###############################################################################

rffmpeg_command = list()

# Add SSH component
rffmpeg_command.append('ssh')
rffmpeg_command.append('-q')
for arg in config['remote_args']:
    if arg:
        rffmpeg_command.append(arg)

# Add user+host string
rffmpeg_command.append('{}@{}'.format(config['remote_user'], target_host))
debug("Running rffmpeg {} on {}@{}".format(our_pid, config['remote_user'], target_host))

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
    if re.search('[*()\s]', arg):
        rffmpeg_command.append('"{}"'.format(arg))
    else:
        rffmpeg_command.append('{}'.format(arg))

rffmpeg_cli = ' '.join(rffmpeg_command)
debug("Remote command for rffmpeg {}: {}".format(our_pid, rffmpeg_cli))

###############################################################################
# Execute the remote command
###############################################################################
p = subprocess.run(rffmpeg_command,
                     shell=False,
                     bufsize=0,
                     universal_newlines=True,
                     stdin=stdin,
                     stderr=stderr,
                     stdout=stdout)

###############################################################################
# Cleanup
###############################################################################
os.remove(our_statefile)
debug("Finished rffmpeg {} with code {}".format(our_pid, p.returncode))
exit(p.returncode)
