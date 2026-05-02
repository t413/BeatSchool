import time, threading, typing, queue
from dataclasses import dataclass, field, asdict
from comms.packet import Packet, ImuPayload
import core.controller as ctrl

PKTRATE_ALPHA = 0.995

@dataclass
class NodeState:
    nodeid: int
    pyld: ImuPayload
    packet_rate_filt: float = -1
    beat_score: float = 0.0
    streak: int = 0
    past: list[ImuPayload] = field(default_factory=list)

    @classmethod
    def new(cls, pkt: Packet) -> 'NodeState':
        if not isinstance(pkt.payload, ImuPayload):
            raise ValueError("expected ImuPayload")
        instance = cls(nodeid=pkt.from_id, pyld=pkt.payload)
        instance.update(pkt)
        return instance

    def update(self, pkt: Packet):
        if pkt.from_id != self.nodeid or not isinstance(pkt.payload, ImuPayload): return
        dt = (pkt.payload.time - self.pyld.time)
        if dt > 0.0: #prevent initial update issue
            if self.packet_rate_filt <= 0.0: #set initial value
                self.packet_rate_filt = 1.0 / dt
            else: self.packet_rate_filt = PKTRATE_ALPHA * self.packet_rate_filt + (1.0 - PKTRATE_ALPHA) / dt
        self.pyld = pkt.payload
        self.past.append(pkt.payload)
        if len(self.past) > 1000:
            self.past.pop(0)

    @staticmethod
    def pktdict(nodeid: int, pyld: typing.Any) -> dict:
        return {'nodeid': nodeid, **asdict(pyld)}

    def to_dict(self) -> dict:
        return NodeState.pktdict(self.nodeid, self.pyld)

    @property
    def last_seen(self) -> float: return self.pyld.time


class NodeRegistry:
    STALE_TIMEOUT_S = 5.0   # seconds before a node is considered offline

    def __init__(self):
        self._nodes: typing.Dict[int, NodeState] = {}
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[Packet]] = []
        self._sub_lock = threading.Lock()
        self._last_print_time = time.time()
        self.media_player = ctrl.media_player

    def _print_status(self):
        now = time.time()
        dt = now - self._last_print_time
        if dt < 1.0:
            return
        with self._lock:
            ototal = 0
            for nid, state in sorted(self._nodes.items()):
                online = (now - state.last_seen) < self.STALE_TIMEOUT_S
                ototal = ototal + 1 if online else ototal
                status = "ON" if online else "OFF"

                print(f"[{status}] 0x{nid:02x}: {state.packet_rate_filt:4.1f} Hz | {state.pyld}")
            print(f"---- {ototal}/{len(self._nodes)} online ----")
        self._last_print_time = now

    # ------------------------------------------------------------------
    # Write path (called from serial reader thread)
    # ------------------------------------------------------------------
    def update(self, pkt: Packet):
        with self._lock:
            if not isinstance(pkt.payload, ImuPayload):
                print(f"skipping non-IMU packet in registry update: {pkt}")
                return
            node = self._nodes.get(pkt.from_id)
            if node is None:
                self._nodes[pkt.from_id] = NodeState.new(pkt)
            else: node.update(pkt)

            # Scoring
        self._print_status()
        self._notify_subscribers(pkt)

    # ------------------------------------------------------------------
    # Read path (called from Flask threads)
    # ------------------------------------------------------------------
    def current_state(self) -> dict:
        with self._lock:
            result = {}
            if self.media_player:
                result['media'] = self.media_player.get_state()
            result['nodes'] = [n.to_dict() for n in self._nodes.values()]
            return result

    def get_node(self, node_id: int) -> typing.Optional[dict]:
        now = time.time()
        with self._lock:
            node = self._nodes.get(node_id)
            if node is None:
                return None
            d = asdict(node)
            d["online"] = (now - node.last_seen) < self.STALE_TIMEOUT_S
            return d

    # ------------------------------------------------------------------
    # SSE pub/sub
    # ------------------------------------------------------------------
    def subscribe(self) -> queue.Queue[Packet]:
        """Return a new queue that receives node_id ints on each update."""
        q = queue.Queue(maxsize=64)
        with self._sub_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._sub_lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def _notify_subscribers(self, pkt: Packet):
        with self._sub_lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(pkt)
                except Exception:
                    pass  # full queue: drop, subscriber will catch up
