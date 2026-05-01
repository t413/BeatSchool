// app.js — RhythmClass coordinator frontend (MVP)

const statePre      = document.getElementById("state-pre");
const sseDot        = document.getElementById("sse-dot");
const sseLabel      = document.getElementById("sse-label");
const updateCounter = document.getElementById("update-counter");
const nodeIdInput   = document.getElementById("node-id-input");

let updateCount = 0;

// ---------------------------------------------------------------------------
// SSE
// ---------------------------------------------------------------------------
function connectSSE() {
  const es = new EventSource("/api/events");

  es.addEventListener("node_update", (e) => {
    updateCount++;
    updateCounter.textContent = `${updateCount} updates`;
    try {
      const data = JSON.parse(e.data);
      renderState(data);
    } catch (err) {
      statePre.textContent = `[parse error] ${err}\n\nRaw:\n${e.data}`;
    }
  });

  es.onopen = () => {
    sseDot.className  = "dot connected";
    sseLabel.textContent = "SSE: connected";
  };

  es.onerror = () => {
    sseDot.className  = "dot error";
    sseLabel.textContent = "SSE: reconnecting…";
    // Browser auto-reconnects; no manual retry needed
  };
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------
function renderState(nodes) {
  if (Object.keys(nodes).length === 0) {
    statePre.textContent = "(no nodes seen yet)";
    return;
  }
  statePre.textContent = JSON.stringify(nodes, null, 2);
}

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------
async function sendZero() {
  try {
    const r = await fetch("/api/zero", { method: "POST" });
    const j = await r.json();
    console.log("ping:", j);
  } catch (e) {
    console.error("ping failed:", e);
  }
}

async function sendPing() {
  try {
    const r = await fetch("/api/ping", { method: "POST" });
    const j = await r.json();
    console.log("ping:", j);
  } catch (e) {
    console.error("ping failed:", e);
  }
}

async function sendVersion() {
  try {
    const r = await fetch("/api/version", { method: "POST" });
    const j = await r.json();
    console.log("ping:", j);
  } catch (e) {
    console.error("ping failed:", e);
  }
}

async function sendMode(modeHex) {
  const nodeId = nodeIdInput.value.trim() || "0xFF";
  // led_mode 0x01 (solid) gets white; others don't need color
  const isSolid = modeHex === "0x01";
  const body = {
    node_id:  nodeId,
    led_mode: parseInt(modeHex, 16),
    r: isSolid ? 200 : 0,
    g: isSolid ? 200 : 0,
    b: isSolid ? 200 : 0,
  };
  try {
    const r = await fetch("/api/set_state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    console.log("set_state:", j);
  } catch (e) {
    console.error("set_state failed:", e);
  }
}

async function playSong() {
  try {
    const r = await fetch("/api/play", { method: "POST" });
    const j = await r.json();
    console.log("play:", j);
  } catch (e) {
    console.error("play failed:", e);
  }
}

async function pauseSong() {
  try {
    const r = await fetch("/api/pause", { method: "POST" });
    const j = await r.json();
    console.log("pause:", j);
  } catch (e) {
    console.error("pause failed:", e);
  }
}

async function restartSong() {
  try {
    const r = await fetch("/api/restart", { method: "POST" });
    const j = await r.json();
    console.log("restart:", j);
  } catch (e) {
    console.error("restart failed:", e);
  }
}

async function fetchSnapshot() {
  try {
    const r = await fetch("/api/nodes");
    const j = await r.json();
    renderState(j);
  } catch (e) {
    console.error("snapshot fetch failed:", e);
  }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
connectSSE();
fetchSnapshot();   // populate immediately before first SSE event arrives
