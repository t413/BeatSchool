"""
scoring_session.py
──────────────────
Real-time IMU movement scoring for a 10-player rhythm game.

OVERVIEW
────────
Each Session ingests pitch/roll packets in real-time (update()), stores every
sample per player, and periodically computes ScoreSnapshots across several axes:

  beat_half    — half-time  (one motion cycle per 2 beats)
  beat_single  — on the beat
  beat_double  — double-time / 8th notes
  beat_triple  — triplet feel
  beat_quad    — 16th notes / quad time
  amplitude    — normalized RMS displacement (effort / expressiveness)
  consistency  — how stable the motion is within the window
  onset_lock   — how well peaks align to actual musical onsets (bonus axis)

CORE IDEA: PHASE COHERENCE (Rayleigh statistic)
────────────────────────────────────────────────
For each beat subdivision we ask: "do motion events fall at consistent
positions within that grid period?" We detect motion events (displacement
peaks / direction-change moments) and compute:

    R = |mean( exp(i·2π·(t_event mod T) / T) )|   for each grid period T

R → 1  : events cluster at a consistent beat phase  → high score
R → 0  : events are random relative to the grid    → low score

This is robust to tempo changes and doesn't care whether the dancer is
on the downbeat or the upbeat — it rewards *consistency* with any subdivision.

SUBDIVISION DISAMBIGUATION
──────────────────────────
Phase coherence alone can't tell half-time from single-time because a
half-time dancer (1 event per 2 beats) will ALSO show coherence at the
single-time grid (events land consistently at the "& " of each bar).
We resolve this by also tracking events_per_beat and comparing it to
each subdivision's expected rate, then weighting the coherence score
accordingly. The `dominant` field reflects this.

DERIVATIVE ESTIMATION
──────────────────────
Simple 3-point backward differences are used for real-time vel/acc/jerk.
For offline re-scoring (score_all) we use Savitzky-Golay over the full
sample buffer, which is much smoother. If your sensor rate is < 20 Hz,
consider increasing SG_WINDOW_SAMPLES.

USAGE
──────
    sess = ScoringSession(beat_times, onset_times)

    # In your receive loop:
    for pkt in stream:
        sess.update(playback_time, pkt)

    # End of song:
    sess.score_all()          # cleaner offline re-score
    sess.save("session.pkl")

    # Plotting:
    t, scores = sess.score_timeline(node_id=3, axis="beat_double")
"""

from __future__ import annotations
import pickle, typing, datetime, logging
from dataclasses import dataclass, asdict
import numpy as np
from scipy.signal import find_peaks, savgol_filter

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Sample:
    """One stored sample with raw and derived signal values."""
    t:           float   # playback time (seconds)
    pitch:       float   # degrees
    roll:        float   # degrees
    # ── Derived (filled during push / score_all) ──
    vel_pitch:   float = 0.0   # deg/s
    vel_roll:    float = 0.0   # deg/s
    acc_pitch:   float = 0.0   # deg/s²
    acc_roll:    float = 0.0   # deg/s²
    jerk:        float = 0.0   # deg/s³ magnitude
    motion_energy: float = 0.0  # |angular velocity| magnitude (deg/s)


@dataclass
class ScoreSnapshot:
    """
    One scored moment for a single player.
    All beat scores are in [0, 1] — higher = better alignment.
    Stored in PlayerBuffer.score_history for plotting.
    """
    t:            float
    beat_half:    float = 0.0   # half-time   (×0.5 beat events)
    beat_single:  float = 0.0   # on the beat (×1)
    beat_double:  float = 0.0   # double-time (×2)
    beat_triple:  float = 0.0   # triplet     (×3)
    beat_quad:    float = 0.0   # 16th-note   (×4)
    amplitude:    float = 0.0   # normalized RMS displacement
    consistency:  float = 0.0   # amplitude regularity
    onset_lock:   float = 0.0   # alignment to musical onsets
    dominant:     str   = "—"   # best-fit subdivision label
    #TODO ideas: sharpness vs smoothness (two scores), circle pattern matching


