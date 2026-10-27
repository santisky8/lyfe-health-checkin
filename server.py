"""Lyfe Health Check-In web app. Standard library only.

  python3 server.py            # then open http://localhost:8765

The page sends the whole conversation to /api/turn. It gets back a clarifying question, the
emergency message, or the prepared evidence (Zetaris SQL, PubMed, H-MEM recall, and the agent's
decisions), which it shows at once. It then calls /api/stream, which streams the model's answer
and ends with the checked answer and the H-MEM memory it was saved as.

  PUBLIC=1 PORT=8766 python3 server.py   # public demo copy behind Tailscale Funnel (demo_on.sh)

Public mode gives each visitor their own H-MEM memory (cookie) and hides error details."""
import json
import os
import re
import secrets
import sys
import hashlib
import shutil
import ipaddress
import threading
import time
import uuid
from collections import deque
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "agent"))
import checkin  # noqa: E402  (loads .env.local)
import library  # noqa: E402
import memory  # noqa: E402
import store  # noqa: E402

PORT = int(os.environ.get("PORT", 8765))
PUBLIC = os.environ.get("PUBLIC") == "1"
_prepared = {}  # evidence waiting for /api/stream, by id; oldest dropped past MAX_WAITING
MAX_WAITING = 100
_lock = threading.Lock()
EMBEDDERS = "https://santisky8.github.io"
# Assistant turns the server really sent (a question it asked or an answer it wrote), by hash.
# The page sends the whole conversation back each time; an "assistant" turn the server never
# issued is dropped, so nobody can slip text past the safety screen by labelling it the agent's.
_issued = {}
MAX_ISSUED = 20000


def _digest(text):
    return hashlib.sha256(str(text)[:4000].encode()).hexdigest()


def issued(text):
    """Remember text the server sent as the agent's own turn."""
    with _lock:
        _issued[_digest(text)] = True
        while len(_issued) > MAX_ISSUED:
            _issued.pop(next(iter(_issued)))


def genuine(turns):
    """Only the person's own turns, plus agent turns this server issued."""
    return [t for t in turns if t["role"] == "user"
            or (t["role"] == "assistant" and _digest(t["content"]) in _issued)]


# Public mode: limits per caller and in total, so nobody can spend the NVIDIA key or fill the
# disk with memory folders by looping on the API. (max requests, per seconds)
# Totals are mostly hourly, so a flood locks everyone out for an hour at most, not a day.
LIMITS = {"model": [("each", 10, 60), ("all", 60, 3600), ("all", 600, 86400)],
          "memory": [("each", 60, 60), ("all", 1500, 3600)]}
_hits = {}  # (kind, caller or "all", window) -> request times inside that window


def allowed(kind, caller):
    """True if this caller may make one more request of this kind (always true locally)."""
    if not PUBLIC:
        return True
    now = time.time()
    windows = [((kind, caller if who == "each" else "all", secs), most, secs)
               for who, most, secs in LIMITS[kind]]
    with _lock:
        if len(_hits) > 10000:  # many callers: forget their windows, never the totals
            for key in [k for k in _hits if k[1] != "all"]:
                del _hits[key]
        for key, most, secs in windows:
            seen = _hits.setdefault(key, deque())
            while seen and seen[0] < now - secs:
                seen.popleft()
            if len(seen) >= most:
                return False
        for key, _, _ in windows:
            _hits[key].append(now)
    return True


def person(value):
    """A Fitbit user id from the request: digits only, since it goes into SQL and H-MEM."""
    if not re.fullmatch(r"\d{1,20}", str(value)):
        raise ValueError("unknown person")
    if PUBLIC and str(value) not in {u["user_id"] for u in users()}:  # no memory for made-up ids
        raise ValueError("unknown person")
    return str(value)


def day(value):
    """An ISO date from the request, or None for the latest week."""
    if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
        raise ValueError("bad date")
    return value or None


