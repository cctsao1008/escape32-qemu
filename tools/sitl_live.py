#!/usr/bin/env python3
"""Phase 2: read-only, localhost-only E62 SITL live telemetry (SSE).

The publisher does no I/O, performs NO RSP/QTest reads and never controls
QEMU. A bounded in-memory ring isolates guest progress from slow browsers.
Overruns are explicit (snapshot.truncated / SSE gap), never silently healed.
"""
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time


class LiveTelemetryHub:
    def __init__(self, *, capacity=2048):
        if not isinstance(capacity, int) or not 1 <= capacity <= 65536:
            raise ValueError("SITL telemetry ring capacity out of range")
        self.capacity = capacity
        self._cv = threading.Condition()
        self._packets = deque(maxlen=capacity)
        self._seq = 0
        self._meta = None
        self._complete = None
        self._closed = False

    def begin(self, meta):
        if not isinstance(meta, dict) or not meta.get("elf_sha256"):
            raise ValueError("Native ELF provenance required for live stream")
        with self._cv:
            if self._meta is not None or self._closed:
                raise RuntimeError("SITL live session already started/closed")
            self._meta = dict(meta)
            self._cv.notify_all()

    def publish(self, sample, events):
        """O(1) memory append; no socket writes and no Guest queries."""
        if not isinstance(sample, dict) or not isinstance(events, list):
            raise ValueError("Already validated native WFI sample/events required")
        with self._cv:
            if self._closed or self._complete is not None:
                raise RuntimeError("Cannot publish after SITL completion")
            if self._meta is None:
                raise RuntimeError("Missing live session provenance")
            self._seq += 1
            self._packets.append((self._seq, {"sample": sample, "events": events}))
            self._cv.notify_all()

    def finish(self, *, native_result, error_type):
        with self._cv:
            if self._complete is None:
                self._complete = {
                    "native_result": native_result,
                    "error_type": error_type,
                    "strict_extended_gate": "NOT_EXECUTED_BY_LIVE_TELEMETRY",
                }
                self._cv.notify_all()

    def snapshot(self):
        with self._cv:
            return self._snapshot_locked()

    def _snapshot_locked(self):
        oldest = self._packets[0][0] if self._packets else self._seq + 1
        return {
            "metadata": self._meta,
            "seq": self._seq,
            "oldest_seq": oldest,
            "truncated": oldest > 1,
            "packets": [p for _, p in self._packets],
            "complete": self._complete,
            "read_only": True,
        }

    def since(self, cursor, *, timeout=1.0):
        """Read-side wait ONLY. Never blocks the guest-side publisher."""
        with self._cv:
            if self._complete is None and not self._closed and self._seq <= cursor:
                self._cv.wait(timeout=timeout)
            oldest = self._packets[0][0] if self._packets else self._seq + 1
            missing = max(0, oldest - cursor - 1)
            packets = [(seq, item) for seq, item in self._packets if seq > cursor]
            return {
                "missing": missing,
                "packets": packets,
                "complete": self._complete,
                "closed": self._closed,
                "seq": self._seq,
                "metadata": self._meta,
            }

    def close(self):
        with self._cv:
            self._closed = True
            self._cv.notify_all()


class _LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class SitlLiveServer:
    """Owns a loopback HTTP/SSE server; never takes possession of QEMU."""

    def __init__(self, *, port, hub=None, viewer_path=None):
        if not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("Live port must be 0..65535")
        self.hub = hub if hub is not None else LiveTelemetryHub()
        self.viewer_path = (Path(viewer_path) if viewer_path is not None else
                            Path(__file__).resolve().parents[1] /
                            "web" / "sitl_trace_viewer.html")
        parent = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass  # Do not mix browser connections with native probe logs.

            def _allowed(self):
                host = self.headers.get("Host", "")
                allowed = {
                    f"127.0.0.1:{parent.port}", f"localhost:{parent.port}",
                }
                origin = self.headers.get("Origin")
                return (host in allowed and
                        (not origin or origin in {
                            f"http://127.0.0.1:{parent.port}",
                            f"http://localhost:{parent.port}",
                        }))

            def do_POST(self):
                self.send_error(405, "Read-only SITL telemetry; no commands")

            def do_GET(self):
                if not self._allowed():
                    self.send_error(403, "Loopback host/origin required")
                    return
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    payload = parent.viewer_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Security-Policy",
                                     "default-src 'self'; script-src 'unsafe-inline'; "
                                     "style-src 'unsafe-inline'; connect-src 'self'; "
                                     "img-src 'none'; object-src 'none'; frame-ancestors 'none'")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if path != "/events":
                    self.send_error(404, "Unknown read-only SITL endpoint")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-transform")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self._stream()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass  # A browser disconnect never affects native Guest.
                finally:
                    self.close_connection = True

            def _emit(self, name, data, seq=None):
                body = "event: " + name + "\n"
                if seq is not None:
                    body += "id: " + str(seq) + "\n"
                body += "data: " + json.dumps(
                    data, allow_nan=False, separators=(",", ":")
                ) + "\n\n"
                self.wfile.write(body.encode("utf-8"))
                self.wfile.flush()

            def _stream(self):
                snap = parent.hub.snapshot()
                cursor = snap["seq"]
                self._emit("snapshot", snap)
                seen_meta = snap["metadata"] is not None
                sent_finish = snap["complete"] is not None
                while True:
                    update = parent.hub.since(cursor, timeout=1.0)
                    if not seen_meta and update["metadata"] is not None:
                        self._emit("begin", {"metadata": update["metadata"]})
                        seen_meta = True
                    if update["missing"]:
                        self._emit("gap", {
                            "missing_packets": update["missing"],
                            "since_seq": cursor,
                        })
                    for seq, packet in update["packets"]:
                        self._emit("frame", packet, seq=seq)
                        cursor = seq
                    if update["missing"] and not update["packets"]:
                        cursor = update["seq"]
                    if update["complete"] is not None and not sent_finish:
                        self._emit("complete", update["complete"])
                        sent_finish = True
                    if update["closed"]:
                        return
                    if not update["packets"] and update["complete"] is None:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                    # A completed stream stays open for history review while
                    # --sitl-live-hold is enabled, without browser reconnect loops.
                    if sent_finish:
                        time.sleep(0.25)

        self._server = _LocalServer(("127.0.0.1", port), Handler)
        self.port = self._server.server_address[1]
        self._thread = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/"

    def start(self):
        if self._thread is not None:
            raise RuntimeError("SITL live server already started")
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="e62-sitl-live-http", daemon=True)
        self._thread.start()
        return self

    def close(self):
        self.hub.close()
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=3)
        self._server.server_close()
