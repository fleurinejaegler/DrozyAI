/* Native WKWebView bridge. Also loads in a normal browser for UI development. */
(() => {
  'use strict';
  if (window.DrowsyRelay) return;
  let state = { running: false, watchSession: null, telemetryRecent: false };
  let latest = null;
  const pending = new Map();
  const emit = (name, detail) => window.dispatchEvent(new CustomEvent(`drowsy:${name}`, { detail }));
  const identifier = () => window.crypto?.randomUUID?.() ?? `cmd-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  function send(type, fields) {
    const native = window.webkit?.messageHandlers?.drowsyRelay;
    if (!native) return Promise.reject(new Error('Open this page inside DrowsyRelay on iPhone.'));
    if (!state.running || !state.watchSession) return Promise.reject(new Error('Watch handshake not ready or relay paused.'));
    const age = Date.now() / 1000 - fields.capturedAt;
    if (!finite(fields.capturedAt) || age > 10 || age < -2) return Promise.reject(new Error('Old or future result rejected.'));
    if (pending.size >= 8) return Promise.reject(new Error('Too many commands awaiting delivery.'));
    const command = { protocol: 1, commandId: identifier(), type, watchSession: state.watchSession, ...fields };
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(command.commandId); reject(new Error('Watch acceptance not confirmed within 12 seconds.'));
      }, 12000);
      pending.set(command.commandId, { resolve, reject, timer });
      try { native.postMessage(command); }
      catch (error) { clearTimeout(timer); pending.delete(command.commandId); reject(error); }
    });
  }
  window.DrowsyRelay = Object.freeze({
    getState: () => ({ ...state }),
    getLatestTelemetry: () => latest,
    sendModelResult({ riskScore, status = 'ready', modelVersion, capturedAt, inputTelemetrySequence }) {
      if (!['ready', 'insufficient_data', 'model_not_connected'].includes(status) ||
          (status === 'ready' ? !finite(riskScore) || riskScore < 0 || riskScore > 1 : riskScore !== null) ||
          typeof modelVersion !== 'string' || !modelVersion || modelVersion.length > 64 ||
          !Number.isInteger(inputTelemetrySequence) || inputTelemetrySequence < 1) {
        return Promise.reject(new Error('Invalid model result; score must be 0–1 or explicitly missing.'));
      }
      return send('model_result', { riskScore, status, modelVersion, capturedAt, inputTelemetrySequence });
    },
    sendCameraAlert(severity, capturedAt) {
      if (!['warning', 'high'].includes(severity)) return Promise.reject(new Error('Invalid camera severity.'));
      return send('camera_alert', { severity, capturedAt });
    },
    clearCameraAlert(capturedAt) { return send('camera_clear', { capturedAt }); },
    _receive(event) {
      if (!event || event.protocol !== 1) return;
      if (event.type === 'state') {
        if (state.watchSession && state.watchSession !== event.watchSession) latest = null;
        state = { ...event }; emit('state', state);
      } else if (event.type === 'telemetry') {
        latest = event.payload; state.watchSession = latest.session; state.telemetryRecent = true;
        emit('telemetry', latest);
      } else if (event.type === 'watch_message') {
        emit('watch', event.payload);
      } else if (event.type === 'model_result') {
        emit('model', event);
      } else if (event.type === 'command_result') {
        emit('delivery', event);
        if (event.status === 'queued' || event.status === 'submitted') return;
        const item = pending.get(event.commandId);
        if (!item) return;
        clearTimeout(item.timer); pending.delete(event.commandId);
        if (event.status === 'accepted') item.resolve(event);
        else item.reject(new Error(`Watch command: ${event.status}`));
      }
    }
  });
})();
