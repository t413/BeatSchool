from __future__ import annotations
import time, logging, json, typing, flask
import comms.packet as pkt
from core.controller import reader, registry

log = logging.getLogger(__name__)

bp = flask.Blueprint('api', __name__, url_prefix='/api')

def configure(a: flask.Flask):
    a.register_blueprint(bp)

def check_serial():
    if not reader:
        flask.abort(503, {"error": "serial not connected"})

@bp.route("/state", methods=["GET"])
def api_nodes():
    return flask.jsonify(registry.current_state())

def _broadcast_cmd(cmd: pkt.Cmd, pyld: bytes | None = None):
    check_serial()
    assert reader
    payload = pkt.UnknownPayload(cmd=0, data=pyld) if pyld else None
    wassent = reader.send(pkt.Packet(type=cmd, payload=payload))
    return flask.jsonify({"ok": True, "sent": str(wassent)})

@bp.route("/ping", methods=["POST"])
def api_ping():
    return _broadcast_cmd(pkt.Cmd.Ping, b'\x01')

@bp.route("/zero", methods=["POST"])
def api_zero():
    return _broadcast_cmd(pkt.Cmd.ZERO)

@bp.route("/version", methods=["POST"])
def api_version():
    return _broadcast_cmd(pkt.Cmd.Version)

@bp.route("/set_state", methods=["POST"])
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

# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------
@bp.route("/events", methods=["GET"])
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

