from __future__ import annotations
import logging, threading, pathlib, glob
import vlc
from core.media_track import MediaTrack

log = logging.getLogger(__name__)

class MediaPlayer:
    def __init__(self):
        self.song_dir: str | None = None
        self.tracks: list[MediaTrack] = []
        self.current_track: MediaTrack | None = None
        self.player: vlc.MediaPlayer | None = None
        self._vlc_instance = vlc.Instance('--no-video')
        self.is_playing = False
        self._lock = threading.Lock()

    def load_songs(self, song_dir: str):
        self.song_dir = song_dir
        self._scan_tracks()
        if self.tracks:
            log.info(f"Found {len(self.tracks)} tracks in {self.song_dir}")
            self.select_track(self.tracks[0])

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
        if not self.current_track:
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
            return True

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
        if not self.current_track:
            return { 'playing': False }
        t = self.get_current_time()
        track = self.current_track
        state = {
            'playing': self.is_playing,
            'track': track.name,
            'analyzed': track.analyzed,
            'duration': track.duration,
            'current_time': t,
        }
        for attr in ['beats', 'onsets']:
            times = getattr(track, attr, [])
            future = [b for b in times if b > t]
            state[f'next_{attr[:-1]}'] = future[0] if future else None
        return state

    def to_json(self) -> dict:
        ret = self.get_state()
        ret['tracks'] = [t.to_json() for t in self.tracks]
        return ret
