"""Local web dashboard: serves one page and a JSON snapshot of CointOS.

Bound to loopback only. The page polls `/api/state`; all data comes from
`ecosystem.views.snapshot`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

from ecosystem import views

PAGE = Path(__file__).resolve().parent / "web/dashboard.html"


def app(environ: dict, start_response) -> list[bytes]:
    path = environ.get("PATH_INFO", "/")
    if path == "/api/state":
        try:
            body, status = json.dumps(views.snapshot()).encode(), "200 OK"
        except Exception as error:  # the page shows the error instead of going blank
            body = json.dumps({"error": f"{type(error).__name__}: {error}"}).encode()
            status = "500 Internal Server Error"
        start_response(status, [("Content-Type", "application/json"), ("Cache-Control", "no-store")])
        return [body]
    if path in ("/", "/index.html"):
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [PAGE.read_bytes()]
    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"not found"]


def quiet_handler() -> type:
    return type("QuietHandler", (WSGIRequestHandler,), {"log_message": lambda *_: None})


def main() -> None:
    port = int(os.environ.get("COINTOS_DASHBOARD_PORT", "4200"))
    with make_server("127.0.0.1", port, app, handler_class=quiet_handler()) as server:
        print(f"CointOS dashboard on http://127.0.0.1:{port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
