"""One way to call the local model, streamed or not.

Ollama (LLM_BASE_URL on port 11434) gets its native /api/chat with thinking switched off, which
is several times faster on a CPU for reasoning models such as qwen3. Anything else (Meterless
Nightshift, other OpenAI-compatible servers) gets the standard /v1/chat/completions call.

Backup: when NVIDIA_API_KEY is set and Nightshift doesn't answer (the Windows laptop is off),
the same Nemotron models are called on NVIDIA's own cloud, and via() says so in the trace.
"""
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import config  # noqa: F401  (loads .env.local)


def _is_ollama(base):
    return ":11434" in base or os.environ.get("LLM_KIND") == "ollama"


NVIDIA_CLOUD = "https://integrate.api.nvidia.com/v1"
_up = {"at": 0.0, "ok": True, "until": 0.0}  # last check; "until": skip Nightshift after an error


def _primary_up(base):
    """True when the configured server takes a connection within 2 s and hasn't failed a
    request in the last minute."""
    if time.time() < _up["until"]:
        return False
    if time.time() - _up["at"] > 30:
        url = urllib.parse.urlsplit(base)
        try:
            port = url.port or (443 if url.scheme == "https" else 80)
            socket.create_connection((url.hostname, port), timeout=2).close()
            _up["ok"] = True
        except OSError:
            _up["ok"] = False
        _up["at"] = time.time()
    return _up["ok"]


def _route():
    """(base URL, API key, label) of the server to call: Nightshift, or NVIDIA's cloud as backup."""
    base = os.environ.get("LLM_BASE_URL", "http://localhost:8088/v1").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "rt-local")
    if _is_ollama(base):
        return base, key, "Ollama"
    if os.environ.get("NVIDIA_API_KEY") and not _primary_up(base):
        return NVIDIA_CLOUD, os.environ["NVIDIA_API_KEY"], "NVIDIA cloud (Nightshift offline)"
    return base, key, "Meterless Nightshift"


def via():
    """Which server answers right now, for the trace and the page."""
    return _route()[2]


def chat(messages, stream=False, max_tokens=None, model=None, temperature=0.2):
    """Return the reply text, or with stream=True a generator of text pieces."""
    if model is None and _thinks():
        # A reasoning model's answer is held back until it is complete anyway (see _pieces),
        # so it is asked for whole. Through Nightshift's web hotspot about one reply in three
        # arrives with the model's reasoning in front of the answer: ask again, and if every
        # try leaks, keep only what follows the first section heading.
        for _ in range(3):
            text = _chat(messages, False, max_tokens, None, temperature)
            if not _leaked(text):
                break
        else:
            heading = re.search(r"(?m)^[ \t]*\*\*[^*\n]{3,60}\*\*", text)
            text = text[heading.start():] if heading else text
        return iter([text]) if stream else text
    return _chat(messages, stream, max_tokens, model, temperature)


def _leaked(text):
    """True when the reply opens with the model's own reasoning ("The user is asking...")
    instead of the answer, which always speaks to the person as "you"."""
    return text.lstrip().lower().startswith(("the user", "we need", "okay", "let me", "i need"))


def _chat(messages, stream, max_tokens, model, temperature):
    base, key, _ = _route()
    model = model or os.environ.get("LLM_MODEL", "default")
    timeout = int(os.environ.get("LLM_TIMEOUT", "180"))  # Ultra can think for a minute or two
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
        # Always send a limit: Nightshift's web hotspot applies a short default, which cuts
        # Nemotron Ultra off mid-reasoning so the unfinished reasoning arrives as the answer.
        body = {"model": model, "messages": messages, "stream": stream,
                "temperature": temperature,
                "max_tokens": max_tokens or int(os.environ.get("LLM_MAX_TOKENS", "8192"))}
        # Nightshift's web hotspot sits behind Cloudflare, which refuses Python's default
        # User-Agent (error 1010), so the agent names itself.
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                   "User-Agent": "lyfe-health-checkin/1.0"}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    try:
        for wait in (2, 4, 0):
            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
                break
            except urllib.error.HTTPError as e:
                # Nightshift's queue is full (several check-ins at once): wait, don't fall back
                if e.code != 429 or not wait or base == NVIDIA_CLOUD:
                    raise
                time.sleep(wait)
    except (urllib.error.HTTPError, urllib.error.URLError):
        # Nightshift is up but failing (for example NVIDIA refused the key saved in it): skip
        # it for a minute and send this request to NVIDIA's cloud instead.
        if base == NVIDIA_CLOUD or not os.environ.get("NVIDIA_API_KEY"):
            raise
        _up["until"] = time.time() + 60
        return _chat(messages, stream, max_tokens, model, temperature)
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
