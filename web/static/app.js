import { VisualMetrics, heartSummary } from './metrics.mjs';

const $ = id => document.getElementById(id);
const metrics = new VisualMetrics();
let stream = null, worker = null, ready = false, busy = false, generation = 0;
let lastFrame = -1, lastCapture = 0, starting = false, trackAvailable = false;
let sessionStarted = null, heart = { status: 'disconnected', samples: [] };
let sessionLog = [], lastLog = 0, processingMs = 0, frameTimes = [], cameraSelection = null;
const overlay = $('overlay'), overlayContext = overlay.getContext('2d');

function cameraStatus(label, active = false) {
  $('camera-badge').textContent = label;
  $('camera-badge').classList.toggle('live', active);
  $('camera-state').textContent = label;
  $('camera-state').style.color = active ? '#197968' : '';
}

async function enumerateCameras() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const devices = await navigator.mediaDevices.enumerateDevices();
  const selected = $('camera-select').value;
  const cameras = devices.filter(d => d.kind === 'videoinput');
  $('camera-select').replaceChildren(new Option('Default camera', ''));
  cameras.forEach((camera, i) => $('camera-select').add(new Option(camera.label || `Camera ${i + 1}`, camera.deviceId)));
  $('camera-select').value = selected;
}

function stopCamera(message = 'Camera stopped. Readings are unavailable until you restart.') {
  generation++;
  stream?.getTracks().forEach(track => track.stop());
  stream = null;
  worker?.terminate(); worker = null; ready = false; busy = false; trackAvailable = false;
  $('video').srcObject = null; $('camera-placeholder').hidden = false;
  overlayContext.clearRect(0, 0, overlay.width, overlay.height);
  $('camera-button').innerHTML = 'Start camera <span>↗</span>';
  $('camera-select').disabled = false;
  $('camera-message').textContent = message;
  $('tracking-label').textContent = 'Camera inactive'; $('fps').textContent = '— fps';
  cameraStatus('Off'); metrics.reset(); frameTimes = []; lastFrame = -1;
}

async function startCamera() {
  if (starting) return;
  starting = true; $('camera-button').disabled = true;
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera access is unavailable in this browser. Open the local dashboard in Safari or Chrome.');
    if (!window.Worker || !window.createImageBitmap) throw new Error('This browser cannot run the local face tracker. Try an updated Safari or Chrome.');
    cameraStatus('Starting'); $('camera-message').textContent = 'Requesting camera access and loading the local face tracker…';
    const deviceId = $('camera-select').value;
    stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: {
      width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 20, max: 30 },
      ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
    } });
    const localGeneration = ++generation;
    const track = stream.getVideoTracks()[0];
    cameraSelection = track.label || 'Selected camera';
    $('camera-source').textContent = cameraSelection;
    $('video').srcObject = stream;
    await $('video').play();
    track.addEventListener('ended', () => { if (localGeneration === generation) stopCamera('The camera disconnected. Choose an available camera and restart.'); });
    track.addEventListener('mute', () => {
      if (localGeneration === generation) {
        trackAvailable = false; metrics.push(performance.now(), null); cameraStatus('Interrupted');
        $('tracking-label').textContent = 'Camera interrupted';
      }
    });
    track.addEventListener('unmute', () => { if (localGeneration === generation) trackAvailable = true; });
    trackAvailable = !track.muted;
    $('camera-placeholder').hidden = true;
    $('camera-select').disabled = true;
    $('camera-button').textContent = 'Stop camera';
    await enumerateCameras();
    worker = new Worker('/static/vision-worker.mjs');
    worker.onerror = () => { if (localGeneration === generation) stopCamera('The local face tracker could not load. See README for camera setup.'); };
    worker.onmessage = ({ data }) => {
      if (localGeneration !== generation) return;
      if (data.type === 'ready') {
        ready = true; cameraStatus('Live', true); $('camera-message').textContent = 'Local camera analysis active. Keep your face and eyes visible.';
        if (sessionStarted === null) sessionStarted = Date.now();
        requestAnimationFrame(loop);
      } else if (data.type === 'result') {
        busy = false;
        // Reject old results; a slow or interrupted pipeline is not current evidence.
        if (performance.now() - data.t > 500 || !trackAvailable || document.hidden) {
          metrics.push(performance.now(), null); return;
        }
        metrics.push(data.t, data.closure);
        processingMs = data.ms;
        frameTimes.push(performance.now());
        frameTimes = frameTimes.filter(t => performance.now() - t <= 2000);
        $('tracking-label').textContent = data.closure === null ? 'No visible face · estimate unavailable' : 'Face tracked · eyes observed';
        cameraStatus(data.closure === null ? 'No face' : 'Live', data.closure !== null);
        drawLandmarks(data.points);
      } else if (data.type === 'error') {
        stopCamera(`Face tracker stopped: ${data.message}`);
      }
    };
    worker.postMessage({ type: 'init' });
  } catch (error) {
    const messages = {
      NotAllowedError: 'Camera access was denied. Allow camera access for this local page in your browser settings.',
      NotFoundError: 'No camera was found. Connect a webcam or enable iPhone Continuity Camera.',
      NotReadableError: 'The camera is busy or unavailable. Close other camera apps and retry.',
      OverconstrainedError: 'The selected camera is unavailable. Choose Default camera and retry.',
    };
    stopCamera(messages[error.name] || error.message);
  } finally { starting = false; $('camera-button').disabled = false; }
}

