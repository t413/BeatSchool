from __future__ import annotations
import logging, argparse, os, datetime
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
launch_args = argparse.Namespace()

def init_reader(port, baud):
    global reader
    reader = SerialReader(port, baud, registry.update)
    reader.start()

def save_args(args: argparse.Namespace):
    global launch_args
    launch_args = args

def get_logfile_path(topic: str) -> str:
    if launch_args.logdir and not os.path.exists(launch_args.logdir):
        os.makedirs(launch_args.logdir)
    now_str = datetime.datetime.now().strftime("%y%m%d-%H%M%S")
    fname = f"{now_str}_{topic}" if "." in topic else f"{now_str}_{topic}.log"
    return os.path.join(launch_args.logdir, fname) if launch_args.logdir else fname

def get_current_logfile() -> str:
    """gets current logging system logging path"""
    import logging
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            return handler.baseFilename
    return ""
