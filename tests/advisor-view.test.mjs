import test from 'node:test';
import assert from 'node:assert/strict';
import { advisorView } from '../web/static/advisor-view.mjs';

const health={compute_host:'GX10',local_llm:{enabled:true,model:'llama3.2:3b'}};
test('fresh LLM explanation appears with its compute host and timing',()=>{
  const view=advisorView({advice:{source:'llm',reason:'Eyes stayed open.',latency_ms:820}},true,health);
  assert.equal(view.text,'Eyes stayed open.');assert.equal(view.label,'Live explanation');
  assert.equal(view.detail,'GX10 · llama3.2:3b · 0.8s');
});
test('stale explanations are hidden instead of presented as current advice',()=>{
  const view=advisorView({advice:{source:'llm',reason:'Old explanation'}},false,health);
  assert.equal(view.label,'Waiting for data');assert.ok(!view.text.includes('Old explanation'));
});
test('fallback and pending advice never claim to be LLM output',()=>{
  for(const llm_status of ['generating','fallback']){
    const view=advisorView({advice:{source:'fallback',reason:'Automatic advice',llm_status}},true,health);
    assert.notEqual(view.label,'Live explanation');assert.equal(view.text,'Automatic advice');
  }
});