async function loop(now) {
  if (!stream || !ready) return;
  requestAnimationFrame(loop);
  const video = $('video');
  if (document.hidden || !trackAvailable || video.readyState < 2) {
    metrics.push(now, null); return;
  }
  // Bound inference to 15 fps. The worker prevents inference from blocking the UI.
  if (busy || now - lastCapture < 66 || lastFrame === video.currentTime) return;
  busy = true; lastCapture = now; lastFrame = video.currentTime;
  const activeGeneration = generation;
  try {
    const bitmap = await createImageBitmap(video);
    if (activeGeneration !== generation || !worker) { bitmap.close(); return; }
    worker.postMessage({ type: 'frame', t: now, bitmap }, [bitmap]);
  } catch {
    if (activeGeneration === generation) stopCamera('Camera frames could not be processed. Restart the camera or try another browser.');
  }
}

function drawLandmarks(points) {
  const video = $('video');
  overlay.width = video.videoWidth || 640; overlay.height = video.videoHeight || 480;
  overlayContext.clearRect(0, 0, overlay.width, overlay.height);
  overlayContext.fillStyle = '#a2eac4';
  points?.forEach(p => { overlayContext.beginPath(); overlayContext.arc(p.x * overlay.width, p.y * overlay.height, 2.5, 0, Math.PI * 2); overlayContext.fill(); });
}

async function request(path, body = {}) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Connection action failed');
  return result;
}

$('camera-button').addEventListener('click', () => stream ? stopCamera() : startCamera());
$('scan-button').addEventListener('click', async () => {
  const button = $('scan-button'); button.disabled = true; button.textContent = 'Scanning…';
  $('watch-devices').replaceChildren();
  try {
    const result = await request('/api/scan');
    $('watch-message').textContent = result.error || (result.devices.length ? 'Select your watch below.' : 'No broadcasters found. Enable Broadcast Heart Rate on your watch and retry.');
    result.devices.forEach(device => {
      const choice = document.createElement('button'); choice.className = 'secondary'; choice.textContent = `Connect ${device.name}`;
      choice.addEventListener('click', async () => {
        choice.disabled = true;
        try { await request('/api/connect', { id: device.id }); $('watch-devices').replaceChildren(); }
        catch (error) { $('watch-message').textContent = error.message; choice.disabled = false; }
      });
      $('watch-devices').append(choice);
    });
  } catch (error) { $('watch-message').textContent = error.message; }
  finally { button.disabled = false; button.textContent = 'Scan for watch'; }
});
$('disconnect-button').addEventListener('click', async () => {
  try { await request('/api/disconnect'); }
  catch (error) { $('watch-message').textContent = error.message; }
});

async function pollWatch() {
  try {
    const response = await fetch('/api/state');
    if (!response.ok) throw new Error('Bridge offline');
    heart = await response.json();
    if (heart.bpm !== null && sessionStarted === null) sessionStarted = Date.now();
  } catch {
    heart = { status: 'unavailable', bpm: null, message: 'The local watch bridge is offline. Restart the dashboard server.', samples: [] };
  }
  setTimeout(pollWatch, 1000);
}

