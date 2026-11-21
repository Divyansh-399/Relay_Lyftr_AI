"""CI browser contract check against the Docker frontend with controlled chat replies."""
from playwright.sync_api import expect, sync_playwright


def main():
    seen = []

    def chat(route):
        data = route.request.post_data_json
        seen.append(data)
        headers = {"Access-Control-Allow-Origin": "http://localhost:3000"}
        if data["message"] == "Unavailable":
            return route.fulfill(status=503, headers=headers, json={"detail": "all providers unavailable"})
        cached = len(seen) == 2
        return route.fulfill(headers=headers, json={
            "session_id": data["session_id"], "reply": "Hello from the contract fixture",
            "metadata": {"model": "openai/test", "resolution_source": "LLM_CACHE" if cached else "LIVE_INFERENCE",
                         "latency_ms": 2 if cached else 120, "input_tokens": 10, "output_tokens": 6,
                         "key_id": None if cached else "key_1", "fallback_attempts": 0},
        })

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.route("**/chat", chat)
        page.goto("http://localhost:3000")
        expect(page.get_by_text("Gateway online")).to_be_visible()
        draft = page.get_by_test_id("chat-input")
        draft.fill("Hello")
        page.get_by_test_id("send-button").click()
        answer = page.get_by_test_id("assistant-message")
        expect(answer).to_contain_text("Hello from the contract fixture")
        for name, value in {"source": "LIVE_INFERENCE", "model": "openai/test", "latency": "120 ms",
                            "input-tokens": "10", "output-tokens": "6"}.items():
            expect(answer.get_by_test_id("meta-" + name)).to_have_text(value)
        expect(draft).to_have_value("")
        page.get_by_role("button", name="Resilience Lab").click()
        page.get_by_role("button", name="Replay first turn").click()
        expect(answer.get_by_test_id("meta-source")).to_have_text("LLM_CACHE")
        assert seen[0]["session_id"] != seen[1]["session_id"]
        page.reload()
        expect(answer).to_have_count(0)
        draft.fill("Unavailable")
        draft.press("Enter")
        expect(page.get_by_role("alert")).to_contain_text("all providers unavailable")
        expect(draft).to_have_value("Unavailable")
        assert seen[2]["session_id"] not in {seen[0]["session_id"], seen[1]["session_id"]}
        browser.close()


if __name__ == "__main__":
    main()
