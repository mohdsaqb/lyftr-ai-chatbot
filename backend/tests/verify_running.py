"""Black-box checks for a running backend. Successful calls can use Groq credits."""

import argparse
import uuid

import httpx


def verify(client, session, simulation_enabled):
    def chat(sid, message, failure=None, status=200):
        headers = {"X-Simulate-Failure": failure} if failure else {}
        response = client.post("/chat", json={"session_id": sid, "message": message}, headers=headers)
        assert response.status_code == status, f"{sid}: expected HTTP {status}, got {response.status_code}"
        body = response.json()
        if status != 200:
            assert "detail" in body
            return body
        assert body["session_id"] == sid and isinstance(body["reply"], str) and body["reply"].strip()
        meta = body["metadata"]
        assert meta["resolution_source"] in ("LIVE_INFERENCE", "LLM_CACHE")
        assert isinstance(meta["model"], str) and meta["model"].strip()
        for field in ("input_tokens", "output_tokens", "latency_ms", "fallback_attempts"):
            assert type(meta[field]) is int and meta[field] >= 0, field
        assert meta["key_id"] in (None, "key_1", "key_2")
        return body

    def history(sid, status=200):
        response = client.get(f"/sessions/{sid}/messages")
        assert response.status_code == status, f"history for {sid}: HTTP {response.status_code}"
        return response.json()

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}
    marker = uuid.uuid4().hex[:12]
    message = f"Reply with this code: {marker}"
    assert history(session, 404) == {"detail": "session not found"}
    if not simulation_enabled:
        result = chat(session, message, "*=429")
        assert marker in result["reply"] and result["metadata"]["resolution_source"] == "LIVE_INFERENCE"
        print("PASS: wildcard failure header ignored on a fresh request")
        return

    live = chat(session, message)
    cached = chat(session + "-cache", message)
    meta, hit = live["metadata"], cached["metadata"]
    assert marker in live["reply"] and live["reply"] == cached["reply"]
    assert (meta["resolution_source"], meta["key_id"], meta["fallback_attempts"]) == ("LIVE_INFERENCE", "key_1", 0)
    assert (hit["resolution_source"], hit["key_id"], hit["fallback_attempts"]) == ("LLM_CACHE", None, 0)
    for field in ("model", "input_tokens", "output_tokens"):
        assert hit[field] == meta[field], field
    print(f"First call {meta['latency_ms']} ms, cache hit {hit['latency_ms']} ms")
    assert hit["latency_ms"] < meta["latency_ms"], "cache hit was not faster"
    followup = "Repeat the code from my previous message."
    second = chat(session, followup)
    assert marker in second["reply"] and second["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    expected = []
    for question, answer in [(message, live), (followup, second)]:
        expected.extend([{"role": "user", "content": question}, {
            "role": "assistant", "content": answer["reply"], "metadata": answer["metadata"],
        }])
    assert history(session) == {"session_id": session, "messages": expected}
    other = uuid.uuid4().hex[:12]
    different = chat(session + "-different", f"Reply with this code: {other}")
    assert other in different["reply"] and different["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    print("PASS: cache, usage, session history, context and different first messages")

    for code in (429, 500):
        result = chat(session + f"-{code}", message, f"key_1={code}")
        m = result["metadata"]
        assert (m["resolution_source"], m["key_id"], m["fallback_attempts"]) == ("LIVE_INFERENCE", "key_2", 1)
        assert marker in result["reply"], "backup reply did not contain the requested code"
    for failure in ("key_1=429,key_2=500", "*=429"):
        assert chat(session, message, failure, 503) == {"detail": "all providers unavailable"}
    for invalid in (" ", "a" * 4001):
        chat(session, invalid, status=422)
    assert history(session)["messages"] == expected
    print("PASS: both backup cases, both all-key failures, validation and unchanged history")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--session", default="qa-" + uuid.uuid4().hex)
    parser.add_argument("--simulation-disabled", action="store_true")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=90) as client:
        verify(client, args.session, not args.simulation_disabled)
