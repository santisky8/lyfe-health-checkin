"""One way to call the local model, streamed or not.

Ollama (LLM_BASE_URL on port 11434) gets its native /api/chat with thinking switched off, which
is several times faster on a CPU for reasoning models such as qwen3. Anything else (Meterless
Nightshift, other OpenAI-compatible servers) gets the standard /v1/chat/completions call.
"""
import json
import os
import re
import urllib.request

import config  # noqa: F401  (loads .env.local)


def _is_ollama(base):
    return ":11434" in base or os.environ.get("LLM_KIND") == "ollama"


def chat(messages, stream=False, max_tokens=None, model=None, temperature=0.2):
    """Return the reply text, or with stream=True a generator of text pieces."""
    base = os.environ.get("LLM_BASE_URL", "http://localhost:8088/v1").rstrip("/")
    model = model or os.environ.get("LLM_MODEL", "default")
    timeout = int(os.environ.get("LLM_TIMEOUT", "600"))
    if _is_ollama(base):
        url = base.removesuffix("/v1") + "/api/chat"
        options = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens
        body = {"model": model, "messages": messages, "stream": stream, "think": False,
                "options": options}
        headers = {"Content-Type": "application/json"}
    else:
        url = base + "/chat/completions"
        body = {"model": model, "messages": messages, "stream": stream,
                "temperature": temperature}
        if max_tokens:
            body["max_tokens"] = max_tokens
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {os.environ.get('LLM_API_KEY', 'rt-local')}"}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    resp = urllib.request.urlopen(req, timeout=timeout)
    if not stream:
        with resp:
            data = json.load(resp)
        text = data["message"]["content"] if _is_ollama(base) else \
            data["choices"][0]["message"]["content"]
        return clean(text)
    return _pieces(resp, _is_ollama(base))


def _pieces(resp, ollama):
    """Yield answer text. Reasoning models behind Nightshift (Nemotron Ultra) may send their
    reasoning first, ending in </think> with no opening tag, so hold text back until that tag
    shows up; if it never does, the held text was the answer."""
    held, thinking = "", not ollama
    for piece in _raw_pieces(resp, ollama):
        if not thinking:
            yield piece
            continue
        held += piece
        if "</think>" in held:
            thinking = False
            rest = held.rsplit("</think>", 1)[1].lstrip()
            if rest:
                yield rest
        elif len(held) > 200 and "<think>" not in held and not _thinks():
            thinking = False
            yield held
    if thinking and held:
        yield clean(held)


def _thinks():
    """True when LLM_MODEL is known to reason before answering."""
    return any(k in os.environ.get("LLM_MODEL", "") for k in ("ultra", "think", "deep"))


def _raw_pieces(resp, ollama):
    with resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            if ollama:  # one JSON object per line
                piece = json.loads(line).get("message", {}).get("content")
            else:       # server-sent events
                if not line.startswith("data:") or line == "data: [DONE]":
                    continue
                piece = json.loads(line[5:])["choices"][0].get("delta", {}).get("content")
            if piece:
                yield piece


def clean(text):
    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S)
    if "</think>" in text:  # reasoning sent without an opening tag
        text = text.rsplit("</think>", 1)[1]
    return text.strip()
