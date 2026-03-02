from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any

from hypercorn.asyncio import serve
from hypercorn.config import Config as HyperConfig
from quart import Quart, Response, jsonify, request, send_from_directory


class StandaloneWebUIServer:
    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.settings = plugin.settings
        self.webui_dir = Path(__file__).resolve().parent / "webui"
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
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if (
                sock.connect_ex(
                    (
                        self.settings.standalone_webui_host,
                        self.settings.standalone_webui_port,
                    )
                )
                == 0
            ):
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

    def _register_routes(self) -> None:
        @self.app.before_request
        async def _auth_guard():
            if request.method == "OPTIONS":
                return None
            if not request.path.startswith("/api/"):
                return None
            if not self.settings.standalone_webui_token:
                return None
            header_token = (request.headers.get("X-Oyasumi-Token") or "").strip()
            query_token = (request.args.get("token") or "").strip()
            provided = header_token or query_token
            if provided == self.settings.standalone_webui_token:
                return None
            return jsonify({"status": "error", "message": "invalid token"}), 401

        @self.app.after_request
        async def _cors_headers(response: Response):
            if request.path.startswith("/api/"):
                response.headers["Access-Control-Allow-Origin"] = "*"
                response.headers["Access-Control-Allow-Headers"] = (
                    "Content-Type, X-Oyasumi-Token"
                )
                response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
            return response

        @self.app.route("/", methods=["GET"])
        async def index_page():
            return await send_from_directory(str(self.webui_dir), "index.html")

        @self.app.route("/healthz", methods=["GET"])
        async def healthz():
            return jsonify({"status": "ok"})

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
