from __future__ import annotations

import asyncio
import hmac
import http.client
import secrets
from weakref import WeakValueDictionary
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
from quart import Quart, Response, jsonify, redirect, request, send_from_directory

from astrbot.api import logger


class StandaloneWebUIServer:
    _ACTIVE_SERVERS: "WeakValueDictionary[str, StandaloneWebUIServer]" = (
        WeakValueDictionary()
    )
    _SESSION_COOKIE_NAME = "oyasumi_webui_session"
    _SESSION_TTL = timedelta(hours=12)
    _LOGIN_WINDOW = timedelta(minutes=10)
    _LOGIN_LOCKOUT = timedelta(minutes=10)
    _LOGIN_MAX_ATTEMPTS = 8
    _START_RECOVERY_TIMEOUT_SEC = 10.0
    _START_RECOVERY_STEP_SEC = 0.25
    _STOP_WAIT_TIMEOUT_SEC = 5.0
    _STOP_WAIT_STEP_SEC = 0.2
    _INTERNAL_SHUTDOWN_PATH = "/__oyasumi_internal/shutdown"
    _INTERNAL_SHUTDOWN_HEADER = "X-Oyasumi-Shutdown-Token"

    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.settings = plugin.settings
        self.webui_dir = Path(__file__).resolve().parent / "webui"
        self._sessions: dict[str, datetime] = {}
        self._login_attempts: dict[str, list[datetime]] = {}
        self._login_lockouts: dict[str, datetime] = {}
        self.app = Quart(
            "oyasumi_standalone_webui",
            static_folder=str(self.webui_dir),
            static_url_path="/static",
        )
        self._shutdown_event = asyncio.Event()
        self._serve_task: asyncio.Task | None = None
        self._register_routes()

    async def start(self) -> None:
        if self._serve_task and not self._serve_task.done():
            return
        if not str(self.settings.standalone_webui_token or "").strip():
            raise RuntimeError(
                "standalone_webui_token must be configured and non-empty"
            )

        await self._stop_local_stale_server()
        if await self._is_port_in_use():
            logger.warning(
                "[oyasumi] standalone webui port is occupied, trying graceful recovery: %s:%s",
                self.settings.standalone_webui_host,
                self.settings.standalone_webui_port,
            )
            recovered = await self._recover_occupied_port()
            if not recovered:
                raise RuntimeError(
                    "standalone webui port already in use: "
                    f"{self.settings.standalone_webui_host}:{self.settings.standalone_webui_port}"
                )

        config = HyperConfig()
        config.bind = [
            f"{self.settings.standalone_webui_host}:{self.settings.standalone_webui_port}"
        ]
        config.accesslog = None

        self._shutdown_event = asyncio.Event()
        self._serve_task = asyncio.create_task(
            serve(self.app, config, shutdown_trigger=self._shutdown_trigger)
        )
        self._register_active_server()
        self._serve_task.add_done_callback(self._on_serve_task_done)
        await asyncio.sleep(0)
        if self._serve_task.done():
            exc = self._serve_task.exception()
            if exc is not None:
                self._serve_task = None
                self._unregister_active_server()
                raise exc

    async def stop(self) -> None:
        if not self._serve_task:
            self._unregister_active_server()
            return

        logger.info(
            "[oyasumi] standalone webui stop requested: %s:%s",
            self.settings.standalone_webui_host,
            self.settings.standalone_webui_port,
        )
        self._shutdown_event.set()
        try:
            await asyncio.wait_for(self._serve_task, timeout=8)
        except asyncio.TimeoutError:
            logger.warning("[oyasumi] standalone webui stop timeout, force cancel task")
            if not self._serve_task.done():
                self._serve_task.cancel()
                try:
                    await self._serve_task
                except BaseException:
                    pass
        except Exception as exc:
            logger.warning("[oyasumi] standalone webui stop failed: %s", exc)
        finally:
            self._serve_task = None
            self._unregister_active_server()

        if await self._wait_for_port_released():
            logger.info(
                "[oyasumi] standalone webui stopped and port released: %s:%s",
                self.settings.standalone_webui_host,
                self.settings.standalone_webui_port,
            )
        else:
            logger.warning(
                "[oyasumi] standalone webui task stopped but port is still occupied: %s:%s",
                self.settings.standalone_webui_host,
                self.settings.standalone_webui_port,
            )

    async def _shutdown_trigger(self) -> None:
        await self._shutdown_event.wait()

    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    def _cleanup_expired_sessions(self) -> None:
        now = self._utcnow()
        expired = [sid for sid, expiry in self._sessions.items() if expiry <= now]
        for sid in expired:
            self._sessions.pop(sid, None)

    def _create_session(self) -> str:
        self._cleanup_expired_sessions()
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = self._utcnow() + self._SESSION_TTL
        return session_id

    def _read_cookie_session_id(self) -> str:
        return (request.cookies.get(self._SESSION_COOKIE_NAME) or "").strip()

    def _is_cookie_session_valid(self) -> bool:
        self._cleanup_expired_sessions()
        session_id = self._read_cookie_session_id()
        if not session_id:
            return False
        expiry = self._sessions.get(session_id)
        if expiry is None:
            return False
        if expiry <= self._utcnow():
            self._sessions.pop(session_id, None)
            return False
        return True

    def _is_token_matched(self, provided: str) -> bool:
        configured = str(self.settings.standalone_webui_token or "")
        if not configured.strip():
            return False
        return hmac.compare_digest(provided, configured)

    def _is_request_authenticated(self) -> bool:
        return self._is_cookie_session_valid()

    def _get_client_ip(self) -> str:
        forwarded_for = (request.headers.get("X-Forwarded-For") or "").strip()
        if forwarded_for:
            first_hop = forwarded_for.split(",")[0].strip()
            if first_hop:
                return first_hop
        return (request.remote_addr or "unknown").strip() or "unknown"

    def _cleanup_login_attempts(self, client_ip: str) -> None:
        now = self._utcnow()
        recent = [
            ts
            for ts in self._login_attempts.get(client_ip, [])
            if now - ts <= self._LOGIN_WINDOW
        ]
        if recent:
            self._login_attempts[client_ip] = recent
        else:
            self._login_attempts.pop(client_ip, None)

        lockout_until = self._login_lockouts.get(client_ip)
        if lockout_until and lockout_until <= now:
            self._login_lockouts.pop(client_ip, None)

    def _is_login_rate_limited(self, client_ip: str) -> bool:
        self._cleanup_login_attempts(client_ip)
        lockout_until = self._login_lockouts.get(client_ip)
        if lockout_until and lockout_until > self._utcnow():
            return True
        return False

    def _record_login_failure(self, client_ip: str) -> None:
        now = self._utcnow()
        self._cleanup_login_attempts(client_ip)
        attempts = self._login_attempts.setdefault(client_ip, [])
        attempts.append(now)
        if len(attempts) >= self._LOGIN_MAX_ATTEMPTS:
            self._login_lockouts[client_ip] = now + self._LOGIN_LOCKOUT
            self._login_attempts.pop(client_ip, None)

    def _clear_login_failures(self, client_ip: str) -> None:
        self._login_attempts.pop(client_ip, None)
        self._login_lockouts.pop(client_ip, None)

    def _is_request_secure(self) -> bool:
        if request.scheme == "https":
            return True
        forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").strip()
        if forwarded_proto:
            first_hop = forwarded_proto.split(",")[0].strip().lower()
            return first_hop == "https"
        return False

    def _delete_current_session(self) -> None:
        session_id = self._read_cookie_session_id()
        if session_id:
            self._sessions.pop(session_id, None)

    def _register_routes(self) -> None:
        @self.app.route(self._INTERNAL_SHUTDOWN_PATH, methods=["POST"])
        async def internal_shutdown():
            provided = (
                request.headers.get(self._INTERNAL_SHUTDOWN_HEADER) or ""
            ).strip()
            if not self._is_token_matched(provided):
                return jsonify({"status": "error", "message": "unauthorized"}), 401
            asyncio.create_task(self._trigger_internal_shutdown())
            return jsonify({"status": "ok"})

        @self.app.before_request
        async def _auth_guard():
            if request.method == "OPTIONS":
                return None
            if not request.path.startswith("/api/"):
                return None
            if request.path in {"/api/auth/status", "/api/auth/login"}:
                return None
            if self._is_request_authenticated():
                return None
            return jsonify({"status": "error", "message": "unauthorized"}), 401

        @self.app.after_request
        async def _cors_headers(response: Response):
            if request.path.startswith("/api/"):
                origin = (request.headers.get("Origin") or "").strip()
                allowed = self._get_allowed_cors_origins()
                if origin and origin in allowed:
                    response.headers["Access-Control-Allow-Origin"] = origin
                    response.headers["Vary"] = "Origin"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type"
                response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
            return response

        @self.app.route("/", methods=["GET"])
        async def index_page():
            if not self._is_request_authenticated():
                return redirect("/login")
            return await send_from_directory(str(self.webui_dir), "index.html")

        @self.app.route("/login", methods=["GET"])
        async def login_page():
            if self._is_request_authenticated():
                return redirect("/")
            return await send_from_directory(str(self.webui_dir), "login.html")

        @self.app.route("/healthz", methods=["GET"])
        async def healthz():
            return jsonify({"status": "ok"})

        @self.app.route("/api/auth/status", methods=["GET", "OPTIONS"])
        async def api_auth_status():
            if request.method == "OPTIONS":
                return Response(status=204)
            require_login = True
            authenticated = self._is_request_authenticated()
            return jsonify(
                {
                    "status": "ok",
                    "data": {
                        "require_login": require_login,
                        "authenticated": authenticated,
                    },
                }
            )

        @self.app.route("/api/auth/login", methods=["POST", "OPTIONS"])
        async def api_auth_login():
            if request.method == "OPTIONS":
                return Response(status=204)

            client_ip = self._get_client_ip()
            if self._is_login_rate_limited(client_ip):
                return (
                    jsonify({"status": "error", "message": "too many login attempts"}),
                    429,
                )

            payload = await request.get_json(silent=True) or {}
            provided = str(payload.get("token") or "")
            if not self._is_token_matched(provided):
                self._record_login_failure(client_ip)
                return (
                    jsonify({"status": "error", "message": "token mismatch"}),
                    401,
                )

            self._clear_login_failures(client_ip)
            session_id = self._create_session()
            response = jsonify(
                {
                    "status": "ok",
                    "data": {
                        "require_login": True,
                        "authenticated": True,
                    },
                }
            )
            response.set_cookie(
                self._SESSION_COOKIE_NAME,
                session_id,
                max_age=int(self._SESSION_TTL.total_seconds()),
                httponly=True,
                secure=self._is_request_secure(),
                samesite="Lax",
            )
            return response

        @self.app.route("/api/auth/logout", methods=["POST", "OPTIONS"])
        async def api_auth_logout():
            if request.method == "OPTIONS":
                return Response(status=204)
            self._delete_current_session()
            response = jsonify({"status": "ok", "data": {"authenticated": False}})
            response.delete_cookie(self._SESSION_COOKIE_NAME)
            return response

        @self.app.route("/api/users", methods=["GET", "OPTIONS"])
        async def api_users():
            if request.method == "OPTIONS":
                return Response(status=204)
            return await self.plugin.webui_users_api()

        @self.app.route("/api/dashboard", methods=["GET", "OPTIONS"])
        async def api_dashboard():
            if request.method == "OPTIONS":
                return Response(status=204)
            return await self.plugin.webui_dashboard_api()

        @self.app.route("/api/sessions", methods=["GET", "OPTIONS"])
        async def api_sessions():
            if request.method == "OPTIONS":
                return Response(status=204)
            return await self.plugin.webui_sessions_api()

        @self.app.route("/api/summary", methods=["GET", "OPTIONS"])
        async def api_summary():
            if request.method == "OPTIONS":
                return Response(status=204)
            return await self.plugin.webui_summary_api()

        @self.app.route("/api/analysis", methods=["POST", "OPTIONS"])
        async def api_analysis():
            if request.method == "OPTIONS":
                return Response(status=204)
            return await self.plugin.webui_analysis_api()

        @self.app.route("/api/client-log", methods=["POST", "OPTIONS"])
        async def api_client_log():
            if request.method == "OPTIONS":
                return Response(status=204)
            payload = await request.get_json(silent=True) or {}
            level = str(payload.get("level") or "info").strip().lower()
            message = str(payload.get("message") or "").strip()
            extra = payload.get("extra")

            if not message:
                return jsonify({"status": "error", "message": "message is required"}), 400

            if len(message) > 500:
                message = message[:500]

            if isinstance(extra, dict):
                safe_extra = {
                    str(k)[:80]: str(v)[:300]
                    for k, v in extra.items()
                }
            else:
                safe_extra = {"value": str(extra)[:300]} if extra is not None else {}

            log_message = "[oyasumi-webui] %s | extra=%s"
            if level == "error":
                logger.error(log_message, message, safe_extra)
            elif level == "warning":
                logger.warning(log_message, message, safe_extra)
            else:
                logger.info(log_message, message, safe_extra)

            return jsonify({"status": "ok", "data": {"accepted": True}})

        @self.app.route("/api/snapshot", methods=["GET", "OPTIONS"])
        async def api_snapshot():
            if request.method == "OPTIONS":
                return Response(status=204)
            return await self.plugin.webui_snapshot_api()

        @self.app.route("/api/overview", methods=["GET", "OPTIONS"])
        async def api_overview():
            if request.method == "OPTIONS":
                return Response(status=204)
            return await self.plugin.webui_overview_api()

        @self.app.route("/api/leaderboard", methods=["GET", "OPTIONS"])
        async def api_leaderboard():
            if request.method == "OPTIONS":
                return Response(status=204)
            return await self.plugin.webui_leaderboard_api()

        @self.app.route("/api/user_insight", methods=["GET", "OPTIONS"])
        async def api_user_insight():
            if request.method == "OPTIONS":
                return Response(status=204)
            return await self.plugin.webui_user_insight_api()

    async def _is_port_in_use(self) -> bool:
        host = self._resolve_probe_host()
        port = int(self.settings.standalone_webui_port)
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=0.5,
            )
        except Exception:
            return False
        writer.close()
        await writer.wait_closed()
        return True

    async def _recover_occupied_port(self) -> bool:
        wait_steps = max(
            1,
            int(self._START_RECOVERY_TIMEOUT_SEC / self._START_RECOVERY_STEP_SEC),
        )
        shutdown_requested = False
        for _ in range(wait_steps):
            if await self._request_internal_shutdown():
                shutdown_requested = True
            if not await self._is_port_in_use():
                logger.info(
                    "[oyasumi] standalone webui port recovered: %s:%s",
                    self.settings.standalone_webui_host,
                    self.settings.standalone_webui_port,
                )
                return True
            await asyncio.sleep(self._START_RECOVERY_STEP_SEC)
        if shutdown_requested:
            logger.warning(
                "[oyasumi] standalone webui shutdown was requested but the port is still busy after %.1fs: %s:%s",
                self._START_RECOVERY_TIMEOUT_SEC,
                self.settings.standalone_webui_host,
                self.settings.standalone_webui_port,
            )
        else:
            logger.warning(
                "[oyasumi] standalone webui graceful recovery request was not accepted: %s:%s",
                self.settings.standalone_webui_host,
                self.settings.standalone_webui_port,
            )
        return False

    async def _request_internal_shutdown(self) -> bool:
        token = str(self.settings.standalone_webui_token or "").strip()
        if not token:
            return False
        host = self._resolve_probe_host()
        port = int(self.settings.standalone_webui_port)

        def _post_shutdown() -> bool:
            conn = http.client.HTTPConnection(host, port, timeout=1.5)
            try:
                conn.request(
                    "POST",
                    self._INTERNAL_SHUTDOWN_PATH,
                    body="",
                    headers={self._INTERNAL_SHUTDOWN_HEADER: token},
                )
                resp = conn.getresponse()
                resp.read()
                return resp.status == 200
            finally:
                conn.close()

        try:
            return await asyncio.to_thread(_post_shutdown)
        except Exception:
            return False

    async def _trigger_internal_shutdown(self) -> None:
        await asyncio.sleep(0)
        self._shutdown_event.set()

    def _bind_key(self) -> str:
        return (
            f"{self.settings.standalone_webui_host}:"
            f"{int(self.settings.standalone_webui_port)}"
        )

    def _register_active_server(self) -> None:
        self._ACTIVE_SERVERS[self._bind_key()] = self

    def _unregister_active_server(self) -> None:
        bind_key = self._bind_key()
        current = self._ACTIVE_SERVERS.get(bind_key)
        if current is self:
            self._ACTIVE_SERVERS.pop(bind_key, None)

    def _on_serve_task_done(self, task: asyncio.Task | None) -> None:
        self._unregister_active_server()

    async def _stop_local_stale_server(self) -> None:
        bind_key = self._bind_key()
        active = self._ACTIVE_SERVERS.get(bind_key)
        if active is None or active is self:
            return
        if active._serve_task is None or active._serve_task.done():
            active._unregister_active_server()
            return

        logger.warning(
            "[oyasumi] found stale standalone webui instance in current process, stopping it: %s",
            bind_key,
        )
        try:
            await active.stop()
        except Exception as exc:
            logger.warning(
                "[oyasumi] failed to stop stale standalone webui instance in current process: %s",
                exc,
            )

    async def _wait_for_port_released(self) -> bool:
        wait_steps = max(
            1,
            int(self._STOP_WAIT_TIMEOUT_SEC / self._STOP_WAIT_STEP_SEC),
        )
        for _ in range(wait_steps):
            if not await self._is_port_in_use():
                return True
            await asyncio.sleep(self._STOP_WAIT_STEP_SEC)
        return not await self._is_port_in_use()

    def _resolve_probe_host(self) -> str:
        host = str(self.settings.standalone_webui_host or "127.0.0.1")
        if host in {"0.0.0.0", "::"}:
            return "127.0.0.1"
        return host

    def _get_allowed_cors_origins(self) -> set[str]:
        host = str(self.settings.standalone_webui_host or "127.0.0.1")
        port = int(self.settings.standalone_webui_port)
        candidates = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
            f"https://127.0.0.1:{port}",
            f"https://localhost:{port}",
        }
        if host and host not in {"0.0.0.0", "::"}:
            candidates.add(f"http://{host}:{port}")
            candidates.add(f"https://{host}:{port}")
        return candidates
