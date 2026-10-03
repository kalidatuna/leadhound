"""Optional LLM backends for drafts. Keys come from environment variables only.

provider = anthropic  ->  ANTHROPIC_API_KEY
provider = leadhound  ->  the seller's server (Pro key or trial, no API key needed)
provider = openai     ->  OPENAI_API_KEY (optional for local servers), base_url defaults to OpenAI.
                           Ollama: base_url = http://localhost:11434/v1, model = llama3.1
"""
from __future__ import annotations

import json
import os

from .net import FetchError, Fetcher

DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5"}


class LLMError(Exception):
    pass


def complete(cfg, system: str, prompt: str, fetcher: Fetcher | None = None, max_tokens: int = 500, hosted_token: str | None = None) -> str:
    fetcher = fetcher or Fetcher(min_interval=0, timeout=90, retries=1)
    provider = cfg.llm_provider
    if provider == "leadhound":  # the seller's server writes it: needs a valid Pro key or trial
        from . import licensing
        if not hosted_token:
            raise LLMError("leadhound AI needs Pro or a trial")
        try:
            return licensing.post_json("/v1/ai", {"token": hosted_token, "system": system, "prompt": prompt, "max_tokens": max_tokens}, 90)["text"].strip()
        except (ValueError, KeyError) as e:
            raise LLMError(str(e)) from e
    if provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("set ANTHROPIC_API_KEY")
        body = {"model": cfg.llm_model or DEFAULT_MODELS["anthropic"], "max_tokens": max_tokens,
                "system": system, "messages": [{"role": "user", "content": prompt}]}
        r = fetcher.request("https://api.anthropic.com/v1/messages", method="POST",
                            data=json.dumps(body).encode(),
                            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                     "content-type": "application/json"})
        if r.status >= 400:
            raise LLMError(f"Anthropic HTTP {r.status}: {r.text()[:300]}")
        parts = r.json().get("content", [])
        return "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
    if provider == "openai":
        if not cfg.llm_model:
            raise LLMError("set [llm] model in leadhound.ini")
        base = (cfg.llm_base_url or "https://api.openai.com/v1").rstrip("/")
        headers = {"content-type": "application/json"}
        if os.environ.get("OPENAI_API_KEY"):
            headers["Authorization"] = f"Bearer {os.environ['OPENAI_API_KEY']}"
        body = {"model": cfg.llm_model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        try:
            r = fetcher.request(f"{base}/chat/completions", method="POST", data=json.dumps(body).encode(),
                                headers=headers)
        except FetchError as e:
            raise LLMError(str(e)) from e
        if r.status >= 400:
            raise LLMError(f"LLM HTTP {r.status}: {r.text()[:300]}")
        return r.json()["choices"][0]["message"]["content"].strip()
    raise LLMError("no LLM configured: set [llm] provider = anthropic or openai")
