from __future__ import annotations
import logging, json, typing, flask, queue
import comms.packet as pkt
import core.controller as ctrl
from core.node_registry import NodeState

log = logging.getLogger(__name__)

bp = flask.Blueprint('api', __name__, url_prefix='/api')

def configure(a: flask.Flask):
    a.register_blueprint(bp)

def check_serial():
    if not ctrl.reader:
        flask.abort(503, {"error": "serial not connected"})

@bp.route("/state", methods=["GET"])
def api_nodes():
    return flask.jsonify(ctrl.registry.current_state())

def _broadcast_cmd(cmd: pkt.Cmd, pyld: bytes | None = None):
    check_serial()
    assert ctrl.reader
    payload = pkt.UnknownPayload(cmd=0, data=pyld) if pyld else None
    wassent = ctrl.reader.send(pkt.Packet(type=cmd, payload=payload))
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
    assert(ctrl.reader)
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
    ctrl.reader.send(packet.to_bytes())
    return flask.jsonify({"ok": True, "sent": str(packet)})

# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

MEDIA_ALWAYS_UPDATE_T = 2.0

def _build_sse_update(pktq: queue.Queue[pkt.Packet], scoreq: queue.Queue[dict], lastmedia: dict) -> tuple[dict, dict]:
    # first empty queues:
    timeout = 0.2 if ctrl.media_player.is_playing else 2.0
    pkts = []
    try:
        pkts = [pktq.get(timeout=timeout)]
    except queue.Empty:
        pass
    while not pktq.empty(): pkts.append(pktq.get_nowait()) #drain remaining
    score_events = []
    while not scoreq.empty(): score_events.append(scoreq.get_nowait())

    # now build update dict
    update: dict = {
        'updates': [NodeState.pktdict(p.from_id, p.payload) for p in pkts],
        'scores': score_events,
        'state': ctrl.get_system_state(),
    }

    track = ctrl.media_player.current_track
    needs_update  = lastmedia.get('playing')  != ctrl.media_player.is_playing
    needs_update |= lastmedia.get('track')    != (track.name if track else None)
    needs_update |= lastmedia.get('analyzed') != (track.analyzed if track else None)
    dt = ctrl.media_player.get_current_time() - lastmedia.get('current_time', -1000)
    if needs_update or dt > MEDIA_ALWAYS_UPDATE_T:
        print(f"media update after {dt:.2f}s and needs_update={needs_update}")
        mstatus = ctrl.media_player.get_state()
        update['media'] = mstatus
        lastmedia = mstatus
    return update, lastmedia


@bp.route("/events", methods=["GET"])
def api_events():
    def generate():
        q = ctrl.registry.subscribe()
        score_q = ctrl.registry.subscribe_scores()
        try:
            last_media_sts = {} #help detect important state chaging
            while True:
                try:
                    update, last_media_sts = _build_sse_update(q, score_q, last_media_sts)
                    snapshot = json.dumps(update)
                    yield f"event: node_update\ndata: {snapshot}\n\n"
                except queue.Empty:
                    snapshot = json.dumps(ctrl.registry.current_state())
                    yield f"event: node_update\ndata: {snapshot}\n\n"
        except GeneratorExit:
            pass
        finally:
            ctrl.registry.unsubscribe(q)
            ctrl.registry.unsubscribe_scores(score_q)

    return flask.Response(
        flask.stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind proxy
        },
    )
