"""Dependency-free authenticated HTTP/SSE gateway for the command center."""
from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

from app.dashboard.service import DashboardAuthorizationError, DashboardService, RuntimeCommandGateway

_STATIC = Path(__file__).with_name("static")


class DashboardServer:
    def __init__(self, service: DashboardService, commands: RuntimeCommandGateway,
                 host: str = "127.0.0.1", port: int = 0,
                 event_loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.service, self.commands = service, commands
        self.event_loop = event_loop
        self.httpd = ThreadingHTTPServer((host, port), self._handler())
        self.thread: Thread | None = None

    @property
    def address(self) -> tuple[str, int]: return self.httpd.server_address

    def start(self) -> None:
        self.thread = Thread(target=self.httpd.serve_forever, name="dashboard", daemon=True); self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown(); self.httpd.server_close()
        if self.thread: self.thread.join(timeout=2)

    def _handler(self):
        service, commands, event_loop = self.service, self.commands, self.event_loop
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/": return self._file("index.html", "text/html; charset=utf-8")
                if parsed.path.startswith("/static/"):
                    name = parsed.path.removeprefix("/static/")
                    if name not in {"app.js", "styles.css"}: return self._json(HTTPStatus.NOT_FOUND, {"error":"not_found"})
                    return self._file(name, "text/javascript" if name.endswith(".js") else "text/css")
                if not self._authorized(parsed): return self._json(HTTPStatus.UNAUTHORIZED, {"error":"unauthorized"})
                query=parse_qs(parsed.query)
                if parsed.path == "/api/system": return self._json(HTTPStatus.OK, service.snapshot())
                if parsed.path == "/api/health": return self._json(HTTPStatus.OK, service.health())
                if parsed.path == "/api/events": return self._json(HTTPStatus.OK, service.events(since=int(query.get("since",[0])[0])))
                if parsed.path == "/api/search": return self._json(HTTPStatus.OK, service.search(query.get("q",[""])[0]))
                if parsed.path == "/api/perception/screenshot": return self._screenshot()
                projections={"/api/missions":"missions","/api/tasks":"tasks","/api/agents":"agents",
                    "/api/schedules":"schedules","/api/actions":"actions","/api/approvals":"approvals",
                    "/api/resources":"resources","/api/world":"world","/api/system/inventory":"inventory",
                    "/api/recovery":"recovery","/api/security":"security","/api/logs":"logs"}
                projections.update({"/api/analytics":"analytics", "/api/notifications":"notifications"})
                projections.update({"/api/memory":"memory", "/api/skills":"skills"})
                if parsed.path in projections:
                    return self._json(HTTPStatus.OK, service.snapshot()[projections[parsed.path]])
                if parsed.path == "/api/stream":
                    since=int(query.get("since",[0])[0]); events=service.events(since=since)
                    if not events:
                        import time
                        deadline=time.monotonic()+15
                        while time.monotonic()<deadline and not events:
                            time.sleep(.1); events=service.events(since=since)
                    body="".join(f"id: {item['sequence']}\ndata: {json.dumps(item)}\n\n" for item in events).encode()
                    self.send_response(HTTPStatus.OK); self.send_header("Content-Type","text/event-stream"); self.send_header("Cache-Control","no-cache"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
                return self._json(HTTPStatus.NOT_FOUND, {"error":"not_found"})
            def do_POST(self):
                if not self._authorized(urlparse(self.path)): return self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"})
                if self.path != "/api/commands": return self._json(HTTPStatus.NOT_FOUND,{"error":"not_found"})
                future = None
                try:
                    length=int(self.headers.get("Content-Length","0"))
                    if length > 16_384: return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,{"error":"too_large"})
                    data=json.loads(self.rfile.read(length)); token=self.headers.get("Authorization","").removeprefix("Bearer ")
                    operation=commands.execute(token,str(data["command"]),dict(data.get("payload",{})))
                    if event_loop:
                        future = asyncio.run_coroutine_threadsafe(operation, event_loop)
                        result = future.result(timeout=30)
                    else:
                        result = asyncio.run(operation)
                    return self._json(HTTPStatus.ACCEPTED,result)
                except DashboardAuthorizationError: return self._json(HTTPStatus.UNAUTHORIZED,{"error":"unauthorized"})
                except (KeyError,ValueError,TypeError,json.JSONDecodeError) as error: return self._json(HTTPStatus.BAD_REQUEST,{"error":str(error)})
                except FutureTimeoutError:
                    if future: future.cancel()
                    return self._json(HTTPStatus.GATEWAY_TIMEOUT,{"error":"runtime_command_timeout"})
                except Exception:
                    return self._json(HTTPStatus.INTERNAL_SERVER_ERROR,{"error":"runtime_command_failed"})
            def _authorized(self, parsed):
                supplied=self.headers.get("Authorization","").removeprefix("Bearer ")
                return commands.authorized(supplied)
            def _file(self,name,content_type):
                body=(_STATIC/name).read_bytes(); self.send_response(HTTPStatus.OK); self._security_headers()
                self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
            def _json(self,status,payload):
                body=json.dumps(payload,default=str).encode(); self.send_response(status); self._security_headers()
                self.send_header("Content-Type","application/json"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
            def _screenshot(self):
                perception = service.runtime.perception
                reference = perception.latest.screenshot_reference if perception and perception.latest else None
                path = Path(reference).resolve() if reference else None
                if not path or not path.is_file() or path.suffix.casefold() not in {".png", ".jpg", ".jpeg"}:
                    return self._json(HTTPStatus.NOT_FOUND, {"error":"screenshot_unavailable"})
                roots = tuple((Path.cwd() / name).resolve() for name in ("screenshots", "data"))
                if not any(path == root or root in path.parents for root in roots):
                    return self._json(HTTPStatus.FORBIDDEN, {"error":"screenshot_not_permitted"})
                if path.stat().st_size > 5_000_000:
                    return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error":"screenshot_too_large"})
                body = path.read_bytes(); self.send_response(HTTPStatus.OK); self._security_headers()
                self.send_header("Content-Type", "image/png" if path.suffix.casefold() == ".png" else "image/jpeg")
                self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)
            def _security_headers(self):
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return Handler