# Subdivision name → events-per-beat multiplier
# (how many motion events a player in this style produces per beat)
SUBDIVISIONS: dict[str, float] = {
    "beat_half":   0.5,   # one motion cycle every 2 beats
    "beat_single": 1.0,
    "beat_double": 2.0,
    "beat_triple": 3.0,
    "beat_quad":   4.0,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Beat-grid utilities
# ═══════════════════════════════════════════════════════════════════════════════

def local_beat_period(t: float, beat_times: np.ndarray) -> float:
    """
    Interpolate the beat-period (seconds/beat) at playback time t,
    using the nearest pair of beat grid points.
    Falls back to median period if out of range.
    """
    if len(beat_times) < 2:
        return 0.5  # 120 BPM fallback
    idx = int(np.searchsorted(beat_times, t))
    idx = np.clip(idx, 1, len(beat_times) - 1)
    return float(beat_times[idx] - beat_times[idx - 1])


def beats_in_range(t0: float, t1: float, beat_times: np.ndarray) -> int:
    """Count how many beat grid points fall in [t0, t1]."""
    return int(np.sum((beat_times >= t0) & (beat_times <= t1)))


def phase_coherence(event_times: np.ndarray, grid_period: float) -> float:
    """
    Rayleigh statistic: how consistently do events cluster within a
    repeating grid of `grid_period` seconds?

    Returns 0 (events randomly distributed) → 1 (perfect beat lock).

    Requires at least 2 events; returns 0 otherwise.
    """
    if len(event_times) < 2 or grid_period <= 0:
        return 0.0
    phases = (event_times % grid_period) / grid_period * 2.0 * np.pi
    R = float(np.abs(np.mean(np.exp(1j * phases))))
    return R


def beat_score_weighted(
    events: np.ndarray,
    window_sec: float,
    beat_times: np.ndarray,
    mid_t: float,
) -> dict[str, float]:
    """
    Compute phase-coherence scores for each subdivision AND weight them
    by how close the observed events-per-beat ratio is to the expected
    rate for that subdivision.

    Weighting prevents half-time from scoring equally to single-time just
    because both are internally consistent.
    """
    n_beats = max(1, beats_in_range(mid_t - window_sec / 2,
                                     mid_t + window_sec / 2, beat_times))
    base_period = local_beat_period(mid_t, beat_times)
    n_events = len(events)
    events_per_beat = n_events / n_beats if n_beats > 0 else 0.0

    scores: dict[str, float] = {}
    for key, epb_expected in SUBDIVISIONS.items():
        # Grid period for this subdivision
        grid_period = base_period / epb_expected  # seconds per grid slot

        coherence = phase_coherence(events, grid_period)

        # Rate weight: 1 when observed rate matches expected, tapers off
        if epb_expected > 0:
            rate_ratio = events_per_beat / epb_expected
            # Gaussian in log-ratio space; ±1 octave = ~0.6 weight
            rate_weight = float(np.exp(-0.5 * (np.log2(rate_ratio + 1e-6)) ** 2))
        else:
            rate_weight = 0.0

        scores[key] = float(coherence * rate_weight)

    return scores


# ═══════════════════════════════════════════════════════════════════════════════
# Motion event detection
# ═══════════════════════════════════════════════════════════════════════════════

def detect_displacement_peaks(
    samples: list[Sample],
    min_prominence: float = 1.5,
    min_distance_ms: float = 80.0,
) -> np.ndarray:
    """
    Find times of displacement extrema (direction-change moments).

    Uses |combined_angle| = sqrt(pitch² + roll²).  These are instants where
    the dancer has fully committed to a direction and is about to reverse —
    the perceptual "hit" of a motion.

    min_prominence : degrees — ignore small wiggles below this threshold.
    min_distance_ms: minimum time between peaks in milliseconds.
    """
    if len(samples) < 5:
        return np.array([])

    ts     = np.array([s.t for s in samples])
    angles = np.hypot(
        np.array([s.pitch for s in samples]),
        np.array([s.roll  for s in samples])
    )

    dt_mean = float(np.mean(np.diff(ts))) if len(ts) > 1 else 0.02
    min_distance_samples = max(2, int((min_distance_ms / 1000.0) / dt_mean))

    peak_idxs, _ = find_peaks(
        angles,
        prominence=min_prominence,
        distance=min_distance_samples,
    )
    return ts[peak_idxs]


def detect_velocity_peaks(
    samples: list[Sample],
    min_prominence: float = 5.0,
) -> np.ndarray:
    """
    Find times of maximum angular velocity magnitude (energy peaks).

    These occur at displacement zero-crossings for sinusoidal motion, i.e.
    when the dancer is passing through center at maximum speed — the "groove"
    moment in many dance styles.

    Useful as an alternative event detector; try both and pick the one with
    higher coherence scores.
    """
    if len(samples) < 5:
        return np.array([])

    ts      = np.array([s.t for s in samples])
    energies = np.array([s.motion_energy for s in samples])

    peak_idxs, _ = find_peaks(energies, prominence=min_prominence)
    return ts[peak_idxs]


# ═══════════════════════════════════════════════════════════════════════════════
# Player buffer
# ═══════════════════════════════════════════════════════════════════════════════

# Savitzky-Golay params for offline derivative smoothing
SG_WINDOW_SAMPLES = 9    # must be odd; increase if sensor rate < 30 Hz
SG_POLY_ORDER     = 3


class PlayerBuffer:
    """
    Per-player sample store and derivative computation.

    Online (push):     fast backward-difference derivatives for real-time use.
    Offline (smooth):  Savitzky-Golay over full buffer for cleaner scoring.
    """

    def __init__(self, node_id: int):
        self.node_id      = node_id
        self.samples:       list[Sample]        = []
        self.score_history: list[ScoreSnapshot] = []

    # ── Ingestion ──────────────────────────────────────────────────────────

    def push(self, t: float, pitch: float, roll: float) -> Sample:
        """Append one sample and compute incremental derivatives."""
        s = Sample(t=t, pitch=pitch, roll=roll)

        if len(self.samples) >= 1:
            p = self.samples[-1]
            dt = t - p.t
            if dt > 1e-6:
                s.vel_pitch = (pitch - p.pitch) / dt
                s.vel_roll  = (roll  - p.roll)  / dt

        if len(self.samples) >= 2:
            p = self.samples[-1]
            dt = t - p.t
            if dt > 1e-6:
                s.acc_pitch = (s.vel_pitch - p.vel_pitch) / dt
                s.acc_roll  = (s.vel_roll  - p.vel_roll)  / dt

        if len(self.samples) >= 3:
            p = self.samples[-1]
            dt = t - p.t
            if dt > 1e-6:
                dacc = np.hypot(s.acc_pitch - p.acc_pitch, s.acc_roll - p.acc_roll)
                s.jerk = dacc / dt

        s.motion_energy = np.hypot(s.vel_pitch, s.vel_roll)
        self.samples.append(s)
        return s

    def smooth_derivatives(self) -> None:
        """
        (Re)compute vel/acc/jerk/energy for all samples using Savitzky-Golay.
        Call this after recording is done for cleaner offline scoring.
        """
        n = len(self.samples)
        if n < SG_WINDOW_SAMPLES:
            return

        ts     = np.array([s.t     for s in self.samples])
        pitches = np.array([s.pitch for s in self.samples])
        rolls   = np.array([s.roll  for s in self.samples])

        # Uniform-time SG: compute derivative in index space then divide by dt
        dt_mean = float(np.mean(np.diff(ts)))

        def sg_deriv(arr: np.ndarray, order: int) -> np.ndarray:
            return savgol_filter(arr, SG_WINDOW_SAMPLES, SG_POLY_ORDER,
                                 deriv=order, delta=dt_mean)

        vp = sg_deriv(pitches, 1)
        vr = sg_deriv(rolls,   1)
        ap = sg_deriv(pitches, 2)
        ar = sg_deriv(rolls,   2)
        jp = sg_deriv(pitches, 3)
        jr = sg_deriv(rolls,   3)

        for i, s in enumerate(self.samples):
            s.vel_pitch    = float(vp[i])
            s.vel_roll     = float(vr[i])
            s.acc_pitch    = float(ap[i])
            s.acc_roll     = float(ar[i])
            s.jerk         = float(np.hypot(jp[i], jr[i]))
            s.motion_energy = float(np.hypot(vp[i], vr[i]))

    # ── Windowing ──────────────────────────────────────────────────────────

    def window(self, up_to_t: float, duration: float) -> list[Sample]:
        """Return samples in (up_to_t - duration, up_to_t]."""
        t0 = up_to_t - duration
        return [s for s in self.samples if t0 < s.t <= up_to_t]


# ═══════════════════════════════════════════════════════════════════════════════
# Scoring session
# ═══════════════════════════════════════════════════════════════════════════════

class ScoringSession:
    """
    One full game session.

    Parameters
    ──────────
    beat_times      : np.ndarray
        Times (seconds) of individual beats from librosa.beat.beat_track()
        or derived by subdividing downbeats.  This is the primary rhythm grid.

    onset_times     : np.ndarray
        Musical onset times from librosa.onset.onset_detect().
        Used for the bonus `onset_lock` score.

    session_id      : str (optional)
        Human-readable ID; auto-generated from timestamp if omitted.

    metadata        : dict (optional)
        Song name, BPM, time signature, etc.  Saved in the pkl.
    """

    # ── Tuning knobs ──────────────────────────────────────────────────────
    SCORE_INTERVAL     = 2.0    # seconds between score snapshots
    SCORE_WINDOW       = 8.0    # seconds of history used per score
    MIN_PEAK_PROM      = 0.5    # degrees — min prominence for displacement peak
    MIN_VEL_PROM       = 1.0    # deg/s   — min prominence for velocity peak
    ONSET_LOCK_WINDOW  = 0.06   # ±60 ms tolerance window for onset alignment
    AMPLITUDE_MIDPOINT = 15.0   # degrees where tanh(amplitude) = 0.76
    # ─────────────────────────────────────────────────────────────────────

    def __init__(
        self,
        beat_times:      np.ndarray | list[float],
        onset_times:     np.ndarray | list[float],
        session_id:      typing.Optional[str]  = None,
        metadata:        typing.Optional[dict] = None,
    ):
        self.beat_times      = np.asarray(beat_times,      dtype=float)
        self.onset_times     = np.asarray(onset_times,     dtype=float)
        self.session_id      = session_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.metadata        = metadata or {}
        self.created_at      = datetime.datetime.now().isoformat()

        self.players: dict[int, PlayerBuffer] = {}
        self._last_score_t: dict[int, float]  = {}   # node_id → last scored time

    # ══════════════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════════════

    def update(self, playback_time: float, nodeid: int, pitch: float, roll: float) -> None:
        """Adds a new sample, called from receive loop"""
        if nodeid not in self.players:
            self.players[nodeid] = PlayerBuffer(nodeid)

        buf = self.players[nodeid]
        buf.push(playback_time, pitch, roll)

        last = self._last_score_t.get(nodeid, -(self.SCORE_INTERVAL + self.SCORE_WINDOW))
        if playback_time - last >= self.SCORE_INTERVAL:
            snap = self._score_window(buf, playback_time, smooth=False)
            buf.score_history.append(snap)
            self._last_score_t[nodeid] = playback_time
            log.info(f"scored at {playback_time:.2f}s with {len(buf.score_history)} scores -> {asdict(snap)}")

    def score_all(self, smooth: bool = True) -> None:
        """
        Full offline re-score of every player across the whole session.
        Replaces any real-time snapshots with cleaner Savitzky-Golay scores.
        Call at end of session before saving.

        smooth=True  : re-derive vel/acc/jerk with SG filter first.
        smooth=False : use whatever derivatives were computed in real-time.
        """
        for buf in self.players.values():
            if len(buf.samples) < 10:
                continue
            if smooth:
                buf.smooth_derivatives()

            t_start = buf.samples[0].t  + self.SCORE_WINDOW
            t_end   = buf.samples[-1].t
            buf.score_history = []

            t = t_start
            while t <= t_end:
                snap = self._score_window(buf, t, smooth=True)
                buf.score_history.append(snap)
                t += self.SCORE_INTERVAL

    def save(self, path: str) -> None:
        """Pickle the entire session (all samples + scores) to disk."""
        with open(path, "wb") as fh:
            pickle.dump(self, fh, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"Session saved → {path}  "
              f"({len(self.players)} players, "
              f"{sum(len(b.samples) for b in self.players.values())} total samples)")

    @classmethod
    def load(cls, path: str) -> "ScoringSession":
        """Load a pickled session from disk."""
        with open(path, "rb") as fh:
            return pickle.load(fh)

    # ── Querying ──────────────────────────────────────────────────────────

    def score_timeline(
        self, node_id: int, axis: str
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Return (times, scores) for a given scoring axis and player.
        Useful for plotting a single score axis over time.

        axis: one of beat_half, beat_single, beat_double, beat_triple,
              beat_quad, amplitude, consistency, onset_lock
        """
        buf = self.players.get(node_id)
        if not buf or not buf.score_history:
            return np.array([]), np.array([])
        times  = np.array([s.t              for s in buf.score_history])
        scores = np.array([getattr(s, axis) for s in buf.score_history])
        return times, scores

    def all_timelines(self, node_id: int) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        """Return all scored axes for a player as {axis: (times, scores)}."""
        axes = [
            "beat_half","beat_single","beat_double","beat_triple","beat_quad",
            "amplitude","consistency","onset_lock",
        ]
        return {ax: self.score_timeline(node_id, ax) for ax in axes}

    def summary(self) -> dict[int, dict[str, float]]:
        """
        Mean score per axis per player over the full session.
        Returns {node_id: {axis: mean_score, ..., 'dominant': label}}.
        """
        axes = [
            "beat_half","beat_single","beat_double","beat_triple","beat_quad",
            "amplitude","consistency","onset_lock",
        ]
        result: dict[int, dict[str, float]] = {}
        for nid, buf in self.players.items():
            if not buf.score_history:
                continue
            row: dict[str, float] = {
                ax: float(np.mean([getattr(s, ax) for s in buf.score_history]))
                for ax in axes
            }
            # Most common dominant label (excluding "—")
            labels = [s.dominant for s in buf.score_history if s.dominant != "—"]
            row["dominant"] = max(set(labels), key=labels.count) if labels else "—"
            result[nid] = row
        return result

    def log_summary(self):
        """uses logging log.info to print the summary for each player {nid:08x}"""
        summ = self.summary()
        log.info(f"--- Session Summary: {self.session_id} ({len(summ)} players) ---")
        for nid, stats in summ.items():
            dom = stats.pop('dominant', '—')
            metrics = " ".join([f"{k}:{v:.2f}" for k, v in stats.items()])
            log.info(f"Player 0x{nid:04x} | DOM: {dom:12} | {metrics}")
        log.info("--- End Summary ---")

    # ══════════════════════════════════════════════════════════════════════
    # Internal scoring logic
    # ══════════════════════════════════════════════════════════════════════

    def _score_window(
        self, buf: PlayerBuffer, t: float, smooth: bool
    ) -> ScoreSnapshot:
        """Compute a full ScoreSnapshot for one player at time t."""
        snap = ScoreSnapshot(t=t)
        window = buf.window(t, self.SCORE_WINDOW)
        if len(window) < 10:
            return snap

        # ── Choose motion events ────────────────────────────────────────────
        # Try displacement peaks first (direction-change moments).
        # Fall back to velocity peaks if too few peaks are found.
        events = detect_displacement_peaks(window, self.MIN_PEAK_PROM)
        event_type = "displacement"
        if len(events) < 3:
            events = detect_velocity_peaks(window, self.MIN_VEL_PROM)
            event_type = "velocity"  # noqa: F841  (kept for future diagnostics)

        # ── Beat subdivision scores ─────────────────────────────────────────
        mid_t = float(np.mean([s.t for s in window]))
        beat_scores = beat_score_weighted(
            events, self.SCORE_WINDOW, self.beat_times, mid_t
        )
        for key, val in beat_scores.items():
            setattr(snap, key, round(val, 4))

        # Dominant subdivision: highest weighted score above threshold
        best_key   = max(beat_scores, key=beat_scores.get)
        best_score = beat_scores[best_key]
        snap.dominant = best_key if best_score >= 0.35 else "—"

        # ── Amplitude ───────────────────────────────────────────────────────
        #
        # RMS of combined angle displacement, squashed by tanh so that
        # AMPLITUDE_MIDPOINT degrees ≈ 0.76 (a full, expressive movement).
        pitches = np.array([s.pitch for s in window])
        rolls   = np.array([s.roll  for s in window])
        rms_angle = float(np.sqrt(np.mean(pitches ** 2 + rolls ** 2)))
        snap.amplitude = round(float(np.tanh(rms_angle / self.AMPLITUDE_MIDPOINT)), 4)

        # ── Consistency ─────────────────────────────────────────────────────
        #
        # How repeatable is the amplitude peak-to-peak?
        # Low coefficient of variation → consistent → score near 1.
        # High variation → erratic → score near 0.
        combined = np.abs(pitches + rolls)  # signed combination for peak detection
        peak_idxs, _ = find_peaks(combined, distance=3)
        if len(peak_idxs) >= 3:
            peak_vals = combined[peak_idxs]
            cv = float(np.std(peak_vals) / (np.mean(peak_vals) + 1e-6))
            snap.consistency = round(float(np.exp(-cv * 3.0)), 4)

        # ── Onset lock ──────────────────────────────────────────────────────
        #
        # How many motion events land within ±ONSET_LOCK_WINDOW seconds of
        # a musical onset?  Normalized to [0, 1] by the number of onsets
        # in this window.
        onsets_in_window = self.onset_times[
            (self.onset_times >= t - self.SCORE_WINDOW) & (self.onset_times <= t)
        ]
        if len(onsets_in_window) > 0 and len(events) > 0:
            hits = 0
            for ev in events:
                dists = np.abs(onsets_in_window - ev)
                if np.min(dists) <= self.ONSET_LOCK_WINDOW:
                    hits += 1
            snap.onset_lock = round(
                float(hits) / float(len(onsets_in_window)), 4
            )

        return snap


# ═══════════════════════════════════════════════════════════════════════════════
# Quick plotting helper  (requires matplotlib; optional dependency)
# ═══════════════════════════════════════════════════════════════════════════════

def plot_player_scores(
    session: ScoringSession,
    node_id: int,
    axes_to_plot: typing.Optional[list[str]] = None,
    figsize: tuple = (14, 8),
) -> None:
    """
    Plot score timelines for a single player.
    Requires matplotlib.

    Scores above the center line (0.5) indicate strong performance on that axis.
    The dominant subdivision shading shows windows where the player locked onto
    a particular groove.
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        print("matplotlib not installed — skipping plot.")
        return

    if axes_to_plot is None:
        axes_to_plot = [
            "beat_half", "beat_single", "beat_double", "beat_triple", "beat_quad",
            "amplitude", "consistency", "onset_lock",
        ]

    buf = session.players.get(node_id)
    if not buf or not buf.score_history:
        print(f"No score history for node {node_id}")
        return

    n_axes = len(axes_to_plot)
    fig, axs = plt.subplots(n_axes, 1, figsize=figsize, sharex=True)
    if n_axes == 1:
        axs = [axs]

    colors = plt.cm.tab10(np.linspace(0, 1, n_axes))

    for i, (ax_name, color) in enumerate(zip(axes_to_plot, colors)):
        times, scores = session.score_timeline(node_id, ax_name)
        axs[i].plot(times, scores, color=color, linewidth=1.5, label=ax_name)
        axs[i].axhline(0.5, color="gray", linewidth=0.5, linestyle="--")
        axs[i].set_ylim(0, 1)
        axs[i].set_ylabel(ax_name, fontsize=8, rotation=0, labelpad=80, ha="right")
        axs[i].fill_between(times, 0, scores, alpha=0.15, color=color)

    axs[-1].set_xlabel("Playback time (s)")
    fig.suptitle(f"Player {node_id}  |  Session {session.session_id}")
    plt.tight_layout()
    plt.show()


def plot_all_players(
    session: ScoringSession,
    axis: str = "beat_single",
    figsize: tuple = (14, 6),
) -> None:
    """
    Overlay one score axis for all players on the same chart.
    Good for comparing synchronization across the group.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed — skipping plot.")
        return

    fig, ax = plt.subplots(figsize=figsize)
    colors = plt.cm.tab10(np.linspace(0, 1, len(session.players)))

    for color, (nid, buf) in zip(colors, session.players.items()):
        times, scores = session.score_timeline(nid, axis)
        if len(times):
            ax.plot(times, scores, label=f"Node {nid}", color=color, linewidth=1.5)

    ax.axhline(0.5, color="gray", linewidth=0.5, linestyle="--")
    ax.set_ylim(0, 1)
    ax.set_xlabel("Playback time (s)")
    ax.set_ylabel(axis)
    ax.set_title(f"All players — {axis}  |  Session {session.session_id}")
    ax.legend(ncol=5, fontsize=8)
    plt.tight_layout()
    plt.show()


# ═══════════════════════════════════════════════════════════════════════════════
# Minimal self-test / usage demo
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # ── Simulate a 60-second song at 120 BPM ────────────────────────────────
    bpm         = 120.0
    beat_period = 60.0 / bpm                         # 0.5 s per beat
    song_len    = 60.0
    beat_times  = np.arange(0, song_len, beat_period)
    onset_times = beat_times.copy()                  # simplification
    downbeats   = beat_times[::4]                    # every 4 beats

    sess = ScoringSession(
        beat_times     = beat_times,
        onset_times    = onset_times,
        session_id     = "demo_session",
        metadata       = {"song": "Test 120bpm", "bpm": bpm},
    )

    rng = np.random.default_rng(42)

    # ── Simulate 3 players at different subdivisions ─────────────────────────
    sample_rate = 50  # Hz
    dt          = 1.0 / sample_rate

    PLAYER_STYLES = {
        1: {"freq": 1.0 / beat_period,        "label": "single time"},
        2: {"freq": 2.0 / beat_period,        "label": "double time"},
        3: {"freq": 0.5 / beat_period,        "label": "half time"},
    }

    for t_step in np.arange(0, song_len, dt):
        for nid, style in PLAYER_STYLES.items():
            freq = style["freq"]
            pitch = 15.0 * np.sin(2 * np.pi * freq * t_step) + rng.normal(0, 0.8)
            roll  =  8.0 * np.cos(2 * np.pi * freq * t_step) + rng.normal(0, 0.8)
            pkt   = Packet(node_id=nid, pitch=float(pitch), roll=float(roll))
            sess.update(t_step, pkt)

    print("Real-time ingestion complete.")
    print("Running full offline re-score with Savitzky-Golay derivatives…")
    sess.score_all(smooth=True)

    print("\nSession summary:")
    for nid, row in sess.summary().items():
        style = PLAYER_STYLES[nid]["label"]
        print(f"\n  Player {nid}  ({style})")
        for k, v in row.items():
            if k != "dominant":
                print(f"    {k:>15s}: {v:.3f}")
        print(f"    {'dominant':>15s}: {row['dominant']}")

    sess.save("/tmp/demo_session.pkl")

    # Reload and verify
    loaded = ScoringSession.load("/tmp/demo_session.pkl")
    print(f"\nReloaded session '{loaded.session_id}' with "
          f"{len(loaded.players)} players — OK")
