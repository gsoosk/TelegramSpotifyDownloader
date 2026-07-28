"""Telegram Spotify Downloader bot.

A simple Telegram bot that downloads songs, albums, playlists and artists from a
Spotify link using spotDL v4 (which sources the audio from YouTube) and sends the
resulting MP3 files back to the user.

Built on python-telegram-bot v22 (async) and spotdl v4.
"""

import asyncio
import logging
import os
import re
import shutil
import uuid
from pathlib import Path

from dotenv import dotenv_values

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
DOWNLOADS_DIR = BASE_DIR / "downloads"

# A Spotify web link or URI for a track, album, playlist or artist.
SPOTIFY_URL_RE = re.compile(
    r"(https?://open\.spotify\.com/(?:intl-\w+/)?(?:track|album|playlist|artist)/\w+"
    r"|spotify:(?:track|album|playlist|artist):\w+)",
    re.IGNORECASE,
)

# spotdl progress markers.
FOUND_RE = re.compile(r"Found (\d+) song", re.IGNORECASE)
COMPLETE_RE = re.compile(r"(\d+)/(\d+) complete")

# Per-song stage lines emitted by spotdl's --simple-tui mode, e.g.
#   "Rick Astley - Never Gonna Give You Up: Downloading"
STAGE_RE = re.compile(
    r"^(?P<name>.+): (?P<stage>Searching for song|Getting audio meta|Downloading|"
    r"Converting|Embedding metadata|Done|Skipped|Error)$"
)

STAGE_FRACTION = {
    "Searching for song": 0.15,
    "Getting audio meta": 0.35,
    "Downloading": 0.55,
    "Converting": 0.75,
    "Embedding metadata": 0.90,
    "Done": 1.0,
    "Skipped": 1.0,
    "Error": 1.0,
}

STAGE_LABEL = {
    "Searching for song": "🔎 Searching",
    "Getting audio meta": "📋 Getting metadata",
    "Downloading": "⬇️ Downloading audio",
    "Converting": "🎛️ Converting",
    "Embedding metadata": "🏷️ Adding tags",
    "Done": "✅ Done",
    "Skipped": "⏭️ Already downloaded",
    "Error": "⚠️ Error",
}

import json


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"AUTH": {"ENABLE": False, "PASSWORD": "", "OWNER_ID": None, "USERS": []}}


def save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)


config = load_config()
config.setdefault("AUTH", {})
config["AUTH"].setdefault("ENABLE", False)
config["AUTH"].setdefault("PASSWORD", "")
config["AUTH"].setdefault("OWNER_ID", None)
config["AUTH"].setdefault("USERS", [])


def get_token() -> str:
    env = dotenv_values(BASE_DIR / ".env")
    token = env.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError(
            "No Telegram token found. Put TELEGRAM_TOKEN in a .env file "
            "or set it as an environment variable."
        )
    return token


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------
def is_authorized(chat_id: int) -> bool:
    if not config["AUTH"]["ENABLE"]:
        return True
    if config["AUTH"]["OWNER_ID"] and chat_id == config["AUTH"]["OWNER_ID"]:
        return True
    return chat_id in config["AUTH"]["USERS"]


def try_login(chat_id: int, text: str) -> bool:
    password = config["AUTH"]["PASSWORD"]
    if password and text.strip() == password:
        if chat_id not in config["AUTH"]["USERS"]:
            config["AUTH"]["USERS"].append(chat_id)
        if not config["AUTH"]["OWNER_ID"]:
            config["AUTH"]["OWNER_ID"] = chat_id
        save_config(config)
        return True
    return False


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------
def render_progress(state: dict, width: int = 20) -> str:
    total = state["total"] or 1
    completed = state["completed"]
    stage = state["stage"]
    frac = STAGE_FRACTION.get(stage, 0.0)
    # A song counted as completed already contributes a full unit via `completed`.
    current = completed + (0.0 if stage in ("Done", "Skipped", "Error") else frac)
    overall = min(current / total, 1.0)

    filled = int(width * overall)
    bar = "█" * filled + "░" * (width - filled)
    pct = int(overall * 100)

    lines = []
    if total > 1:
        lines.append(f"⬇️ Downloading  ({min(completed + 1, total)}/{total})")
    else:
        lines.append("⬇️ Downloading")
    if state["name"]:
        lines.append(f"🎵 {state['name']}")
    lines.append(STAGE_LABEL.get(stage, "…"))
    lines.append(f"[{bar}] {pct}%")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if config["AUTH"]["ENABLE"] and not is_authorized(chat_id):
        await update.message.reply_text(
            "👋 Welcome!\n\nThis bot is private. Please send the password to sign in. "
            "If you don't know it, contact the bot owner."
        )
        return
    await update.message.reply_text(
        "🎵 *Spotify Downloader*\n\n"
        "Send me a Spotify link and I'll fetch the audio for you.\n\n"
        "Supported links:\n"
        "• Track\n• Album\n• Playlist\n• Artist\n\n"
        "Example: `https://open.spotify.com/track/...`",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Just send a Spotify link (track, album, playlist or artist) and I'll "
        "download it and send the MP3 files back.\n\n"
        "Commands:\n"
        "/start – welcome / sign in\n"
        "/help – this message\n"
        "/logout – sign out (if auth is enabled)"
    )


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in config["AUTH"]["USERS"]:
        config["AUTH"]["USERS"].remove(chat_id)
        save_config(config)
        await update.message.reply_text("👋 You've been signed out.")
    else:
        await update.message.reply_text("You weren't signed in.")


