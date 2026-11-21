"""Run against a deployed gateway: python scripts/verify_live.py https://your-api"""
import json
import sys
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

base = sys.argv[1].rstrip("/")
prefix = uuid.uuid4().hex
question = f"Repeat this identifier exactly: {prefix}"


def call(path, body=None, failure=None, status=200):
    headers = {"Content-Type":"application/json"}
    if failure:
        headers["X-Simulate-Failure"] = failure
    req = Request(base + path, data=json.dumps(body).encode() if body else None, headers=headers)
    try:
        response = urlopen(req, timeout=120)
    except HTTPError as exc:
        response = exc
    with response:
        data = json.load(response)
        assert response.status == status, (path, response.status, data)
        return data


def send(session, text, **opts):
    return call("/chat", {"session_id":prefix+session, "message":text}, **opts)


health = call("/health")
assert health["keys_configured"] >= 2 and health["cache_enabled"]
live = send("a", question)
hit = send("b", question)
assert live["metadata"]["resolution_source"] == "LIVE_INFERENCE"
assert hit["metadata"]["resolution_source"] == "LLM_CACHE" and hit["reply"] == live["reply"]
assert hit["metadata"]["latency_ms"] < live["metadata"]["latency_ms"]
for field in ("input_tokens", "output_tokens"):
    assert hit["metadata"][field] == live["metadata"][field]
assert hit["metadata"]["key_id"] is None and hit["metadata"]["fallback_attempts"] == 0
follow = send("a", "What identifier did I give you?")
assert prefix in follow["reply"]
routed = send("c", question, failure="key_1=429")
assert routed["metadata"]["key_id"] == "key_2" and routed["metadata"]["fallback_attempts"] == 1
assert send("a", question, failure="*=429", status=503)["detail"] == "all providers unavailable"
assert "detail" in send("a", " ", status=422)
rows = call("/sessions/"+prefix+"a/messages")["messages"]
assert [m["role"] for m in rows] == ["user","assistant"] * 2
assert call("/sessions/"+prefix+"unknown/messages",status=404)["detail"] == "session not found"
print(json.dumps({"live":live["metadata"],"cache":hit["metadata"],"fallback":routed["metadata"],
                  "history_messages":len(rows)}, indent=2))

