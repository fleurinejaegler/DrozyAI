import { VisualMetrics, heartSummary } from './metrics.mjs';
import { LiveModelFeatures } from './model-features.mjs';
import { ScoreDisplay } from './score-display.mjs';
import { advisorView } from './advisor-view.mjs';
import { ModelScoreDisplay, watchReadings } from './dashboard-readings.mjs';

const $ = id => document.getElementById(id);
const metrics = new VisualMetrics();
const modelFeatures = new LiveModelFeatures();
const scoreDisplay = new ScoreDisplay();
const modelScoreDisplay = new ModelScoreDisplay();
let relayInfo = null, relayReceived = 0;
const browserSession = 'browser-'+crypto.randomUUID();
let modelIdentity = { device_id:'demo', session_id:browserSession, data_origin:'live' };
let relaySamples = [];
let modelState = null, modelReceived = 0, modelSending = false, modelMessage = 'Waiting for sensor windows';
let backendHealth = {};
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
  request('/api/live/video/stop',modelIdentity).catch(()=>{});
  modelFeatures.reset(); modelState=null;
  stream?.getTracks().forEach(track => track.stop());
  stream = null;
  worker?.terminate(); worker = null; ready = false; busy = false; trackAvailable = false;
  $('video').srcObject = null; $('camera-placeholder').hidden = false;
  overlayContext.clearRect(0, 0, overlay.width, overlay.height);
  $('camera-button').innerHTML = 'Start camera <span>↗</span>';
  $('camera-select').disabled = false;
  $('recalibrate-button').disabled = true;
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
        ready = true; cameraStatus('Live', true);
        $('recalibrate-button').disabled = false;
        $('camera-message').textContent = 'First 15 seconds: look ahead normally. Later scores use sustained changes from this baseline; ordinary blinks are tolerated.';
        if (sessionStarted === null) sessionStarted = Date.now();
        requestAnimationFrame(loop);
      } else if (data.type === 'result') {
        busy = false;
        // Reject old results; a slow or interrupted pipeline is not current evidence.
        if (performance.now() - data.t > 500 || !trackAvailable || document.hidden) {
          metrics.push(performance.now(), null); modelFeatures.push(performance.timeOrigin+performance.now(),null); return;
        }
        metrics.push(data.t, data.closure);
        modelFeatures.push(performance.timeOrigin+data.t, data.ratios);
        sendVideoWindow(performance.now(), localGeneration);
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
    metrics.push(now, null); modelFeatures.push(performance.timeOrigin+now,null); return;
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
  const inputFresh = now-modelReceived<modelState?.valid_for_ms;
  const modelFresh = modelState?.status==='ok' && inputFresh;
  const displayed = scoreDisplay.snapshot(modelState, modelFresh, Date.now());
  const level = modelFresh ? (modelState.score>=0.90?'High':modelState.score>=0.70?'Elevated':'Low') : stream?'Collecting':'Waiting';
  $('level').textContent = displayed.state ? displayed.state.drowsiness_score.toFixed(1) : level;
  $('level-panel').dataset.level = level;
  $('level-subtitle').textContent = modelFresh ? 'MODEL SCORE / 100' : displayed.state ? `LAST SCORE / 100 · ${displayed.ageSeconds}s old` : 'COLLECTING MODEL INPUTS';
  $('level-reason').textContent = modelFresh ? modelState.advice.action+' · '+modelState.advice.reason : modelMessage;
  $('level-source-text').textContent = modelFresh ? (modelState.mode==='watch_video' ? 'Watch + video · 50/50 average' : modelState.mode==='watch_only'?'Watch model only':'Video model only') : displayed.state ? 'Last prediction · waiting for fresh inputs' : 'Models connected · waiting for data';
  $('component-scores').textContent = modelFresh ? `Watch ${modelState.watch_score===null?'—':(modelState.watch_score*100).toFixed(1)} · Video ${modelState.facial_score===null?'—':(modelState.facial_score*100).toFixed(1)} · ${modelState.advice.source}` : 'Watch — · Video —';
  const scores = modelScoreDisplay.snapshot(modelState, inputFresh, Date.now());
  for (const name of ['watch','video']) {
    $('score-'+name).textContent = scores[name].value;
    $('score-'+name+'-note').textContent = scores[name].note;
  }
  const readings = watchReadings(relayInfo, performance.now()-relayReceived);
  $('blood-oxygen').textContent = readings.oxygen.value;
  $('oxygen-note').textContent = readings.oxygen.note;
  $('watch-temperature').textContent = readings.temperature.value;
  $('temperature-card-note').textContent = readings.temperature.note;
  const advisor = advisorView(modelState, modelFresh, backendHealth);
  $('advisor-status').textContent = advisor.label;
  $('advisor-status').classList.toggle('live', modelFresh && modelState?.advice?.source === 'llm');
  $('advisor-explanation').textContent = advisor.text;
  $('advisor-detail').textContent = advisor.detail;
  const fill = displayed.state ? displayed.state.drowsiness_score : 0;
  $('gauge-fill').style.strokeDasharray = `${fill} 100`;
  $('eye-fraction').textContent = s.fresh && s.observed >= 15000 ? (s.fraction * 100).toFixed(1) : '—';
  $('blink-count').textContent = s.fresh && s.observed >= 15000 ? s.blinkCount : '—';
  $('closure-duration').textContent = s.fresh ? s.currentClosure.toFixed(1) : '—';
  $('coverage').textContent = s.observed > 0 ? `${Math.round(s.coverage * 100)}%` : '—';
  $('coverage-fill').style.width = `${s.coverage * 100}%`;
  if (stream && ready) $('fps').textContent = `${(frameTimes.filter(t => now - t <= 2000).length / 2).toFixed(0)} fps`;
  if (stream && ready && !s.fresh) { $('tracking-label').textContent = 'No current eye observations'; overlayContext.clearRect(0,0,overlay.width,overlay.height); }
  const relayBpm=modelState?.relay?.heart_rate_bpm;
  if(Number.isFinite(relayBpm))heart={...heart,status:'connected',bpm:relayBpm,name:'Garmin app via phone',message:modelState.relay.note,samples:relaySamples};
  const heartFresh = heart.status === 'connected' && heart.bpm !== null;
  $('heart-rate').textContent = heartFresh ? heart.bpm : '—';
  $('heart-note').textContent = heartFresh ? 'Live · Garmin Bluetooth' : heart.status === 'stale' ? 'Signal stale · waiting for watch' : 'Watch not connected';
  $('watch-name').textContent = heart.name || 'Garmin Forerunner 970';
  $('watch-state').textContent = ({ disconnected: 'Not connected', scanning: 'Scanning nearby', connecting: 'Connecting…', connected: heartFresh ? 'Heart rate streaming' : 'Waiting for heart rate', stale: 'Connected · signal stale', unavailable: 'Unavailable' })[heart.status] || 'Unavailable';
  $('watch-dot').style.background = heartFresh ? '#359779' : heart.status === 'stale' ? '#b9782d' : '#c9d1c5';
  if (!$('watch-devices').childElementCount && heart.message) $('watch-message').textContent = heart.message;
  $('disconnect-button').hidden = Number.isFinite(relayBpm) || !['connected','connecting','stale'].includes(heart.status);
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
      sessionLog.push({ time: new Date().toISOString(), level: s.level, basis: modelFresh ? 'connected models; uncalibrated transfer' : 'collecting', modelScore: modelFresh ? modelState.score : null, mode: modelFresh ? modelState.mode : null,
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
    classification: 'uncalibrated model scores; Garmin and RGB transfer experimental',
    model: 'MediaPipe Face Landmarker float16 v1; tasks-vision 0.10.21',
    thresholds: { closureScore: 0.55, elevatedSeconds: 0.8, highSeconds: 1.5, elevatedFraction: 0.12, highFraction: 0.25 },
    physiologicalFeaturesInLevel: modelState?.mode==='watch_video'||modelState?.mode==='watch_only', samples: sessionLog };
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
pollWatch(); pollModels(); update(); setInterval(update,250);

// Keep model-file inference visibly separate from the live visual rule.
fetch('/api/health').then(response => {
  if (!response.ok) throw new Error('Models unavailable');
  return response.json();
}).then(state => {
  backendHealth = state;
  $('compute-location').textContent = state.compute_host === 'GX10' ? 'Processing on GX10' : 'Local processing';
  $('model-availability').textContent = state.models_loaded.includes('small_tcn') ? 'Small TCN loaded' : 'Unavailable';
}).catch(() => { $('model-availability').textContent = 'Unavailable'; });

let featureTestGeneration = 0;
$('advisor-sample-button').addEventListener('click', async () => {
  const button = $('advisor-sample-button'), output = $('advisor-sample-result');
  button.disabled = true; output.hidden = false; output.textContent = 'Generating a sample explanation…';
  try {
    const sample = await request('/api/advisor/sample');
    output.textContent = `Sample inputs · ${sample.advice.source === 'llm' ? 'Local AI' : 'Automatic advice'}: ${sample.advice.reason}`;
  } catch (error) { output.textContent = error.message || 'Sample explanation unavailable.'; }
  finally { button.disabled = false; }
});
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
    const endpoint = body.watch_features || body.facial ? '/api/fusion' : body.hr_mean!==undefined || body.features?.hr_mean!==undefined ? '/api/score' : '/api/facial';
    const result = await request(endpoint, body);
    if (current !== featureTestGeneration) return;
    $('model-test-score').textContent = (result.score * 100).toFixed(1);
    $('model-test-message').textContent = `${result.model || result.mode} · selected file · ${result.advice?.reason || 'live indicator unchanged'}`;
  } catch (error) {
    if (current === featureTestGeneration) $('model-test-message').textContent = error.message || 'Feature inference failed.';
  }
});


