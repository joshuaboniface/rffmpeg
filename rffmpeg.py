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

import logging
import os
import re
import signal
import subprocess
import sys

import yaml

log = logging.getLogger("rffmpeg")


###############################################################################
# Configuration parsing
###############################################################################

# Get configuration file
default_config_file = "/etc/rffmpeg/rffmpeg.yml"
config_file = os.environ.get("RFFMPEG_CONFIG", default_config_file)

# Parse the configuration
with open(config_file, "r") as cfgfile:
    try:
        o_config = yaml.load(cfgfile, Loader=yaml.BaseLoader)
    except Exception as e:
        log.error("ERROR: Failed to parse configuration file: %s", e)
        exit(1)

try:
    config = {
        "state_tempdir": o_config["rffmpeg"]["state"]["tempdir"],
        "state_filename": o_config["rffmpeg"]["state"]["filename"],
        "state_contents": o_config["rffmpeg"]["state"]["contents"],
        "log_to_file": o_config["rffmpeg"]["logging"]["file"],
        "logfile": o_config["rffmpeg"]["logging"]["logfile"],
        "remote_hosts": o_config["rffmpeg"]["remote"]["hosts"],
        "remote_user": o_config["rffmpeg"]["remote"]["user"],
        "remote_args": o_config["rffmpeg"]["remote"]["args"],
        "pre_commands": o_config["rffmpeg"]["commands"]["pre"],
        "ffmpeg_command": o_config["rffmpeg"]["commands"]["ffmpeg"],
        "ffprobe_command": o_config["rffmpeg"]["commands"]["ffprobe"],
    }
except Exception as e:
    log.error("ERROR: Failed to load configuration: %s", e)
    exit(1)

# Handle the fallback configuration using get() to avoid failing
config["ssh_command"] = o_config["rffmpeg"]["commands"].get("ssh", "ssh")
config["fallback_ffmpeg_command"] = o_config["rffmpeg"]["commands"].get("fallback_ffmpeg", config["ffmpeg_command"])
config["fallback_ffprobe_command"] = o_config["rffmpeg"]["commands"].get("fallback_ffprobe", config["ffprobe_command"])

# Parse CLI args (ffmpeg command line)
all_args = sys.argv
cli_ffmpeg_args = all_args[1:]

# Get PID
current_statefile = config["state_tempdir"] + "/" + config["state_filename"].format(pid=os.getpid())

log.info("Starting rffmpeg %s: %s", os.getpid(), " ".join(all_args))


def get_target_host():
    """
    Determine the optimal target host
    """
    log.info("Determining target host")

    # Ensure the state directory exists or create it
    if not os.path.exists(config["state_tempdir"]):
        os.makedirs(config["state_tempdir"])

    # Check for existing state files
    state_files = os.listdir(config["state_tempdir"])

    # Read each statefile to determine which hosts are bad or in use
    bad_hosts = list()
    active_hosts = list()
    for state_file in state_files:
        with open(config["state_tempdir"] + "/" + state_file, "r") as statefile:
            contents = statefile.readlines()
            for line in contents:
                if re.match("^badhost", line):
                    bad_hosts.append(line.split()[1])
                    log.info("Found bad host mark from rffmpeg process %s for host '%s'", re.findall(r"[0-9]+", state_file)[0], line.split()[1])
                else:
                    active_hosts.append(line.split()[0])
                    log.info("Found running rffmpeg process %s against host '%s'", re.findall(r"[0-9]+", state_file)[0], line.split()[0])

    # Get the remote hosts list from the config
    remote_hosts = list()
    for host in config["remote_hosts"]:
        if type(host) is str or host.get("name", None) is None:
            host_name = host
        else:
            host_name = host.get("name")

        if type(host) is str or host.get("weight", None) is None:
            host_weight = 1

        remote_hosts.append({ "name": host_name, "weight": host_weight, "count": 0, "weighted_count": 0, "bad": False })


    # Remove any bad hosts from the remote_hosts list
    for bhost in bad_hosts:
        for rhost in remote_hosts:
            if bhost == rhost["name"]:
                remote_hosts[rhost]["bad"] = True

    # Find out which active hosts are in use
    for idx, rhost in enumerate(remote_hosts):
        # Determine process counts in active_hosts
        count = 0
        for ahost in active_hosts:
            if ahost == rhost["name"]:
                count += 1
        remote_hosts[idx]["count"] = count

    # Reweight the host counts by floor dividing count by weight
    for idx, rhost in enumerate(remote_hosts):
        if rhost["bad"]:
            continue
        if rhost["weight"] > 1:
            remote_hosts[idx]["weighted_count"] = rhost["count"] // rhost["weight"]
        else:
            remote_hosts[idx]["weighted_count"] = rhost["count"]

    # Select the host with the lowest weighted count (first host is parsed last)
    lowest_count = 999
    target_host = None
    for rhost in remote_hosts:
        if rhost["weighted_count"] < lowest_count:
            lowest_count = rhost["weighted_count"]
            target_host = rhost["name"]

    if not target_host:
        log.warning("Failed to find a valid target host - using local fallback instead")
        target_host = "localhost"

    # Write to our state file
    with open(current_statefile, "a") as statefile:
        statefile.write(config["state_contents"].format(host=target_host) + "\n")

    log.info("Selected target host '%s'", target_host)
    return target_host


