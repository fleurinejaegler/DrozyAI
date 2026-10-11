const ageText = milliseconds => `${Math.max(0, Math.floor(milliseconds/1000))}s old`;
const validScore = value => Number.isFinite(value) && value >= 0 && value <= 1;

// Presentation history only: these values never enter inference or alert code.
export class ModelScoreDisplay {
  constructor() { this.last = {}; }
  clear(name) { delete this.last[name]; }
  snapshot(state, fresh, nowMs) {
    const output = {};
    for (const name of ['watch','video']) {
      const component = fresh && ['ok','provisional'].includes(state?.status) ? state.components?.[name] : null;
      const current = component && !component.quality?.baseline_recent_insufficient && validScore(component.score) && Number.isFinite(component.window_end_ms);
      if (current) this.last[name] = {...component};
      const saved = this.last[name];
      const quality=component?.quality||{};
      const baseline=quality.baseline_adjusted ? `15s baseline · raw model ${(quality.raw_score*100).toFixed(1)}/100 · deviation ${(quality.baseline_deviation*100).toFixed(0)}%` : '';
      output[name] = {value:saved ? (saved.score*100).toFixed(1) : '—',
        note:current ? quality.partial_window ? `Provisional · ${quality.observed_seconds.toFixed(1)}/60s observed · excluded from alerts${baseline ? ' · '+baseline : ''}` : baseline || (quality.motion_carried_seconds ? `Live · motion carried for ${quality.motion_carried_seconds}/60s` : 'Live model score') : saved ? `Last score · ${ageText(nowMs-saved.window_end_ms)}` : `Collecting ${name} inputs`};
    }
    return output;
  }
}

export function watchReadings(relay, elapsedMs=0) {
  const extra = Math.max(0, elapsedMs);
  const quality = relay?.quality || {};
  const oxygen = relay?.spo2_percent, temp = quality.temperature_c;
  const hasOxygen = Number.isFinite(oxygen) && oxygen > 0 && oxygen <= 100;
  const oxygenAge = Number.isFinite(relay?.spo2_age_ms) ? relay.spo2_age_ms+extra : null;
  const tempAge = Number.isFinite(quality.temperature_age_ms) ? quality.temperature_age_ms+extra : null;
  return {
    oxygen:{value:hasOxygen ? oxygen.toFixed(0) : '—',
      note:!hasOxygen ? 'No blood oxygen reading from watch' :
        relay.spo2_status==='live' && oxygenAge!==null && oxygenAge<=10000 ? 'Live · Garmin watch' :
        `Last reading · ${oxygenAge===null?'age unknown':ageText(oxygenAge)}`},
    temperature:{value:Number.isFinite(temp) ? temp.toFixed(1) : '—',
      note:Number.isFinite(temp) ? `Last reading · ${tempAge===null?'age unknown':ageText(tempAge)} · watch sensor` : 'Waiting for first reading'}
  };
}
