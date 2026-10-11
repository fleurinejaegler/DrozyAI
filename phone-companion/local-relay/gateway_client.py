"""Transport adapter for your teammate's existing Python model. No model logic."""
import json
import uuid
from urllib.request import Request, urlopen


class RelayClient:
    def __init__(self, base_url, token, client_id="demo"):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.client_id = client_id

    def _request(self, path, data=None):
        body = None if data is None else json.dumps(data, allow_nan=False).encode("utf-8")
        request = Request(self.base_url + path, data=body, headers={
            "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def state(self):
        from urllib.parse import urlencode
        return self._request("/api/state?" + urlencode({"clientId": self.client_id}))

    def _command(self, snapshot, kind, captured_at, **fields):
        command = {"protocol": 1, "commandId": str(uuid.uuid4()), "type": kind,
                   "watchSession": snapshot["watchSession"], "capturedAt": captured_at, **fields}
        return self._request("/api/command", {"clientId": self.client_id, "command": command})

    def send_model_result(self, snapshot, risk_score, model_version, status="ready"):
        packet = snapshot.get("telemetry")
        if not packet or not snapshot.get("phoneRecent"):
            raise ValueError("No recent watch telemetry; do not infer low risk from missing data")
        # Preserve the input's timestamp/session while an inference runs.
        return self._command(snapshot, "model_result", packet["sentAt"], riskScore=risk_score,
                             status=status, modelVersion=model_version,
                             inputTelemetrySequence=packet["sequence"])

    def send_camera_alert(self, snapshot, severity, frame_captured_at):
        return self._command(snapshot, "camera_alert", frame_captured_at, severity=severity)

    def clear_camera_alert(self, snapshot, decision_captured_at):
        return self._command(snapshot, "camera_clear", decision_captured_at)