# ---------------------------------------------------------------------------
# Download flow
# ---------------------------------------------------------------------------
async def run_spotdl(url: str, out_dir: Path, progress_cb) -> None:
    """Run spotdl in simple-tui mode and stream per-song stage progress.

    progress_cb(state) is awaited whenever the state changes, where state holds
    total/completed song counts and the current song name and stage.
    """
    output_template = str(out_dir / "{artists} - {title}.{output-ext}")
    cmd = [
        "spotdl",
        "download",
        url,
        "--simple-tui",
        "--output",
        output_template,
    ]
    logger.info("Running: %s", " ".join(cmd))

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    state = {"total": 0, "completed": 0, "name": "", "stage": ""}
    assert process.stdout is not None
    async for raw in process.stdout:
        line = raw.decode(errors="ignore").strip()
        if not line:
            continue
        logger.info("[spotdl] %s", line)

        found = FOUND_RE.search(line)
        if found:
            state["total"] = int(found.group(1))
            await progress_cb(state)
            continue

        complete = COMPLETE_RE.search(line)
        if complete:
            state["completed"] = int(complete.group(1))
            state["total"] = max(state["total"], int(complete.group(2)))
            await progress_cb(state)
            continue

        stage_match = STAGE_RE.match(line)
        if stage_match:
            state["name"] = stage_match.group("name")
            state["stage"] = stage_match.group("stage")
            # "Done"/"Skipped" completion is reflected by the "N/M complete" line;
            # rendering them here would briefly show 0% before that line arrives.
            if state["stage"] not in ("Done", "Skipped"):
                await progress_cb(state)

    await process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"spotdl exited with code {process.returncode}")


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat_id = update.effective_chat.id
    text = message.text or ""

    match = SPOTIFY_URL_RE.search(text)

    # Authentication gate.
    if config["AUTH"]["ENABLE"] and not is_authorized(chat_id):
        if try_login(chat_id, text):
            await message.reply_text("✅ Signed in successfully. Enjoy! 🍻")
        else:
            await message.reply_text(
                "⚠️ This bot is private and you're not signed in.\n"
                "Please send the password to sign in."
            )
        return

    if not match:
        await message.reply_text(
            "Please send a valid Spotify link (track, album, playlist or artist)."
        )
        return

    url = match.group(1)
    request_id = uuid.uuid4().hex[:12]
    out_dir = DOWNLOADS_DIR / request_id
    out_dir.mkdir(parents=True, exist_ok=True)

    status = await message.reply_text("🔎 Fetching…")

    last_edit = {"text": ""}

    async def progress_cb(state: dict) -> None:
        text = render_progress(state)
        # Only edit when the rendered text actually changes.
        if text == last_edit["text"]:
            return
        last_edit["text"] = text
        try:
            await status.edit_text(text)
        except Exception:
            pass

    try:
        await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
        await run_spotdl(url, out_dir, progress_cb)
    except FileNotFoundError:
        await status.edit_text(
            "❌ spotdl is not installed on the server. Run `pip install spotdl`."
        )
        shutil.rmtree(out_dir, ignore_errors=True)
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Download failed")
        await status.edit_text(f"❌ Download failed: {exc}")
        shutil.rmtree(out_dir, ignore_errors=True)
        return

    mp3_files = sorted(out_dir.rglob("*.mp3"))
    if not mp3_files:
        await status.edit_text(
            "❌ Couldn't find or download the song. It may be unavailable."
        )
        shutil.rmtree(out_dir, ignore_errors=True)
        return

    await status.edit_text(f"📤 Sending {len(mp3_files)} track(s)…")
    sent = 0
    for mp3 in mp3_files:
        title = mp3.stem
        performer = None
        if " - " in title:
            performer, title = title.split(" - ", 1)
        try:
            await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_VOICE)
            with open(mp3, "rb") as audio:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio,
                    title=title,
                    performer=performer,
                    read_timeout=1000,
                    write_timeout=1000,
                )
            sent += 1
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send %s", mp3)

    shutil.rmtree(out_dir, ignore_errors=True)

    if sent:
        await status.edit_text(f"✅ Done! Sent {sent} track(s). Enjoy 🍻")
    else:
        await status.edit_text("❌ There was a problem sending the audio.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Update caused error", exc_info=context.error)


def main() -> None:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    token = get_token()

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_error_handler(on_error)

    logger.info("Bot started. Polling…")
    app.run_polling()


if __name__ == "__main__":
    main()
