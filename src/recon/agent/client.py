"""Model access: cached, rate-limited, audited, and capped.

The cache is the reproducibility mechanism. Responses are keyed by a hash of the exact
request, written to `cache/llm_cache.json`, and committed to the repository - so a judge
who clones this repo reproduces the reported numbers exactly, with no API key and no
network. `--offline` turns a cache miss into an error rather than a call.

Groq's free tier is rate-limited rather than billed, so the limiter here protects the
daily quota rather than a wallet.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

DEFAULT_MODEL = "openai/gpt-oss-120b"
COMPARISON_MODEL = "openai/gpt-oss-20b"


class CacheMiss(RuntimeError):
    pass


class SpendCapExceeded(RuntimeError):
    pass


class ModelCallFailed(RuntimeError):
    """The provider could not produce a valid document. Not a match, and not a crash."""


class Backend(Protocol):
    def complete(self, system: str, user: str, schema: dict, model: str) -> tuple[dict, dict]:
        """Returns (parsed_payload, usage)."""

    def chat(self, messages: list, tools: list, model: str) -> tuple[dict, dict]:
        """One turn of a tool-using conversation. Returns (message_dict, usage)."""


@dataclass
class RateLimiter:
    """Groq free tier: 30 requests/min and a few thousand tokens/min. Stay under both."""

    requests_per_minute: int = 25
    tokens_per_minute: int = 5_000
    enabled: bool = True
    _requests: deque = field(default_factory=deque)
    _tokens: deque = field(default_factory=deque)

    def acquire(self, estimated_tokens: int) -> None:
        if not self.enabled:
            return
        while True:
            now = time.monotonic()
            self._evict(now)
            spent = sum(t for _, t in self._tokens)
            if len(self._requests) < self.requests_per_minute and (
                spent + estimated_tokens <= self.tokens_per_minute
            ):
                self._requests.append(now)
                self._tokens.append((now, estimated_tokens))
                return
            oldest = min(
                (self._requests[0] if self._requests else now),
                (self._tokens[0][0] if self._tokens else now),
            )
            time.sleep(max(0.25, 60 - (now - oldest) + 0.1))

    def _evict(self, now: float) -> None:
        while self._requests and now - self._requests[0] > 60:
            self._requests.popleft()
        while self._tokens and now - self._tokens[0][0] > 60:
            self._tokens.popleft()


class GroqBackend:
    def __init__(self) -> None:
        from groq import Groq  # imported lazily so --offline needs no key

        self._client = Groq()

    def complete(self, system: str, user: str, schema: dict, model: str) -> tuple[dict, dict]:
        response = self._client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=3000,  # gpt-oss emits reasoning before the JSON document
            response_format={"type": "json_schema", "json_schema": schema},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
        }
        return json.loads(response.choices[0].message.content), usage

    def chat(self, messages: list, tools: list, model: str) -> tuple[dict, dict]:
        response = self._client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=3000,
            tools=tools,
            tool_choice="auto",
            messages=messages,
        )
        message = response.choices[0].message
        payload = {
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in (message.tool_calls or [])
            ],
        }
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
        }
        return payload, usage


class CachedLLM:
    def __init__(
        self,
        backend: Backend | None = None,
        cache_path: Path = Path("cache/llm_cache.json"),
        offline: bool = False,
        max_calls: int | None = None,
        audit_dir: Path | None = Path("audit"),
        limiter: RateLimiter | None = None,
    ) -> None:
        self.backend = backend
        self.cache_path = cache_path
        self.offline = offline
        self.max_calls = max_calls or int(os.environ.get("RECON_MAX_LLM_CALLS", "400"))
        self.audit_dir = audit_dir
        self.limiter = limiter or RateLimiter()
        self.cache: dict[str, dict] = self._load()
        self.stats = {"calls": 0, "cache_hits": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def _load(self) -> dict:
        if self.cache_path.exists():
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        return {}

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    @staticmethod
    def key(system: str, user: str, schema: dict, model: str) -> str:
        blob = json.dumps(
            {"system": system, "user": user, "schema": schema, "model": model}, sort_keys=True
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def propose(self, system: str, user: str, schema: dict, model: str = DEFAULT_MODEL) -> dict:
        cache_key = self.key(system, user, schema, model)
        if cache_key in self.cache:
            self.stats["cache_hits"] += 1
            return self.cache[cache_key]["payload"]

        if self.offline:
            raise CacheMiss(f"no cached response for {cache_key[:12]} and --offline is set")
        if self.backend is None:
            raise CacheMiss("no backend configured and no cached response")
        if self.stats["calls"] >= self.max_calls:
            raise SpendCapExceeded(f"hit the {self.max_calls} call cap")

        self.limiter.acquire(len(system) // 3 + len(user) // 3 + 400)
        try:
            payload, usage = self.backend.complete(system, user, schema, model)
        except Exception as exc:  # provider-side failure, surfaced not swallowed
            self.stats["calls"] += 1
            self.stats["failures"] = self.stats.get("failures", 0) + 1
            raise ModelCallFailed(str(exc)[:300]) from exc

        self.stats["calls"] += 1
        self.stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.stats["completion_tokens"] += usage.get("completion_tokens", 0)
        self.cache[cache_key] = {"model": model, "payload": payload, "usage": usage}
        # Persist immediately: on a rate-limited free tier, losing a completed call to a
        # later crash costs minutes of wall clock to recover.
        self.save()
        self._audit(cache_key, model, system, user, payload, usage)
        return payload

    def chat(self, messages: list, tools: list, model: str = DEFAULT_MODEL) -> dict:
        """One turn of an agent loop, cached on the whole conversation so far.

        Keying on the full message list means a replay follows the identical path through
        the loop: same tool calls, same results, same decision. Multi-turn reproducibility
        is otherwise impossible.
        """
        cache_key = self.key(json.dumps(messages, sort_keys=True), "", {"tools": tools}, model)
        if cache_key in self.cache:
            self.stats["cache_hits"] += 1
            return self.cache[cache_key]["payload"]

        if self.offline:
            raise CacheMiss(f"no cached turn for {cache_key[:12]} and --offline is set")
        if self.backend is None:
            raise CacheMiss("no backend configured and no cached turn")
        if self.stats["calls"] >= self.max_calls:
            raise SpendCapExceeded(f"hit the {self.max_calls} call cap")

        self.limiter.acquire(len(json.dumps(messages)) // 3 + 600)
        try:
            payload, usage = self.backend.chat(messages, tools, model)
        except Exception as exc:
            self.stats["calls"] += 1
            self.stats["failures"] = self.stats.get("failures", 0) + 1
            raise ModelCallFailed(str(exc)[:300]) from exc

        self.stats["calls"] += 1
        self.stats["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.stats["completion_tokens"] += usage.get("completion_tokens", 0)
        self.cache[cache_key] = {"model": model, "payload": payload, "usage": usage}
        self.save()
        self._audit(cache_key, model, "[agent turn]", json.dumps(messages)[-2000:], payload, usage)
        return payload

    def _audit(self, key: str, model: str, system: str, user: str, payload: dict, usage: dict) -> None:
        if not self.audit_dir:
            return
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "key": key,
            "model": model,
            "system": system,
            "user": user,
            "response": payload,
            "usage": usage,
        }
        with (self.audit_dir / "llm_calls.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
