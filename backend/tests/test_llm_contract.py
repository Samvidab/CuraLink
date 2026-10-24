"""Contract test: drives the REAL anthropic SDK against a local fake Messages API.

No network and no API key are used, so this does NOT prove a live call works; it
proves our request is accepted by the installed SDK (params, betas, strict tools),
and that the tool loop, field validation and UI actions handle real response shapes.
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.config import get_settings
from app.services import llm_gateway

RESPONSES = [
    {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "stop_reason": "tool_use", "stop_sequence": None,
     "usage": {"input_tokens": 10, "output_tokens": 10},
     "content": [
         {"type": "text", "text": "Let me note that."},
         {"type": "tool_use", "id": "tu_1", "name": "propose_intake_fields", "input": {"fields": [
             {"key": "temperature", "text": "", "temperature_value": 38.2, "temperature_unit": "C"},
             {"key": "symptoms_free_text", "text": "scratchy throat", "temperature_value": None, "temperature_unit": "unstated"}]}},
         {"type": "tool_use", "id": "tu_2", "name": "request_ui_action", "input": {"action": "FIND_CARE"}},
         {"type": "tool_use", "id": "tu_3", "name": "send_email", "input": {"to": "x"}},
     ]},
    {"id": "msg_2", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "stop_reason": "end_turn", "stop_sequence": None,
     "usage": {"input_tokens": 10, "output_tokens": 10},
     "content": [{"type": "text", "text": "Got it. I've put a couple of demo times on your screen."}]},
]


@pytest.fixture()
def fake_api(monkeypatch):
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
            out = json.dumps(RESPONSES[min(len(seen) - 1, 1)]).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key-not-real")
    yield seen
    srv.shutdown()


def test_sdk_request_shape_and_tool_loop(fake_api):
    calls = []

    async def handle(name, args):
        calls.append(name)
        return "ok"

    turn = asyncio.run(llm_gateway.run_turn([{"role": "assistant", "text": "hi"}, {"role": "user", "text": "earlier"}, {"role": "assistant", "text": "sure"}], "my throat hurts", "ctx", handle))
    first = fake_api[0]
    assert first["path"].startswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in first["headers"].get("anthropic-beta", "")
    body = first["body"]
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default" and body["output_config"] == {"effort": "low"}
    assert body["tool_choice"] == {"type": "auto"} and all(t["strict"] for t in body["tools"])
    assert body["messages"][0]["role"] == "user"  # leading assistant greeting dropped
    assert body["messages"][-1]["content"].startswith("my throat hurts")
    # Second request carries tool results, including the rejected unknown tool.
    results = fake_api[1]["body"]["messages"][-1]["content"]
    assert {r["tool_use_id"]: r.get("is_error", False) for r in results} == {"tu_1": False, "tu_2": False, "tu_3": True}
    assert "send_email" not in calls
    assert turn.ui_actions == ["FIND_CARE"] and len(turn.proposed_fields) == 2
    assert turn.text.startswith("Got it.")


def test_end_to_end_through_api_with_sdk(fake_api, student):
    r = student.post("/api/v1/intake/messages", json={"message": "scratchy throat, 38.2 C", "history": []}).json()
    assert r["mode"] == "claude" and "FIND_CARE" in r["next_actions"]
    assert set(r["field_updates"]) == {"temperature", "symptoms_free_text"}
    blocked = [t for t in r["tool_events"] if t["status"] == "rejected"]
    assert blocked and blocked[0]["tool"] == "send_email"