@lru_cache(maxsize=1)  # the Fitbit data never changes while the server runs
def users():
    """People in the Fitbit data, with how many nights of sleep each one logged. Many wore the
    watch only in the day, so the people with the most sleep data come first."""
    found = store.query(
        f"SELECT user_id, min(day) AS first_day, max(day) AS last_day, count(*) AS days, "
        f"sum(CASE WHEN CAST(minutes_asleep AS INT) > 0 THEN 1 ELSE 0 END) AS nights "
        f"FROM {store.table('user_log')} GROUP BY user_id ORDER BY user_id")
    for u in found:
        u["nights"] = int(u["nights"] or 0)
    found.sort(key=lambda u: (u["user_id"] != "1503960366", -u["nights"]))  # demo person first
    for i, u in enumerate(found, 1):
        u["n"] = i
    return found


def log(user_id, as_of, days=28):
    rows = store.query(
        f"SELECT day, steps, active_minutes, minutes_asleep FROM {store.table('user_log')} "
        f"WHERE user_id = ? AND day <= ? ORDER BY day DESC LIMIT ?",
        (user_id, as_of or "9999-12-31", days))
    return list(reversed(rows))


class Handler(BaseHTTPRequestHandler):
    timeout = 20  # a client that stops sending mid-request can't hold a thread forever
    server_version = "lyfe-health-checkin"  # no Python version in the Server header
    sys_version = ""

    def _start(self):
        """Public mode: find or make this visitor's id and point H-MEM at their own memory."""
        self._cookie = None
        if not PUBLIC:
            return
        found = re.search(r"(?:^|;\s*)lhv=([0-9a-f]{16})\b", self.headers.get("Cookie", ""))
        vid = found.group(1) if found else secrets.token_hex(8)
        if not found:
            # SameSite=None + Partitioned: the cookie also works when the showcase site embeds
            # the app, kept separate per embedding site.
            self._cookie = (f"lhv={vid}; Path=/; Max-Age=2592000; HttpOnly; Secure; "
                            "SameSite=None; Partitioned")
        memory.visitor.set(vid)

    def _caller(self):
        """Who is asking: Funnel forwards every request from 127.0.0.1 and appends the real
        address to X-Forwarded-For. Earlier entries come from the caller and can be faked, so
        only the last one counts."""
        ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[-1].strip()
        try:  # one IPv6 user can hold a whole /64, so count the /64 as one caller
            addr = ipaddress.ip_address(ip)
            return str(ipaddress.ip_network(f"{ip}/64", strict=False)) if addr.version == 6 else ip
        except ValueError:
            return ip

    def _cross_site(self):
        """True for a POST from another site (CSRF), or one that isn't JSON: the app always
        sends JSON from its own address, and only the showcase site may embed it."""
        origin = self.headers.get("Origin")
        own = {f"https://{self.headers.get('Host', '')}", f"http://{self.headers.get('Host', '')}"}
        bad_origin = origin is not None and origin not in own | set(EMBEDDERS.split())
        return bad_origin or not self.headers.get("Content-Type", "").startswith("application/json")

    def _headers(self, code, kind):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        if kind.startswith("text/html"):  # only the showcase sites may embed the app
            self.send_header("Content-Security-Policy", f"frame-ancestors 'self' {EMBEDDERS}")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if self._cookie:
            self.send_header("Set-Cookie", self._cookie)

    def _send(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self._headers(code, kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _fail(self, e):
        if not PUBLIC:  # shown in the page, never a stack trace
            return self._send(500, {"error": str(e)[:300]})
        sys.stderr.write(f"error: {e!r}\n")
        self._send(500, {"error": "Something went wrong on the demo server. Please try again."})

    def do_GET(self):
        self._start()
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/":
                return self._send(200, (ROOT / "web" / "index.html").read_bytes(),
                                  "text/html; charset=utf-8")
            if url.path == "/api/status":  # the showcase site checks this to show "Live now"
                self._headers(200, "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(b'{"live": true}')
            if url.path == "/api/users":
                return self._send(200, users())
            if (url.path in ("/api/log", "/api/suggest", "/api/memory")
                    and not allowed("memory", self._caller())):
                return self._send(429, {"error": "Too many requests. Please wait a minute."})
            if url.path == "/api/log":
                return self._send(200, log(person(q["user"]), day(q.get("as_of"))))
            if url.path == "/api/suggest":
                return self._send(200, checkin.suggestions(person(q["user"]), day(q.get("as_of"))))
            if url.path == "/api/memory":
                user = person(q["user"])
                return self._send(200, [dict(m, entry=checkin.journal_entry(m),
                                             answer=checkin.saved_answer(user, m["id"]))
                                        for m in memory.all_memories(user)])
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._fail(e)

    def do_POST(self):
        self._start()
        try:
            size = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self._send(400, {"error": "bad request"})
        if size < 0 or size > 65536:
            return self._send(413, {"error": "message too long"})
        if PUBLIC and self._cross_site():
            return self._send(403, {"error": "forbidden"})
        kind = {"/api/turn": "model", "/api/note": "memory"}.get(self.path)
        if kind and not allowed(kind, self._caller()):
            return self._send(429, {"error": "Too many requests. Please wait a minute."})
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
            if self.path == "/api/turn":
                turns = genuine([{"role": x["role"], "content": str(x["content"])[:4000],
                                  "kind": x.get("kind")} for x in body["turns"][-16:]])
                if not turns or turns[-1]["role"] != "user":
                    raise ValueError("bad conversation")
                prep = checkin.turn(turns, person(body["user"]), day(body.get("as_of")))
                if prep.get("ask"):
                    issued(prep["ask"]["q"])
                if prep.get("urgent") is None and "sources" in prep:
                    prep["id"] = str(uuid.uuid4())
                    with _lock:
                        _prepared[prep["id"]] = prep
                        while len(_prepared) > MAX_WAITING:  # check-ins nobody streamed
                            _prepared.pop(next(iter(_prepared)))
                return self._send(200, prep)
            if self.path == "/api/stream":
                with _lock:
                    prep = _prepared.pop(body["id"])
                return self._stream(prep)
            if self.path == "/api/note":
                return self._send(200, checkin.note(person(body["user"]),
                                                    body["text"].strip()[:500]))
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._fail(e)

    def _stream(self, prep):
        """Server-sent events: {"delta": "..."} while the model writes, then {"done": {...}}."""
        self._headers(200, "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def emit(obj):
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
            self.wfile.flush()

        text = ""
        try:
            for piece in checkin.stream_model(prep):
                text += piece
                emit({"delta": piece})
            done = checkin.finish(prep, text)
            issued(done["text"])
            emit({"done": done})
        except Exception as e:
            sys.stderr.write(f"stream error: {e!r}\n")
            emit({"error": "Something went wrong on the demo server. Please try again."
                  if PUBLIC else str(e)[:300]})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))


VISITOR_DAYS = 7  # public-demo visitors' memories and traces are deleted after this long unused


def forget_visitors():
    """Delete public-demo visitors' memories and traces unused for VISITOR_DAYS, now and every
    six hours. The demo people's own memories (no -v suffix) are kept."""
    while True:
        cutoff = time.time() - VISITOR_DAYS * 86400
        for path in [*(ROOT / "data" / "memory").glob("*-v*"), *(ROOT / "data" / "traces").glob("*-v*")]:
            try:
                # last activity: memory files are rewritten in place, which leaves the folder's
                # own time at the first visit
                last = max([f.stat().st_mtime for f in path.iterdir()] if path.is_dir() else [],
                           default=path.stat().st_mtime)
                if last < cutoff:
                    shutil.rmtree(path) if path.is_dir() else path.unlink()
            except OSError:
                pass
        time.sleep(6 * 3600)


if __name__ == "__main__":
    print(f"Lyfe Health Check-In on http://localhost:{PORT} (data: {store.backend()})"
          + (", public mode" if PUBLIC else ""))
    # Warm up in the background so the first visitor doesn't pay for loading the topic index,
    # the embedding model and the Zetaris login.
    threading.Thread(target=lambda: (users(), library.search("tired in the afternoon")),
                     daemon=True).start()
    if PUBLIC:
        threading.Thread(target=forget_visitors, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
