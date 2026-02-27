#!/usr/bin/env bash

PIDFILE="prod/gunicorn.pid"
LOGFILE="prod/gunicorn.log"
BIND="0.0.0.0:8050"
WORKERS=1
THREADS=4

usage() {
    cat <<EOF
Usage: $(basename "$0") <command>

Commands:
  start   Start the gunicorn server in the background
  reload  Gracefully reload workers (pick up new code)
  stop    Gracefully stop the running server
  status  Show server state and PID
  help    Show this message
EOF
}

cmd_start() {
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "Server already running (PID $(cat "$PIDFILE"))"
        exit 1
    fi

    nohup env OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES gunicorn dashboard:server \
        -w "$WORKERS" \
        --worker-class gthread \
        --threads "$THREADS" \
        -b "$BIND" \
        --pid "$PIDFILE" \
        --access-logfile "$LOGFILE" \
        --error-logfile "$LOGFILE" \
        >> "$LOGFILE" 2>&1 &

    echo "Server started (PID $!), listening on $BIND, logging to $LOGFILE"
}

cmd_reload() {
    if [ ! -f "$PIDFILE" ]; then
        echo "No PID file found ($PIDFILE) — is the server running?"
        exit 1
    fi

    PID=$(cat "$PIDFILE")

    if ! kill -0 "$PID" 2>/dev/null; then
        echo "Process $PID not found — removing stale PID file"
        rm -f "$PIDFILE"
        exit 1
    fi

    kill -HUP "$PID"
    echo "Reload signal sent to master (PID $PID) — workers will restart with new code"
}

cmd_stop() {
    if [ ! -f "$PIDFILE" ]; then
        echo "No PID file found ($PIDFILE) — is the server running?"
        exit 1
    fi

    PID=$(cat "$PIDFILE")

    if ! kill -0 "$PID" 2>/dev/null; then
        echo "Process $PID not found — removing stale PID file"
        rm -f "$PIDFILE"
        exit 1
    fi

    kill "$PID"
    echo "Server stopped (PID $PID)"
    rm -f "$PIDFILE"
}

cmd_status() {
    if [ ! -f "$PIDFILE" ]; then
        echo "Status: stopped (no PID file)"
        return
    fi

    PID=$(cat "$PIDFILE")

    if kill -0 "$PID" 2>/dev/null; then
        echo "Status:  running"
        echo "PID:     $PID"
        echo "Bind:    $BIND"
        echo "Log:     $LOGFILE"
    else
        echo "Status:  stopped (stale PID file — PID $PID no longer exists)"
        echo "PID file: $PIDFILE"
    fi
}

case "${1:-}" in
    start)  cmd_start ;;
    reload) cmd_reload ;;
    stop)   cmd_stop ;;
    status) cmd_status ;;
    help|--help|-h) usage ;;
    "")     echo "Error: no command given"; echo; usage; exit 1 ;;
    *)      echo "Error: unknown command '$1'"; echo; usage; exit 1 ;;
esac
