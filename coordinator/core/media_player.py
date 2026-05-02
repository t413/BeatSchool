# media_player.py
# Handles song loading, beat analysis, and playback control.

from __future__ import annotations
import logging, threading, pathlib
import librosa, vlc
import madmom.features.beats as mbeats
import madmom.features.downbeats as dwnbeats
import madmom.features.onsets as onsets

log = logging.getLogger(__name__)

class MediaPlayer:
    def __init__(self):
        self.song_path: str | None = None
        self.beats: list[float] = []
        self.duration = 0.0
        self.player: vlc.MediaPlayer | None = None
        self._vlc_instance = vlc.Instance('--no-video')
        self.is_playing = False
        self._lock = threading.Lock()

    def load_song(self, song_path: str):
        self.song_path = song_path
        path = pathlib.Path(self.song_path)
        if not path.exists():
            log.error(f"Song file does not exist: {self.song_path}")
            self.song_path = None
            return
        try:
            media = self._vlc_instance.media_new_path(str(path))
            player = self._vlc_instance.media_player_new()
            player.set_media(media)
            self.player = player
        except Exception as exc:
            log.error(f"Failed to load song {self.song_path}: {exc}")
            self.song_path = None
            self.player = None

    def analyze_song(self):
        if not self.song_path:
            return
        path = pathlib.Path(self.song_path)
        try:
            # Load audio for analysis
            y, sr = librosa.load(str(path), sr=None)
            self.duration = librosa.get_duration(y=y, sr=sr)

            # Detect beats
            _, beat_positions = librosa.beat.beat_track(y=y, sr=sr)
            self.beats = librosa.frames_to_time(beat_positions, sr=sr).tolist()
            log.info(f"Loaded song: {self.song_path}, duration: {self.duration:.2f}s, beats: {len(self.beats)}")
        except Exception as e:
            log.error(f"Failed to load song {self.song_path}: {e}")
            self.beats = []
            self.duration = 0.0

        try:
            # beat / downbeat / onset stats
            proc = mbeats.DBNBeatTrackingProcessor(fps=100)
            act = mbeats.RNNBeatProcessor()(self.song_path)
            self.beats = proc(act).tolist()
            print(f"beats: {self.beats}")
            db_proc = dwnbeats.DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
            db_act = dwnbeats.RNNDownBeatProcessor()(self.song_path)
            self.downbeats = db_proc(db_act)
            print(f"downbeats: {self.downbeats}")
            on_proc = onsets.CNNOnsetProcessor()
            onset_env = on_proc.process(self.song_path)
            picker = onsets.OnsetPeakPickingProcessor()
            self.onsets = picker(onset_env)
            print(f"onsets: {self.onsets}")
        except Exception as e:
            log.error(f"Failed madmom analysis {e}")


    def play(self) -> bool:
        with self._lock:
            if self.player is None:
                return False
            if self.player.is_playing():
                self.is_playing = True
                return True
            result = self.player.play()
            self.is_playing = (result == 0)
            return self.is_playing

    def pause(self) -> bool:
        with self._lock:
            if self.player is None or not self.player.is_playing():
                return False
            self.player.pause()
            self.is_playing = False
            return True

    def restart(self) -> bool:
        with self._lock:
            if self.player is None:
                return False
            self.player.stop()
            self.player.set_time(0)
            self.is_playing = False
            return self.play()

    def get_current_time(self) -> float:
        with self._lock:
            if self.player is None:
                return 0.0
            current_ms = self.player.get_time()
            return float(current_ms / 1000.0) if current_ms >= 0 else 0.0

    def is_near_beat(self, current_time: float, tolerance: float = 0.1) -> bool:
        for beat in self.beats:
            if abs(current_time - beat) < tolerance:
                return True
        return False
