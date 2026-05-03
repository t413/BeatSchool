// app.js — BeatSchool coordinator frontend

const sseDot = document.getElementById('sse-dot');
const sseLabel = document.getElementById('sse-label');
const trackTitle = document.getElementById('track-title');
const trackMeta = document.getElementById('track-meta');
const trackSelect = document.getElementById('track-select');
const playBtn = document.getElementById('play-btn');
const resetBtn = document.getElementById('reset-btn');
const nodeGrid = document.getElementById('node-grid');
const waveCanvas = document.getElementById('waveform-canvas');

let currentMedia = { playing: false, track: '', duration: 0, current_time: 0, analyzed: false };
let mediaTracks = [];
const nodeHistories = {};
const nodeStates = {};
const NODE_SLOTS = 10;
const MAX_HISTORY = 60;
let waveformAnimationFrame = null;
let playbackAnchor = null;
let playbackTimeAtAnchor = 0;
let waveformPhase = 0;
let lastWaveTimestamp = null;
let currentSSEStatus = 'connecting';
let lastUpdateTime = null;
let updatesHzFiltered = 0;
const updatesHzAlpha = 0.999;
const NODE_INPUT_SCALE = 0.41;
const WAVEFORM_WINDOW_SECONDS = 10;

// Score tracking
const nodeScores = {};  // node_id -> latest score snapshot
const nodeFinalScores = {};  // node_id -> final score data (from final_scores event)
let finalScoresAvailable = false;  // whether we have final scores to display

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
  const scaledX = Math.sign(normX) * Math.pow(Math.abs(normX), NODE_INPUT_SCALE);
  const scaledY = Math.sign(normY) * Math.pow(Math.abs(normY), NODE_INPUT_SCALE);
  const paddingX = width * 0.12;
  const paddingY = height * 0.12;
  return {
    x: paddingX + ((scaledX + 1) / 2) * (width - paddingX * 2),
    y: paddingY + ((1 - scaledY) / 2) * (height - paddingY * 2),
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
    ctx.lineCap = 'none';
    ctx.lineJoin = 'none';
    for (let i = 1; i < history.length; i++) {
      const alpha = (i / history.length) * 0.72;
      ctx.strokeStyle = `rgba(109, 236, 255, ${alpha})`;
      ctx.beginPath();
      ctx.moveTo(history[i - 1].x, history[i - 1].y);
      ctx.lineTo(history[i].x, history[i].y);
      ctx.stroke();
    }
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
  if (state.media) {
    updateMediaFromSSE(state.media);
  }

  if (Array.isArray(state.updates)) {
    state.updates.forEach((node) => {
      if (typeof node.nodeid !== 'undefined') {
        nodeStates[node.nodeid] = node;
      }
    });
  } else if (Array.isArray(state.nodes)) {
    state.nodes.forEach((node) => {
      if (typeof node.nodeid !== 'undefined') {
        nodeStates[node.nodeid] = node;
      }
    });
  }

  const nodeKeys = Object.keys(nodeStates)
    .map((key) => Number(key))
    .sort((a, b) => a - b)
    .slice(0, NODE_SLOTS);

  for (let slot = 0; slot < NODE_SLOTS; slot += 1) {
    const card = document.getElementById(`node-card-${slot}`);
    const canvas = card.querySelector('.node-canvas');

    if (slot < nodeKeys.length) {
      const nodeKey = nodeKeys[slot];
      const node = nodeStates[nodeKey] || {};
      const pyld = node.pyld || node;
      const pitch = Number(pyld.pitch) || 0;
      const roll = Number(pyld.roll) || 0;
      const online = true;
      const position = mapNodePosition(pitch, roll, canvas.clientWidth, canvas.clientHeight);
      let history = nodeHistories[nodeKey] || [];

      history.push(position);
      if (history.length > MAX_HISTORY) history.shift();

      nodeHistories[nodeKey] = history;
      card.classList.toggle('offline', !online);
      drawNodeTrail(canvas, history, online);
    } else {
      card.classList.add('offline');
      drawNodeTrail(canvas, [], false);
    }
  }
}

