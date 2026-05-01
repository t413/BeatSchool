from __future__ import annotations
import os, time, logging, json, argparse, typing, flask
import comms.packet as pkt
from comms.serial_reader import SerialReader
from core.node_registry import NodeRegistry
from core.media_player import MediaPlayer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
WEBROOT = os.path.join(os.path.dirname(__file__), "webroot")

app = flask.Flask(__name__, static_folder=WEBROOT, static_url_path="")
api = flask.Blueprint('api', __name__, url_prefix='/api')

registry = NodeRegistry()
media_player: MediaPlayer | None = None   # initialised in main()
reader: SerialReader | None = None   # initialised in main()


# ---------------------------------------------------------------------------
# Routes — static
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return app.send_static_file("index.html")


# ---------------------------------------------------------------------------
# Routes — REST API
# ---------------------------------------------------------------------------

def check_serial():
    if not reader:
        return flask.jsonify({"error": "serial not connected"}), 503

@api.route("/state", methods=["GET"])
def api_nodes():
    return flask.jsonify(registry.current_state())

def _broadcast_cmd(cmd: pkt.Cmd, pyld: bytes | None = None):
    check_serial()
    assert reader
    payload = pkt.UnknownPayload(cmd=0, data=pyld) if pyld else None
    wassent = reader.send(pkt.Packet(type=cmd, payload=payload))
    return flask.jsonify({"ok": True, "sent": str(wassent)})

@api.route("/ping", methods=["POST"])
def api_ping():
    return _broadcast_cmd(pkt.Cmd.Ping, b'\x01')

@api.route("/zero", methods=["POST"])
def api_zero():
    return _broadcast_cmd(pkt.Cmd.ZERO)

@api.route("/version", methods=["POST"])
def api_version():
    return _broadcast_cmd(pkt.Cmd.Version)

@api.route("/set_state", methods=["POST"])
def api_set_state():
    check_serial()
    assert(reader)
    pyld = pkt.SetStatePayload(pkt.LedMode.Spotlight)
    data = flask.request.get_json(force=True, silent=True) or {}
    hints = typing.get_type_hints(pyld.__class__)
    for key, val in data.items():
        if hasattr(pyld, key) and key in hints:
            target_type = hints[key]
            try:
                if target_type is int and isinstance(val, str):
                    val = int(val, 0) # allow hex strings for ints
                setattr(pyld, key, target_type(val))
            except (ValueError, TypeError):
                raise ValueError(f"invalid type for {key}, expected {target_type}")
    packet = pkt.Packet(type=pyld.TYPE, payload=pyld)
    print(f"API set_state: sending {packet}")
    hex_bytes = ", ".join(f"0x{b:02x}" for b in packet.to_bytes())
    print(f"pkt binary: [{hex_bytes}]")
    reader.send(packet.to_bytes())
    return flask.jsonify({"ok": True, "sent": str(packet)})

@api.route("/play", methods=["POST"])
def api_play():
    if not media_player:
        return flask.jsonify({"error": "No song loaded"}), 400
    if media_player.play():
        return flask.jsonify({"ok": True})
    return flask.jsonify({"error": "Failed to play"}), 500

@api.route("/pause", methods=["POST"])
def api_pause():
    if not media_player:
        return flask.jsonify({"error": "No song loaded"}), 400
    if media_player.pause():
        return flask.jsonify({"ok": True})
    return flask.jsonify({"error": "Failed to pause"}), 500

@api.route("/restart", methods=["POST"])
def api_restart():
    if not media_player:
        return flask.jsonify({"error": "No song loaded"}), 400
    if media_player.restart():
        return flask.jsonify({"ok": True})
    return flask.jsonify({"error": "Failed to restart"}), 500

# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------
@api.route("/events", methods=["GET"])
def api_events():
    """
    Server-Sent Events endpoint.
    On each node update the client receives:
        event: node_update
        data: <JSON of full nodes snapshot>

    Also sends a heartbeat comment every 15s to keep the connection alive
    through proxies.
    """
    def generate():
        q = registry.subscribe()
        last_heartbeat = time.time()
        try:
            while True:
                # Block for up to 15s waiting for an update
                try:
                    import queue
                    q.get(timeout=15)
                    # Drain any queued-up updates and send one combined snapshot
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except queue.Empty:
                            break
                    snapshot = json.dumps(registry.current_state())
                    yield f"event: node_update\ndata: {snapshot}\n\n"
                    last_heartbeat = time.time()

                except Exception:
                    # Timeout — send SSE comment as keepalive
                    yield ": keepalive\n\n"
                    last_heartbeat = time.time()

        except GeneratorExit:
            pass
        finally:
            registry.unsubscribe(q)

    return flask.Response(
        flask.stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind proxy
        },
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main():
    global reader

    parser = argparse.ArgumentParser(description="RhythmClass coordinator")
    parser.add_argument("--port",  help="Serial port of ESP-Now bridge")
    parser.add_argument("--baud",  type=int, default=115200)
    parser.add_argument("--host",  default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=5000)
    parser.add_argument("--song",  help="Path to song file for beat analysis and playback")
    args = parser.parse_args()

    if reader or (os.environ.get("WERKZEUG_RUN_MAIN") != "true"):
        log.info("Reloader parent process detected, skipping serial init...")
    elif args.port:
        reader = SerialReader(args.port, args.baud, registry.update)
        reader.start()
    else: log.warning("--no-serial: running without serial port (UI development mode)")

    global media_player
    media_player = MediaPlayer(args.song)
    registry.media_player = media_player

    log.info(f"Starting Flask on {args.host}:{args.http_port}")
    app.register_blueprint(api)
    app.run(host=args.host, port=args.http_port, threaded=True, use_reloader=True)

if __name__ == "__main__":
    main()
