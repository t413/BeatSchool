from __future__ import annotations
import logging
from comms.serial_reader import SerialReader
from core.node_registry import NodeRegistry
from core.media_player import MediaPlayer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

media_player = MediaPlayer()
registry = NodeRegistry()
reader: SerialReader | None = None

def init_reader(port, baud):
    global reader
    reader = SerialReader(port, baud, registry.update)
    reader.start()
