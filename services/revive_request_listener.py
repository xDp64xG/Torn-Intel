"""
Local HTTP listener for external revive requests.
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
        notification_condition = threading.Condition()

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

        def log_new_request(request, source):
            target = highlight(row_value(request, "target_name") or f"Target {row_value(request, 'target_id') or '?'}")
            requester = highlight(row_value(request, "requester_name") or f"Requester {row_value(request, 'requester_id') or '?'}")
            requested_at = int(row_value(request, "requested_timestamp") or row_value(request, "created_at") or time.time())
            requested_text = time.strftime("%m-%d %H:%M:%S", time.localtime(requested_at)) if requested_at else "unknown time"
            request_id = muted(str(row_value(request, "request_id") or "?"))
            source_text = muted(str(row_value(request, "source") or source or "external"))
            notes = row_value(request, "notes")

            logger.info(
                f"{info('Revive request received')} [{source}] {target} by {requester} at {success(requested_text)} ({request_id})"
            )
            logger.info(
                "Revive request details: "
                f"request_id={request_id} | requester={requester} | target={target} | "
                f"source={source_text} | notes={muted(str(notes)) if notes else muted('-')}"
            )

        def emit_notification(event_type, request, extra=None):
            payload = dict(request)
            if extra:
                payload.update(extra)
            notification = repo.queue_notification(event_type, request, payload=payload)
            if notification:
                with notification_condition:
                    notification_condition.notify_all()
                logger.info(
                    f"Queued revive notification {event_type} for request={row_value(notification, 'request_id')}"
                )
            return notification

        def log_notification_delivery(notification):
            event_type = str(row_value(notification, "event_type") or "revive_request_fulfilled").lower()
            target = highlight(row_value(notification, "target_name") or f"Target {row_value(notification, 'target_id') or '?'}")
            requester = highlight(row_value(notification, "requester_name") or f"Requester {row_value(notification, 'requester_id') or '?'}")
            requested_at = int(row_value(notification, "requested_timestamp") or row_value(notification, "created_at") or 0)
            requested_text = time.strftime("%m-%d %H:%M:%S", time.localtime(requested_at)) if requested_at else "unknown time"

            if event_type in ("revive_request_received", "request_received"):
                logger.info(
                    f"{info('Revive request received')} {target} by {requester} at {success(requested_text)} "
                    f"({muted(str(row_value(notification, 'request_id') or '?'))})"
                )
                logger.info(
                    f"Request details: requester={requester} | target={target} | source={muted(str(row_value(notification, 'source') or '-'))} | "
                    f"notes={muted(str(row_value(notification, 'notes') or '-'))}"
                )
                return

            reviver = success(row_value(notification, "fulfilled_by_name") or str(row_value(notification, "fulfilled_by_id") or "unknown reviver"))
            revived_at = int(row_value(notification, "revived_timestamp") or row_value(notification, "fulfilled_at") or 0)
            revived_text = time.strftime("%m-%d %H:%M:%S", time.localtime(revived_at)) if revived_at else "unknown time"
            logger.info(
                f"{info('Revive request fulfilled')} {target} by {reviver} at {success(revived_text)} "
                f"({muted(str(row_value(notification, 'request_id') or '?'))})"
            )
            logger.info(
                f"Fulfillment details: requester={requester} | target={target} | reviver={reviver} | revived_at={success(revived_text)}"
            )

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
                        wait_seconds = max(0, int(query.get("wait", [0])[0] or 0))
                        limit = int(query.get("limit", [10])[0] or 10)

                        logger.info(
                            f"Notification request query requester_id={requester_id or '-'} requester_name={requester_name or '-'} limit={limit} wait={wait_seconds}s"
                        )

                        def load_notifications():
                            rows = repo.get_notifications(
                                requester_id=int(requester_id) if requester_id not in (None, "") else None,
                                requester_name=requester_name,
                                limit=limit,
                            )
                            if rows:
                                payload_rows = [dict(row) for row in rows]
                                repo.mark_notifications_notified([row["notification_id"] for row in rows])
                                return payload_rows
                            return []

                        payload = load_notifications()
                        if not payload and wait_seconds > 0:
                            deadline = time.time() + wait_seconds
                            while time.time() < deadline and not payload:
                                with notification_condition:
                                    remaining = deadline - time.time()
                                    if remaining <= 0:
                                        break
                                    notification_condition.wait(timeout=min(remaining, 1.0))
                                payload = load_notifications()

                        if not payload:
                            payload = legacy_notifications(
                                requester_id=int(requester_id) if requester_id not in (None, "") else None,
                                requester_name=requester_name,
                                limit=limit,
                            )

                        if payload:
                            summary_bits = []
                            for notification in payload:
                                event_type = str(notification.get("event_type") or "revive_request_fulfilled").lower()
                                request_id = notification.get("request_id") or "?"
                                target_name = notification.get("target_name") or f"Target {notification.get('target_id') or '?'}"
                                requester_text = notification.get("requester_name") or f"Requester {notification.get('requester_id') or '?'}"
                                summary_bits.append(f"{event_type}:{request_id}:{target_name}:{requester_text}")
                            logger.info(
                                f"Served {len(payload)} notification(s): {' | '.join(summary_bits)}"
                            )
                        else:
                            logger.info("Served 0 notifications for this request")

                        for notification in payload:
                            log_notification_delivery(notification)

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
                    logger.info(
                        "Incoming revive request payload: "
                        f"requester={request_row.get('requester_name') or request_row.get('requester_id') or '-'} | "
                        f"target={request_row.get('target_name') or request_row.get('target_id') or '-'} | "
                        f"source={request_row.get('source') or '-'} | notes={request_row.get('notes') or '-'}"
                    )
                    request_id = repo.create_request(request_row)
                    saved_request = repo.get(request_id)
                    logger.info(
                        "Revive request stored: "
                        f"request_id={request_id} | "
                        f"requester={request_row.get('requester_name') or request_row.get('requester_id') or '-'} | "
                        f"target={request_row.get('target_name') or request_row.get('target_id') or '-'} | "
                        f"source={request_row.get('source') or '-'} | "
                        f"status={request_row.get('status') or '-'}"
                    )
                    if saved_request:
                        log_new_request(saved_request, "post")
                        emit_notification("revive_request_received", saved_request, extra={"source_event": "post"})
                    else:
                        logger.info(
                            "Revive request lookup after insert returned no row; using request payload for logging only"
                        )
                    fulfilled_rows = repo.reconcile_against_database(
                        window_seconds=int(payload.get("window_seconds") or window_seconds),
                        limit=1,
                        return_rows=True,
                    )

                    for fulfilled in fulfilled_rows:
                        logger.info(
                            "Incoming request fulfilled during POST reconcile: "
                            f"request_id={row_value(fulfilled, 'request_id') or '-'} | "
                            f"target={row_value(fulfilled, 'target_name') or row_value(fulfilled, 'target_id') or '-'} | "
                            f"fulfilled_by={row_value(fulfilled, 'fulfilled_by_name') or row_value(fulfilled, 'fulfilled_by_id') or '-'}"
                        )
                        emit_notification("revive_request_fulfilled", fulfilled, extra={"source_event": "reconcile"})
                        log_fulfilled_request(fulfilled, "request")

                    if fulfilled_rows:
                        logger.info(f"Revive request POST reconcile matched {len(fulfilled_rows)} request(s)")
                    else:
                        logger.info("Revive request POST reconcile matched 0 request(s)")

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

        server = ThreadingHTTPServer((host, port), Handler)
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
                    logger.info(
                        "Queued fulfillment from poll: "
                        f"request_id={row_value(fulfilled, 'request_id') or '-'} | "
                        f"target={row_value(fulfilled, 'target_name') or row_value(fulfilled, 'target_id') or '-'} | "
                        f"fulfilled_by={row_value(fulfilled, 'fulfilled_by_name') or row_value(fulfilled, 'fulfilled_by_id') or '-'}"
                    )
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