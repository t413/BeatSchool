# media_player.py
# Handles song loading, beat analysis, and playback control.

from __future__ import annotations
import pygame, librosa, threading, time, logging

log = logging.getLogger(__name__)

class MediaPlayer:
    def __init__(self, song_path: str | None):
        self.song_path = song_path
        self.beats = []  # list of beat times in seconds
        self.duration = 0.0
        self.is_playing = False
        self.start_time = 0.0
        self.paused_time = 0.0
        self._lock = threading.Lock()

        if song_path:
            self._load_song()

    def _load_song(self):
        if not self.song_path:
            return
        try:
            # Load audio for analysis
            y, sr = librosa.load(self.song_path)
            self.duration = librosa.get_duration(y=y, sr=sr)

            # Detect beats
            tempo, beat_positions = librosa.beat.beat_track(y=y, sr=sr)
            self.beats = librosa.frames_to_time(beat_positions, sr=sr).tolist()
            log.info(f"Loaded song: {self.song_path}, duration: {self.duration:.2f}s, beats: {len(self.beats)}")

            # Init pygame mixer
            pygame.mixer.init()
            pygame.mixer.music.load(self.song_path)
        except Exception as e:
            log.error(f"Failed to load song {self.song_path}: {e}")
            self.song_path = None

    def play(self):
        with self._lock:
            if not self.song_path:
                return False
            if self.is_playing:
                return True
            pygame.mixer.music.play()
            self.is_playing = True
            self.start_time = time.time() - self.paused_time
            self.paused_time = 0.0
            return True

    def pause(self):
        with self._lock:
            if not self.is_playing:
                return False
            pygame.mixer.music.pause()
            self.is_playing = False
            self.paused_time = time.time() - self.start_time
            return True

    def restart(self):
        with self._lock:
            if not self.song_path:
                return False
            pygame.mixer.music.stop()
            self.is_playing = False
            self.paused_time = 0.0
            self.start_time = 0.0
            return self.play()

    def get_current_time(self):
        with self._lock:
            if not self.is_playing:
                return self.paused_time
            return time.time() - self.start_time

    def is_near_beat(self, current_time: float, tolerance: float = 0.1) -> bool:
        for beat in self.beats:
            if abs(current_time - beat) < tolerance:
                return True
        return False
