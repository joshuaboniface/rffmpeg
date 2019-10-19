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
import yaml
import subprocess

def debug(msg):
    sys.stderr.write(str(msg) + '\n')

###############################################################################
# Configuration parsing
###############################################################################

# Load config file
default_config_file = '/etc/rffmpeg/rffmpeg.yml'

# Get alternative configuration file from environment
try:
    config_file = os.environ['RFFMPEG_CONFIG']
except:
    config_file = default_config_file

# Parse the configuration
debug('Loading configuration from file "{}"'.format(config_file))
with open(config_file, 'r') as cfgfile:
    try:
        o_config = yaml.load(cfgfile)
    except Exception as e:
        debug('ERROR: Failed ot parse configuration file: {}'.format(e))
        exit(1)
try:
    config = {
        'state_tempdir':   o_config['rffmpeg']['state']['tempdir'],
        'state_filename':  o_config['rffmpeg']['state']['filename'],
        'state_contents':  o_config['rffmpeg']['state']['contents'],
        'remote_hosts':    o_config['rffmpeg']['remote']['hosts'],
        'remote_user':     o_config['rffmpeg']['remote']['user'],
        'remote_args':     o_config['rffmpeg']['remote']['args'],
        'pre_commands':    o_config['rffmpeg']['commands']['pre'],
        'ffmpeg_command':  o_config['rffmpeg']['commands']['ffmpeg'],
        'ffprobe_command': o_config['rffmpeg']['commands']['ffprobe']
    }
except Exception as e:
    debug('ERROR: Failed to load configuration: {}'.format(e))
    exit(1)

# Parse CLI args (ffmpeg command line)
all_args = sys.argv
cli_ffmpeg_args = all_args[1:]

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
our_statefile = config['state_tempdir'] + '/' + config['state_filename'].format(pid=os.getpid())
with open(our_statefile, 'w') as statefile:
    statefile.write(config['state_contents'].format(host=target_host))

###############################################################################
# Set up our remote command
###############################################################################

rffmpeg_command = list()

# Add SSH component
rffmpeg_command.append('ssh')
rffmpeg_command.append('-tt')
rffmpeg_command.append('-q')
for arg in config['remote_args']:
    if arg:
        rffmpeg_command.append(arg)

# Add user+host string
rffmpeg_command.append('{}@{}'.format(config['remote_user'], target_host))
debug("Running rffmpeg against {}@{}".format(config['remote_user'], target_host))

# Add any pre command
for cmd in config['pre_commands']:
    if cmd:
        rffmpeg_command.append(cmd)

# Verify if we're in ffmpeg or ffprobe mode
if all_args[0] == 'ffprobe':
    rffmpeg_command.append(config['ffprobe_command'])
else:
    rffmpeg_command.append(config['ffmpeg_command'])

# Parse and re-quote the arguments
for arg in cli_ffmpeg_args:
    if arg[0] != '-':
        rffmpeg_command.append('"{}"'.format(arg))
    else:
        rffmpeg_command.append('{}'.format(arg))

rffmpeg_cli = ' '.join(rffmpeg_command)
debug("rffmpeg command line: {}".format(rffmpeg_cli))

###############################################################################
# Execute the remote command
###############################################################################
p = subprocess.run(rffmpeg_command,
                     shell=False,
                     bufsize=0,
                     universal_newlines=True,
                     stdin=sys.stdin,
                     stderr=sys.stderr,
                     stdout=sys.stdout)

###############################################################################
# Cleanup
###############################################################################
os.remove(our_statefile)
exit(p.returncode)
