from __future__ import annotations
import logging, pathlib, pickle, threading
import librosa

log = logging.getLogger(__name__)

class MediaTrack:
    def __init__(self, path: str):
        self.path = path
        self.analyzed = False
        self.duration = 0.0
        self.beats: list[float] = []
        self.onsets: list[float] = []
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return pathlib.Path(self.path).stem

    def to_json(self) -> dict:
        return {
            'name': self.name,
            'analyzed': self.analyzed,
            'duration': self.duration,
            'beats': self.beats,
            'onsets': self.onsets,
        }

    @property
    def cache_path(self) -> pathlib.Path:
        path = pathlib.Path(self.path)
        return path.with_suffix('.pkl')

    def load_from_disk(self) -> bool:
        if not (cache_path := self.cache_path) or not cache_path.exists():
            return False
        try:
            with open(cache_path, 'rb') as f:
                data = pickle.load(f)
            self.analyzed = data.get('analyzed', False)
            self.duration = data.get('duration', 0.0)
            self.beats = data.get('beats', [])
            self.onsets = data.get('onsets', [])
            log.info(f"Loaded cached analysis for {self.name}")
            return True
        except Exception as e:
            log.error(f"Failed to load cache for {self.path}: {e}")
            return False

    def save_to_disk(self):
        data = self.to_json()
        try:
            with open(self.cache_path, 'wb') as f:
                pickle.dump(data, f)
            log.info(f"Saved analysis cache for {self.name}")
        except Exception as e:
            log.error(f"Failed to save cache for {self.path}: {e}")

    def analyze(self):
        with self._lock:
            if self.analyzed:
                return
            path = pathlib.Path(self.path)
            if not path.exists():
                log.error(f"Song file does not exist: {self.path}")
                return
            try:
                log.info(f"Analyzing song: {self.name}")
                # Load audio for analysis
                y, sr = librosa.load(str(path), sr=None)
                self.duration = librosa.get_duration(y=y, sr=sr)

                # Detect beats with librosa first
                _, beat_positions = librosa.beat.beat_track(y=y, sr=sr)
                self.beats = librosa.frames_to_time(beat_positions, sr=sr).tolist()

                onset_env = librosa.onset.onset_strength(y=y, sr=sr)
                onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
                self.onsets = librosa.frames_to_time(onset_frames, sr=sr).tolist()

                self.analyzed = True
                self.save_to_disk()
                log.info(f"Analyzed song: {self.name}, duration: {self.duration:.2f}s, beats: {len(self.beats)}")
            except Exception as e:
                log.error(f"Failed to analyze song {self.path}: {e}")
                self.analyzed = False

