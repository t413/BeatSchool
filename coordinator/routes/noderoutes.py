from __future__ import annotations
import logging, json, typing, flask, time
import comms.packet as pkt
from core.controller import reader, registry, media_player
from core.node_registry import NodeState

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

def _build_sse_update(pkts: list, score_events: list, media_player, registry, last_media_update: float) -> tuple[dict, float]:
    """Build SSE update dict and return new last_media_update time."""
    update: dict = {}

    if pkts:
        update['updates'] = [NodeState.pktdict(p.from_id, p.payload) for p in pkts]

    if score_events:
        update['scores'] = score_events

    now = time.time()
    if (now - last_media_update) > 2:
        update['media'] = media_player.get_state()
        last_media_update = now

    return update, last_media_update


def _collect_sse_events(q, score_q, media_player) -> tuple[list, list]:
    """Collect packets and score events from queues with timeout."""
    import queue as queue_module

    timeout = 0.2 if media_player.is_playing else 2.0
    pkts = []

    try:
        pkts = [q.get(timeout=timeout)]
    except queue_module.Empty:
        pass

    # Get additional packets without blocking
    while not q.empty():
        try:
            pkts.append(q.get_nowait())
        except queue_module.Empty:
            break

    # Get all score events
    score_events = []
    while not score_q.empty():
        try:
            score_events.append(score_q.get_nowait())
        except queue_module.Empty:
            break

    return pkts, score_events


@bp.route("/events", methods=["GET"])
def api_events():
    def generate():
        q = registry.subscribe()
        score_q = registry.subscribe_scores()
        try:
            import queue as queue_module, time
            last_media_update = 0
            while True:
                try:
                    pkts, score_events = _collect_sse_events(q, score_q, media_player)

                    if pkts or score_events or (time.time() - last_media_update) > 2:
                        update, last_media_update = _build_sse_update(
                            pkts, score_events, media_player, registry, last_media_update
                        )
                        if update:
                            snapshot = json.dumps(update)
                            yield f"event: node_update\ndata: {snapshot}\n\n"
                    else:
                        # Timeout with no data - send full update
                        snapshot = json.dumps(registry.current_state())
                        yield f"event: node_update\ndata: {snapshot}\n\n"
                except queue_module.Empty:
                    snapshot = json.dumps(registry.current_state())
                    yield f"event: node_update\ndata: {snapshot}\n\n"
        except GeneratorExit:
            pass
        finally:
            registry.unsubscribe(q)
            registry.unsubscribe_scores(score_q)

    return flask.Response(
        flask.stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind proxy
        },
    )