async function sendVideoWindow(now, activeGeneration) {
  if(modelSending)return;
  const window = modelFeatures.window(performance.timeOrigin+now);
  if(!window)return;
  if(window.status) { modelMessage=window.status; return; }
  modelSending=true;
  const identity={...modelIdentity};
  try {
    const result=await request('/api/live/video',{...identity,model:'small_tcn',schema_id:'facial.rgb.geometry.v1',
      sequence:window.sequence,channels:window.channels,features:window.features,
      baseline_reference:window.baselineReference,
      quality:{transfer:'experimental_rgb_mesh',geometry_reference_seconds:15,
               trends_available:window.trendsAvailable},
      window:{start_ms:Math.round(window.startRelativeMs),end_ms:Math.round(window.endRelativeMs)}});
    if(activeGeneration===generation && identity.session_id===modelIdentity.session_id) {
      modelState=result; modelReceived=performance.now(); modelMessage='Waiting for next model window';
    }
  } catch(error) { modelMessage=error.message; }
  finally { modelSending=false; }
}

$('recalibrate-button').addEventListener('click',async()=>{
  if(starting)return;
  stopCamera('Resetting the neutral camera baseline…');
  modelScoreDisplay.clear('video');
  await startCamera();
});

async function pollModels() {
  try {
    const response=await fetch('/api/live/state?'+new URLSearchParams(modelIdentity));
    if(!response.ok)throw new Error('Connected models unavailable');
    const result=await response.json();
    relayInfo=result.relay; relayReceived=performance.now();
    const desired=result.relay.watch_session||browserSession;
    if(desired!==modelIdentity.session_id) {
      request('/api/live/video/stop',modelIdentity).catch(()=>{});
      modelIdentity={device_id:result.relay.client_id,session_id:desired,data_origin:'live'};
      modelFeatures.reset(); modelState=null; relaySamples=[];
      // Keep labelled display history through reconnects; model sessions reset above.
    } else { modelState=result; modelReceived=performance.now(); }
    const quality=result.relay.quality||{};
    if(result.reason==='PARTIAL_VIDEO_PROVISIONAL')modelMessage='Partial video output is provisional; collecting data for the trained 60-second model.';
    $('motion-note').textContent=quality.motion_carried_seconds ? `Motion: last variance carried over ${quality.motion_carried_seconds}/60s (max gap 5s). HR held over ${quality.hr_carried_seconds||0}/60s (max gap 3s).` : 'Motion: using measured samples';
    const temp=quality.temperature_c;
    $('temperature-note').textContent=temp===undefined||temp===null?'Temperature: waiting for first reading':
      `Temperature ${temp.toFixed(1)} °C · last real reading ${quality.temperature_age_ms===null?'age unknown':Math.round(quality.temperature_age_ms/1000)+' s ago'}${quality.temperature_carried?' · carried':''}`;
    if(quality.missing?.length && !stream)modelMessage='Waiting for '+quality.missing.join(', ');
    if(result.relay.heart_rate_bpm!==null && result.relay.heart_rate_bpm!==undefined) {
      const time=result.relay.heart_rate_time_s;
      if(Number.isFinite(time) && (!relaySamples.length || relaySamples.at(-1).time!==time))
        relaySamples.push({time,bpm:result.relay.heart_rate_bpm});
      relaySamples=relaySamples.filter(sample=>Date.now()/1000-sample.time<=300).slice(-300);
      heart={...heart,status:'connected',bpm:result.relay.heart_rate_bpm,name:'Garmin app via phone',message:result.relay.note,samples:relaySamples};
    }
    $('relay-status').textContent=result.relay.status.replaceAll('_',' ')+(result.relay.delivery?' · '+result.relay.delivery.state.replaceAll('_',' '):'');
  } catch(error) { modelState=null; modelMessage=error.message; }
  setTimeout(pollModels,1000);
}


$('pairing-button').addEventListener('click',async()=>{
  const area=$('pairing-details');
  if(!area.hidden) { area.hidden=true;area.textContent='';return; }
  try {
    const setup=await request('/api/setup');
    area.textContent=`Phone URL: ${setup.phone_urls.join(' or ')||`use your Mac Wi-Fi IP with port ${setup.relay_port}`} | Client: ${setup.client_id} | Pairing token: ${setup.pairing_token}`;
    area.hidden=false;
  } catch(error) { area.textContent=error.message;area.hidden=false; }
});
