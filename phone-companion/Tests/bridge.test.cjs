'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../Web/bridge.js'), 'utf8');
function setup(native = true) {
  const messages = [], events = [], timers = new Map(); let timerID = 0;
  const window = { crypto: { randomUUID: () => `command-${messages.length}` }, dispatchEvent: event => events.push(event) };
  if (native) window.webkit = { messageHandlers: { drowsyRelay: { postMessage: msg => messages.push(msg) } } };
  const context = { window, CustomEvent: class { constructor(type, options) { this.type=type; this.detail=options.detail; } },
    setTimeout: fn => { timers.set(++timerID,fn); return timerID; }, clearTimeout: id => timers.delete(id) };
  vm.runInNewContext(source, context);
  window.DrowsyRelay._receive({protocol:1,type:'state',running:true,watchSession:'watch-1'});
  return { bridge: window.DrowsyRelay, messages, events, timers };
}
test('camera command waits for watch acceptance, not queued/submitted status', async () => {
  const {bridge,messages,timers} = setup();
  let finished=false;
  const promise=bridge.sendCameraAlert('high',Date.now()/1000).then(value=>{finished=true;return value;});
  assert.equal(messages[0].watchSession,'watch-1'); assert.equal(messages[0].type,'camera_alert');
  bridge._receive({protocol:1,type:'command_result',commandId:messages[0].commandId,status:'queued'});
  bridge._receive({protocol:1,type:'command_result',commandId:messages[0].commandId,status:'submitted'});
  await Promise.resolve(); assert.equal(finished,false);
  bridge._receive({protocol:1,type:'command_result',commandId:messages[0].commandId,status:'accepted'});
  assert.equal((await promise).status,'accepted'); assert.equal(timers.size,0);
});
test('scores preserve missing values, input sequence, capture time and model version', async () => {
  const {bridge,messages}=setup(); const capturedAt=Date.now()/1000-3;
  const promise=bridge.sendModelResult({riskScore:null,status:'insufficient_data',modelVersion:'test-v1',capturedAt,inputTelemetrySequence:12});
  assert.equal(messages[0].riskScore,null); assert.equal(messages[0].capturedAt,capturedAt); assert.equal(messages[0].inputTelemetrySequence,12);
  bridge._receive({protocol:1,type:'command_result',commandId:messages[0].commandId,status:'insufficient_data'});
  await assert.rejects(promise,/insufficient_data/);
});
test('invalid scores, stale commands and absent native host are rejected', async () => {
  const {bridge,messages}=setup();
  for(const score of [75,NaN,Infinity,true,null]) await assert.rejects(bridge.sendModelResult({riskScore:score,modelVersion:'v1',capturedAt:Date.now()/1000,inputTelemetrySequence:1}),/Invalid model result/);
  await assert.rejects(bridge.sendCameraAlert('high',Date.now()/1000-11),/Old or future/);
  await assert.rejects(setup(false).bridge.sendCameraAlert('high',Date.now()/1000),/inside DrowsyRelay/);
  assert.equal(messages.length,0);
});
test('telemetry is exposed unchanged and session changes clear the cached packet', () => {
  const {bridge,events}=setup(); const payload={session:'watch-1',sequence:1,heartRateBpm:null,gyroscope:null};
  bridge._receive({protocol:1,type:'telemetry',payload}); assert.equal(bridge.getLatestTelemetry(),payload);
  assert.equal(events.at(-1).type,'drowsy:telemetry');
  bridge._receive({protocol:1,type:'state',running:true,watchSession:'watch-2'}); assert.equal(bridge.getLatestTelemetry(),null);
});
test('bounded outstanding commands and receipt timeout do not report success', async () => {
  const {bridge,timers}=setup(); const promises=[];
  for(let i=0;i<8;i++) promises.push(bridge.sendCameraAlert('warning',Date.now()/1000).then(()=>{throw new Error('unexpected success');},error=>error.message));
  await assert.rejects(bridge.sendCameraAlert('high',Date.now()/1000),/Too many/);
  for(const callback of [...timers.values()]) callback();
  for(const result of await Promise.all(promises)) assert.match(result,/not confirmed/);
});
