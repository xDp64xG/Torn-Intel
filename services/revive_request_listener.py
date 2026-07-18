"""
Local HTTP listener for external revive requests.
"""

from __future__ import annotations

import json
import re
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from modules.revives.sync import ReviveSync
from repositories.revive_request_repository import ReviveRequestRepository
from utils.colors import highlight, info, muted, success


ID_SUFFIX_RE = re.compile(r"^(?P<name>.*?)\s*\[(?P<id>\d+)\]\s*$")


class ReviveRequestListener:

    def __init__(self, services):
        self.services = services
        self.repo = ReviveRequestRepository(services.database)

    #######################################################

    def serve(self, host=None, port=None, poll_seconds=15, window_seconds=21600):

        host = host or self.services.settings.revive_listener_host
        port = int(port or self.services.settings.revive_listener_port)
        poll_seconds = max(1, int(poll_seconds or 15))
        window_seconds = max(60, int(window_seconds or 21600))
        logger = self.services.logger
        repo = self.repo
        syncer = ReviveSync(self.services)

        def row_value(row, field, default=None):
            if row is None:
                return default
            try:
                if isinstance(row, dict):
                    return row.get(field, default)
                return row[field]
            except Exception:
                return getattr(row, field, default)

        def log_fulfilled_request(request, source):
            target = highlight(row_value(request, "target_name") or f"Target {row_value(request, 'target_id') or '?'}")
            reviver = success(row_value(request, "fulfilled_by_name") or str(row_value(request, "fulfilled_by_id") or "unknown reviver"))
            revived_at = int(row_value(request, "revived_timestamp") or row_value(request, "fulfilled_at") or 0)
            revived_text = time.strftime("%m-%d %H:%M:%S", time.localtime(revived_at)) if revived_at else "unknown time"
            request_id = muted(str(row_value(request, "request_id") or "?"))
            requester = highlight(row_value(request, "requester_name") or f"Requester {row_value(request, 'requester_id') or '?'}")
            payout_template = (
                f"Payout template: {requester}, your revive request for {target} was fulfilled by {reviver} "
                f"at {revived_text}. Please send the agreed payout."
            )
            logger.success(
                f"{info('Revive request fulfilled')} [{source}] {target} by {reviver} at {success(revived_text)} ({request_id})"
            )
            logger.info(payout_template)

        def emit_notification(event_type, request, extra=None):
            payload = dict(request)
            if extra:
                payload.update(extra)
            notification = repo.queue_notification(event_type, request, payload=payload)
            if notification:
                logger.info(
                    f"Queued revive notification {event_type} for request={row_value(notification, 'request_id')}"
                )
            return notification

        def legacy_notifications(requester_id=None, requester_name=None, limit=10):
            rows = repo.get_unnotified_fulfilled(
                requester_id=requester_id,
                requester_name=requester_name,
                limit=limit,
            )
            payload = []
            for row in rows:
                row_dict = dict(row)
                row_dict["event_type"] = row_dict.get("event_type") or "revive_request_fulfilled"
                payload.append(row_dict)
            repo.mark_notified([row["request_id"] for row in rows])
            return payload

        class Handler(BaseHTTPRequestHandler):

            def _send_json(self, code, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                self._send_json(200, {"ok": True})

            def do_GET(self):
                try:
                    raw_path = str(self.path or "")
                    parsed = urlparse(self.path)
                    path = str(parsed.path or "")
                    logger.info(f"Revive listener GET raw={raw_path} parsed={path}")

                    if path == "/health" or raw_path.endswith("/health"):
                        self._send_json(
                            200,
                            {
                                "ok": True,
                                "service": "revive_request_listener",
                                "timestamp": int(time.time()),
                            },
                        )
                        return

                    if "revive-request" in raw_path and "notifications" in raw_path:
                        query = parse_qs(parsed.query)
                        requester_id = query.get("requester_id", [None])[0]
                        requester_name = query.get("requester_name", [None])[0]
                        rows = repo.get_notifications(
                            requester_id=int(requester_id) if requester_id not in (None, "") else None,
                            requester_name=requester_name,
                            limit=int(query.get("limit", [10])[0] or 10),
                        )
                        if rows:
                            payload = [dict(row) for row in rows]
                            repo.mark_notifications_notified([row["notification_id"] for row in rows])
                        else:
                            payload = legacy_notifications(
                                requester_id=int(requester_id) if requester_id not in (None, "") else None,
                                requester_name=requester_name,
                                limit=int(query.get("limit", [10])[0] or 10),
                            )
                        self._send_json(200, {"ok": True, "notifications": payload})
                        return

                    self._send_json(404, {"ok": False, "error": "not_found", "path": path, "raw_path": raw_path})
                except Exception as exc:
                    logger.error(f"Revive listener GET error: {type(exc).__name__}: {exc}")
                    self._send_json(500, {"ok": False, "error": "internal_error"})
                return

            def do_POST(self):
                if self.path != "/revive-request":
                    self._send_json(404, {"ok": False, "error": "not_found"})
                    return

                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length > 0 else b"{}"

                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    self._send_json(400, {"ok": False, "error": "invalid_json"})
                    return

                try:
                    request_row = self._normalize_request_payload(payload)
                    request_id = repo.create_request(request_row)
                    saved_request = repo.get(request_id)
                    if saved_request:
                        emit_notification("revive_request_received", saved_request, extra={"source_event": "post"})
                    fulfilled_rows = repo.reconcile_against_database(
                        window_seconds=int(payload.get("window_seconds") or window_seconds),
                        limit=1,
                        return_rows=True,
                    )

                    for fulfilled in fulfilled_rows:
                        emit_notification("revive_request_fulfilled", fulfilled, extra={"source_event": "reconcile"})
                        log_fulfilled_request(fulfilled, "request")

                    rows = repo.db.select(
                        "SELECT * FROM revive_requests WHERE request_id = ? LIMIT 1",
                        (str(request_id),),
                    )
                    saved = dict(rows[0]) if rows else {"request_id": request_id}
                    self._send_json(200, {"ok": True, "request": saved})
                except ValueError as exc:
                    self._send_json(400, {"ok": False, "error": str(exc)})
                except Exception as exc:
                    logger.error(f"Revive listener error: {type(exc).__name__}: {exc}")
                    self._send_json(500, {"ok": False, "error": "internal_error"})

            def log_message(self, _format, *_args):
                return

            def _normalize_request_payload(self, payload):
                requested_at = payload.get("requested_at") or payload.get("requested_timestamp") or int(time.time())

                requester_id = payload.get("requester_id")
                requester_name = payload.get("requester_name") or payload.get("requester") or payload.get("usuario")
                requester_name, requester_id = _coerce_name_id(requester_name, requester_id)

                target_id = payload.get("target_id")
                target_name = payload.get("target_name") or payload.get("target")
                target_name, target_id = _coerce_name_id(target_name, target_id)

                if target_id is None and not target_name:
                    raise ValueError("target_id_or_name_required")

                request_id = payload.get("request_id") or f"revreq:{int(time.time() * 1000)}:{target_id or target_name}"

                return {
                    "request_id": str(request_id),
                    "requested_timestamp": int(requested_at),
                    "created_at": int(time.time()),
                    "requester_id": int(requester_id) if requester_id is not None else None,
                    "requester_name": requester_name,
                    "target_id": int(target_id) if target_id is not None else None,
                    "target_name": target_name,
                    "source": payload.get("source") or payload.get("function") or "external",
                    "status": "pending",
                    "fulfilled_revive_id": None,
                    "fulfilled_at": None,
                    "fulfilled_by_id": None,
                    "fulfilled_by_name": None,
                    "matched_at": None,
                    "notes": payload.get("notes") or payload.get("details"),
                    "raw_payload": payload,
                }

        server = HTTPServer((host, port), Handler)
        server.timeout = 1
        logger.info(f"Revive request listener running on http://{host}:{port}")
        if host in ("127.0.0.1", "localhost"):
            logger.info(
                "Listener is bound to localhost only. For other computers, run with --host 0.0.0.0 and use this machine's LAN IP in Tampermonkey."
            )
        logger.info(f"Pending revive requests will be polled every {poll_seconds}s")

        next_poll_at = time.time() + poll_seconds

        try:
            while True:
                server.handle_request()

                now = time.time()
                if now < next_poll_at:
                    continue

                next_poll_at = now + poll_seconds
                pending = repo.pending_count()
                if pending <= 0:
                    continue

                imported = syncer.sync(mode="live")
                matched_rows = repo.reconcile_against_database(
                    window_seconds=window_seconds,
                    limit=max(50, pending),
                    return_rows=True,
                )

                for fulfilled in matched_rows:
                    emit_notification("revive_request_fulfilled", fulfilled, extra={"source_event": "poll"})
                    log_fulfilled_request(fulfilled, "poll")

                logger.info(
                    f"{info('Revive listener poll')} pending={highlight(str(pending))} "
                    f"imported={highlight(str(imported))} matched={success(str(len(matched_rows)))}"
                )
        except KeyboardInterrupt:
            logger.info("Revive request listener stopped")
        finally:
            server.server_close()


def _coerce_name_id(name, value_id):
    if value_id not in (None, ""):
        try:
            value_id = int(value_id)
        except Exception:
            value_id = None

    if name:
        text = str(name).strip()
        match = ID_SUFFIX_RE.match(text)
        if match:
            parsed_name = match.group("name").strip()
            parsed_id = int(match.group("id"))
            return parsed_name or text, value_id or parsed_id
        return text, value_id

    return None, value_id