function update() {
  const now = performance.now();
  const s = metrics.snapshot(now);
  $('level').textContent = s.level;
  $('level-panel').dataset.level = s.level;
  $('level-subtitle').textContent = ['High','Elevated','Low'].includes(s.level) ? 'VISUAL CUES' : s.level === 'Collecting' ? 'OBSERVING YOUR EYES' : 'FOR CAMERA DATA';
  $('level-reason').textContent = s.reason;
  const fill = { Waiting: 0, Unavailable: 0, Collecting: 12, Low: 25, Elevated: 60, High: 95 }[s.level];
  $('gauge-fill').style.strokeDasharray = `${fill} 100`;
  $('eye-fraction').textContent = s.fresh && s.observed >= 15000 ? (s.fraction * 100).toFixed(1) : '—';
  $('blink-count').textContent = s.fresh && s.observed >= 15000 ? s.blinkCount : '—';
  $('closure-duration').textContent = s.fresh ? s.currentClosure.toFixed(1) : '—';
  $('coverage').textContent = s.observed > 0 ? `${Math.round(s.coverage * 100)}%` : '—';
  $('coverage-fill').style.width = `${s.coverage * 100}%`;
  if (stream && ready) $('fps').textContent = `${(frameTimes.filter(t => now - t <= 2000).length / 2).toFixed(0)} fps`;
  if (stream && ready && !s.fresh) { $('tracking-label').textContent = 'No current eye observations'; overlayContext.clearRect(0,0,overlay.width,overlay.height); }
  const heartFresh = heart.status === 'connected' && heart.bpm !== null;
  $('heart-rate').textContent = heartFresh ? heart.bpm : '—';
  $('heart-note').textContent = heartFresh ? 'Live · Garmin Bluetooth' : heart.status === 'stale' ? 'Signal stale · waiting for watch' : 'Watch not connected';
  $('watch-name').textContent = heart.name || 'Garmin Forerunner 970';
  $('watch-state').textContent = ({ disconnected: 'Not connected', scanning: 'Scanning nearby', connecting: 'Connecting…', connected: heartFresh ? 'Heart rate streaming' : 'Waiting for heart rate', stale: 'Connected · signal stale', unavailable: 'Unavailable' })[heart.status] || 'Unavailable';
  $('watch-dot').style.background = heartFresh ? '#359779' : heart.status === 'stale' ? '#b9782d' : '#c9d1c5';
  if (!$('watch-devices').childElementCount && heart.message) $('watch-message').textContent = heart.message;
  $('disconnect-button').hidden = !['connected','connecting','stale'].includes(heart.status);
  $('scan-button').hidden = ['connected','connecting','stale'].includes(heart.status);
  const summary = heartSummary(heart.samples || [], Date.now() / 1000);
  $('heart-delta').textContent = heartFresh && summary.delta !== null ? `${summary.delta >= 0 ? '+' : ''}${summary.delta.toFixed(1)} bpm vs baseline` : 'Baseline pending';
  if (sessionStarted !== null) {
    const elapsed = Math.floor((Date.now() - sessionStarted) / 1000);
    $('session-time').textContent = `${String(Math.floor(elapsed / 60)).padStart(2,'0')}:${String(elapsed % 60).padStart(2,'0')}`;
    const active = s.fresh || heartFresh;
    $('session-label').textContent = active ? 'Session active' : 'Session · signals unavailable';
    $('session-dot').style.background = active ? '#359779' : '#b9782d';
    if (now - lastLog >= 1000) {
      lastLog = now;
      sessionLog.push({ time: new Date().toISOString(), level: s.level, basis: 'unvalidated camera rules',
        eyeClosureFraction: s.fresh && s.observed >= 15000 ? s.fraction : null,
        observedSeconds: s.observed / 1000, visibleCoverage: s.coverage, blinkEvents: s.fresh ? s.blinkCount : null,
        currentClosureSeconds: s.fresh ? s.currentClosure : null, heartRateBpm: heartFresh ? heart.bpm : null,
        heartRateSource: heartFresh ? heart.name : null, processingMs: s.fresh ? processingMs : null });
      if (sessionLog.length > 36000) sessionLog.shift();
    }
  }
  drawHeartChart();
}