def bad_host(target_host):
    log.info("Setting bad host %s", target_host)

    # Rewrite the statefile, removing all instances of the target_host that were added before
    with open(current_statefile, "r+") as statefile:
        new_statefile = statefile.readlines()
        statefile.seek(0)
        for line in new_statefile:
            if target_host not in line:
                statefile.write(line)
        statefile.truncate()

    # Add the bad host to the statefile
    # This will affect this run, as well as any runs that start while this one is active; once
    # this run is finished and its statefile removed, however, the host will be retried again
    with open(current_statefile, "a") as statefile:
        statefile.write("badhost " + config["state_contents"].format(host=target_host) + "\n")


def setup_remote_command(target_host):
    """
    Craft the target command
    """
    rffmpeg_ssh_command = list()
    rffmpeg_ffmpeg_command = list()

    # Add SSH component
    rffmpeg_ssh_command.append(config["ssh_command"])
    rffmpeg_ssh_command.append("-q")

    # Set our connection timeouts, in case one of several remote machines is offline
    rffmpeg_ssh_command.append("-o")
    rffmpeg_ssh_command.append("ConnectTimeout=1")
    rffmpeg_ssh_command.append("-o")
    rffmpeg_ssh_command.append("ConnectionAttempts=1")
    rffmpeg_ssh_command.append("-o")
    rffmpeg_ssh_command.append("StrictHostKeyChecking=no")
    rffmpeg_ssh_command.append("-o")
    rffmpeg_ssh_command.append("UserKnownHostsFile=/dev/null")

    for arg in config["remote_args"]:
        if arg:
            rffmpeg_ssh_command.append(arg)

    # Add user+host string
    rffmpeg_ssh_command.append("{}@{}".format(config["remote_user"], target_host))
    log.info("Running as %s@%s", config["remote_user"], target_host)

    # Add any pre command
    for cmd in config["pre_commands"]:
        if cmd:
            rffmpeg_ffmpeg_command.append(cmd)

    # Prepare our default stdin/stdout/stderr (normally, stdout to stderr)
    stdin = sys.stdin
    stdout = sys.stderr
    stderr = sys.stderr

    # Verify if we're in ffmpeg or ffprobe mode
    if "ffprobe" in all_args[0]:
        rffmpeg_ffmpeg_command.append(config["ffprobe_command"])
        stdout = sys.stdout
    else:
        rffmpeg_ffmpeg_command.append(config["ffmpeg_command"])

    # Determine if version, encorders, or decoders is an argument; if so, we output stdout to stdout
    # Weird workaround for something Jellyfin requires...
    if "-version" in cli_ffmpeg_args or "-encoders" in cli_ffmpeg_args or "-decoders" in cli_ffmpeg_args:
        stdout = sys.stdout

    # Parse and re-quote any problematic arguments
    for arg in cli_ffmpeg_args:
        # Match bad shell characters: * ( ) whitespace
        if re.search("[*()\s|\[\]]", arg):
            rffmpeg_ffmpeg_command.append('"{}"'.format(arg))
        else:
            rffmpeg_ffmpeg_command.append("{}".format(arg))

    return rffmpeg_ssh_command, rffmpeg_ffmpeg_command, stdin, stdout, stderr


