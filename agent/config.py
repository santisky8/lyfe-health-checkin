"""Settings from .env.local (gitignored): KEY=value lines or a Meterless Quick Connect link."""
import os
import urllib.parse


def load_env():
    """Read .env.local (gitignored). Accepts KEY=value lines or a Meterless Quick Connect link
    (http://<host>:<port>/connect#k=<key>&m=<model>)."""
    path = os.path.join(os.path.dirname(__file__), "..", ".env.local")
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if "/connect#" in line:
            base, frag = line.split("/connect#", 1)
            params = dict(p.split("=", 1) for p in frag.split("&") if "=" in p)
            os.environ.setdefault("LLM_BASE_URL", base.rstrip("/") + "/v1")
            if "k" in params:
                os.environ.setdefault("LLM_API_KEY", params["k"])
            if "m" in params:
                os.environ.setdefault("LLM_MODEL", urllib.parse.unquote(params["m"]))
        elif "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_env()