function drawHeartChart() {
  const canvas = $('heart-chart'), ctx = canvas.getContext('2d');
  const rect = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(rect.width * ratio) || canvas.height !== Math.round(rect.height * ratio)) {
    canvas.width = Math.round(rect.width * ratio); canvas.height = Math.round(rect.height * ratio);
  }
  ctx.setTransform(ratio,0,0,ratio,0,0); ctx.clearRect(0,0,rect.width,rect.height);
  const pad = { left: 35, right: 16, top: 10, bottom: 25 };
  const width = rect.width - pad.left - pad.right, height = rect.height - pad.top - pad.bottom;
  const rows = heart.samples || [], now = Date.now() / 1000, start = now - 300;
  const valid = rows.filter(s => s.time >= start && s.time <= now);
  $('chart-empty').hidden = valid.length > 0;
  const low = valid.length ? Math.max(0, Math.floor((Math.min(...valid.map(s=>s.bpm)) - 8) / 10) * 10) : 40;
  const high = valid.length ? Math.ceil((Math.max(...valid.map(s=>s.bpm)) + 8) / 10) * 10 : 100;
  ctx.font = '9px -apple-system, sans-serif'; ctx.fillStyle = '#94a38d'; ctx.strokeStyle = '#edf1e9'; ctx.lineWidth = 1;
  for (let i=0; i<4; i++) {
    const y = pad.top + i * height / 3;
    ctx.beginPath(); ctx.moveTo(pad.left,y); ctx.lineTo(rect.width-pad.right,y); ctx.stroke();
    ctx.textAlign = 'right'; ctx.fillText(String(Math.round(high - i * (high-low) / 3)),pad.left-9,y+3);
  }
  ctx.textAlign = 'center';
  [0,1,2,3,4,5].forEach(i=>ctx.fillText(i === 5 ? 'Now' : `${5-i}m ago`,pad.left + i*width/5,rect.height-5));
  ctx.strokeStyle = '#368a6e'; ctx.lineWidth = 2; ctx.beginPath();
  let previous = null;
  valid.forEach(s=> {
    const x = pad.left + (s.time-start)/300*width, y = pad.top+(high-s.bpm)/(high-low)*height;
    if (previous === null || s.time-previous.time > 5) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    previous = s;
  }); ctx.stroke();
  if (valid.length) {
    const last = valid.at(-1); ctx.fillStyle = '#368a6e'; ctx.beginPath();
    ctx.arc(pad.left+(last.time-start)/300*width,pad.top+(high-last.bpm)/(high-low)*height,3,0,Math.PI*2); ctx.fill();
  }
}

$('export-button').addEventListener('click', () => {
  const payload = { app: 'Drowsy live prototype', exported: new Date().toISOString(), camera: cameraSelection,
    classification: 'observed metrics; drowsiness level is an unvalidated visual rule',
    model: 'MediaPipe Face Landmarker float16 v1; tasks-vision 0.10.21',
    thresholds: { closureScore: 0.55, elevatedSeconds: 0.8, highSeconds: 1.5, elevatedFraction: 0.12, highFraction: 0.25 },
    physiologicalFeaturesInLevel: false, samples: sessionLog };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)], { type:'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = `drowsy-session-${new Date().toISOString().replaceAll(':','-')}.json`;
  link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden && stream) { metrics.push(performance.now(), null); overlayContext.clearRect(0,0,overlay.width,overlay.height); }
});
window.addEventListener('pagehide', () => stopCamera());
navigator.mediaDevices?.addEventListener('devicechange', () => enumerateCameras().catch(()=>{}));
enumerateCameras().catch(()=>{});
pollWatch(); update(); setInterval(update,250);

// Keep model-file inference visibly separate from the live visual rule.
fetch('/api/health').then(response => {
  if (!response.ok) throw new Error('Models unavailable');
  return response.json();
}).then(state => {
  $('model-availability').textContent = state.models_loaded.includes('small_tcn') ? 'Small TCN loaded' : 'Unavailable';
}).catch(() => { $('model-availability').textContent = 'Unavailable'; });

let featureTestGeneration = 0;
$('feature-file').addEventListener('change', async event => {
  const current = ++featureTestGeneration;
  $('model-test-score').textContent = '—';
  const file = event.target.files?.[0];
  if (!file) { $('model-test-message').textContent = 'No feature file selected.'; return; }
  try {
    if (file.size > 512 * 1024) throw new Error('Choose a JSON feature file smaller than 512 KB.');
    const body = JSON.parse(await file.text());
    if (current !== featureTestGeneration) return;
    $('model-test-message').textContent = 'Running the model on your selected features…';
    const result = await request('/api/facial', body);
    if (current !== featureTestGeneration) return;
    $('model-test-score').textContent = (result.score * 100).toFixed(1);
    $('model-test-message').textContent = `${result.model === 'small_tcn' ? 'Small TCN' : 'Logistic regression'} · selected file · live indicator unchanged`;
  } catch (error) {
    if (current === featureTestGeneration) $('model-test-message').textContent = error.message || 'Feature inference failed.';
  }
});
