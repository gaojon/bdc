#!/bin/bash
# ============================================================================
# BDC - English Word Learning System Console Script
# Usage: ./console.sh {start|stop|restart|update}
# ============================================================================

set -e

PROJECT_DIR="/home/jon/bdc"
PROJECT_NAME="bdc"
PID_FILE="$PROJECT_DIR/.bdc.pid"
LOG_FILE="$PROJECT_DIR/.bdc.log"
BIND_ADDR="0.0.0.0:80"
PORT="${BIND_ADDR##*:}"
GUNICORN="/home/jon/miniconda3/bin/gunicorn"
WSGI_APP="config.wsgi:application"
WORKERS=1
TIMEOUT=120

cd "$PROJECT_DIR"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Return 0 (true) if something is listening on the given TCP port.
_port_in_use() {
    local port="$1"
    ss -tln 2>/dev/null | grep -q ":$port "
}

# Kill every PID currently holding the given port (returns non-zero if none).
_kill_port_holder() {
    local port="$1"
    local pids
    pids=$(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | sort -u)
    if [ -z "$pids" ]; then
        return 1
    fi
    for p in $pids; do
        kill -9 "$p" 2>/dev/null || true
    done
    sleep 1
    return 0
}

# ---------------------------------------------------------------------------
# start - Launch gunicorn in daemon mode
# ---------------------------------------------------------------------------
start() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "BDC is already running (PID: $(cat "$PID_FILE"))"
        return 1
    fi

    # Clean up stale PID file
    [ -f "$PID_FILE" ] && rm -f "$PID_FILE"

    echo "Starting BDC..."
    $GUNICORN --bind "$BIND_ADDR" \
              --workers $WORKERS \
              --timeout $TIMEOUT \
              --daemon \
              --pid "$PID_FILE" \
              --access-logfile "$LOG_FILE" \
              --error-logfile "$LOG_FILE" \
              "$WSGI_APP"

    sleep 1
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "BDC started successfully (PID: $(cat "$PID_FILE"))"
        echo "Listening on $BIND_ADDR"
    else
        echo "Failed to start BDC. Check $LOG_FILE for details."
        return 1
    fi
}

# ---------------------------------------------------------------------------
# stop - Gracefully shut down via the PID file
# ---------------------------------------------------------------------------
stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "BDC is not running (no PID file found)"
        return 1
    fi

    PID=$(cat "$PID_FILE")
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "BDC is not running (PID $PID not found). Removing stale PID file."
        rm -f "$PID_FILE"
        return 1
    fi

    echo "Stopping BDC (PID: $PID)..."
    # gunicorn --daemon calls setsid(), so the master is its own process-group
    # leader. Send SIGTERM to the whole group (negative PID) so workers shut
    # down with the master instead of being orphaned and holding the port.
    kill -- -"$PID" 2>/dev/null || kill "$PID"

    # Wait up to 10 seconds for graceful shutdown. Key: the master exiting is
    # NOT enough — the worker is a separate process and may take a moment to
    # finish in-flight requests while still holding the port. So poll until the
    # port is actually free before declaring success.
    for i in {1..10}; do
        if ! _port_in_use "$PORT"; then
            echo "BDC stopped."
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done

    # Force kill whatever still holds the port (orphaned worker etc.)
    echo "Port $PORT still in use after graceful stop, force killing..."
    _kill_port_holder "$PORT" || true
    rm -f "$PID_FILE"
    echo "BDC force stopped."
}

# ---------------------------------------------------------------------------
# restart - Stop then start
# ---------------------------------------------------------------------------
restart() {
    echo "=== Restarting BDC ==="
    stop || true   # proceed even if stop fails (e.g. not running)
    sleep 1
    start
}

# ---------------------------------------------------------------------------
# update - Stop, git pull, then start
# ---------------------------------------------------------------------------
update() {
    echo "=== Updating BDC ==="
    stop || true   # proceed even if stop fails (e.g. not running)
    sleep 1

    echo "Pulling latest code from git..."
    git pull origin master

    echo "=== Update complete, starting BDC ==="
    start
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
case "${1:-}" in
    start)   start ;;
    stop)    stop ;;
    restart) restart ;;
    update)  update ;;
    *)
        echo "Usage: $0 {start|stop|restart|update}"
        exit 1
        ;;
esac
