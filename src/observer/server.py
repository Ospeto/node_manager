import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .controller import ObserverController
from ..utils.logger import get_logger


class ObserverServer:
    def __init__(self, host: str, port: int, controller: ObserverController, allow_origin: str = "*"):
        self.host = host
        self.port = port
        self.controller = controller
        self.allow_origin = allow_origin
        self.logger = get_logger(__name__)
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def _handler(self):
        controller = self.controller
        allow_origin = self.allow_origin

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, status: int, payload: dict, include_cors: bool = False) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                if include_cors:
                    self.send_header("Access-Control-Allow-Origin", allow_origin)
                    self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                if self.path == "/observer/status":
                    self.send_response(204)
                    self.send_header("Access-Control-Allow-Origin", allow_origin)
                    self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")
                    self.end_headers()
                    return
                self.send_response(404)
                self.end_headers()

            def do_GET(self):
                if self.path == "/health":
                    self._send_json(200, controller.health_payload())
                    return
                if self.path == "/observer/status":
                    self._send_json(200, controller.build_status_payload(), include_cors=True)
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                if self.path != "/observer/snapshot":
                    self.send_response(404)
                    self.end_headers()
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0

                body = self.rfile.read(length)
                signature = self.headers.get("X-Observer-Signature", "")
                status, payload = controller.handle_snapshot(body=body, signature=signature)
                self._send_json(status, payload)

            def log_message(self, fmt, *args):
                return

        return Handler

    def start(self) -> None:
        self._server = ThreadingHTTPServer((self.host, self.port), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.logger.info("Observer server listening on %s:%s", self.host, self.port)

    def stop(self) -> None:
        if not self._server:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=3)
        self.logger.info("Observer server stopped")
