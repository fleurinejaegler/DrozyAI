export function advisorView(state, fresh, health = {}) {
  const host = health.compute_host || 'Local';
  const model = health.local_llm?.model || 'llama3.2:3b';
  const detail = `${host} · ${model}`;
  if (health.local_llm?.enabled === false)
    return { label: 'Disabled', text: 'Automatic model advice is available. Local AI explanations are disabled.', detail };
  if (!fresh || !state?.advice)
    return { label: 'Waiting for data', text: 'Start the camera or connect the watch. An explanation will appear after a valid model window.', detail };
  const advice = state.advice;
  if (advice.source === 'llm')
    return { label: 'Live explanation', text: advice.reason,
      detail: detail + (Number.isFinite(advice.latency_ms) ? ` · ${(advice.latency_ms / 1000).toFixed(1)}s` : '') };
  return { label: advice.llm_status === 'generating' ? 'Generating…' : 'Automatic advice',
    text: advice.reason, detail };
}
