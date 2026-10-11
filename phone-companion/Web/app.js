'use strict';
const byId = id => document.getElementById(id);
let latest = null, receivedAt = 0, cameraStream = null, modelResult = null;
const number = value => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(value % 1 ? 1 : 0) : '--';
function render() {
  const packet = latest && Date.now() - receivedAt <= 10000 ? latest : {};
  byId('hr').textContent = number(packet.heartRateBpm);
  byId('spo2').textContent = number(packet.spo2Percent);
  byId('hrv').textContent = number(packet.hrvRmssdMs);
  byId('temperature').textContent = number(packet.temperatureC);
  byId('freshness').textContent = packet.sequence ? 'LIVE' : 'NO RECENT DATA';
  byId('motion').textContent = `Accelerometer: ${packet.accelerometer?.x?.length ?? '--'} samples · Gyroscope: ${packet.gyroscope?.x?.length ?? '--'} samples`;
  if (modelResult) {
    const model = modelResult.payload;
    byId('model').textContent = modelResult.accepted && model.status === 'ready' && Date.now()/1000-model.capturedAt <= 10
      ? `Vitals model risk: ${Math.round(model.riskScore*100)}/100 · ${model.modelVersion}`
      : `Risk: -- · ${modelResult.deliveryStatus === 'accepted' ? 'Result stale or missing' : modelResult.deliveryStatus}`;
  }
}
window.addEventListener('drowsy:telemetry', event => {
  latest = event.detail; receivedAt = Date.now(); render();
  byId('packet').textContent = JSON.stringify(latest, null, 2);
});
window.addEventListener('drowsy:state', event => {
  const state = event.detail;
  byId('connection').textContent = !state.running ? 'Relay paused.' : state.watchSession ? 'Watch linked. Live telemetry enabled.' : (state.watchConnectionStatus || 'Select the watch and open DrowsyAlert in live mode.');
});
window.addEventListener('drowsy:watch', event => {
  if (event.detail.type === 'user_acknowledged') byId('delivery').textContent = 'START acknowledged on watch; elevated status is retained.';
});
window.addEventListener('drowsy:model', event => { modelResult = event.detail; render(); });
window.addEventListener('drowsy:delivery', event => {
  byId('events').textContent = JSON.stringify(event.detail, null, 2);
});
async function manual(severity) {
  byId('delivery').textContent = 'Submitting manual command…';
  try {
    const time = Date.now()/1000;
    if (severity) await window.DrowsyRelay.sendCameraAlert(severity, time);
    else await window.DrowsyRelay.clearCameraAlert(time);
    byId('delivery').textContent = 'Watch accepted the command.';
  } catch (error) { byId('delivery').textContent = error.message; }
}
byId('warning').addEventListener('click', () => manual('warning'));
byId('high').addEventListener('click', () => manual('high'));
byId('clear').addEventListener('click', () => manual(null));
function stopCamera() {
  cameraStream?.getTracks().forEach(track => track.stop()); cameraStream = null;
  byId('camera').srcObject = null; byId('camera').style.display = 'none';
}
byId('start-camera').addEventListener('click', async () => {
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera capture is unavailable in this WebView. Validate capture on your target iPhone.');
    stopCamera(); cameraStream = await navigator.mediaDevices.getUserMedia({video:{facingMode:'user'},audio:false});
    byId('camera').srcObject = cameraStream; byId('camera').style.display = 'block';
    byId('camera-status').textContent = 'Local preview active. No video classifier connected.';
  } catch (error) { byId('camera-status').textContent = error.message; }
});
byId('stop-camera').addEventListener('click', stopCamera);
window.addEventListener('drowsy:pause', () => { stopCamera(); latest = null; modelResult = null; byId('model').textContent = 'Relay paused. Risk: --'; render(); });
window.addEventListener('pagehide', stopCamera);
setInterval(render, 1000);
