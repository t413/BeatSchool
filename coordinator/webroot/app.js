// app.js — RhythmClass coordinator frontend

const sseDot = document.getElementById('sse-dot');
const sseLabel = document.getElementById('sse-label');
const updateCounter = document.getElementById('update-counter');
const trackTitle = document.getElementById('track-title');
const trackMeta = document.getElementById('track-meta');
const trackSelect = document.getElementById('track-select');
const playBtn = document.getElementById('play-btn');
const resetBtn = document.getElementById('reset-btn');
const nodeGrid = document.getElementById('node-grid');
const waveCanvas = document.getElementById('waveform-canvas');

let updateCount = 0;
let currentMedia = { playing: false, track: '', duration: 0, current_time: 0, analyzed: false, tracks: [] };
const nodeHistories = {};
const NODE_SLOTS = 10;
const MAX_HISTORY = 20;
let waveformAnimationFrame = null;
let playbackAnchor = null;
let playbackTimeAtAnchor = 0;
let waveformPhase = 0;
let lastWaveTimestamp = null;

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function padTime(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function createNodeGrid() {
  nodeGrid.innerHTML = '';
  for (let slot = 0; slot < NODE_SLOTS; slot += 1) {
    const card = document.createElement('article');
    card.className = 'node-card offline';
    card.id = `node-card-${slot}`;
    card.innerHTML = `<canvas data-slot="${slot}" class="node-canvas"></canvas>`;
    nodeGrid.appendChild(card);
  }
}

function resizeCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

function mapNodePosition(pitch, roll, width, height) {
  const normX = clamp(roll / 90, -1, 1);
  const normY = clamp(pitch / 90, -1, 1);
  const paddingX = width * 0.12;
  const paddingY = height * 0.12;
  return {
    x: paddingX + ((normX + 1) / 2) * (width - paddingX * 2),
    y: paddingY + ((1 - normY) / 2) * (height - paddingY * 2),
  };
}

function drawNodeTrail(canvas, history, online) {
  const ctx = resizeCanvas(canvas);
  const rect = canvas.getBoundingClientRect();
  const width = rect.width;
  const height = rect.height;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = 'rgba(8, 12, 20, 0.95)';
  ctx.fillRect(0, 0, width, height);

  if (!history || history.length === 0) {
    ctx.fillStyle = 'rgba(255, 255, 255, 0.04)';
    ctx.fillRect(0, 0, width, height);
    return;
  }

  if (history.length > 1) {
    ctx.lineWidth = 3.5;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(109, 236, 255, 0.72)';
    ctx.beginPath();
    history.forEach((point, index) => {
      if (index === 0) {
        ctx.moveTo(point.x, point.y);
      } else {
        ctx.lineTo(point.x, point.y);
      }
    });
    ctx.stroke();
  }

  const latest = history[history.length - 1];
  ctx.beginPath();
  ctx.fillStyle = online ? '#7df4ff' : '#7b86a8';
  ctx.shadowColor = online ? 'rgba(125, 244, 255, 0.9)' : 'rgba(120, 138, 164, 0.5)';
  ctx.shadowBlur = 14;
  ctx.arc(latest.x, latest.y, 5.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.shadowBlur = 0;
}

function renderNodes(state) {
  const nodeKeys = Object.keys(state)
    .filter((key) => key.startsWith('0x'))
    .sort((a, b) => Number.parseInt(a, 16) - Number.parseInt(b, 16))
    .slice(0, NODE_SLOTS);

  updateCount += 1;
  updateCounter.textContent = `${updateCount} updates`;

  const mediaCandidate = state.media || state.media_player || state.media_state || state.mediaState;
  if (mediaCandidate) {
    updateMediaFromSSE(mediaCandidate);
  }

  for (let slot = 0; slot < NODE_SLOTS; slot += 1) {
    const card = document.getElementById(`node-card-${slot}`);
    const canvas = card.querySelector('.node-canvas');

    if (slot < nodeKeys.length) {
      const nodeKey = nodeKeys[slot];
      const node = state[nodeKey];
      const pyld = node.pyld || {};
      const pitch = Number(pyld.pitch) || 0;
      const roll = Number(pyld.roll) || 0;
      const online = Boolean(node.online);
      const position = mapNodePosition(pitch, roll, canvas.clientWidth, canvas.clientHeight);
      let history = nodeHistories[nodeKey] || [];

      if (online) {
        history.push(position);
        if (history.length > MAX_HISTORY) history.shift();
      } else {
        history = [];
      }

      nodeHistories[nodeKey] = history;
      card.classList.toggle('offline', !online);
      drawNodeTrail(canvas, history, online);
    } else {
      card.classList.add('offline');
      drawNodeTrail(canvas, [], false);
    }
  }
}

function updateMediaFromSSE(mediaCandidate) {
  const nextMedia = { ...currentMedia, ...mediaCandidate };
  nextMedia.duration = Number(mediaCandidate.duration) || currentMedia.duration;
  nextMedia.track = mediaCandidate.track || currentMedia.track;

  if (currentMedia.playing && nextMedia.playing) {
    const sseTime = Number(mediaCandidate.current_time) || 0;
    const localTime = Number(currentMedia.current_time) || 0;
    const drift = Math.abs(sseTime - localTime);

    if (drift > 0.35) {
      nextMedia.current_time = sseTime;
      playbackAnchor = Date.now();
      playbackTimeAtAnchor = sseTime;
    } else {
      nextMedia.current_time = localTime;
    }
  } else {
    nextMedia.current_time = Number(mediaCandidate.current_time) || currentMedia.current_time;
  }

  const stateChanged = nextMedia.track !== currentMedia.track
    || nextMedia.playing !== currentMedia.playing
    || nextMedia.duration !== currentMedia.duration;

  currentMedia = nextMedia;

  if (stateChanged || !currentMedia.playing) {
    renderMedia(currentMedia);
  }
}

function selectTrack(trackName) {
  if (!trackName) return;
  fetch(`/media/select/${encodeURIComponent(trackName)}`, { method: 'POST' })
    .then((r) => r.json())
    .then((json) => {
      if (json.ok) {
        currentMedia.track = trackName;
        renderMedia(currentMedia);
      }
    })
    .catch((err) => console.error('track select failed:', err));
}

function togglePlay() {
  const targetPlaying = !currentMedia.playing;
  const endpoint = targetPlaying ? '/media/play' : '/media/pause';
  fetch(endpoint, { method: 'POST' })
    .then((r) => r.json())
    .then((json) => {
      if (json.ok) {
        currentMedia.playing = targetPlaying;
        renderMedia(currentMedia);
      }
    })
    .catch((err) => console.error('play toggle failed:', err));
}

function resetTrack() {
  fetch('/media/restart', { method: 'POST' })
    .then((r) => r.json())
    .then((json) => {
      if (json.ok) {
        currentMedia.current_time = 0;
        renderMedia(currentMedia);
      }
    })
    .catch((err) => console.error('reset failed:', err));
}

function renderTrackSelection(media) {
  const tracks = Array.isArray(media.tracks) ? media.tracks : [];
  const existing = Array.from(trackSelect.options).map((option) => option.value);
  const trackNames = tracks.map((track) => track.name);
  const same = existing.length === trackNames.length && trackNames.every((name, index) => name === existing[index]);

  if (!same) {
    trackSelect.innerHTML = '<option value="">Select track</option>';
    tracks.forEach((track) => {
      const option = document.createElement('option');
      option.value = track.name;
      option.textContent = track.name;
      trackSelect.appendChild(option);
    });
  }

  if (media.track) {
    trackSelect.value = media.track;
  }
}

function fetchMediaState() {
  fetch('/media/state')
    .then((r) => r.json())
    .then((json) => {
      if (json && typeof json === 'object') {
        currentMedia = { ...currentMedia, ...json };
        renderMedia(currentMedia);
      }
    })
    .catch((err) => console.error('failed to load media state:', err));
}

function drawWaveform(media) {
  const ctx = resizeCanvas(waveCanvas);
  const rect = waveCanvas.getBoundingClientRect();
  const width = rect.width;
  const height = rect.height;
  ctx.clearRect(0, 0, width, height);

  ctx.fillStyle = '#06101c';
  ctx.fillRect(0, 0, width, height);

  if (!media.track) {
    ctx.fillStyle = '#5b6d95';
    ctx.font = '500 14px Inter, sans-serif';
    ctx.fillText('No track loaded', 16, height / 2 - 6);
    return;
  }

  const track = (media.tracks || []).find((item) => item.name === media.track) || {};
  const beats = Array.isArray(track.beats) ? track.beats : [];
  const onsets = Array.isArray(track.onsets) ? track.onsets : [];
  const duration = Math.max(media.duration || 1, 1);
  const currentTime = clamp(media.current_time || 0, 0, duration);
  const windowDuration = Math.min(14, duration);

  let windowStart = 0;
  let windowEnd = Math.min(duration, windowDuration);
  let centerX;

  if (duration > windowDuration) {
    windowStart = clamp(currentTime - windowDuration / 2, 0, duration - windowDuration);
    windowEnd = windowStart + windowDuration;
    centerX = width * 0.5;
  } else {
    windowStart = 0;
    windowEnd = duration;
    centerX = duration === 0 ? width * 0.5 : (currentTime / duration) * width;
  }

  const visibleDuration = Math.max(windowEnd - windowStart, 0.01);

  ctx.strokeStyle = 'rgba(255,255,255,0.05)';
  ctx.lineWidth = 1;
  for (let line = 1; line <= 3; line += 1) {
    const y = (height / 4) * line;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  ctx.fillStyle = 'rgba(82, 230, 255, 0.1)';
  ctx.fillRect(0, height * 0.72, width, height * 0.16);

  ctx.lineCap = 'round';
  ctx.lineWidth = 6;
  ctx.strokeStyle = 'rgba(67, 185, 255, 0.38)';
  beats.filter((time) => time >= windowStart && time <= windowEnd).forEach((beatTime) => {
    const x = ((beatTime - windowStart) / visibleDuration) * width;
    ctx.beginPath();
    ctx.moveTo(x, height * 0.17);
    ctx.lineTo(x, height * 0.83);
    ctx.stroke();
  });

  ctx.lineWidth = 3.5;
  ctx.strokeStyle = 'rgba(255, 98, 191, 0.28)';
  onsets.filter((time) => time >= windowStart && time <= windowEnd).forEach((onsetTime) => {
    const x = ((onsetTime - windowStart) / visibleDuration) * width;
    ctx.beginPath();
    ctx.moveTo(x, height * 0.35);
    ctx.lineTo(x, height * 0.65);
    ctx.stroke();
  });

  ctx.beginPath();
  const waveY = height * 0.48;
  const phaseOffset = waveformPhase;
  ctx.lineWidth = 2.5;
  ctx.strokeStyle = 'rgba(123, 220, 255, 0.28)';
  ctx.lineCap = 'round';
  for (let x = 0; x <= width; x += 3) {
    const phase = (x / width) * Math.PI * 3.3 + phaseOffset;
    const y = waveY + Math.sin(phase) * 6.5;
    if (x === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  ctx.fillStyle = 'rgba(255,255,255,0.06)';
  ctx.fillRect(centerX - 1, 0, 2, height);
  ctx.fillStyle = 'rgba(255,255,255,0.04)';
  ctx.fillRect(centerX - 8, 0, 16, height);
}

function renderMedia(media) {
  if (!media) return;

  currentMedia = { ...currentMedia, ...media };
  trackTitle.textContent = media.track || 'No track selected';
  trackMeta.textContent = `${media.playing ? 'playing' : 'paused'} · ${padTime(media.current_time || 0)} / ${padTime(media.duration || 0)}`;
  playBtn.textContent = media.playing ? 'Pause' : 'Play';
  resetBtn.disabled = media.playing;
  renderTrackSelection(media);

  if (media.playing) {
    playbackAnchor = Date.now();
    playbackTimeAtAnchor = media.current_time || 0;
    startWaveformLoop();
  } else {
    stopWaveformLoop();
  }

  drawWaveform(currentMedia);
}

function sendPing() {
  fetch('/api/ping', { method: 'POST' }).catch((err) => console.error('ping failed:', err));
}

function sendZero() {
  fetch('/api/zero', { method: 'POST' }).catch((err) => console.error('zero failed:', err));
}

function startWaveformLoop() {
  if (waveformAnimationFrame !== null) return;

  function loop() {
    if (!currentMedia.playing) {
      waveformAnimationFrame = null;
      lastWaveTimestamp = null;
      return;
    }

    const now = Date.now();
    if (playbackAnchor !== null) {
      const elapsed = (now - playbackAnchor) / 1000;
      currentMedia.current_time = Math.min(currentMedia.duration || 0, playbackTimeAtAnchor + elapsed);
    }

    if (lastWaveTimestamp === null) {
      lastWaveTimestamp = now;
    }
    const delta = (now - lastWaveTimestamp) / 1000;
    lastWaveTimestamp = now;
    waveformPhase += delta * 1.7;

    drawWaveform(currentMedia);
    waveformAnimationFrame = requestAnimationFrame(loop);
  }

  loop();
}

function stopWaveformLoop() {
  if (waveformAnimationFrame !== null) {
    cancelAnimationFrame(waveformAnimationFrame);
    waveformAnimationFrame = null;
  }
  lastWaveTimestamp = null;
}

function connectSSE() {
  const es = new EventSource('/api/events');

  es.addEventListener('node_update', (e) => {
    try {
      const data = JSON.parse(e.data);
      renderNodes(data);
    } catch (err) {
      console.error('SSE parse error:', err);
    }
  });

  es.onopen = () => {
    sseDot.className = 'status-dot connected';
    sseLabel.textContent = 'SSE: connected';
  };

  es.onerror = () => {
    sseDot.className = 'status-dot error';
    sseLabel.textContent = 'SSE: reconnecting…';
  };
}

function init() {
  createNodeGrid();
  document.querySelectorAll('.node-canvas').forEach((canvas) => resizeCanvas(canvas));
  resizeCanvas(waveCanvas);
  connectSSE();
  fetchMediaState();
  drawWaveform(currentMedia);
  window.addEventListener('resize', () => {
    document.querySelectorAll('.node-canvas').forEach((canvas) => resizeCanvas(canvas));
    resizeCanvas(waveCanvas);
    drawWaveform(currentMedia);
  });
}

init();