function updateMediaFromSSE(newMedia) {
  const oldMedia = currentMedia;
  currentMedia = newMedia; //save state
  if (oldMedia.analyzed != newMedia.analyzed) {
    console.log("refreshing media state, analysis status changed")
    fetchMediaState();
  }
  if (oldMedia.playing && newMedia.playing) {
    const newTime = Number(newMedia.current_time) || 0;
    const oldTime = Number(oldMedia.current_time) || 0;
    const drift = Math.abs(newTime - oldTime);

    if (drift > 0.35) {
      console.log("sse playback time drift", drift);
      playbackAnchor = Date.now();
      playbackTimeAtAnchor = newTime;
    }
  }

  const stateChanged = newMedia.track !== currentMedia.track
    || newMedia.playing !== currentMedia.playing
    || newMedia.duration !== currentMedia.duration;
  const timeChanged = Math.abs((newMedia.current_time || 0) - (currentMedia.current_time || 0)) > 0.15;

  if (stateChanged || !newMedia.playing || timeChanged) {
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
  const existing = Array.from(trackSelect.options).map((option) => option.value);
  const trackNames = mediaTracks.map((track) => track.name);
  const same = existing.length === trackNames.length && trackNames.every((name, index) => name === existing[index]);

  if (!same) {
    trackSelect.innerHTML = '<option value="">Select track</option>';
    mediaTracks.forEach((track) => {
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
        if (Array.isArray(json.tracks)) {
          currentMedia = json;
          mediaTracks = json.tracks;
          console.log("full media state updated", json);
        }
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

  const track = (mediaTracks || []).find((item) => item.name === media.track) || {};
  const beats = Array.isArray(track.beats) ? track.beats : [];
  const onsets = Array.isArray(track.onsets) ? track.onsets : [];
  const duration = Math.max(media.duration || 1, 1);
  const currentTime = clamp(media.current_time || 0, 0, duration);
  trackMeta.textContent = `${media.playing ? 'playing' : 'paused'} · ${padTime(currentTime)} / ${padTime(duration)}`;
  const windowDuration = Math.min(WAVEFORM_WINDOW_SECONDS, duration);

  let windowStart = 0;
  let windowEnd = Math.min(duration, windowDuration);
  let centerX;

  if (duration > windowDuration) {
    windowStart = Math.max(0, currentTime - windowDuration / 2);
    windowEnd = windowStart + windowDuration;
    // Adjust centerX if we're clamped at the start
    centerX = ((currentTime - windowStart) / windowDuration) * width;
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
  ctx.lineWidth = 0;
  ctx.fillStyle = 'rgba(67, 185, 255, 0.32)';
  beats.filter((time) => time >= windowStart && time <= windowEnd).forEach((beatTime) => {
    const x = ((beatTime - windowStart) / visibleDuration) * width;
    ctx.fillRect(x - 3.5, height * 0.14, 7, height * 0.72);
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
  ctx.lineWidth = 1;

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
    // Clear final scores when playback restarts
    finalScoresAvailable = false;
    document.querySelectorAll('.score-display').forEach(el => el.style.display = 'none');
  } else {
    stopWaveformLoop();
    // Show final scores when playback stops
    renderPlayerScores();
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

function updateSSELabel(status = currentSSEStatus) {
  currentSSEStatus = status;
  sseLabel.textContent = `${status} · ${updatesHzFiltered.toFixed(1)} Hz`;
}

function handleScoreEvent(scoreEvent) {
  const { type, node_id, data } = scoreEvent;

  if (type === 'score' && node_id !== null) {
    // Intermediate score event
    console.log("Received score event", scoreEvent);
    nodeScores[node_id] = data;
    showScoreFlourish(node_id, data);
  } else if (type === 'final_scores') {
    // Final scores event - data is {node_id: {metrics, dominant, ...}}
    Object.assign(nodeFinalScores, data);
    finalScoresAvailable = true;
    // Show final scores immediately when they arrive
    renderPlayerScores();
  }
}

function showScoreFlourish(nodeId, scoreSnapshot) {
  // Find the best-scoring axis for this snapshot
  const axes = [
    'beat_half', 'beat_single', 'beat_double', 'beat_triple', 'beat_quad',
    'amplitude', 'consistency', 'onset_lock'
  ];

  let bestAxis = null;
  let bestScore = 0;

  for (const axis of axes) {
    const score = scoreSnapshot[axis] || 0;
    if (score > bestScore && score > 0.6) {  // Only show if score is significant
      bestScore = score;
      bestAxis = axis;
    }
  }

  if (bestAxis && bestScore > 0.6) {
    const slot = Object.keys(nodeStates).map(Number).sort((a, b) => a - b).indexOf(Number(nodeId));
    if (slot >= 0 && slot < NODE_SLOTS) {
      const card = document.getElementById(`node-card-${slot}`);
      if (card) {
        showCardOverlay(card, bestAxis, bestScore);
      }
    }
  }
}

function formalName(metricname) {
  // clean up const-case metric name for display
  return metricname.replaceAll(/_/g, ' ').toLowerCase().replaceAll(/\b\w/g, l => l.toUpperCase());
}

function showCardOverlay(card, metricName, score) {
  // Remove existing overlay if any
  let overlay = card.querySelector('.score-overlay');
  const needsAdd = !overlay;
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.className = 'score-overlay';
  }

  // Format the metric name to title case
  overlay.textContent = `${formalName(metricName)}\n${(score * 100).toFixed(0)}%`;
  overlay.style.opacity = '1';

  // Randomize position and tilt
  const randomX = 40 + Math.random() * 20; // 40-60% from left
  const randomY = 35 + Math.random() * 30; // 35-65% from top
  const randomTilt = -15 + Math.random() * 30; // -15 to 15 degrees

  overlay.style.left = `${randomX}%`;
  overlay.style.top = `${randomY}%`;
  overlay.style.transform = `translate(-50%, -50%) rotate(${randomTilt}deg)`;
  if (needsAdd) card.appendChild(overlay); //add after style/content setup

  // Fade out after 1.5 seconds
  setTimeout(() => {
    overlay.style.opacity = '0';
  }, 1500);
}

function renderPlayerScores() {
  // Show final scores above each player card if available
  if (!finalScoresAvailable || Object.keys(nodeFinalScores).length === 0) {
    return;
  }

  const nodeIds = Object.keys(nodeStates).map(k => Number(k)).sort((a, b) => a - b);

  for (let slot = 0; slot < NODE_SLOTS; slot += 1) {
    const card = document.getElementById(`node-card-${slot}`);
    if (!card) continue;

    let scoreDisplay = card.querySelector('.score-display');
    if (slot < nodeIds.length) {
      const nodeId = nodeIds[slot];
      const scoreData = nodeFinalScores[nodeId];

      if (scoreData) {
        if (!scoreDisplay) {
          scoreDisplay = document.createElement('div');
          scoreDisplay.className = 'score-display';
          card.appendChild(scoreDisplay);
        }

        // Calculate ranking - count how many players have higher total score
        const scores = Object.values(nodeFinalScores);
        const thisScore = Object.values(scoreData).reduce((a, b) => (typeof b === 'number' ? a + b : a), 0);
        const ranking = scores.filter(s => {
          const s_total = Object.values(s).reduce((a, b) => (typeof b === 'number' ? a + b : a), 0);
          return s_total > thisScore;
        }).length + 1;

        const dominantTxt = (scoreData.dominant.length > 2)? (formalName(scoreData.dominant) + ' Champ') : '';
        scoreDisplay.innerHTML = `<div class="rank">#${ranking}</div><div class="dominant">${dominantTxt}</div>`;
        scoreDisplay.style.display = 'block';
      }
    } else if (scoreDisplay) {
      scoreDisplay.style.display = 'none';
    }
  }
}

function connectSSE() {
  const es = new EventSource('/api/events');

  es.addEventListener('node_update', (e) => {
    try {
      const data = JSON.parse(e.data);
      const now = performance.now();
      if (lastUpdateTime && now > lastUpdateTime) {
        const instUPS = 1000 / (now - lastUpdateTime);
        updatesHzFiltered = updatesHzFiltered ? (updatesHzAlpha * updatesHzFiltered) + ((1 - updatesHzAlpha) * instUPS) : instUPS;
      }
      lastUpdateTime = now;

      // Process score events if present
      if (data.scores && Array.isArray(data.scores)) {
        for (const scoreEvent of data.scores) {
          handleScoreEvent(scoreEvent);
        }
      }

      renderNodes(data);
      updateSSELabel(data.state? data.state : currentSSEStatus);
    } catch (err) {
      console.error('SSE parse error:', err);
    }
  });

  es.onopen = () => {
    sseDot.className = 'status-dot connected';
    updateSSELabel('connected');
  };

  es.onerror = () => {
    sseDot.className = 'status-dot error';
    updateSSELabel('reconnecting…');
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
