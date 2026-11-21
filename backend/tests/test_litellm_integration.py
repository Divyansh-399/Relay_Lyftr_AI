"""Exercise the installed LiteLLM client and cache against a local HTTP provider."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from main import create_app


def test_real_client_cache_and_http_failover(tmp_path, monkeypatch):
    pytest.importorskip("litellm")
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            key = self.headers["Authorization"]
            calls.append(key)
            if key == "Bearer local-a":
                status, body = 429, {"error":{"message":"rate limit","type":"rate_limit_error"}}
            else:
                status, body = 200, {
                    "id":"chatcmpl-local", "object":"chat.completion","created":1,"model":"gpt-4o-mini",
                    "choices":[{"index":0,"message":{"role":"assistant","content":"Paris"},"finish_reason":"stop"}],
                    "usage":{"prompt_tokens":12,"completion_tokens":1,"total_tokens":13}
                }
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("OPENAI_API_BASE", f"http://127.0.0.1:{server.server_port}/v1")
        monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
        monkeypatch.setenv("LLM_API_KEYS","local-a,local-b")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'integration.db'}")
        with TestClient(create_app()) as c:
            def ask(sid):
                res = c.post("/chat",json={"session_id":sid,"message":"Capital of France?"})
                assert res.status_code == 200, res.text
                return res.json()
            live, hit = ask("one"), ask("two")
            assert live["metadata"]["key_id"] == "key_2"
            assert live["metadata"]["fallback_attempts"] == 1
            assert live["metadata"]["input_tokens"] == 12
            assert hit["reply"] == live["reply"]
            assert hit["metadata"]["resolution_source"] == "LLM_CACHE"
            assert hit["metadata"]["key_id"] is None
            assert calls == ["Bearer local-a","Bearer local-b"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

