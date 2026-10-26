"""Lyfe Health Check-In web app. Standard library only.

  python3 server.py            # then open http://localhost:8765

The page calls /api/prepare first (safety check, Zetaris SQL, H-MEM recall: a few seconds),
shows that evidence, then calls /api/respond for the model's answer (can take minutes on a
local CPU model).

  PUBLIC=1 PORT=8766 python3 server.py   # public demo copy behind Tailscale Funnel (demo_on.sh)

Public mode gives each visitor their own H-MEM memory (cookie) and hides error details."""
import json
import os
import re
import secrets
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "agent"))
import checkin  # noqa: E402  (loads .env.local)
import memory  # noqa: E402
import store  # noqa: E402

PORT = int(os.environ.get("PORT", 8765))
PUBLIC = os.environ.get("PUBLIC") == "1"
_prepared = {}
_lock = threading.Lock()


def users():
    return store.query(
        f"SELECT user_id, min(day) AS first_day, max(day) AS last_day, count(*) AS days "
        f"FROM {store.table('user_log')} GROUP BY user_id ORDER BY user_id")


def log(user_id, as_of, days=28):
    rows = store.query(
        f"SELECT day, steps, active_minutes, minutes_asleep FROM {store.table('user_log')} "
        f"WHERE user_id = ? AND day <= ? ORDER BY day DESC LIMIT ?",
        (user_id, as_of or "9999-12-31", days))
    return list(reversed(rows))


class Handler(BaseHTTPRequestHandler):
    def _start(self):
        """Public mode: find or make this visitor's id and point H-MEM at their own memory."""
        self._cookie = None
        if not PUBLIC:
            return
        found = re.search(r"(?:^|;\s*)lhv=([0-9a-f]{16})\b", self.headers.get("Cookie", ""))
        vid = found.group(1) if found else secrets.token_hex(8)
        if not found:
            self._cookie = f"lhv={vid}; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax"
        memory.visitor.set(vid)

    def _headers(self, code, kind):
        self.send_response(code)
        self.send_header("Content-Type", kind)
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
            if url.path == "/api/log":
                return self._send(200, log(q["user"], q.get("as_of")))
            if url.path == "/api/memory":
                return self._send(200, memory.all_memories(q["user"]))
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._fail(e)

    def do_POST(self):
        self._start()
        size = int(self.headers.get("Content-Length", 0))
        if size > 65536:
            return self._send(413, {"error": "message too long"})
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
            if self.path == "/api/prepare":
                prep = checkin.prepare(body["question"].strip()[:1500], body["user"],
                                       body.get("as_of") or None, bool(body.get("clarified")))
                if prep.get("clarify"):
                    return self._send(200, prep)
                prep["id"] = str(uuid.uuid4())
                with _lock:
                    _prepared[prep["id"]] = prep
                return self._send(200, prep)
            if self.path == "/api/turn":
                turns = [{"role": x["role"], "content": str(x["content"])[:4000],
                          "kind": x.get("kind")} for x in body["turns"][-16:]]
                prep = checkin.turn(turns, body["user"], body.get("as_of") or None)
                if prep.get("urgent") is None and "sources" in prep:
                    prep["id"] = str(uuid.uuid4())
                    with _lock:
                        _prepared[prep["id"]] = prep
                return self._send(200, prep)
            if self.path == "/api/respond":
                with _lock:
                    prep = _prepared.pop(body["id"])
                return self._send(200, checkin.respond(prep))
            if self.path == "/api/stream":
                with _lock:
                    prep = _prepared.pop(body["id"])
                return self._stream(prep)
            if self.path == "/api/note":
                return self._send(200, checkin.note(body["user"], body["text"].strip()[:500]))
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
            emit({"done": checkin.finish(prep, text)})
        except Exception as e:
            sys.stderr.write(f"stream error: {e!r}\n")
            emit({"error": "Something went wrong on the demo server. Please try again."
                  if PUBLIC else str(e)[:300]})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s\n" % (fmt % args))


if __name__ == "__main__":
    print(f"Lyfe Health Check-In on http://localhost:{PORT} (data: {store.backend()})"
          + (", public mode" if PUBLIC else ""))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
