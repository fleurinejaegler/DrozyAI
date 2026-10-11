import test from 'node:test';
import assert from 'node:assert/strict';
import {ModelScoreDisplay, watchReadings} from '../web/static/dashboard-readings.mjs';

test('missing oxygen is unavailable and carried temperature keeps its age',()=>{
  const result=watchReadings({spo2_percent:null,quality:{temperature_c:27.5,temperature_age_ms:12000,temperature_carried:true}},1000);
  assert.equal(result.oxygen.value,'—');
  assert.equal(result.temperature.value,'27.5');
  assert.match(result.temperature.note,/13s old/);
});
test('oxygen measurement age advances without repeated polls making it fresh',()=>{
  const relay={spo2_percent:98,spo2_age_ms:1000,spo2_status:'live'};
  assert.equal(watchReadings(relay).oxygen.value,'98');
  assert.match(watchReadings(relay,10000).oxygen.note,/Last reading · 11s old/);
  assert.equal(watchReadings({...relay,spo2_percent:101}).oxygen.value,'—');
});
test('individual scores retain real zero during gaps and refresh independently',()=>{
  const display=new ModelScoreDisplay();
  const state={status:'ok',components:{watch:{score:0,window_end_ms:1000},video:{score:.9,window_end_ms:1000}}};
  let result=display.snapshot(state,true,1000);
  assert.equal(result.watch.value,'0.0');assert.equal(result.video.value,'90.0');
  result=display.snapshot({status:'ok',components:{video:{score:.8,window_end_ms:12000}}},true,12000);
  assert.match(result.watch.note,/Last score · 11s old/);assert.equal(result.video.value,'80.0');
  assert.equal(display.snapshot(null,false,20000).video.value,'80.0');
  assert.equal(new ModelScoreDisplay().snapshot(null,false,1000).watch.value,'—');
});

test('partial video is displayed as provisional while the main score remains unavailable',()=>{
  const display=new ModelScoreDisplay();
  const state={status:'provisional',score:null,components:{video:{score:1,window_end_ms:1000,
    quality:{partial_window:true,observed_seconds:12}}}};
  const result=display.snapshot(state,true,1000);
  assert.equal(result.video.value,'100.0');
  assert.match(result.video.note,/Provisional · 12.0\/60s observed · excluded from alerts/);
  assert.equal(result.watch.value,'—');
});

test('baseline adjustment is labelled with the unchanged raw model score',()=>{
  const display=new ModelScoreDisplay();
  const state={status:'ok',components:{video:{score:.4,window_end_ms:1000,
    quality:{baseline_adjusted:true,raw_score:1,baseline_deviation:.4}}}};
  const result=display.snapshot(state,true,1000);
  assert.equal(result.video.value,'40.0');
  assert.match(result.video.note,/15s baseline · raw model 100.0\/100 · deviation 40%/);
  display.clear('video');
  assert.equal(display.snapshot(null,false,2000).video.value,'—');
});
