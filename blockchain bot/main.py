

from __future__ import annotations
"""
main.py – Entry point for the Token‑Referral Bot
==============================================
• FastAPI app that exposes Telegram webhook ("/api/webhook")
• Delegates startup/shutdown to BotManager
• Health endpoint and optional file proxy

Env vars required:
    TELEGRAM_BOT_TOKEN   ← bot father token
    WEBHOOK_URL          ← full https URL pointing to /api/webhook on this app
    PORT                 ← (Render / Fly.io) port to listen on (default 8000)

Optional env vars inherited by BotManager / other modules (POOL_WALLET_ADDRESS, etc.).
"""

import os
import io
import logging
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import uvicorn
from telegram import Update

# Local imports
from bot_manager import BotManager  # ← همان فایل bot_manager.py پروژه شما

# ────────────────────────── Logging ────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("MainApp")

# ────────────────────────── FastAPI app ────────────────────────
app = FastAPI(title="Token‑Referral Bot")

# BotManager instance (created on startup)
bot_manager: BotManager | None = None

# ────────────────────────── Startup / Shutdown ────────────────
@app.on_event("startup")
async def on_startup():
    global bot_manager
    bot_manager = BotManager(app)  # BotManager expects FastAPI instance
    await bot_manager.startup()

@app.on_event("shutdown")
async def on_shutdown():
    if bot_manager:
        await bot_manager.shutdown()

# ────────────────────────── Telegram Webhook ──────────────────
@app.post("/api/webhook")
async def telegram_webhook(req: Request):
    if not bot_manager or not bot_manager.bot:
        raise HTTPException(503, "Bot not ready")

    data = await req.json()
    logger.debug("Telegram update: %s", data)
    update = Update.de_json(data, bot_manager.bot)
    await bot_manager.process_update(update)
    return {"ok": True}

# ────────────────────────── File proxy (optional) ─────────────
async def _tg_file_url(bot, file_id: str) -> str:
    f = await bot.get_file(file_id)
    path = str(f.file_path)
    if path.startswith("http"):
        return path
    return f"https://api.telegram.org/file/bot{bot.token}/{path}"

@app.get("/api/file/{file_id:path}")
async def proxy_file(file_id: str):
    if not bot_manager or not bot_manager.bot:
        raise HTTPException(503, "Bot not ready")
    url = await _tg_file_url(bot_manager.bot, file_id)
    async with httpx.AsyncClient() as cli:
        r = await cli.get(url)
    if r.status_code != 200:
        raise HTTPException(r.status_code, "Upstream error")
    return StreamingResponse(io.BytesIO(r.content), media_type="application/octet-stream")

# ────────────────────────── Health Endpoint ───────────────────
@app.get("/health")
async def health():
    return {
        "status": "running" if bot_manager and bot_manager.is_running else "starting",
        "version": "1.0.0",
    }

# ────────────────────────── Root (info) ───────────────────────
@app.get("/")
async def root():
    return {"msg": "Token‑Referral Bot – powered by FastAPI & Telegram"}

# ────────────────────────── Local run helper ──────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
