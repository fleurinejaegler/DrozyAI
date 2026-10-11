import test from 'node:test';
import assert from 'node:assert/strict';
import { VisualMetrics, heartSummary } from '../web/static/metrics.mjs';

test('missing and stale face observations cannot produce Low', () => {
  const m = new VisualMetrics();
  assert.equal(m.snapshot(0).level, 'Waiting');
  for (let t=0; t<=20000; t+=100) m.push(t, 0.1);
  assert.equal(m.snapshot(20000).level, 'Low');
  assert.equal(m.snapshot(20600).level, 'Unavailable');
  m.push(20700,null);
  assert.equal(m.snapshot(20700).level, 'Unavailable');
});

test('rolling eye fraction is duration-weighted and excludes missing-face gaps', () => {
  const m = new VisualMetrics();
  m.push(0,1); m.push(100,1); m.push(400,0); m.push(500,0);
  m.push(1000,null); m.push(2000,0); m.push(2100,0);
  const s = m.snapshot(2100);
  assert.equal(s.observed,600);
  assert.ok(Math.abs(s.fraction-400/600)<1e-9);
  assert.equal(s.level,'Collecting');
});

test('continuous closure triggers cues before the rolling window is ready', () => {
  const m = new VisualMetrics();
  for (let t=0; t<=2000; t+=100) {
    m.push(t,0.9);
    if (t===800) assert.equal(m.snapshot(t).level,'Elevated');
    if (t===1500) assert.equal(m.snapshot(t).level,'High');
  }
  m.push(3000,0.9);
  assert.equal(m.snapshot(3000).currentClosure,0);
});

test('one closure is counted once, and interruptions are not blink events', () => {
  const m = new VisualMetrics();
  m.push(0,0.1); m.push(100,0.9); m.push(200,0.9); m.push(300,0.1);
  assert.equal(m.snapshot(300).blinkCount,1);
  assert.equal(m.snapshot(300).blinkDuration,200);
  m.push(400,0.9); m.push(500,null); m.push(600,0.1);
  assert.equal(m.snapshot(600).blinkCount,1);
});

test('old history expires and insufficient coverage cannot become Low', () => {
  const m = new VisualMetrics();
  for (let t=0;t<=20000;t+=100) m.push(t,0.1);
  m.push(50000,0.1);
  assert.equal(m.snapshot(50000).level,'Collecting');
  m.push(90000,0.1);
  assert.equal(m.snapshot(90000).observed,0);
});

test('BPM trends wait for baseline coverage and reject stale readings', () => {
  assert.deepEqual(heartSummary([],100),{bpm:null,delta:null});
  assert.equal(heartSummary([{time:99,bpm:60}],100).delta,null);
  const rows = Array.from({length:40},(_,i)=>({time:i,bpm:i<=30?60:70}));
  assert.equal(heartSummary(rows,39).delta,10);
  assert.equal(heartSummary(rows,45).bpm,null);
});
