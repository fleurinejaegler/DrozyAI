// Prototype rules, not a trained drowsiness classifier. All time is monotonic ms.
export const WINDOW = 60000;
export const MIN_OBSERVED = 15000;
export const MAX_GAP = 500;
export const CLOSE_THRESHOLD = 0.55;

export class VisualMetrics {
  constructor() { this.reset(); }
  reset() {
    this.segments = []; this.blinks = []; this.last = null; this.closedAt = null;
    this.started = null; this.lastBlinkDuration = null;
  }
  push(t, closure) {
    if (!Number.isFinite(t)) return;
    if (this.started === null) this.started = t;
    const valid = Number.isFinite(closure);
    const closed = valid && closure >= CLOSE_THRESHOLD;
    const gap = this.last ? t - this.last.t : Infinity;
    if (this.last && gap > 0 && gap <= MAX_GAP && this.last.valid && valid) {
      this.segments.push({ start: this.last.t, end: t, closed: this.last.closed });
    } else { this.closedAt = null; }
    if (valid && closed && this.closedAt === null) this.closedAt = t;
    if (valid && !closed && this.closedAt !== null) {
      const duration = t - this.closedAt;
      // Completed closures are events; don't count every frame as a blink.
      if (duration >= 80 && duration <= 800) {
        this.blinks.push({ t, duration }); this.lastBlinkDuration = duration;
      }
      this.closedAt = null;
    }
    if (!valid) this.closedAt = null;
    this.last = { t, valid, closed, closure };
    this.segments = this.segments.filter(s => s.end > t - WINDOW);
    this.blinks = this.blinks.filter(b => b.t > t - WINDOW);
  }
  snapshot(t) {
    const cutoff = t - WINDOW;
    let observed = 0, closed = 0;
    for (const s of this.segments) {
      const dt = Math.max(0, Math.min(s.end, t) - Math.max(s.start, cutoff));
      observed += dt; if (s.closed) closed += dt;
    }
    const fresh = !!this.last?.valid && t - this.last.t <= MAX_GAP;
    const currentClosure = fresh && this.closedAt !== null ? (t - this.closedAt) / 1000 : 0;
    const ready = fresh && observed >= MIN_OBSERVED;
    const fraction = observed > 0 ? closed / observed : null;
    const duration = this.started === null ? 0 : Math.min(WINDOW, Math.max(0, t - this.started));
    const coverage = duration > 0 ? Math.min(1, observed / duration) : 0;
    let level = "Waiting", reason = "Start the camera to collect eye-closure observations.";
    if (this.started !== null && !fresh) { level = "Unavailable"; reason = "Face tracking interrupted. No current estimate."; }
    else if (fresh && currentClosure >= 1.5) { level = "High"; reason = "Continuous eye closure has exceeded 1.5 seconds."; }
    else if (fresh && currentClosure >= 0.8) { level = "Elevated"; reason = "Your current eye closure has exceeded 0.8 seconds."; }
    else if (fresh && (!ready || coverage < 0.8)) { level = "Collecting"; reason = coverage < 0.8 && observed >= MIN_OBSERVED ? "Tracking coverage is too low for a rolling estimate." : "Collecting at least 15 seconds of visible-eye observations."; }
    else if (ready && fraction >= 0.25) { level = "High"; reason = "Eyes were classified closed for at least 25% of observed time."; }
    else if (ready && fraction >= 0.12) { level = "Elevated"; reason = "Eyes were classified closed for at least 12% of observed time."; }
    else if (ready) { level = "Low"; reason = "Few eye-closure cues were detected in the current window."; }
    return { level, reason, observed, coverage, fraction, currentClosure, fresh, ready,
      blinkCount: this.blinks.filter(b => b.t > cutoff && b.t <= t).length,
      blinkDuration: this.lastBlinkDuration, closure: fresh ? this.last.closure : null };
  }
}

export function heartSummary(samples, nowSeconds) {
  const rows = samples.filter(s => Number.isFinite(s.bpm) && Number.isFinite(s.time) && s.time <= nowSeconds && nowSeconds - s.time <= 300);
  if (!rows.length || nowSeconds - rows.at(-1).time >= 5) return { bpm: null, delta: null };
  const baselineRows = rows.filter(s => s.time - rows[0].time <= 30);
  const enough = baselineRows.length >= 20 && baselineRows.at(-1).time - baselineRows[0].time >= 25;
  const baseline = enough ? baselineRows.reduce((sum, s) => sum + s.bpm, 0) / baselineRows.length : null;
  const recent = rows.filter(s => nowSeconds - s.time <= 5);
  const average = recent.reduce((sum, s) => sum + s.bpm, 0) / recent.length;
  return { bpm: rows.at(-1).bpm, delta: baseline === null ? null : average - baseline };
}
