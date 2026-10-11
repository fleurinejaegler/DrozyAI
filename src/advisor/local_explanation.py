"""Short local explanations; scores and alert actions stay in Python."""
from __future__ import annotations

import json
import os
import time
from urllib.parse import urlsplit

import requests

MODEL = os.getenv('LLM_MODEL', 'llama3.2:3b')
BASE_URL = os.getenv('LLM_BASE_URL', 'http://127.0.0.1:11434/v1').rstrip('/')
TIMEOUT = float(os.getenv('LLM_TIMEOUT', '4'))

SYSTEM_PROMPT = """Describe the supplied measurements and experimental model
score in one factual sentence, at most 25 words. Give NO instructions or
recommendations: the website displays Python's chosen action separately.
Describe the result as an 'experimental model score'. Never say 'likelihood',
'probability', 'fatigue detected' or 'safe to drive'. The score is uncalibrated,
not proof of fatigue. Missing watch/camera data, baselines and trends are unknown.
Do not invent causes or verified yawns, and do not repeat numeric scores.
Example: 'The camera model reports an elevated experimental score.'
Return JSON only: {"reason":"one short factual sentence"}."""


def explain(payload: dict) -> dict:
    started = time.monotonic()
    schema = {'type': 'object', 'properties': {'reason': {'type': 'string'}},
              'required': ['reason'], 'additionalProperties': False}
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': json.dumps(payload, allow_nan=False)}]
    url = urlsplit(BASE_URL)
    native = url.hostname in {'localhost','127.0.0.1'} and url.port == 11434
    body = {
        'model': MODEL,
        'messages': messages,
        'temperature': 0,
        'max_tokens': 64,
        'response_format': {'type': 'json_schema', 'json_schema': {
            'name': 'explanation', 'schema': schema}},
    }
    endpoint = f'{BASE_URL}/chat/completions'
    if native:
        endpoint = f'{url.scheme}://{url.netloc}/api/chat'
        body = {'model':MODEL,'messages':messages,'stream':False,'format':schema,
                'options':{'num_ctx':2048,'num_predict':64,'temperature':0},'keep_alive':'30m'}
    response = requests.post(endpoint, json=body, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()
    output = json.loads(data['message']['content'] if native else data['choices'][0]['message']['content'])
    reason = output.get('reason') if isinstance(output, dict) else None
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 400:
        raise ValueError('Invalid local explanation')
    return {'reason': reason.strip(), 'source': 'llm', 'model': MODEL,
            'compute_host': os.getenv('DROWSY_COMPUTE_LABEL', 'local'),
            'latency_ms': round((time.monotonic() - started) * 1000)}