def run_command(rffmpeg_ssh_command, rffmpeg_ffmpeg_command, stdin, stdout, stderr):
    """
    Execute the command using subprocess
    """
    rffmpeg_command = rffmpeg_ssh_command + rffmpeg_ffmpeg_command
    p = subprocess.run(
        rffmpeg_command, shell=False, bufsize=0, universal_newlines=True, stdin=stdin, stderr=stderr, stdout=stdout
    )
    returncode = p.returncode

    return returncode


def run_local_ffmpeg():
    """
    Fallback call to local ffmpeg
    """
    rffmpeg_ffmpeg_command = list()

    # Prepare our default stdin/stdout/stderr (normally, stdout to stderr)
    stdin = sys.stdin
    stdout = sys.stderr
    stderr = sys.stderr

    # Verify if we're in ffmpeg or ffprobe mode
    if "ffprobe" in all_args[0]:
        rffmpeg_ffmpeg_command.append(config["fallback_ffprobe_command"])
        stdout = sys.stdout
    else:
        rffmpeg_ffmpeg_command.append(config["fallback_ffmpeg_command"])

    # Determine if version, encorders, or decoders is an argument; if so, we output stdout to stdout
    # Weird workaround for something Jellyfin requires...
    specials = ["-version", "-encoders", "-decoders", "-hwaccels"]
    if any(item in specials for item in cli_ffmpeg_args):
        stdout = sys.stdout

    # Parse and re-quote any problematic arguments
    for arg in cli_ffmpeg_args:
        rffmpeg_ffmpeg_command.append("{}".format(arg))

    log.info("Local command: %s", " ".join(rffmpeg_ffmpeg_command))

    return run_command([], rffmpeg_ffmpeg_command, stdin, stdout, stderr)


def run_remote_ffmpeg(target_host):
    rffmpeg_ssh_command, rffmpeg_ffmpeg_command, stdin, stdout, stderr = setup_remote_command(target_host)
    log.info("Remote command: %s '%s'", " ".join(rffmpeg_ssh_command), " ".join(rffmpeg_ffmpeg_command))

    return run_command(rffmpeg_ssh_command, rffmpeg_ffmpeg_command, stdin, stdout, stderr)


def cleanup(signum="", frame=""):
    # Remove the current statefile
    try:
        os.remove(current_statefile)
    except FileNotFoundError:
        pass


def main():
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGQUIT, cleanup)
    signal.signal(signal.SIGHUP, cleanup)

    log_to_file = config.get("log_to_file", False)
    if log_to_file:
        logfile = config.get("logfile")
        logging.basicConfig(
            filename=logfile, level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    log.info("Starting rffmpeg PID %s", os.getpid())

    # Main process loop; executes until the ffmpeg command actually runs on a reachable host
    returncode = 1
    while True:
        target_host = get_target_host()
        if target_host == "localhost":
            returncode = run_local_ffmpeg()
            break
        else:
            returncode = run_remote_ffmpeg(target_host)

            # A returncode of 255 means that the SSH process failed;
            # ffmpeg does not throw this return code (https://ffmpeg.org/pipermail/ffmpeg-user/2013-July/016245.html)
            if returncode == 255:
                log.info(
                    "SSH failed to host %s with retcode %s: marking this host as bad and retrying",
                    target_host,
                    returncode,
                )
                bad_host(target_host)
            else:
                # The SSH succeeded, so we can abort the loop
                break

    cleanup()
    if returncode == 0:
        log.info("Finished rffmpeg PID %s with return code %s", os.getpid(), returncode)
    else:
        log.error("Finished rffmpeg PID %s with return code %s", os.getpid(), returncode)
    exit(returncode)


if __name__ == "__main__":
    main()
