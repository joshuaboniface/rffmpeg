#!/usr/bin/env bash
set -euo pipefail   # safer defaults

# Author: Juha Leivo
# Version: 1.1.0
# Date: 2025-11-03
#
# Prevent unauthorized SSH command execution by allowing only a limited set of binaries.
#
# History
#   1.0.0 - 2025-11-02, initial version
#   1.1.0 - 2025-11-03, moved to use logging 1.0.0

# Function to log messages both to TTY and to a logfile in syslog format
# Ref logging.sh version 1.0.0
log_msg() {
    local level="$1"
    shift
    # Concatenate all arguments into a single string
    local msg="$*"

    # Map level to syslog priority
    local prio="notice"
    case "$level" in
        INFO)   prio="info" ;;
        WARN)   prio="warning" ;;
        ERROR)  prio="err" ;;
        DEBUG)  prio="debug" ;;
        *)      prio="notice"
                msg="$level $msg" ;;
    esac

    if [ -t 1 ]; then
        # Interactive TTY: print plain message without level prefix
        echo "$msg"
    else
        # Non‑interactive: send to syslog
    logger -p user.$prio -t "$(basename "$0")" "$level $msg"
    fi
}

log_debug() { log_msg DEBUG "$@"; }
log_info()  { log_msg INFO  "$@"; }
log_warn()  { log_msg WARN  "$@"; }
log_error() { log_msg ERROR "$@"; }
# ------------------------------------------------------------------
# Whitelist of absolute paths to allowed binaries
ALLOWED=(
    /usr/bin/ffmpeg
    /usr/bin/ffprobe
    /usr/local/bin/ffmpeg
    /usr/local/bin/ffprobe
    /usr/lib/jellyfin-ffmpeg/ffmpeg
    /usr/lib/jellyfin-ffmpeg/ffprobe
)

# ------------------------------------------------------------------
REQ_CMD="${SSH_ORIGINAL_COMMAND:-}"
if [[ -z "$REQ_CMD" ]]; then
    echo "You may run only: ${ALLOWED[*]}"
    exit 0
fi

# Split the command into an array preserving quoting
read -r -a ARGS <<<"$REQ_CMD"
BIN="${ARGS[0]}"

# Resolve symlinks if possible
if command -v realpath >/dev/null; then
    BIN=$(realpath -m "$BIN")
else
    BIN=$(readlink -f "$BIN" 2>/dev/null || echo "$BIN")
fi

log_debug "Checking for bin $BIN"

# Whitelist check
for ok in "${ALLOWED[@]}"; do
    if [[ "$BIN" == "$ok" ]]; then
    log_info "Running command $REQ_CMD"
        eval "exec $REQ_CMD"
    fi
done

log_error "Not allowed $REQ_CMD"
echo "ERROR: command not allowed." # For SSH to show the error on client
exit 1
