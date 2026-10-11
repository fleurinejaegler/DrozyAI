'use strict';
// Local demo transport only: no classifier, no persistence, no external dependencies.
const http = require('node:http');
const crypto = require('node:crypto');

function createRelayServer({ token, allowOrigin = '', now = () => Date.now() / 1000 } = {}) {
  if (typeof token !== 'string' || token.length < 16) throw new Error('A pairing token of 16+ characters is required.');
  const clients = new Map();
  function reply(res, status, body) { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(body)); }
  function authenticated(req) {
    const expected = Buffer.from(`Bearer ${token}`), actual = Buffer.from(req.headers.authorization || '');
    return actual.length === expected.length && crypto.timingSafeEqual(actual, expected);
  }
  async function read(req) {
    const parts = []; let count = 0;
    for await (const part of req) { count += part.length; if (count > 65536) throw new Error('Request too large'); parts.push(part); }
    return JSON.parse(Buffer.concat(parts).toString('utf8'));
  }
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const recent = stamp => finite(stamp) && now() - stamp <= 10 && now() - stamp >= -2;
  function validate(command, state) {
    if (!command || command.protocol !== 1 || typeof command.commandId !== 'string' || !command.commandId || command.commandId.length > 128) return 'invalid_command';
    if (!state || !state.running || now() - state.lastPhoneAt > 10) return 'phone_unavailable';
    if (command.watchSession !== state.watchSession || !state.watchSession) return 'wrong_session';
    if (!recent(command.capturedAt)) return 'stale';
    if (command.type === 'model_result') {
      if (!['ready', 'insufficient_data', 'model_not_connected'].includes(command.status)) return 'invalid_model_status';
      if (command.status === 'ready' ? !finite(command.riskScore) || command.riskScore < 0 || command.riskScore > 1 : command.riskScore !== null) return 'invalid_score';
      if (typeof command.modelVersion !== 'string' || !command.modelVersion || command.modelVersion.length > 64) return 'invalid_model_version';
      if (!Number.isInteger(command.inputTelemetrySequence)) return 'invalid_input_sequence';
      const stamp = state.inputs.get(command.inputTelemetrySequence);
      if (!recent(stamp) || command.capturedAt < stamp - 2) return 'unknown_or_stale_input';
    } else if (command.type === 'camera_alert') {
      if (!['warning', 'high'].includes(command.severity)) return 'invalid_severity';
    } else if (command.type !== 'camera_clear') return 'invalid_type';
    return null;
  }
  const server = http.createServer(async (req, res) => {
    if (allowOrigin && req.headers.origin === allowOrigin) {
      res.setHeader('Access-Control-Allow-Origin', allowOrigin);
      res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type');
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
      res.setHeader('Vary', 'Origin');
    }
    if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }
    if (!authenticated(req)) { reply(res, 401, { error: 'unauthorized' }); return; }
    try {
      const url = new URL(req.url, 'http://relay.local');
      if (req.method === 'POST' && url.pathname === '/api/phone/exchange') {
        const body = await read(req);
        if (!body || body.protocol !== 1 || typeof body.clientId !== 'string' || !/^[\w-]{1,64}$/.test(body.clientId) ||
            typeof body.relaySession !== 'string' || body.relaySession.length > 128 ||
            !(body.watchSession === null || typeof body.watchSession === 'string') || typeof body.running !== 'boolean') {
          reply(res, 400, { error: 'invalid_exchange' }); return;
        }
        let state = clients.get(body.clientId);
        if (!state) {
          if (clients.size >= 16) { reply(res, 429, { error: 'too_many_clients' }); return; }
          state = { queue: [], seen: [], events: [], inputs: new Map() }; clients.set(body.clientId, state);
        }
        if (state.watchSession !== body.watchSession || state.relaySession !== body.relaySession) {
          state.queue = []; state.inputs.clear(); state.telemetry = null;
        }
        Object.assign(state, { watchSession: body.watchSession, relaySession: body.relaySession, running: body.running, lastPhoneAt: now() });
        const packet = body.telemetry;
        if (packet && packet.type === 'telemetry' && packet.source === 'watch_sensors' && packet.schema === 1 &&
            packet.session === state.watchSession && Number.isInteger(packet.sequence) && recent(packet.sentAt)) {
          state.telemetry = packet; state.inputs.set(packet.sequence, packet.sentAt);
        }
        for (const [seq, stamp] of state.inputs) if (!recent(stamp)) state.inputs.delete(seq);
        // Network retries may repeat events; consumers deduplicate by commandId/status.
        if (Array.isArray(body.events)) state.events = state.events.concat(body.events.slice(-32)).slice(-64);
        const commands = state.queue.filter(command => !validate(command, state)).slice(0, 8);
        state.queue = []; // No automatic replay: phone receipts determine final delivery.
        reply(res, 200, { protocol: 1, commands }); return;
      }
      if (req.method === 'GET' && url.pathname === '/api/state') {
        const state = clients.get(url.searchParams.get('clientId') || 'demo');
        if (!state) { reply(res, 404, { error: 'phone_not_connected' }); return; }
        reply(res, 200, { protocol: 1, watchSession: state.watchSession, phoneRecent: state.running && now() - state.lastPhoneAt <= 10,
          telemetry: state.telemetry && recent(state.telemetry.sentAt) ? state.telemetry : null, events: state.events }); return;
      }
      if (req.method === 'POST' && url.pathname === '/api/command') {
        const body = await read(req), state = clients.get(body.clientId || 'demo'), command = body.command;
        const error = validate(command, state);
        if (error) { reply(res, 422, { error }); return; }
        if (state.seen.includes(command.commandId)) { reply(res, 409, { error: 'duplicate' }); return; }
        // Latest model result replaces an older pending model result; cameras retain ordering.
        if (command.type === 'model_result') state.queue = state.queue.filter(item => item.type !== 'model_result');
        if (state.queue.length >= 8) { reply(res, 429, { error: 'command_queue_full' }); return; }
        state.queue.push(command); state.seen.push(command.commandId); state.seen = state.seen.slice(-128);
        reply(res, 202, { protocol: 1, commandId: command.commandId, status: 'queued' }); return;
      }
      reply(res, 404, { error: 'not_found' });
    } catch (error) { reply(res, 400, { error: 'invalid_request' }); }
  });
  server.requestTimeout = 10000; server.headersTimeout = 10000;
  return server;
}
module.exports = { createRelayServer };
if (require.main === module) {
  const token = process.env.DROWSY_RELAY_TOKEN || crypto.randomBytes(24).toString('hex');
  const port = Number(process.env.PORT || 8765), host = process.env.HOST || '127.0.0.1';
  const server = createRelayServer({ token, allowOrigin: process.env.DROWSY_RELAY_ORIGIN || '' });
  server.on('error', error => { console.error(error.message); process.exitCode = 1; });
  server.listen(port, host, () => {
    console.log(`Local relay listening on ${host}:${port}`);
    console.log(`Pairing token: ${token}`);
    console.log('Client ID: demo. Enter the laptop LAN address on iPhone, not localhost.');
  });
}
