#!/usr/bin/env python3
"""limited-wrapper.py

Author: GPT-OSS:120b
Version: 1.1.0
Date: 2025-11-03

Python 3 implementation of the limited-wrapper.sh script.
It restricts SSH command execution to a whitelist of allowed binaries
and logs activity either to the console (interactive) or to syslog.

History
   1.0.0 - 2025-11-03, initial version

"""

import os
import sys
import shlex
import logging
import logging.handlers
from typing import List

# ---------------------------------------------------------------------------
# Logging utilities
# ---------------------------------------------------------------------------

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("limited-wrapper.py")
    logger.setLevel(logging.DEBUG)  # Capture all levels; handlers will filter
    # Ensure no duplicate handlers if the module is reloaded
    logger.handlers.clear()

    if sys.stdout.isatty():
        # Interactive TTY – simple console output without timestamp or level prefix
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(console)
    else:
        # Non‑interactive – forward to syslog. Let syslog generate its own timestamp,
        # hostname, and program identifier (the logger name). No extra formatter is
        # needed to avoid adding the PID or duplicate timestamps.
        try:
            syslog = logging.handlers.SysLogHandler(address="/dev/log")
        except OSError:
            # Fallback for systems without /dev/log (e.g., macOS)
            syslog = logging.handlers.SysLogHandler(address=("localhost", 514))
        syslog.setLevel(logging.DEBUG)
        # Prefix with logger name (script tag) to match original format
        syslog.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logger.addHandler(syslog)
    return logger

_logger = _setup_logger()


def log_msg(level: str, *msg: str) -> None:
    """Log a message with an explicit level prefix.

    The original Bash implementation prefixed the log line with the level
    (e.g. ``DEBUG`` or ``INFO``) before sending it to syslog. To preserve that
    format we construct ``full_msg = f"{level.upper()} {text}"`` and log the
    resulting string. This ensures syslog entries look like:
    ``limited-wrapper.sh: DEBUG <message>`` while interactive console output
    remains readable.
    """
    text = " ".join(msg)
    level = level.upper()
    full_msg = f"{level} {text}"
    if level == "DEBUG":
        _logger.debug(full_msg)
    elif level == "INFO":
        _logger.info(full_msg)
    elif level in ("WARN", "WARNING"):
        _logger.warning(full_msg)
    elif level == "ERROR":
        _logger.error(full_msg)
    else:
        _logger.info(full_msg)


def log_debug(*msg: str) -> None:
    log_msg("DEBUG", *msg)


def log_info(*msg: str) -> None:
    log_msg("INFO", *msg)


def log_warn(*msg: str) -> None:
    log_msg("WARN", *msg)


def log_error(*msg: str) -> None:
    log_msg("ERROR", *msg)

# ---------------------------------------------------------------------------
# Whitelist of absolute paths to allowed binaries
# ---------------------------------------------------------------------------
ALLOWED: List[str] = [
    "/usr/bin/ffmpeg",
    "/usr/bin/ffprobe",
    "/usr/local/bin/ffmpeg",
    "/usr/local/bin/ffprobe",
    "/usr/lib/jellyfin-ffmpeg/ffmpeg",
    "/usr/lib/jellyfin-ffmpeg/ffprobe",
]


def main() -> None:
    req_cmd = os.getenv("SSH_ORIGINAL_COMMAND", "")
    if not req_cmd:
        # No command supplied – show the whitelist and exit successfully
        print("You may run only: " + " ".join(ALLOWED))
        sys.exit(0)

    # Parse the command string respecting shell quoting (handles spaces in arguments)
    # Using shlex.split provides proper handling of quoted arguments, unlike the
    # original bash script which split on whitespace only.
    try:
        args = shlex.split(req_cmd, posix=True)
    except ValueError as e:
        log_error(f"Failed to parse SSH_ORIGINAL_COMMAND: {e}")
        print("ERROR: could not parse command.")
        sys.exit(1)

    if not args:
        log_error("Empty command after parsing.")
        print("ERROR: empty command.")
        sys.exit(1)

    bin_path = os.path.realpath(args[0])
    log_debug(f"Checking for bin {bin_path}")

    if bin_path in ALLOWED:
        log_info(f"Running command {req_cmd}")
        # Ensure the argument list uses the resolved binary path as argv[0]
        args[0] = bin_path
        # Replace the current process with the requested command without PATH lookup
        os.execv(bin_path, args)
        # execv only returns on failure
        log_error(f"Failed to exec {req_cmd}")
        sys.exit(1)
    else:
        log_error(f"Not allowed {req_cmd}")
        print("ERROR: command not allowed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
