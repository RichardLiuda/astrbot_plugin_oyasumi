from __future__ import annotations

import asyncio
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
from quart import Quart, Response, jsonify, redirect, request, send_from_directory


class StandaloneWebUIServer:
    _SESSION_COOKIE_NAME = "oyasumi_webui_session"
    _SESSION_TTL = timedelta(hours=12)

    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.settings = plugin.settings
        self.webui_dir = Path(__file__).resolve().parent / "webui"
        self._sessions: dict[str, datetime] = {}
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

        if await self._is_port_in_use():
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
        await asyncio.sleep(0)
        if self._serve_task.done():
            exc = self._serve_task.exception()
            if exc is not None:
                self._serve_task = None
                raise exc

    async def stop(self) -> None:
        if not self._serve_task:
            return

        self._shutdown_event.set()
        try:
            await asyncio.wait_for(self._serve_task, timeout=5)
        except Exception:
            if not self._serve_task.done():
                self._serve_task.cancel()
                try:
                    await self._serve_task
                except BaseException:
                    pass
        finally:
            self._serve_task = None

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

    def _delete_current_session(self) -> None:
        session_id = self._read_cookie_session_id()
        if session_id:
            self._sessions.pop(session_id, None)

    def _register_routes(self) -> None:
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

            payload = await request.get_json(silent=True) or {}
            provided = str(payload.get("token") or "")
            if not self._is_token_matched(provided):
                return (
                    jsonify({"status": "error", "message": "token mismatch"}),
                    401,
                )

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
                secure=(request.scheme == "https"),
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
        host = str(self.settings.standalone_webui_host or "127.0.0.1")
        port = int(self.settings.standalone_webui_port)
        check_host = host if host not in {"0.0.0.0", "::"} else "127.0.0.1"
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(check_host, port),
                timeout=0.5,
            )
        except Exception:
            return False
        writer.close()
        await writer.wait_closed()
        return True

    def _get_allowed_cors_origins(self) -> set[str]:
        host = str(self.settings.standalone_webui_host or "127.0.0.1")
        port = int(self.settings.standalone_webui_port)
        candidates = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        if host and host not in {"0.0.0.0", "::"}:
            candidates.add(f"http://{host}:{port}")
        return candidates
