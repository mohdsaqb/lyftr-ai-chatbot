import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.main import app


class GatewayTests(unittest.TestCase):
    """Exercise the real Router and Cache. Replace only the outbound Groq HTTP call."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.dict(os.environ, {
            "LLM_API_KEYS": "test-first,test-second",
            "GROQ_MODEL_1": "groq/openai/gpt-oss-20b",
            "GROQ_MODEL_2": "groq/openai/gpt-oss-120b",
            "DATABASE_URL": f"sqlite:///{Path(directory.name) / 'app.db'}",
            "ENABLE_FAILURE_SIMULATION": "true",
        }))
        self.calls = []
        self.primary_status = 200
        self.backup_status = 200

        async def send(client, request, **kwargs):
            self.assertEqual(str(request.url), "https://api.groq.com/openai/v1/chat/completions")
            key = request.headers["authorization"]
            self.calls.append(key)
            if self.primary_status != 200 and key == "Bearer test-first":
                return httpx.Response(self.primary_status, request=request, json={
                    "error": {"message": "quota exhausted", "type": "insufficient_quota"}
                })
            if self.backup_status != 200 and key == "Bearer test-second":
                return httpx.Response(self.backup_status, request=request, json={
                    "error": {"message": "invalid API key", "code": "invalid_api_key"}
                })
            body = {
                "id": "chat-test", "object": "chat.completion", "created": int(time.time()),
                "model": json.loads(request.content)["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Paris"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 27, "completion_tokens": 3, "total_tokens": 30},
            }
            if key == "Bearer test-first":
                body["service_tier"] = "on_demand"
            return httpx.Response(200, request=request, json=body)

        self.enterContext(patch.object(httpx.AsyncClient, "send", send))
        self.client = self.enterContext(TestClient(app))

    def post(self, session, text="Capital?", header=None, **kwargs):
        headers = {"X-Simulate-Failure": header} if header else {}
        return self.client.post("/chat", headers=headers, json={"session_id": session, "message": text, **kwargs})

    def test_real_cache_round_trip(self):
        self.assertEqual(self.client.get("/health").json(),
                         {"status": "ok", "cache_enabled": True, "keys_configured": 2})
        live = self.post("first").json()
        cached = self.post("second").json()
        self.assertEqual(live["metadata"]["resolution_source"], "LIVE_INFERENCE")
        self.assertEqual(live["metadata"]["key_id"], "key_1")
        self.assertEqual(cached["metadata"], {
            "resolution_source": "LLM_CACHE", "key_id": None, "fallback_attempts": 0,
            "model": "groq/openai/gpt-oss-20b", "input_tokens": 27, "output_tokens": 3,
            "latency_ms": cached["metadata"]["latency_ms"],
        })
        self.assertEqual(live["reply"], cached["reply"])
        self.assertEqual(self.calls, ["Bearer test-first"])
        self.assertEqual(self.client.get("/sessions/second/messages").json()["messages"][-1]["metadata"],
                         cached["metadata"])
        for response in [self.post("second"), self.post("third", "Different"), self.post("fourth", system_prompt="Short")]:
            self.assertEqual(response.json()["metadata"]["resolution_source"], "LIVE_INFERENCE")

    def test_simulation(self):
        self.post("cached")
        for status in (429, 500, 502, 503):
            meta = self.post(str(status), header=f"key_1={status}").json()["metadata"]
            self.assertEqual((meta["key_id"], meta["fallback_attempts"], meta["resolution_source"]),
                             ("key_2", 1, "LIVE_INFERENCE"))
            self.assertEqual(self.calls[-1], "Bearer test-second")
        for header in ("*=429", "key_1=429,key_2=500"):
            response = self.post("failed", header=header)
            self.assertEqual((response.status_code, response.json()), (503, {"detail": "all providers unavailable"}))
            self.assertEqual(self.client.get("/sessions/failed/messages").status_code, 404)
        self.assertEqual(len(self.calls), 5)
        self.assertEqual(self.post("fresh", "New").json()["metadata"]["key_id"], "key_1")

    def test_provider_status_fallback(self):
        for status in (401, 403, 429, 500, 502, 503):
            self.primary_status = status
            result = self.post(str(status), str(status))
            self.assertEqual(result.status_code, 200, f"primary HTTP {status}")
            self.assertEqual(result.json()["reply"], "Paris")
            meta = result.json()["metadata"]
            self.assertEqual(self.calls[-2:], ["Bearer test-first", "Bearer test-second"])
            self.assertEqual((meta["key_id"], meta["fallback_attempts"]), ("key_2", 1))
            self.assertEqual(meta["model"], "groq/openai/gpt-oss-120b")
            calls = len(self.calls)
            cached = self.post(f"repeat-{status}", str(status)).json()["metadata"]
            self.assertEqual((cached["model"], cached["key_id"], cached["fallback_attempts"]),
                             (meta["model"], None, 0))
            self.assertEqual(len(self.calls), calls)

    def test_rejected_backup_is_not_saved(self):
        for status in (401, 403, 404, 429, 500):
            with self.subTest(status=status), self.assertLogs("app.gateway", level="WARNING") as logs:
                self.calls.clear()
                self.backup_status = status
                response = self.post("rejected", header="key_1=429")
                self.assertEqual(self.calls, ["Bearer test-second"])
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"detail": "all providers unavailable"})
                self.assertEqual(self.client.get("/sessions/rejected/messages").status_code, 404)
                output = "\n".join(logs.output)
                self.assertIn("attempts=key_1,key_2 simulated=key_1", output)
                self.assertIn(f"sdk_status={status}", output)
                self.assertNotIn("test-second", output)
