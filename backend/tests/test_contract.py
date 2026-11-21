import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from gateway import Gateway
from main import create_app


class Memory:
    def __init__(self):
        self.cache = self
        self.values = {}

    def get_cache(self, key):
        return self.values.get(key)

    def set_cache(self, key, value, ttl):
        self.values[key] = value


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'chat.db'}")
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "true")
    calls = []
    broken = set()

    async def provider(**params):
        await asyncio.sleep(.015)
        calls.append(params)
        if params["api_key"] in broken:
            raise RuntimeError("provider quota exceeded")
        messages = params["messages"]
        reply = "|".join(m["content"] for m in messages)
        return NS(choices=[NS(message=NS(content=reply))],
                  usage=NS(prompt_tokens=len(reply), completion_tokens=5))

    def factory():
        return Gateway(["secret-a", "secret-b"], "openai/test", provider, Memory())

    with TestClient(create_app(factory)) as client:
        yield client, calls, broken, factory


def post(c, sid="a", msg="Hello", header=None, **fields):
    return c.post("/chat", json=dict(session_id=sid, message=msg, **fields),
                  headers={"X-Simulate-Failure": header} if header else {})


def test_cache_identity_usage_and_latency(harness):
    c, calls, _, _ = harness
    first = post(c, msg="  Hello ").json()
    cached = post(c, "b").json()
    live, hit = first["metadata"], cached["metadata"]
    assert live["resolution_source"] == "LIVE_INFERENCE"
    assert hit == dict(live, resolution_source="LLM_CACHE", key_id=None, latency_ms=hit["latency_ms"])
    assert first["reply"] == cached["reply"] and hit["latency_ms"] < live["latency_ms"]
    assert len(calls) == 1
    assert post(c, "c", "Other").json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert post(c, "d", system_prompt="Different").json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_history_prompt_and_restart(harness):
    c, calls, _, factory = harness
    post(c, msg="My name is Sam", system_prompt="Be brief")
    follow = post(c, msg="My name?").json()
    assert "Sam" in follow["reply"]
    assert calls[-1]["messages"][0]["content"] == "Be brief"
    assert len(calls[-1]["messages"]) == 4
    assert follow["metadata"]["output_tokens"] == 5
    with TestClient(create_app(factory)) as fresh:
        rows = fresh.get("/sessions/a/messages").json()["messages"]
        assert [m["role"] for m in rows] == ["user","assistant"] * 2
        assert rows[-1]["metadata"] == follow["metadata"]
        assert "metadata" not in rows[0]
    assert post(c, "other", "My name?").json()["reply"].count("Sam") == 0


@pytest.mark.parametrize("status", [429,500,502,503])
def test_failover_and_request_scoping(harness, status):
    c, _, _, _ = harness
    post(c)
    result = post(c, "b", header=f"key_1={status}").json()
    assert result["metadata"]["key_id"] == "key_2"
    assert result["metadata"]["fallback_attempts"] == 1
    assert post(c, "c", "New").json()["metadata"]["key_id"] == "key_1"


def test_all_failed_is_atomic(harness):
    c, _, broken, _ = harness
    for header in ("*=429", "key_1=429,key_2=500"):
        r = post(c, header=header)
        assert r.status_code == 503 and r.json() == {"detail":"all providers unavailable"}
        assert c.get("/sessions/a/messages").status_code == 404
    broken.add("secret-a")
    assert post(c).json()["metadata"]["fallback_attempts"] == 1
    broken.add("secret-b")
    assert post(c, msg="Next").status_code == 503
    assert len(c.get("/sessions/a/messages").json()["messages"]) == 2


@pytest.mark.parametrize("body", [{}, {"message":"ok"}, {"session_id":"x"}, {"session_id":" ","message":"ok"},
                                  {"session_id":"a","message":"   "}, {"session_id":"a","message":"x"*4001},
                                  {"session_id":"s"*129,"message":"x"}])
def test_validation(harness, body):
    c = harness[0]
    r = c.post("/chat", json=body)
    assert r.status_code == 422 and "detail" in r.json()
    assert c.get("/sessions/a/messages").status_code == 404


def test_health_json_cors_and_switch(harness, monkeypatch):
    c, _, _, factory = harness
    assert c.get("/health").json() == {"status":"ok","keys_configured":2,"cache_enabled":True}
    assert c.get("/health", headers={"Origin":"http://localhost:3000"}).headers["access-control-allow-origin"] == "http://localhost:3000"
    assert c.post("/chat", content="{", headers={"Content-Type":"application/json"}).status_code == 422
    assert post(c, header="key_1=403").status_code == 422
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION","false")
    with TestClient(create_app(factory)) as fresh:
        assert post(fresh, header="*=429").status_code == 200


def test_overlapping_turns(harness):
    c, calls, _, _ = harness
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda text: post(c, msg=text).status_code, ["one", "two"]))
    assert results == [200,200]
    assert [len(p["messages"]) for p in calls] == [2,4]


def test_private_history_headers_and_denied_origin(harness):
    client = harness[0]
    post(client)
    response = client.get("/sessions/a/messages", headers={"Origin": "https://unlisted.example"})
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "access-control-allow-origin" not in response.headers
    denied = client.options("/chat", headers={"Origin": "https://unlisted.example",
                                              "Access-Control-Request-Method": "POST"})
    assert denied.status_code == 400 and "detail" in denied.json()


def test_validation_redaction_and_body_limit(harness):
    client, calls, _, _ = harness
    secret = "private input"
    for fields in ({"session_id": "a", "message": secret, "system_prompt": "x"*4001},
                   {"session_id": "a", "message": secret, "extra": "x"*131072}):
        response = client.post("/chat", json=fields)
        assert response.status_code == 422 and secret not in response.text
    assert calls == []
    assert client.get("/sessions/a/messages").status_code == 404


def test_global_capacity_and_separate_health(harness):
    client, calls, _, _ = harness
    for _ in range(60):
        assert post(client, header="*=429").status_code == 503
    response = post(client, sid="fresh")
    assert response.status_code == 429 and "retry-after" in response.headers
    assert calls == [] and client.get("/health").status_code == 200


def test_equal_length_usage_and_different_histories(harness):
    client = harness[0]
    first = post(client, "a", "blue").json()
    other = post(client, "b", "pink").json()
    assert first["metadata"]["input_tokens"] == other["metadata"]["input_tokens"]
    a = post(client, "a", "repeat").json()
    b = post(client, "b", "repeat").json()
    assert a["reply"] != b["reply"]
    assert b["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_context_boundary_preserves_stored_turn(harness):
    client, calls, _, _ = harness
    client.app.state.db.append("full", "system", "q"*4000, "r"*60000, {})
    response = post(client, "full")
    assert response.status_code == 422 and calls == []
    assert len(client.get("/sessions/full/messages").json()["messages"]) == 2


def test_usage_caps_and_public_metadata(harness):
    client, calls, _, _ = harness
    response = post(client)
    assert calls[0]["max_tokens"] == 1024
    assert response.json()["metadata"]["key_id"] == "key_1"
    assert all(key not in response.text for key in ("secret-a", "secret-b"))


def test_maximum_valid_text_and_session_id(harness):
    client = harness[0]
    assert post(client, sid="s"*128, msg="  "+"z"*4000+" ").status_code == 200

