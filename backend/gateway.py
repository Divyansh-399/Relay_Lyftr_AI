import hashlib
import json
import os

DEFAULT_MODEL = "openai/gpt-4o-mini"


class Unavailable(Exception):
    pass


class Gateway:
    def __init__(self, keys, model, complete, cache):
        self.keys = keys
        self.model = model
        self.complete = complete
        self.cache = cache

    @classmethod
    def configured(cls):
        from litellm import acompletion
        from litellm.caching.caching import Cache

        keys = [k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip()]
        if len(set(keys)) < 2 or len(keys) != len(set(keys)):
            raise ValueError("Configure at least two distinct LLM_API_KEYS")
        return cls(keys, os.getenv("LLM_MODEL", DEFAULT_MODEL), acompletion, Cache(type="local"))

    async def answer(self, messages, failures):
        # The cache identity deliberately excludes credentials and session identifiers.
        payload = json.dumps([self.model, messages], sort_keys=True, ensure_ascii=False)
        cache_key = hashlib.sha256(payload.encode()).hexdigest()
        if not failures:
            hit = self.cache.cache.get_cache(key=cache_key)
            if hit is not None:
                return hit["reply"], dict(hit["usage"], resolution_source="LLM_CACHE",
                                           key_id=None, fallback_attempts=0)
        for index, key in enumerate(self.keys):
            key_id = f"key_{index + 1}"
            if key_id in failures or "*" in failures:
                continue
            try:
                result = await self.complete(model=self.model, api_key=key, messages=messages,
                                             timeout=25, num_retries=0, max_tokens=1024)
                reply = result.choices[0].message.content
                usage = {"model": self.model, "input_tokens": result.usage.prompt_tokens,
                         "output_tokens": result.usage.completion_tokens}
                if not isinstance(reply, str) or not reply.strip():
                    continue
                if not all(isinstance(usage[k], int) and usage[k] >= 0
                           for k in ("input_tokens", "output_tokens")):
                    continue
            except Exception:
                # Provider exception text can contain credentials. Do not expose it.
                continue
            self.cache.cache.set_cache(key=cache_key, value={"reply": reply, "usage": usage}, ttl=3600)
            return reply, dict(usage, resolution_source="LIVE_INFERENCE", key_id=key_id,
                               fallback_attempts=index)
        raise Unavailable

