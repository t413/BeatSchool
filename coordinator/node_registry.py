# node_registry.py
# Holds the last-known state for every node seen on the network.
# Thread-safe: serial_reader writes from its thread; Flask reads from the main thread.

import time, threading
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional

from packet import Packet, ImuPayload


@dataclass
class NodeState:
    pyld: ImuPayload
    last_seen: float = field(default_factory=time.time)
    packet_count: int = 0
    _last_print_count: int = 0
    last_pitch: float = 0.0
    last_roll: float = 0.0
    beat_score: float = 0.0
    streak: int = 0


class NodeRegistry:
    STALE_TIMEOUT_S = 5.0   # seconds before a node is considered offline

    def __init__(self):
        self._nodes: Dict[int, NodeState] = {}
        self._lock = threading.Lock()
        # Subscribers for SSE: list of queue.Queue
        self._subscribers: list = []
        self._sub_lock = threading.Lock()
        self._last_print_time = time.time()
        self.media_player = None

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

                # Calculate rate
                diff_pkts = state.packet_count - state._last_print_count
                rate = diff_pkts / dt
                state._last_print_count = state.packet_count

                print(f"[{status}] 0x{nid:02x}: {rate:4.1f} pkts/s | {state.pyld}")
            print(f"---- {ototal}/{len(self._nodes)} online ----")
        self._last_print_time = now

    # ------------------------------------------------------------------
    # Write path (called from serial reader thread)
    # ------------------------------------------------------------------
    def update(self, pkt: Packet):
        with self._lock:
            pyld = pkt.payload
            if not isinstance(pyld, ImuPayload):
                print(f"skipping non-IMU packet in registry update: {pkt}")
                return
            node = self._nodes.get(pkt.from_id)
            if node is None:
                node = NodeState(pyld=pyld)
                self._nodes[pkt.from_id] = node
            else: node.pyld = pyld
            node.last_seen = time.time()
            node.packet_count += 1

            # Scoring
            if self.media_player and self.media_player.is_playing:
                current_time = self.media_player.get_current_time()
                if self.media_player.is_near_beat(current_time):
                    dpitch = abs(pyld.pitch - node.last_pitch)
                    droll = abs(pyld.roll - node.last_roll)
                    if dpitch + droll > 1.0:  # threshold for movement
                        node.beat_score += 1
                        node.streak += 1
                    else:
                        node.streak = 0
            node.last_pitch = pyld.pitch
            node.last_roll = pyld.roll

        self._print_status()
        self._notify_subscribers(pkt.from_id)

    # ------------------------------------------------------------------
    # Read path (called from Flask threads)
    # ------------------------------------------------------------------
    def current_state(self) -> dict:
        now = time.time()
        with self._lock:
            result = {}
            if self.media_player:
                t = self.media_player.get_current_time()
                nextbeats = [b for b in self.media_player.beats if b > t]
                result['media'] = {
                    'playing': self.media_player.is_playing,
                    'next_beat': nextbeats[0] if nextbeats else None,
                    'track': self.media_player.song_path,
                    'duration': self.media_player.duration,
                    'current_time': t,
                }
            for nid, state in self._nodes.items():
                d = asdict(state)
                d["online"] = (now - state.last_seen) < self.STALE_TIMEOUT_S
                result[hex(nid)] = d
            return result

    def get_node(self, node_id: int) -> Optional[dict]:
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
    def subscribe(self):
        """Return a new queue that receives node_id ints on each update."""
        import queue
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

    def _notify_subscribers(self, node_id: int):
        with self._sub_lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(node_id)
                except Exception:
                    pass  # full queue: drop, subscriber will catch up
