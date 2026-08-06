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
BIND_ADDR="0.0.0.0:8000"
GUNICORN="/home/jon/miniconda3/bin/gunicorn"
WSGI_APP="config.wsgi:application"
WORKERS=1
TIMEOUT=120

cd "$PROJECT_DIR"

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
    kill "$PID"

    # Wait up to 10 seconds for graceful shutdown
    for i in {1..10}; do
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "BDC stopped."
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done

    # Force kill if graceful shutdown times out
    echo "Graceful shutdown timed out, force killing..."
    kill -9 "$PID" 2>/dev/null || true
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
