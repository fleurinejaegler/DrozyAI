import test from 'node:test';
import assert from 'node:assert/strict';
import { ScoreDisplay } from '../web/static/score-display.mjs';

test('real zero remains visible during gaps without becoming a fresh score', () => {
  const display=new ScoreDisplay();
  assert.equal(display.snapshot(null,false,1000).state,null);
  const result={status:'ok',score:0,drowsiness_score:0,window_end_ms:1000};
  assert.equal(display.snapshot(result,true,1500).state.score,0);
  const held=display.snapshot({status:'collecting',score:null},false,13500);
  assert.equal(held.state.score,0);assert.equal(held.fresh,false);assert.equal(held.ageSeconds,12);
});

test('new predictions replace history; invalid values and session changes cannot reuse it', () => {
  const display=new ScoreDisplay();
  display.snapshot({status:'ok',score:.7,drowsiness_score:70,window_end_ms:1000},true,1500);
  assert.equal(display.snapshot({status:'ok',score:.2,drowsiness_score:20,window_end_ms:6000},true,6500).state.score,.2);
  assert.equal(display.snapshot({status:'ok',score:NaN},true,7000).state.score,.2);
  display.reset();assert.equal(display.snapshot(null,false,8000).state,null);
});
