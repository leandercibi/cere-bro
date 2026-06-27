"""Thin HTTP wrapper around Cerebro's route() for local testing.

Run: python serve.py
POST /message  {"text": "had dal chawal for lunch"}
GET  /health
"""
from __future__ import annotations

import asyncio
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

from lib.config import get_settings
from lib.db import init_db
from app.router import route

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
logger = logging.getLogger("cerebro.serve")

settings = get_settings()
init_db(settings.db_path)

loop = asyncio.new_event_loop()
Thread(target=loop.run_forever, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/message":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            text = body.get("text", "")
            user_id = body.get("user_id", settings.telegram_allowed_user_id)

            future = asyncio.run_coroutine_threadsafe(
                route(text, user_id=user_id, settings=settings), loop
            )
            result = future.result(timeout=120)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "reply": result.reply_text,
                "tool_called": result.tool_called,
                "tools_called": result.tools_called,
            }).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        logger.info(format, *args)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8008), Handler)
    logger.info("Cerebro HTTP server on http://localhost:8008")
    server.serve_forever()
