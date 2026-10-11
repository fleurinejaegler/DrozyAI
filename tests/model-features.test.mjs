import test from 'node:test';
import assert from 'node:assert/strict';
import { LiveModelFeatures,CHANNELS } from '../web/static/model-features.mjs';

test('video uses actual geometry and produces the complete saved model schema',()=>{
 const a=new LiveModelFeatures();
 for(let t=0;t<=76000;t+=50)a.push(t,[.3,.3,.1]);
 const out=a.window(76000);
 assert.deepEqual(out.channels,CHANNELS);
 assert.equal(out.sequence.length,15);assert.equal(out.sequence[0].length,60);
 assert.equal(Object.keys(out.features).length,22);
 assert.ok(out.sequence[0].every(x=>Math.abs(x-1)<1e-6));
 assert.ok(out.sequence[14].every(x=>x>.99));
 assert.equal(out.features.blinks_per_minute,0);
 assert.equal(a.window(77000),null);
});
test('tracking gaps are not filled and cannot become full coverage',()=>{
 const a=new LiveModelFeatures();
 for(let t=0;t<=16000;t+=50)a.push(t,[.3,.3,.1]);
 for(let t=70000;t<=76000;t+=50)a.push(t,[.3,.3,.1]);
 assert.match(a.window(76000).status,/observed seconds/);
});
test('a completed short closure becomes a blink used by prediction',()=>{
 const a=new LiveModelFeatures();
 for(let t=0;t<=76000;t+=50)a.push(t,[t>=30000&&t<30300?.1:.3,t>=30000&&t<30300?.1:.3,.1]);
 const out=a.window(76000);
 assert.equal(out.sequence[6].reduce((a,b)=>a+b),1);
 assert.ok(out.features.blinks_per_minute>0);
 assert.ok(out.features.eye_closed_fraction>0);
});
test('reset clears calibration and all history',()=>{
 const a=new LiveModelFeatures();for(let t=0;t<=76000;t+=50)a.push(t,[.3,.3,.1]);
 a.reset();assert.match(a.window(76000).status,/Calibrating/);
 assert.equal(a.baselineReference,null);
});

test('the first 15 seconds freeze neutral geometry and later changes do not move it',()=>{
 const a=new LiveModelFeatures();
 for(let t=0;t<=16000;t+=50)a.push(t,[.3,.3,.1]);
 const baseline=[...a.baselineReference];
 for(let t=16050;t<=76000;t+=50)a.push(t,[.15,.15,.5]);
 assert.deepEqual(a.window(76000).baselineReference,baseline);
 assert.ok(Math.abs(baseline[0]-1)<1e-9);
 assert.ok(Math.abs(baseline[9]-.1)<1e-9);
 assert.equal(baseline[2],0);
});

test('mouth opening already present in the baseline cannot become a new yawn',()=>{
 const a=new LiveModelFeatures();
 for(let t=0;t<=76000;t+=50)a.push(t,[.3,.3,.7]);
 const out=a.window(76000);
 assert.equal(out.features.mouth_open_fraction,0);
 assert.equal(out.features.longest_mouth_open_seconds,0);
});

test('camera window boundaries align to UTC multiples of five seconds',()=>{
 const a=new LiveModelFeatures(), epoch=1790000000234;
 for(let t=epoch;t<=epoch+81000;t+=50)a.push(t,[.3,.3,.1]);
 const out=a.window(epoch+81000);
 assert.equal(out.endRelativeMs%5000,0);
 assert.equal(out.endRelativeMs-out.startRelativeMs,60000);
});

test('partial live windows use available geometry and preserve missing seconds',()=>{
 const a=new LiveModelFeatures();
 for(let t=0;t<=35000;t+=50)a.push(t,[.3,.3,.1]);
 const out=a.window(35000);
 assert.equal(out.partial,true);
 assert.ok(out.observedSeconds>=10 && out.observedSeconds<54);
 assert.ok(out.sequence[14].some(x=>x===0));
 assert.ok(Object.values(out.features).every(Number.isFinite));
 assert.equal(out.features.valid_frame_fraction,out.observedSeconds/60);
});

test('an empty recent view cannot produce a new partial-window prediction',()=>{
 const a=new LiveModelFeatures();
 for(let t=0;t<=50000;t+=50)a.push(t,[.3,.3,.1]);
 for(let t=50050;t<=65000;t+=50)a.push(t,null);
 assert.match(a.window(65000).status,/recent face observation/);
});
