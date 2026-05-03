from __future__ import annotations
import logging, threading, pathlib, glob, random
try: import vlc #CI can't import this
except ImportError: vlc = None

from core.media_track import MediaTrack

log = logging.getLogger(__name__)

class MediaPlayer:
    def __init__(self):
        self.song_dir: str | None = None
        self.tracks: list[MediaTrack] = []
        self.current_track: MediaTrack | None = None
        self.player: vlc.MediaPlayer | None = None
        try:
            self._vlc_instance = vlc.Instance('--no-video') if vlc else None
        except Exception as exc:
            self._vlc_instance = None
            log.error(f"Failed to initialize VLC: {exc}")
        self.is_playing = False
        self._lock = threading.Lock()
        self._playback_ended_handled = False  # track if we've already called end_session

    def load_songs(self, song_dir: str):
        self.song_dir = song_dir
        self._scan_tracks()
        if self.tracks:
            log.info(f"Found {len(self.tracks)} tracks in {self.song_dir}")
            self.select_track(random.choice(self.tracks))

    def _scan_tracks(self):
        if not self.song_dir: return
        pattern = pathlib.Path(self.song_dir) / '**'
        extensions = ['*.mp3', '*.wav', '*.flac', '*.m4a', '*.aac', '*.ogg']
        for ext in extensions:
            for path in glob.glob(str(pattern / ext), recursive=True):
                track = MediaTrack(path)
                track.load_from_disk()
                self.tracks.append(track)
        log.info(f"Scanned {len(self.tracks)} tracks in {self.song_dir}")

    def select_track(self, track: str|MediaTrack, allow_analyze: bool = True, force: bool = False) -> bool:
        if isinstance(track, str):
            for t in self.tracks:
                if t.name == track:
                    track = t
                    break
        if not track or not isinstance(track, MediaTrack):
            log.error(f"Track not found: {track}")
            return False
        self.current_track = track
        log.info(f"Selected track: {track.name}")
        if (not track.analyzed or force) and allow_analyze:
            threading.Thread(target=track.analyze, daemon=True).start()
        self._load_vlc()
        return True

    def _load_vlc(self):
        if not self.current_track or not vlc:
            return
        try:
            media = self._vlc_instance.media_new_path(self.current_track.path)
            player = self._vlc_instance.media_player_new()
            player.set_media(media)
            self.player = player
        except Exception as exc:
            log.error(f"Failed to load song {self.current_track.path}: {exc}")
            self.player = None

    def play(self) -> bool:
        with self._lock:
            if self.player is None:
                return False

            # If we're at the end of playback, reset to beginning first
            current_time = self.player.get_time()
            duration_ms = self.current_track.duration * 1000 if self.current_track else 0
            if current_time >= duration_ms - 100:  # Within 100ms of end
                self.player.set_time(0)
                self._playback_ended_handled = False  # Allow restart

            if self.player.is_playing():
                self.is_playing = True
                return True

            fresh_start = (self.player.get_time() <= 0)
            result = self.player.play()
            self.is_playing = (result == 0)
            if fresh_start:
                import core.controller as ctrl
                ctrl.registry.start_session()
                self._playback_ended_handled = False  # reset flag on fresh start
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
            import core.controller as ctrl
            ctrl.registry.end_session()
            self._playback_ended_handled = True  # mark as handled
            return True

    def check_playback_end(self) -> bool:
        """
        Check if scoring session should end based on rhythm timing.
        Triggers end_session() when we pass the last beat + 1s, or 1s before song end,
        whichever comes first. Returns True if scoring end was detected and handled.
        Call periodically (e.g., from get_state).
        """
        if not self.current_track or self._playback_ended_handled:
            return False

        if self.player is None:
            return False

        # Check if track has been analyzed and has beats
        if not self.current_track.analyzed or not self.current_track.beats:
            return False

        current_time = self.get_current_time()

        # Calculate scoring end time: min(last_beat + 1s, duration - 1s)
        last_beat = self.current_track.beats[-1]
        scoring_end_time = min(last_beat + 1.0, self.current_track.duration - 1.0)

        # Trigger scoring end if we've passed the scoring end time
        if current_time >= scoring_end_time:
            with self._lock:
                self._playback_ended_handled = True
                self.is_playing = False  # Update playing state when scoring ends
                import core.controller as ctrl
                ctrl.registry.end_session()
                log.info(f"Scoring session ended at {current_time:.2f}s (last beat: {last_beat:.2f}s, scoring end: {scoring_end_time:.2f}s)")
                return True

        return False

    def get_current_time(self) -> float:
        with self._lock:
            if self.player is None:
                return 0.0
            current_ms = self.player.get_time()
            return float(current_ms / 1000.0) if current_ms >= 0 else 0.0

    def is_near_beat(self, current_time: float, tolerance: float = 0.1) -> bool:
        if not self.current_track or not self.current_track.analyzed:
            return False
        for beat in self.current_track.beats:
            if abs(current_time - beat) < tolerance:
                return True
        return False

    def get_state(self) -> dict:
        self.check_playback_end()  # detect and handle natural end-of-playback
        t = self.get_current_time()
        track = self.current_track
        return {
            'playing': self.is_playing,
            'track': track.name if track else None,
            'analyzed': track.analyzed if track else None,
            'duration': track.duration if track else None,
            'current_time': t,
        }

    def to_json(self) -> dict:
        """same as get_state but includes all tracks info. lots of data"""
        ret = self.get_state()
        ret['tracks'] = [t.to_json() for t in self.tracks]
        return ret
