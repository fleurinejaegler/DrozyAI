// Display history never becomes a fresh inference or an alert input.
export class ScoreDisplay {
  constructor() { this.reset(); }
  reset() { this.last = null; }
  snapshot(state, fresh, nowMs) {
    if (fresh && state?.status === 'ok' && Number.isFinite(state.score)
        && state.score >= 0 && state.score <= 1 && Number.isFinite(state.window_end_ms)) {
      this.last = {...state};
    }
    return {state: this.last, fresh: Boolean(fresh && this.last),
      ageSeconds: this.last ? Math.max(0, Math.floor((nowMs-this.last.window_end_ms)/1000)) : null};
  }
}
