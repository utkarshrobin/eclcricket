import os
import io
import time
import random
import asyncio
import urllib.request
import urllib.error
import struct
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatMemberHandler, filters,
    ContextTypes, TypeHandler
)
from motor.motor_asyncio import AsyncIOMotorClient

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("WARNING: Pillow not installed. Team scoreboard image generation disabled.")
    print("Install with: pip install Pillow")

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
TOKEN      = os.getenv("BOT_TOKEN")
MONGO_URI  = os.getenv("MONGO_URI")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT       = int(os.environ.get("PORT", "8080"))

OWNER_IDS = [8722613907, 8782578728, 8000127916]

# Path to the scoreboard template image (1536x1024).
# Place the template PNG next to this script named scoreboard_template.png,
# OR set SCOREBOARD_TEMPLATE_URL to the remote image URL.
SCOREBOARD_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scoreboard_template.png"
)
SCOREBOARD_TEMPLATE_URL = os.getenv(
    "SCOREBOARD_TEMPLATE_URL",
    "https://res.cloudinary.com/dxgfxfoog/image/upload/v1778123859/scoreboard_template.png"
)

# ---------------------------------------------------------------------------
# MongoDB Setup
# ---------------------------------------------------------------------------
try:
    _mongo_client = AsyncIOMotorClient(MONGO_URI)
    db         = _mongo_client["cricket_bot_db"]
    users_col  = db["users"]
    chats_col  = db["interacted_chats"]
except Exception as e:
    print(f"MongoDB Connection Error: {e}")
    users_col = None
    chats_col = None

# ---------------------------------------------------------------------------
# Media URLs
# ---------------------------------------------------------------------------
MEDIA = {
    "batter_turn": "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777818927/VID_20260503195533_zt4tux.mp4",
    "bowler_turn": "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777694389/VID_20260502092829_np7h5d.mp4",
    "out":         "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777641612/1777641553346_zexrt4.mp4",
    "duck":        "https://media.giphy.com/media/krewXUB6LBja/giphy.gif",
    "50":          "https://media.giphy.com/media/07oir8PhvSReDNpNi7/giphy.gif",
    "100":         "https://media.giphy.com/media/pR0jymbIr7HrrpISUW/giphy.gif",
    "yorker":      "https://media.giphy.com/media/2CUJFvoRXDrUeG1mOS/giphy.gif",
    0: "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777717596/VID_20260502_155429_102_xtppvn.mp4",
    1: "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642218/animation.gif_1_u1ksyt.mp4",
    2: "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642586/VID_20260501_190546_668_tdnzth.mp4",
    3: "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642484/VID_20260501_190413_260_cylqql.mp4",
    4: "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777644250/VID_20260501_193031_696_quwh5m.mp4",
    5: "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642378/VID_20260501_190216_576_yonoc2.mp4",
    6: "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777818980/VID_20260503195551_qcyvct.mp4",
}

# Static scoreboard image used for SOLO mode (and as fallback)
SCOREBOARD_IMG   = "https://res.cloudinary.com/dxgfxfoog/image/upload/v1777876839/file_000000001fc07207a39f861ace603999_tjaafo.png"
TEAMS_ROSTER_IMG = "https://res.cloudinary.com/dxgfxfoog/image/upload/v1777706897/file_00000000c1947207ae83551202e6e003_f4o3y9.png"

# ---------------------------------------------------------------------------
# Scoreboard Pillow image (TEAM mode only)
# ---------------------------------------------------------------------------
# Template coordinates are for a 1536×1024 image.
# Adjust these if your template has different dimensions.
_SB = {
    # Circle at top-centre (group logo or "LIVE" text)
    # Exact pixel analysis: horizontal span x=622-910, vertical span y=59-373
    "circle_cx": 766,  "circle_cy": 216,  "circle_r": 144,

    # Team A — score box: x=337-565, dark region y=575-665 → centre (451, 620)
    #          overs box: dark region y=665-720 → centre (451, 692)
    "team_a_score_cx": 451, "team_a_score_cy": 620,
    "team_a_overs_cx": 451, "team_a_overs_cy": 692,

    # Team B — score box: x=983-1187, same y spans → centre (1085, 620) / (1085, 692)
    "team_b_score_cx": 1085, "team_b_score_cy": 620,
    "team_b_overs_cx": 1085, "team_b_overs_cy": 692,

    # Bottom bar — four equal columns (384 px wide) centred at 192/576/960/1344
    # Labels drawn by us at bar_label_y, values at bar_value_y
    "bar_label_y":    855,
    "bar_value_y":    920,
    "innings_cx":     192,
    "crr_cx":         576,
    "bowler_cx":      960,
    "batter_cx":     1344,
}

_FONT_PATHS = [
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
    # macOS
    "/System/Library/Fonts/Helvetica.ttc",
    # Windows
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

_TEMPLATE_B64 = (
    "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"
    "itlWTVHLonLmX7tvlUu3v2+VVFbK8qmRWXZ3zfKpmZ37fKqhtlWRTIrgWH37fKjlZ37fKrSFsoyq"
    "blYcoPdt8qUuYPft8oQ4mk2DOQlLiVCWd+3ypbt79vlXNxR0TZCUpTXb3zfKhdvft8qKK2IQpZWd"
    "r3zfKpdvfN8qaK2V5UMqu7Xvm+VDte+b5VUVsqyoWVva98PKp2vfN8qKK2VZVMqt7Xvh5UO174eV"
    "WkbKsqmVWdr3w8qna98PKrSVsryqZVb2vfDyqdr3w8qtJWyrKhlV3a98PKocvfDyq0lbKcqmVW9r"
    "3zfKh2vfN8qNI2yvKjZWdr3w8qna98PKqgsryqZVb2vfDyqdr3zfKmitlWVTKre174eVDte+HlVp"
    "K2VZVMqt7Xvm+VDte+b5UUNsTKhlVva98PKp2vfDyqorZVlUyqzte+HlU7Xvh5VUViZVMqs7Xvm+"
    "VTte+b5VUFlWVTKrO175vlQ7Xvh5VUNleVTKrO174eVS7e+HlVRWyvKplVna983yqdr3zfKiitiZ"
    "VMqsu2/dN8qna983yporZXlQyq3te+b5VO174eVVFZVlUyqzte+HlU7Xvm+VVFYllLJ+174eVHte"
    "+b5UUVleVTKrRl75vlU7Xvm+VNFZXlUsre175vlRs3v2+VVBZVZSyuDWH37PhBQtYPfs+EFUVlGV"
    "HKrO179vlUu3vm+VVFbK7KWT3b3zfKgS2/dDyqouollLJ7t74eVC45jyoobYtlLJtOY8qNhzVRWL"
    "ZSyuihMpNjZo3lWZaUGxMpI32I9CiMllLLXmohvjnPgeB9CXPR/c5/jG+hA0ZrIWWrNRW+1VHxrf"
    "VRD6Eb4Kg/74eqqyozAI24cVr6bDxupag+GcW/ZQ9mhgtBA2PrvqpMqEbSSu1cMg/G9COWnh3kyO"
    "VT5ZJO6dccuCRNBZe6qdazGhoVfTy37u3iSKWVpRWP08v3RyIqZxuld5VWgrQvA6n5L/AGXUfdn+"
    "VH2bUjdO/wAqzqXWeXHwKnLyaPZ9WN1RJ5VPbCsG6pl+Es11EcqHhDzJ+TT7Z1o3VUvwkDidad9V"
    "L8JZkFnk4/yo1zcnlmr2yrRuq5h+kocUrzvq5T+ksqCOTj/Kh5s/zM0DEawbqqUfpInEa12+qlP6"
    "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"
    "FBQn/9k="
)

_template_cache: bytes | None = None


def _load_font(size: int):
    """Load a bold font at the given size, falling back to PIL default."""
    for path in _FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _get_template_bytes() -> bytes | None:
    """Return raw bytes of the template image (cached after first load)."""
    global _template_cache
    if _template_cache is not None:
        return _template_cache

    # 1. Always works — embedded JPEG (compressed, no files or URLs needed)
    try:
        import base64 as _b64
        _template_cache = _b64.b64decode(_TEMPLATE_B64)
        return _template_cache
    except Exception as exc:
        print(f"[scoreboard] Embedded decode failed: {exc}")

    # 2. Local file fallback
    if os.path.exists(SCOREBOARD_TEMPLATE_PATH):
        try:
            with open(SCOREBOARD_TEMPLATE_PATH, "rb") as f:
                _template_cache = f.read()
            return _template_cache
        except Exception as exc:
            print(f"[scoreboard] Local file failed: {exc}")

    # 3. Remote URL last resort
    try:
        req = urllib.request.Request(
            SCOREBOARD_TEMPLATE_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            _template_cache = resp.read()
        return _template_cache
    except Exception as exc:
        print(f"[scoreboard] Download failed: {exc}")

    return None


async def _fetch_group_photo_bytes(context, chat_id: int) -> bytes | None:
    """Attempt to download the group profile photo. Returns bytes or None."""
    try:
        chat = await context.bot.get_chat(chat_id)
        if not chat.photo:
            return None
        file = await chat.photo.get_big_file()
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        return buf.getvalue()
    except Exception:
        return None


def _draw_centered_text(draw: "ImageDraw.ImageDraw", cx: int, cy: int,
                         text: str, font, fill=(255, 255, 255),
                         shadow: bool = True):
    """Draw text centred at (cx, cy) with an optional drop-shadow."""
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = cx - w // 2
    y = cy - h // 2
    if shadow:
        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 180))
    draw.text((x, y), text, font=font, fill=fill)


async def generate_team_scoreboard_image(context, chat_id: int, game: dict) -> bytes | None:
    """
    Build a custom scoreboard PNG by drawing match data onto the template.
    Returns PNG bytes, or None if generation fails.
    Only called in TEAM mode.
    """
    if not PIL_AVAILABLE:
        return None

    template_bytes = _get_template_bytes()
    if template_bytes is None:
        return None

    try:
        img = Image.open(io.BytesIO(template_bytes)).convert("RGBA")
        draw = ImageDraw.Draw(img)

        score_font     = _load_font(60)
        overs_font     = _load_font(30)
        bar_label_font = _load_font(22)
        bar_value_font = _load_font(26)
        circle_font    = _load_font(44)

        team_a = game.get("team_a", {})
        team_b = game.get("team_b", {})

        # ── Circle area: group photo filling the circle perfectly ─────────
        group_photo_bytes = await _fetch_group_photo_bytes(context, chat_id)
        cx_c = _SB["circle_cx"]
        cy_c = _SB["circle_cy"]
        r_c  = _SB["circle_r"]
        placed_photo = False
        if group_photo_bytes:
            try:
                gp = Image.open(io.BytesIO(group_photo_bytes)).convert("RGBA")
                # Crop to square from centre then resize to fill circle exactly
                gw, gh = gp.size
                crop_side = min(gw, gh)
                left  = (gw - crop_side) // 2
                top   = (gh - crop_side) // 2
                gp    = gp.crop((left, top, left + crop_side, top + crop_side))
                diam  = r_c * 2
                gp    = gp.resize((diam, diam), Image.LANCZOS)
                # Circular mask with 2-px anti-alias feather
                mask = Image.new("L", (diam, diam), 0)
                m_draw = ImageDraw.Draw(mask)
                m_draw.ellipse((0, 0, diam - 1, diam - 1), fill=255)
                paste_x = cx_c - r_c
                paste_y = cy_c - r_c
                img.paste(gp, (paste_x, paste_y), mask)
                placed_photo = True
            except Exception:
                pass
        if not placed_photo:
            _draw_centered_text(draw, cx_c, cy_c,
                                "LIVE", circle_font, fill=(255, 215, 0))

        # ── Team A score  (yellow text centred inside score box) ──────────
        a_score    = f"{team_a.get('score', 0)}/{team_a.get('wickets', 0)}"
        a_balls    = team_b.get("balls_bowled", 0)
        a_ov, a_bl = divmod(a_balls, 6)
        a_overs    = f"{a_ov}.{a_bl} Ov"

        _draw_centered_text(draw, _SB["team_a_score_cx"], _SB["team_a_score_cy"],
                            a_score, score_font, fill=(255, 220, 0))
        _draw_centered_text(draw, _SB["team_a_overs_cx"], _SB["team_a_overs_cy"],
                            a_overs, overs_font, fill=(255, 240, 120))

        # ── Team B score  (yellow text centred inside score box) ──────────
        b_score    = f"{team_b.get('score', 0)}/{team_b.get('wickets', 0)}"
        b_balls    = team_a.get("balls_bowled", 0)
        b_ov, b_bl = divmod(b_balls, 6)
        b_overs    = f"{b_ov}.{b_bl} Ov"

        _draw_centered_text(draw, _SB["team_b_score_cx"], _SB["team_b_score_cy"],
                            b_score, score_font, fill=(255, 220, 0))
        _draw_centered_text(draw, _SB["team_b_overs_cx"], _SB["team_b_overs_cy"],
                            b_overs, overs_font, fill=(255, 240, 120))

        # ── Bottom bar ────────────────────────────────────────────────────
        innings_num = game.get("innings", 1)
        innings_txt = f"{'1st' if innings_num == 1 else '2nd'} Innings"

        # Current Run Rate
        bat_team  = game.get("batting_team_ref", {})
        bowl_team = game.get("bowling_team_ref", {})
        b_bowled  = bowl_team.get("balls_bowled", 0)
        crr_txt   = f"{(bat_team.get('score', 0) / b_bowled * 6):.2f}" if b_bowled > 0 else "0.00"

        # Best Bowler across both teams
        all_players = team_a.get("players", []) + team_b.get("players", [])
        best_bowler_txt  = "N/A"
        best_bowler_name = "N/A"
        if all_players:
            best_bowler = max(
                (p for p in all_players if p.get("balls_bowled", 0) > 0),
                key=lambda p: p.get("wickets", 0) * 100 - p.get("conceded", 0),
                default=None,
            )
            if best_bowler:
                best_bowler_name = best_bowler["name"][:12]
                best_bowler_txt  = f"{best_bowler['wickets']}W / {best_bowler['conceded']}R"

        # Best Batter across both teams
        best_batter_txt  = "N/A"
        best_batter_name = "N/A"
        if all_players:
            best_batter = max(all_players, key=lambda p: p.get("runs", 0), default=None)
            if best_batter and best_batter.get("runs", 0) > 0:
                best_batter_name = best_batter["name"][:12]
                best_batter_txt  = f"{best_batter['runs']} ({best_batter['balls_faced']})"

        # Draw: label line then value line directly below, both centred per column
        label_y = _SB["bar_label_y"]
        value_y = _SB["bar_value_y"]
        label_color = (160, 200, 255)   # soft blue-white for labels
        value_color = (255, 255, 255)   # pure white for values

        for cx, lbl, val in [
            (_SB["innings_cx"], "INNINGS",       innings_txt),
            (_SB["crr_cx"],     "RUN RATE",      crr_txt),
            (_SB["bowler_cx"],  "BEST BOWLER",   best_bowler_name),
            (_SB["batter_cx"],  "TOP BATTER",    best_batter_name),
        ]:
            _draw_centered_text(draw, cx, label_y, lbl, bar_label_font, fill=label_color)
            _draw_centered_text(draw, cx, value_y, val, bar_value_font, fill=value_color)

        # Extra stat line for bowler/batter figures
        extra_y = value_y + 32
        _draw_centered_text(draw, _SB["bowler_cx"], extra_y,
                            best_bowler_txt, bar_label_font, fill=(220, 220, 220))
        _draw_centered_text(draw, _SB["batter_cx"], extra_y,
                            best_batter_txt, bar_label_font, fill=(220, 220, 220))

        # ── Finalise ──────────────────────────────────────────────────────
        img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf.getvalue()

    except Exception as exc:
        print(f"[scoreboard] Image generation error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def get_user_level(exp: int) -> str:
    if exp < 1000:
        return "Newbie 🔰"
    elif exp <= 5000:
        return "Pro ⚡"
    elif exp <= 8000:
        return "Legendary 🌟"
    else:
        return "Unbeaten 👑"


def get_next_level_info(exp: int):
    if exp < 1000:
        return "Pro ⚡", 1000 - exp
    elif exp <= 5000:
        return "Legendary 🌟", 5001 - exp
    elif exp <= 8000:
        return "Unbeaten 👑", 8001 - exp
    else:
        return None, 0


async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if chats_col is not None and update.effective_chat:
        try:
            title = update.effective_chat.title or "Private/Unknown"
            await chats_col.update_one(
                {"chat_id": update.effective_chat.id},
                {"$set": {
                    "chat_id": update.effective_chat.id,
                    "type": update.effective_chat.type,
                    "title": title,
                }},
                upsert=True,
            )
        except Exception:
            pass


async def track_bot_kicks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    if result.new_chat_member.status in ["left", "kicked"]:
        if chats_col is not None:
            await chats_col.delete_one({"chat_id": chat.id})
    elif result.new_chat_member.status in ["member", "administrator"]:
        if chats_col is not None:
            title = chat.title or "Group"
            await chats_col.update_one(
                {"chat_id": chat.id},
                {"$set": {"chat_id": chat.id, "type": chat.type, "title": title}},
                upsert=True,
            )


async def send_media_safely(context, chat_id, media_url, caption,
                             reply_markup=None, reply_to_message_id=None):
    try:
        if media_url.endswith(".gif") or "giphy.com" in media_url:
            await context.bot.send_animation(
                chat_id=chat_id, animation=media_url, caption=caption,
                parse_mode="HTML", reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
                read_timeout=20, write_timeout=20,
            )
        else:
            await context.bot.send_video(
                chat_id=chat_id, video=media_url, caption=caption,
                parse_mode="HTML", reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
                read_timeout=20, write_timeout=20,
            )
    except Exception as e:
        print(f"Failed to send media {media_url}: {e}. Using fallback.")
        fallback = f"<a href='{media_url}'>&#8205;</a>{caption}"
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=fallback, parse_mode="HTML",
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception as e2:
            print(f"Fallback failed: {e2}")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def init_user_db(user_id, first_name, username):
    if users_col is None:
        return
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        await users_col.insert_one({
            "user_id": user_id, "first_name": first_name, "username": username,
            "exp": 0, "weekly_runs": 0, "weekly_wickets": 0,
            "weekly_conceded": 0, "weekly_balls_bowled": 0, "weekly_balls_faced": 0,
            "highest_score": {"runs": 0, "balls": 0},
            "total_runs": 0, "balls_faced": 0,
            "solo_matches": 0, "team_matches": 0,
            "total_6s": 0, "total_4s": 0,
            "centuries": 0, "half_centuries": 0, "ducks": 0,
            "balls_bowled": 0, "runs_conceded": 0, "wickets": 0,
            "motm": 0, "hat_tricks": 0,
        })
    else:
        update_fields = {}
        if user.get("first_name") != first_name:
            update_fields["first_name"] = first_name
        if username and user.get("username") != username:
            update_fields["username"] = username
        if update_fields:
            await users_col.update_one({"user_id": user_id}, {"$set": update_fields})


async def update_user_db(user_id, updates):
    if users_col is None:
        return
    await users_col.update_one({"user_id": user_id}, {"$inc": updates}, upsert=True)


async def update_highest_score(user_id, runs, balls):
    if users_col is None:
        return
    user = await users_col.find_one({"user_id": user_id})
    if user and runs > user.get("highest_score", {}).get("runs", 0):
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"highest_score": {"runs": runs, "balls": balls}}},
        )


async def update_match_played(players, mode):
    if users_col is None:
        return
    field = "solo_matches" if mode == "SOLO" else "team_matches"
    for p in players:
        await update_user_db(p["id"], {field: 1})


async def commit_player_stats(game):
    if users_col is None:
        return
    if game.get("mode") != "TEAM":
        players = game.get("players", [])
    else:
        team_a = game.get("team_a", {}).get("players", [])
        team_b = game.get("team_b", {}).get("players", [])
        players = team_a + team_b

    for p in players:
        runs       = p.get("runs", 0)
        balls_faced = p.get("balls_faced", 0)
        await update_highest_score(p["id"], runs, balls_faced)
        updates = {
            "total_runs": runs,
            "balls_faced": balls_faced,
            "balls_bowled": p.get("balls_bowled", 0),
            "runs_conceded": p.get("conceded", 0),
            "wickets": p.get("wickets", 0),
            "total_4s": p.get("match_4s", 0),
            "total_6s": p.get("match_6s", 0),
            "weekly_runs": runs,
            "weekly_balls_faced": balls_faced,
            "weekly_balls_bowled": p.get("balls_bowled", 0),
            "weekly_conceded": p.get("conceded", 0),
            "weekly_wickets": p.get("wickets", 0),
        }
        if runs == 0 and p.get("is_out", False):
            updates["ducks"] = 1
        if runs >= 100:
            updates["centuries"] = 1
        elif runs >= 50:
            updates["half_centuries"] = 1
        await update_user_db(p["id"], updates)

    await update_match_played(players, game.get("mode", "SOLO"))
    potm = get_potm_data(game)
    if potm:
        await update_user_db(potm["id"], {"motm": 1})


def get_potm_data(game):
    best_player = None
    best_score  = -999
    if game.get("mode") != "TEAM":
        players = game.get("players", [])
    else:
        players = (
            game.get("team_a", {}).get("players", [])
            + game.get("team_b", {}).get("players", [])
        )
    for p in players:
        score = p.get("runs", 0) + (p.get("wickets", 0) * 15) - (p.get("conceded", 0) * 0.5)
        if score > best_score:
            best_score  = score
            best_player = p
    return best_player


# ---------------------------------------------------------------------------
# Game-state utilities
# ---------------------------------------------------------------------------

async def is_admin(chat, user_id):
    try:
        admins = await chat.get_administrators()
        for admin in admins:
            if admin.user.id == user_id:
                return True
        return False
    except Exception:
        try:
            member = await chat.get_member(user_id)
            return member.status in ["administrator", "creator"]
        except Exception:
            return False


def get_next_num(players):
    nums = [p["num"] for p in players if "num" in p]
    i = 1
    while i in nums:
        i += 1
    return i


def is_user_playing_anywhere(context, user_id):
    for cid, data in context.bot_data.items():
        if not isinstance(data, dict):
            continue
        if data.get("state") in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
            continue
        if any(p.get("id") == user_id for p in data.get("players", [])):
            return True
        if "team_a" in data and any(
            p.get("id") == user_id for p in data.get("team_a", {}).get("players", [])
        ):
            return True
        if "team_b" in data and any(
            p.get("id") == user_id for p in data.get("team_b", {}).get("players", [])
        ):
            return True
    return False


def get_user_from_mention(update):
    target_user     = None
    target_username = None
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    else:
        for entity in (update.message.entities or []):
            if entity.type == "text_mention":
                target_user = entity.user
                break
            elif entity.type == "mention":
                target_username = (
                    update.message.text[entity.offset: entity.offset + entity.length]
                    .lstrip("@")
                    .lower()
                )
                break
    return target_user, target_username


def dismiss_batter(game, batter):
    batter["is_out"]        = True
    batter["is_striker"]    = False
    batter["is_non_striker"] = False
    if game.get("striker") and game["striker"]["id"] == batter["id"]:
        game["striker"] = None
    if game.get("non_striker") and game["non_striker"]["id"] == batter["id"]:
        game["non_striker"] = None


def swap_strike(game):
    st = game.get("striker")
    ns = game.get("non_striker")
    if st and ns:
        game["striker"]  = ns
        game["non_striker"] = st
        game["striker"]["is_striker"]      = True
        game["striker"]["is_non_striker"]  = False
        game["non_striker"]["is_striker"]  = False
        game["non_striker"]["is_non_striker"] = True
    elif st and not ns:
        game["non_striker"] = st
        game["striker"]     = None
        game["non_striker"]["is_non_striker"] = True
        game["non_striker"]["is_striker"]     = False
    elif ns and not st:
        game["striker"]   = ns
        game["non_striker"] = None
        game["striker"]["is_striker"]     = True
        game["striker"]["is_non_striker"] = False


# ---------------------------------------------------------------------------
# Scorecard text generation
# ---------------------------------------------------------------------------

def generate_scorecard(game):
    if game.get("mode") == "TEAM":
        return generate_team_scorecard(game)
    # SOLO scorecard (text only)
    text = "📊 <b>SOLO SCORECARD</b> 📊\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for p in game.get("players", []):
        overs, balls = divmod(p.get("balls_bowled", 0), 6)
        eco = (
            (p["conceded"] / p["balls_bowled"]) * 6
            if p.get("balls_bowled", 0) > 0
            else 0.00
        )
        text += (
            f"👤 <b>{p['name']}</b>\n"
            f"  🏏 Bat: <b>{p.get('runs', 0)}</b> ({p.get('balls_faced', 0)})\n"
            f"  🥎 Bowl: <b>{p.get('wickets', 0)}</b>W | "
            f"{p.get('conceded', 0)}R | {overs}.{balls} Ov (Eco: {eco:.1f})\n"
            "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        )
    return text


def generate_team_scorecard(game):
    text = "🏆 <b>MATCH SCORECARD</b> 🏆\n━━━━━━━━━━━━━━━━━━━━━━\n"

    state = game.get("state", "")

    if game.get("innings") == 2 and state != "TEAM_FINISHED":
        target     = game.get("target", 0)
        bat_score  = game.get("batting_team_ref", {}).get("score", 0)
        runs_needed = target - bat_score
        balls_rem  = (game.get("target_overs", 0) * 6) - game.get("bowling_team_ref", {}).get("balls_bowled", 0)
        overs_left = balls_rem / 6 if balls_rem > 0 else 0
        rrr        = (runs_needed / overs_left) if overs_left > 0 else 0.0

        text += (
            f"🎯 <b>Target:</b> {target} | Need <b>{max(0, runs_needed)}</b> runs in <b>{balls_rem}</b> balls.\n"
            f"📈 <b>Required Run Rate (RRR):</b> {rrr:.2f}\n━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    for team_key, team_name in [("team_a", "🔴 TEAM A"), ("team_b", "🔵 TEAM B")]:
        team = game.get(team_key)
        if not team:
            continue

        # Balls faced by this team = balls bowled by the OPPONENT team
        opp_key   = "team_b" if team_key == "team_a" else "team_a"
        opp_team  = game.get(opp_key, {})
        played_balls = opp_team.get("balls_bowled", 0)
        played_overs, rem_balls = divmod(played_balls, 6)
        total_overs_played = played_overs + (rem_balls / 6)
        rr = (team["score"] / total_overs_played) if total_overs_played > 0 else 0.0

        text += (
            f"🎖️ <b>{team_name}</b> ➜ <b>{team['score']}/{team['wickets']}</b> "
            f"<i>({played_overs}.{rem_balls} Ov)</i> | <b>RR: {rr:.2f}</b>\n\n"
        )

        # Batters
        batters_txt = ""
        for p in team.get("players", []):
            if p.get("balls_faced", 0) > 0 or p.get("is_striker") or p.get("is_non_striker") or p.get("is_out"):
                status = "❌" if p.get("is_out") else "🏏"
                sr = (p["runs"] / p["balls_faced"] * 100) if p.get("balls_faced", 0) > 0 else 0.0
                batters_txt += (
                    f"  {status} {p['name'][:12]} ➜ <b>{p.get('runs', 0)}</b> "
                    f"({p.get('balls_faced', 0)}) [SR: {sr:.1f}]\n"
                )
        if batters_txt:
            text += f"<i>Batters:</i>\n{batters_txt}\n"

        # Bowlers (players from this team who bowled)
        bowlers_txt = ""
        for p in team.get("players", []):
            if p.get("balls_bowled", 0) > 0:
                p_ov, p_bl = divmod(p["balls_bowled"], 6)
                eco = (p["conceded"] / p["balls_bowled"]) * 6
                bowlers_txt += (
                    f"  {p['name'][:12]} ➜ {p_ov}.{p_bl} Ov | "
                    f"<b>{p.get('conceded', 0)}R</b> | "
                    f"<b>{p.get('wickets', 0)}W</b> [Eco: {eco:.1f}]\n"
                )
        if bowlers_txt:
            text += f"🥎 <i>Bowlers:</i>\n{bowlers_txt}"
        text += "━━━━━━━━━━━━━━━━━━━━━━\n"

    if state == "TEAM_FINISHED":
        team_a_score = game.get("team_a", {}).get("score", 0)
        team_b_score = game.get("team_b", {}).get("score", 0)

        if team_a_score > team_b_score:
            bat_ref = game.get("batting_team_ref", {})
            if bat_ref is game.get("team_a") and game.get("innings") == 2:
                wickets_left = (len(game["team_a"]["players"]) - 1) - game["team_a"]["wickets"]
                result_str = f"🎉 <b>Team A 🔴 WINS by {wickets_left} wickets!</b>\n"
            else:
                result_str = f"🎉 <b>Team A 🔴 WINS by {team_a_score - team_b_score} runs!</b>\n"
        elif team_b_score > team_a_score:
            bat_ref = game.get("batting_team_ref", {})
            if bat_ref is game.get("team_b") and game.get("innings") == 2:
                wickets_left = (len(game["team_b"]["players"]) - 1) - game["team_b"]["wickets"]
                result_str = f"🎉 <b>Team B 🔵 WINS by {wickets_left} wickets!</b>\n"
            else:
                result_str = f"🎉 <b>Team B 🔵 WINS by {team_b_score - team_a_score} runs!</b>\n"
        else:
            result_str = "🤝 <b>IT'S A TIE!</b> 🤝\n"

        text += result_str + "━━━━━━━━━━━━━━━━━━━━━━\n"

    return text


def get_potm(game):
    best = get_potm_data(game)
    if best:
        best_id   = best["id"]
        best_name = best["name"]
        return (
            f"\n🏅 <b>PLAYER OF THE MATCH: "
            f"<a href='tg://user?id={best_id}'>{best_name}</a></b> 🏅\n"
            "Here is your reward, take this 💋\n"
        )
    return ""


def generate_teams_message(game):
    text = "🏟️ <b>TEAMS ROSTER</b> 🏟️\n\n"
    is_playing = game.get("state") == "PLAYING"
    bat_team   = game.get("batting_team_ref", {}) if is_playing else {}
    bowl_team  = game.get("bowling_team_ref", {}) if is_playing else {}

    for team_key, team_dict in [("team_a", game.get("team_a", {})), ("team_b", game.get("team_b", {}))]:
        team_name = "🔴 <b>TEAM A</b>" if team_key == "team_a" else "🔵 <b>TEAM B</b>"
        text += f"{team_name}\n"
        for i, p in enumerate(team_dict.get("players", []), 1):
            cap    = " (C) 👑" if team_dict.get("captain") == p["id"] else ""
            status = ""
            if is_playing:
                if team_dict is bat_team:
                    if p.get("is_out"):
                        status = " - (Out)"
                    elif p.get("is_striker"):
                        status = " - (On Strike)"
                    elif p.get("is_non_striker"):
                        status = " - (Non Striker)"
                    else:
                        status = " - (Available)"
                elif team_dict is bowl_team:
                    cb = game.get("current_bowler") or {}
                    if cb.get("id") == p["id"]:
                        status = " - (Bowling)"
            pid = p["id"]; pname = p["name"]; text += f" {p.get('num', i)}. <a href='tg://user?id={pid}'>{pname}</a>{cap}<i>{status}</i>\n"
        text += "\n"
    return text


# ---------------------------------------------------------------------------
# Scorecard sender — PILLOW image for TEAM mode, static image for SOLO
# ---------------------------------------------------------------------------

async def trigger_full_scorecard_message(context: ContextTypes.DEFAULT_TYPE,
                                          chat_id: int, game_data: dict):
    scorecard  = generate_scorecard(game_data)
    potm_text  = get_potm(game_data) if game_data.get("state") in ["NOT_PLAYING", "TEAM_FINISHED"] else ""
    final_text = f"{scorecard}{potm_text}"

    markup = None
    if game_data.get("state") in ["NOT_PLAYING", "TEAM_FINISHED"]:
        bot_info = await context.bot.get_me()
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("PLAY AGAIN 🔄", callback_data="play_again")],
            [InlineKeyboardButton("ADD IN GROUP ➕", url=f"https://t.me/{bot_info.username}?startgroup=true")],
        ])

    # Telegram caps photo captions at 1024 characters.
    # Split into image + separate text message if needed.
    MAX_CAPTION = 1024
    use_separate_text = len(final_text) > MAX_CAPTION

    if game_data.get("mode") == "TEAM":
        # Generate custom Pillow scoreboard image
        img_bytes = await generate_team_scoreboard_image(context, chat_id, game_data)
        if img_bytes:
            try:
                if use_separate_text:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=io.BytesIO(img_bytes),
                        caption="📊 <b>TEAM SCORECARD</b> — see details below.",
                        parse_mode="HTML",
                    )
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=final_text,
                        parse_mode="HTML",
                        reply_markup=markup,
                    )
                else:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=io.BytesIO(img_bytes),
                        caption=final_text,
                        parse_mode="HTML",
                        reply_markup=markup,
                    )
                return
            except Exception as e:
                print(f"[scoreboard] Failed to send Pillow image: {e}")
                # Fall through to static image fallback

        # Pillow failed — use static image
        try:
            if use_separate_text:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=SCOREBOARD_IMG,
                    caption="📊 <b>TEAM SCORECARD</b> — see details below.",
                    parse_mode="HTML",
                )
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=final_text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=SCOREBOARD_IMG,
                    caption=final_text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
        except Exception as e:
            print(f"[scoreboard] Fallback photo also failed: {e}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=final_text,
                parse_mode="HTML",
                reply_markup=markup,
            )
    else:
        # SOLO mode — use static image
        try:
            if use_separate_text:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=SCOREBOARD_IMG,
                    caption="📊 <b>SCORECARD</b> — see details below.",
                    parse_mode="HTML",
                )
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=final_text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=SCOREBOARD_IMG,
                    caption=final_text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
        except Exception as e:
            print(f"[scoreboard] Solo photo failed: {e}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=final_text,
                parse_mode="HTML",
                reply_markup=markup,
            )


async def send_top_performers_message(context: ContextTypes.DEFAULT_TYPE,
                                       chat_id: int, game: dict):
    text = "🌟 <b>TOP PERFORMERS OF THE MATCH</b> 🌟\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for team_key, team_name in [("team_a", "🔴 TEAM A"), ("team_b", "🔵 TEAM B")]:
        team = game.get(team_key)
        if not team or not team.get("players"):
            continue
        best_batter = max(team["players"], key=lambda x: x.get("runs", 0))
        best_bowler = max(
            team["players"],
            key=lambda x: x.get("wickets", 0) * 100 - x.get("conceded", 0),
        )
        text += f"\n<b>{team_name}</b>\n"
        text += (
            f"🏏 <b>Best Batter:</b> {best_batter['name'][:15]} ➜ "
            f"<b>{best_batter.get('runs', 0)}</b> ({best_batter.get('balls_faced', 0)})\n"
        )
        b_ov, b_bl = divmod(best_bowler.get("balls_bowled", 0), 6)
        text += (
            f"🥎 <b>Best Bowler:</b> {best_bowler['name'][:15]} ➜ "
            f"<b>{best_bowler.get('wickets', 0)}W</b> for {best_bowler.get('conceded', 0)}R "
            f"({b_ov}.{b_bl} Ov)\n"
        )
    text += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
    await context.bot.send_message(chat_id, text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# AFK system
# ---------------------------------------------------------------------------

def set_afk_timer(context, chat_id, user_id, role):
    clear_afk_timer(context, chat_id)
    game = context.bot_data.get(chat_id)
    if not game:
        return
    if game.get("mode") == "TEAM":
        context.job_queue.run_once(team_afk_warning_10, 10,  data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk10_{chat_id}")
        context.job_queue.run_once(team_afk_warning_30, 30,  data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk30_{chat_id}")
        context.job_queue.run_once(team_afk_timeout,    60,  data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk60_{chat_id}")
    else:
        context.job_queue.run_once(afk_warning_start,   10,  data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk10_{chat_id}")
        context.job_queue.run_once(afk_warning_30,      30,  data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk30_{chat_id}")
        context.job_queue.run_once(afk_timeout,         60,  data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk60_{chat_id}")


def clear_afk_timer(context, chat_id):
    for prefix in ["afk1_", "afk10_", "afk30_", "afk60_", "afk90_"]:
        for job in context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}"):
            job.schedule_removal()


async def check_solo_winner_exp(game):
    if game.get("mode") == "SOLO" and game.get("players"):
        best = max(game["players"], key=lambda x: x.get("runs", 0))
        await update_user_db(best["id"], {"exp": 60})


# ── Solo AFK ────────────────────────────────────────────────────────────────

async def afk_warning_start(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role:
        return
    player = next((p for p in game.get("players", []) if p["id"] == user_id), None)
    if not player:
        return
    await context.bot.send_message(
        chat_id,
        f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, "
        "it is your turn! You have <b>50 seconds</b> to play. ⏳",
        parse_mode="HTML",
    )


async def afk_warning_30(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role:
        return
    player = next((p for p in game.get("players", []) if p["id"] == user_id), None)
    if not player:
        return
    await context.bot.send_message(
        chat_id,
        f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, "
        "HURRY UP! You only have <b>30 seconds</b> left to play! ⏰",
        parse_mode="HTML",
    )


async def afk_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role:
        return

    player = next((p for p in game.get("players", []) if p["id"] == user_id), None)
    if not player:
        return

    await context.bot.send_message(
        chat_id,
        f"⏳ <b>TIME'S UP!</b> {player['name']} was AFK for 60 seconds and has been ELIMINATED! ❌",
        parse_mode="HTML",
    )

    elim_idx = next(
        (i for i, p in enumerate(game.get("players", [])) if p["id"] == user_id), -1
    )
    if elim_idx == -1:
        return
    game["players"] = [p for p in game["players"] if p["id"] != user_id]

    if len(game["players"]) < 2:
        await commit_player_stats(game)
        game["state"] = "NOT_PLAYING"
        await context.bot.send_message(chat_id, "Not enough players left! Match abandoned. 🛑", parse_mode="HTML")
        return

    if elim_idx < game["batter_idx"]:
        game["batter_idx"] -= 1

    if game["batter_idx"] >= len(game["players"]):
        await check_solo_winner_exp(game)
        await commit_player_stats(game)
        game["state"] = "NOT_PLAYING"
        await context.bot.send_message(chat_id, "🏁 <b>MATCH FINISHED!</b> 🏁", parse_mode="HTML")
        await trigger_full_scorecard_message(context, chat_id, game)
        return

    available_bowlers = [i for i in range(len(game["players"])) if i != game["batter_idx"]]
    if available_bowlers:
        game["bowler_idx"] = random.choice(available_bowlers)
    else:
        await commit_player_stats(game)
        game["state"] = "NOT_PLAYING"
        await context.bot.send_message(chat_id, "Not enough players left! Match abandoned. 🛑", parse_mode="HTML")
        return

    game["waiting_for"]           = "BOWLER"
    game["balls_bowled"]          = 0
    game["special_used_this_over"] = False
    await trigger_bowl(context, chat_id)


# ── Team AFK ─────────────────────────────────────────────────────────────────

async def team_afk_warning_10(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role:
        return
    all_players = game.get("team_a", {}).get("players", []) + game.get("team_b", {}).get("players", [])
    player = next((p for p in all_players if p["id"] == user_id), None)
    if not player:
        return
    await context.bot.send_message(
        chat_id,
        f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, "
        "you have been AFK! You have <b>50 more seconds</b> left to play. ⏳",
        parse_mode="HTML",
    )


async def team_afk_warning_30(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role:
        return
    all_players = game.get("team_a", {}).get("players", []) + game.get("team_b", {}).get("players", [])
    player = next((p for p in all_players if p["id"] == user_id), None)
    if not player:
        return
    await context.bot.send_message(
        chat_id,
        f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, "
        "HURRY UP! You only have <b>30 seconds</b> left to play! ⏰",
        parse_mode="HTML",
    )


async def team_afk_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role:
        return

    all_players = game.get("team_a", {}).get("players", []) + game.get("team_b", {}).get("players", [])
    player = next((p for p in all_players if p["id"] == user_id), None)
    if not player:
        return

    if role == "BATTER":
        dismiss_batter(game, player)
        game["batting_team_ref"]["score"]   = max(0, game["batting_team_ref"]["score"] - 5)
        player["runs"]                       = max(0, player.get("runs", 0) - 5)
        game["batting_team_ref"]["wickets"] += 1
        await context.bot.send_message(
            chat_id,
            f"⏳ <b>TIME'S UP!</b> {player['name']} was AFK for 60 seconds! ❌\n"
            "📉 <b>PENALTY:</b> -5 Runs to the team and batter! They are OUT!",
            parse_mode="HTML",
        )
        if game["batting_team_ref"]["wickets"] >= len(game["batting_team_ref"]["players"]) - 1:
            await process_team_innings_end(context, chat_id, game)
            return
        game["waiting_for"] = "TEAM_BATTER_SELECT"
        await context.bot.send_message(
            chat_id,
            "🏏 Captain/Host, please select the next batter using <code>/batting [number]</code>.",
            parse_mode="HTML",
        )
    elif role == "BOWLER":
        game["batting_team_ref"]["score"] += 5
        player["conceded"] = player.get("conceded", 0) + 5
        await context.bot.send_message(
            chat_id,
            f"⏳ <b>TIME'S UP!</b> {player['name']} timed out! ❌\n"
            "📈 <b>PENALTY:</b> +5 Runs to Batting Team!\n"
            "Captain/Host, please select a NEW bowler to continue the over using "
            "<code>/bowling [number]</code>.",
            parse_mode="HTML",
        )
        if game.get("innings") == 2 and game["batting_team_ref"]["score"] >= game.get("target", 0):
            await process_team_innings_end(context, chat_id, game)
            return
        game["waiting_for"]  = "TEAM_BOWLER_SELECT"
        game["last_bowler_id"] = player["id"]


# ---------------------------------------------------------------------------
# Queue / match lifecycle jobs
# ---------------------------------------------------------------------------

async def queue_reminder(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
    game    = context.bot_data.get(chat_id)
    if not game or game.get("state") != "JOINING" or game.get("mode") != "SOLO":
        context.job.schedule_removal()
        return
    await context.bot.send_message(
        chat_id,
        f"⏳ <b>Queue is open!</b> Type /join to enter the match! "
        f"There are 35 seconds left to join. (Total: {len(game['players'])}) 🏏",
        parse_mode="HTML",
    )


async def auto_start_match(context: ContextTypes.DEFAULT_TYPE):
    job     = context.job
    chat_id = job.data["chat_id"]
    for j in context.job_queue.get_jobs_by_name(f"queueremind_{chat_id}"):
        j.schedule_removal()
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "JOINING":
        return
    if len(game.get("players", [])) >= 2:
        game.update({
            "state": "PLAYING", "waiting_for": "BOWLER",
            "batter_idx": 0, "bowler_idx": 1,
            "balls_bowled": 0, "special_used_this_over": False, "is_free_hit": False,
        })
        await context.bot.send_message(
            chat_id,
            "⏳ <b>70 seconds are up! THE MATCH AUTO-STARTS NOW!</b> 🚨\nLet's head to the pitch! 🏟️",
            parse_mode="HTML",
        )
        await trigger_bowl(context, chat_id)
    else:
        game["state"] = "NOT_PLAYING"
        await context.bot.send_message(
            chat_id,
            "⏳ <b>70 seconds are up, but there are not enough players!</b> Match setup abandoned. 🛑",
            parse_mode="HTML",
        )


async def trigger_team_captains(context, chat_id, game):
    game["state"] = "TEAM_CAPTAINS"
    for team_key in ["team_a", "team_b"]:
        random.shuffle(game[team_key]["players"])
        for idx, p in enumerate(game[team_key]["players"], 1):
            p["num"] = idx
    roster = generate_teams_message(game)
    await context.bot.send_photo(chat_id, photo=TEAMS_ROSTER_IMG, caption=roster, parse_mode="HTML")
    kb = [[
        InlineKeyboardButton("Team A Captain 👑", callback_data="team_cap_a"),
        InlineKeyboardButton("Team B Captain 👑", callback_data="team_cap_b"),
    ]]
    await context.bot.send_message(
        chat_id,
        "Who will lead the teams? Members click your team's button to become the Captain! ⚡",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def team_join_timeout(context: ContextTypes.DEFAULT_TYPE):
    job     = context.job
    chat_id = job.data["chat_id"]
    game    = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_JOINING":
        return
    if len(game["team_a"]["players"]) < 2 or len(game["team_b"]["players"]) < 2:
        game["is_paused_waiting_players"] = True
        await context.bot.send_message(
            chat_id,
            "⏳ Time's up! But we need at least 2 players in each team! The queue is paused. ⏸️\n"
            "Once both teams have 2 players, the setup will automatically proceed!",
            parse_mode="HTML",
        )
        return
    await trigger_team_captains(context, chat_id, game)


async def spamfree_timeout(context: ContextTypes.DEFAULT_TYPE):
    job     = context.job
    chat_id = job.data["chat_id"]
    game    = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_SPAMFREE_WAIT":
        return
    game["spamfree"] = False
    game["state"]    = "PLAYING"
    await context.bot.send_message(
        chat_id,
        "⏳ Time is up! ⚠️ <b>SPAM IS ALLOWED.</b>\n\n"
        "Batting Captain/Host, please select your opening pair using:\n"
        "<code>/batting [number]</code> (do it twice).",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_type = update.message.chat.type
    chat_id   = update.effective_chat.id

    if chat_type != "private":
        current_time = time.time()
        cooldown = context.bot_data.get(f"start_cooldown_{chat_id}", 0)
        if current_time < cooldown:
            rem = int(cooldown - current_time)
            await update.message.reply_text(f"⏳ Start command is under cooldown! Try again after {rem} seconds.")
            return
        context.bot_data[f"start_cooldown_{chat_id}"] = current_time + 5

    if chat_type == "private":
        if context.args:
            try:
                group_id = int(context.args[0])
                if "active_bowlers" not in context.bot_data:
                    context.bot_data["active_bowlers"] = {}
                context.bot_data["active_bowlers"][update.effective_user.id] = group_id

                game = context.bot_data.get(group_id)
                if game and game.get("state") == "PLAYING" and game.get("waiting_for") == "BOWLER":
                    if game.get("mode") == "SOLO":
                        bowler = game["players"][game["bowler_idx"]]
                    else:
                        bowler = game.get("current_bowler")

                    if bowler and update.effective_user.id == bowler["id"]:
                        keyboard = []
                        if not game.get("special_used_this_over"):
                            keyboard.append([InlineKeyboardButton("🎯 Try for yorker 🎯", callback_data=f"special_{group_id}")])
                        await update.message.reply_text(
                            "🥎 <b>Your Turn to Bowl!</b>\nType 1-6 or Try for yorker! 🤔👇",
                            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                            parse_mode="HTML",
                        )
                        return
                    else:
                        await update.message.reply_text("It is not your turn to bowl right now! 🚫🏏")
                        return
            except ValueError:
                pass

        welcome_private = (
            "🏏 <b>PLAY LIVE CRICKET INSIDE TELEGRAM</b>\n\n"
            "⚡ Real-time matches\n"
            "🏆 Compete with friends\n"
            "🎯 Become LEGEND 👑\n\n"
            "Ready to dominate?"
        )
        bot_info   = await context.bot.get_me()
        kb_private = [
            [InlineKeyboardButton("ADD IN GROUP TO PLAY ➕", url=f"https://t.me/{bot_info.username}?startgroup=true")],
            [InlineKeyboardButton("STATS 📊", callback_data="dm_stats"), InlineKeyboardButton("Support Group 💬", url="https://t.me/eclplays")],
            [InlineKeyboardButton("Contact Developer 👨‍💻", url="https://t.me/xrztz")],
        ]
        await update.message.reply_photo(
            photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777818831/file_00000000677c71fa8d7d9caa8a1b3cc9_k7l0au.png",
            caption=welcome_private,
            reply_markup=InlineKeyboardMarkup(kb_private),
            parse_mode="HTML",
        )
        return

    game = context.bot_data.get(chat_id)
    if game is None:
        game = {"state": "NOT_PLAYING"}
        context.bot_data[chat_id] = game

    if game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
        await update.message.reply_text("❌ A match is already active in this group! Finish it or ask an admin to /endmatch first.")
        return

    welcome_text = (
        "Welcome to the <b>ELITE CRICKET BOT</b> Arena! 🏆\n"
        "Join our official community at @eclplays. 🏏\n\n"
        "🔥 <b>A tournament is currently going on! Register via @eclregisbot</b> 🔥\n\n"
        "Choose your mode: 👇"
    )
    keyboard = [
        [InlineKeyboardButton("Solo Game 🏏", callback_data="solo_game")],
        [InlineKeyboardButton("Team Game 👥", callback_data="team_game")],
        [InlineKeyboardButton("Cancel ❌",    callback_data="cancel")],
    ]
    await update.message.reply_photo(
        photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777690770/IMG_20260502_082816_001_t0wejv.jpg",
        caption=welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def create_team_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_SETUP_HOST":
        await update.message.reply_text("❌ No team game setup is active! Click 'Team Game' in /start first.")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can create the teams!")
        return

    game["state"]                     = "TEAM_JOINING"
    game["is_paused_waiting_players"] = False
    game["team_a"] = {"players": [], "captain": None, "score": 0, "wickets": 0, "balls_bowled": 0}
    game["team_b"] = {"players": [], "captain": None, "score": 0, "wickets": 0, "balls_bowled": 0}

    kb = [[
        InlineKeyboardButton("Join Team A 🔴", callback_data="join_team_a"),
        InlineKeyboardButton("Join Team B 🔵", callback_data="join_team_b"),
    ]]
    context.job_queue.run_once(team_join_timeout, 10, data={"chat_id": chat_id}, name=f"team_join_{chat_id}")
    await update.message.reply_text(
        "⚔️ <b>TEAM REGISTRATION OPEN!</b> ⚔️\n\n"
        "Players, choose your sides! You have 10 seconds to join. ⏳\n"
        "<b>(Host can type /rejoin to extend 30s or use /add or /remove)</b>",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


async def changecap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM":
        await update.message.reply_text("❌ No active team match right now!")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can change captains!")
        return
    if game.get("state") in ["TEAM_SETUP_HOST", "TEAM_JOINING", "TEAM_CAPTAINS"] and (
        not game.get("team_a", {}).get("captain") or not game.get("team_b", {}).get("captain")
    ):
        await update.message.reply_text("❌ Cannot change captains before both teams have selected their initial captains!")
        return
    if not context.args:
        await update.message.reply_text("Usage: /changecap a OR /changecap b (while replying to a user's message or tagging @username)")
        return
    team_choice = context.args[0].lower()
    if team_choice not in ["a", "b"]:
        await update.message.reply_text("❌ Please specify team 'a' or 'b'. Example: /changecap a")
        return

    team_key = f"team_{team_choice}"
    target_user, target_username = get_user_from_mention(update)
    target_player = None
    if target_user:
        target_player = next((p for p in game[team_key]["players"] if p["id"] == target_user.id), None)
    elif target_username:
        target_player = next((p for p in game[team_key]["players"] if p.get("username") == target_username), None)

    if not target_player:
        await update.message.reply_text(f"❌ User not found in Team {team_choice.upper()}! Make sure to reply to their message or tag them correctly.")
        return
    game[team_key]["captain"] = target_player["id"]
    await update.message.reply_text(f"✅ Team {team_choice.upper()} captain changed to {target_player['name']}!")


async def rejoin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game    = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_JOINING":
        return
    if update.effective_user.id != game.get("host_id"):
        return
    for job in context.job_queue.get_jobs_by_name(f"team_join_{chat_id}"):
        job.schedule_removal()
    context.job_queue.run_once(team_join_timeout, 30, data={"chat_id": chat_id}, name=f"team_join_{chat_id}")
    await update.message.reply_text("⏳ <b>Registration Extended!</b> 30 more seconds to join the teams! 👥", parse_mode="HTML")


async def changeover_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM" or game.get("state") != "PLAYING":
        await update.message.reply_text("❌ No active team match is currently playing!")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can change the number of overs!")
        return
    if game.get("innings") != 1:
        await update.message.reply_text("❌ You can only change the number of overs during the 1st innings!")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("👉 Usage: `/changeover [number]` (e.g., `/changeover 5`)", parse_mode="Markdown")
        return

    new_overs  = int(context.args[0])
    played_overs = game["bowling_team_ref"]["balls_bowled"] // 6
    if new_overs <= played_overs:
        await update.message.reply_text(f"❌ The match has already crossed {played_overs} overs! The new target must be greater than {played_overs} overs.")
        return
    game["target_overs"] = new_overs
    await update.message.reply_text(f"✅ <b>Overs updated!</b> The match is now set for <b>{new_overs} overs</b> per side.", parse_mode="HTML")


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM":
        await update.message.reply_text("❌ No active team match setup found!")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can add players manually!")
        return
    if not context.args:
        await update.message.reply_text("Usage: /add a OR /add b (while replying to a user's message or tagging @username)")
        return
    team_choice = context.args[0].lower()
    if team_choice not in ["a", "b"]:
        await update.message.reply_text("❌ Please specify team 'a' or 'b'. Example: /add a")
        return

    team_key = f"team_{team_choice}"
    target_user, target_username = get_user_from_mention(update)

    if not target_user and target_username and users_col is not None:
        db_user = await users_col.find_one({"username": target_username})
        if db_user:
            class DummyUser:
                def __init__(self, uid, fname, uname):
                    self.id         = uid
                    self.first_name = fname
                    self.username   = uname
                    self.is_bot     = False
            target_user = DummyUser(db_user["user_id"], db_user["first_name"], db_user["username"])

    if not target_user:
        await update.message.reply_text("❌ Please reply to a user's message or make sure they have played before if using @username!")
        return
    if target_user.is_bot:
        await update.message.reply_text("❌ You cannot add a bot to the team!")
        return
    if is_user_playing_anywhere(context, target_user.id):
        await update.message.reply_text("❌ User is already in a game or in a queue in either this or another group.")
        return

    in_a = any(p["id"] == target_user.id for p in game["team_a"]["players"])
    in_b = any(p["id"] == target_user.id for p in game["team_b"]["players"])
    if in_a:
        await update.message.reply_text(f"❌ {target_user.first_name} is already in Team A 🔴!")
        return
    if in_b:
        await update.message.reply_text(f"❌ {target_user.first_name} is already in Team B 🔵!")
        return

    username = target_user.username.lower() if target_user.username else None
    await init_user_db(target_user.id, target_user.first_name, username)
    new_player = {
        "id": target_user.id, "name": target_user.first_name, "username": username,
        "runs": 0, "balls_faced": 0, "wickets": 0, "conceded": 0,
        "balls_bowled": 0, "is_out": False, "match_4s": 0, "match_6s": 0,
    }
    if game.get("state") != "TEAM_JOINING":
        new_player["num"] = get_next_num(game[team_key]["players"])
    game[team_key]["players"].append(new_player)
    team_name = "TEAM A 🔴" if team_choice == "a" else "TEAM B 🔵"
    await update.message.reply_text(
        f"✅ <b>{target_user.first_name}</b> has been manually added to {team_name} by the Host! 👥",
        parse_mode="HTML",
    )

    if game.get("is_paused_waiting_players"):
        if len(game["team_a"]["players"]) >= 2 and len(game["team_b"]["players"]) >= 2:
            game["is_paused_waiting_players"] = False
            await context.bot.send_message(chat_id, "✅ Minimum player requirement met! Resuming setup... ▶️")
            await trigger_team_captains(context, chat_id, game)


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM":
        await update.message.reply_text("❌ No active team match setup found!")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can remove players manually!")
        return
    target_user, target_username = get_user_from_mention(update)
    if not target_user and not target_username:
        await update.message.reply_text("❌ Please reply to a user's message or tag their @username properly!")
        return

    removed     = False
    target_name = ""
    for team_key in ["team_a", "team_b"]:
        for p in list(game[team_key]["players"]):
            if (target_user and p["id"] == target_user.id) or (target_username and p.get("username") == target_username):
                target_name = p["name"]
                game[team_key]["players"].remove(p)
                for i, pr in enumerate(game[team_key]["players"], 1):
                    pr["num"] = i
                removed = True
                break

    if removed:
        await update.message.reply_text(f"✅ <b>{target_name}</b> has been successfully removed from their team! Numbers updated. 🚪", parse_mode="HTML")
    else:
        name_str = target_user.first_name if target_user else target_username
        await update.message.reply_text(f"❌ {name_str} is not in any team!")


async def changehost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM" or game.get("state") in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
        await update.message.reply_text("❌ No active team match to change host!")
        return

    user_id  = update.effective_user.id
    is_host  = (user_id == game.get("host_id"))
    in_team_a = any(p["id"] == user_id for p in game.get("team_a", {}).get("players", []))
    in_team_b = any(p["id"] == user_id for p in game.get("team_b", {}).get("players", []))

    if not (is_host or in_team_a or in_team_b):
        await update.message.reply_text("⚠️ Warning: Only the Game Host or active players in Team A/B can use this command!")
        return

    target_user, target_username = get_user_from_mention(update)
    if not target_user and target_username and users_col is not None:
        db_user = await users_col.find_one({"username": target_username})
        if db_user:
            class DummyUser:
                def __init__(self, uid, fname, uname):
                    self.id = uid; self.first_name = fname; self.username = uname; self.is_bot = False
            target_user = DummyUser(db_user["user_id"], db_user["first_name"], db_user["username"])

    if not target_user:
        await update.message.reply_text("❌ Please reply to a user's message or ensure they have played before if using @username!")
        return
    if target_user.is_bot:
        await update.message.reply_text("❌ A bot cannot be the Game Host!")
        return

    if is_host:
        game["host_id"] = target_user.id
        await update.message.reply_text(f"✅ Host privileges successfully transferred to <b>{target_user.first_name}</b>! 👑", parse_mode="HTML")
    else:
        game["host_vote_target"] = target_user.id
        game["host_vote_name"]   = target_user.first_name
        game["host_votes"]       = set()
        kb = [[InlineKeyboardButton("Vote ✅ (0/4)", callback_data="vote_host")]]
        await update.message.reply_text(
            f"🗳️ Vote initiated to change host to <b>{target_user.first_name}</b>!\n4 votes required.",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML",
        )


async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        return
    chat_id = update.effective_chat.id
    game    = context.bot_data.get(chat_id)
    if not game or game.get("state") != "JOINING":
        await update.message.reply_text("No match is open for joining! Type /start ❌🏏")
        return
    user = update.effective_user
    if is_user_playing_anywhere(context, user.id):
        await update.message.reply_text("❌ You are already in a game or in a queue in either this or another group.")
        return
    if any(p["id"] == user.id for p in game.get("players", [])):
        await update.message.reply_text(f"⚠️ <b>{user.first_name}</b>, you are ALREADY in the queue! Please wait for the match to start. ⏳🧍‍♂️", parse_mode="HTML")
        return

    username = user.username.lower() if user.username else None
    await init_user_db(user.id, user.first_name, username)
    game["players"].append({
        "id": user.id, "name": user.first_name, "username": username,
        "runs": 0, "conceded": 0, "wickets": 0,
        "balls_bowled": 0, "balls_faced": 0, "match_4s": 0, "match_6s": 0,
    })

    timer_msg = ""
    if len(game["players"]) == 1:
        context.job_queue.run_once(auto_start_match, 70, data={"chat_id": chat_id}, name=f"autostart_{chat_id}")
        context.job_queue.run_repeating(queue_reminder, interval=35, first=35, data={"chat_id": chat_id}, name=f"queueremind_{chat_id}")
        timer_msg = "\n⏳ <i>Auto-start timer initiated: Match begins in 70 seconds!</i>"
    await update.message.reply_text(
        f"✅ <b>{user.first_name}</b> joined! (Total: {len(game['players'])}) 👥{timer_msg}",
        parse_mode="HTML",
    )


async def leavesolo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game:
        return
    if game.get("state") == "PLAYING":
        await update.message.reply_text("❌ The match has already started! You can't leave now.")
        return
    if game.get("state") == "JOINING":
        user_id = update.effective_user.id
        if any(p["id"] == user_id for p in game.get("players", [])):
            game["players"] = [p for p in game["players"] if p["id"] != user_id]
            await update.message.reply_text(
                f"👋 <b>{update.effective_user.first_name}</b> has left the queue. (Total: {len(game['players'])}) 👥",
                parse_mode="HTML",
            )
            if len(game["players"]) == 0:
                for prefix in ["autostart_", "queueremind_"]:
                    for job in context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}"):
                        job.schedule_removal()
                await update.message.reply_text("Queue is empty! 🏏 Timer stopped.")
        else:
            await update.message.reply_text("You are not in the queue! ❌")


async def startsolo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.message.chat.type == "private":
        return
    if not await is_admin(update.effective_chat, update.effective_user.id):
        await update.message.reply_text("❌ Only group admins can start the match manually!")
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "JOINING":
        return
    if len(game.get("players", [])) < 2:
        await update.message.reply_text("We need at least 2 players! 👥🏏")
        return
    for prefix in ["autostart_", "queueremind_"]:
        for job in context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}"):
            job.schedule_removal()
    game.update({
        "state": "PLAYING", "waiting_for": "BOWLER",
        "batter_idx": 0, "bowler_idx": 1,
        "balls_bowled": 0, "special_used_this_over": False, "is_free_hit": False,
    })
    await update.message.reply_text("🏏 <b>THE MATCH HAS BEGUN!</b> 🏏", parse_mode="HTML")
    await trigger_bowl(context, chat_id)


async def endmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    if not await is_admin(update.effective_chat, update.effective_user.id):
        await update.message.reply_text("❌ Only group admins can end the match!")
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
        await update.message.reply_text("❌ There is no active match to end!")
        return
    keyboard = [
        [InlineKeyboardButton("Yes, End Match ✅", callback_data=f"endmatch_yes_{chat_id}")],
        [InlineKeyboardButton("Cancel ❌",          callback_data=f"endmatch_no_{chat_id}")],
    ]
    await update.message.reply_text(
        "⚠️ <b>Admin Action:</b> Are you sure you want to force-end the current match?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def soloscore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "SOLO" or game.get("state") in ["NOT_PLAYING", None]:
        await update.message.reply_text("❌ No active solo match is currently being played!")
        return
    await trigger_full_scorecard_message(context, chat_id, game)


async def teamscore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM" or game.get("state") in ["NOT_PLAYING", None]:
        await update.message.reply_text("❌ No active team match is currently being played!")
        return
    await trigger_full_scorecard_message(context, chat_id, game)


async def teams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM" or game.get("state") in ["NOT_PLAYING", "TEAM_SETUP_HOST", "TEAM_JOINING"]:
        await update.message.reply_text("❌ No active team match right now!")
        return
    roster = generate_teams_message(game)
    await update.message.reply_photo(photo=TEAMS_ROSTER_IMG, caption=roster, parse_mode="HTML")


async def batting_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM":
        await update.message.reply_text("❌ There is no active team match currently! This command is only for team matches.")
        return
    if game.get("state") != "PLAYING":
        await update.message.reply_text("❌ The match hasn't started yet!")
        return
    if game.get("waiting_for") not in ["TEAM_OPENERS_BAT", "TEAM_BATTER_SELECT"]:
        await update.message.reply_text("❌ Batters are already on the pitch! You cannot change them right now.")
        return

    batting_team = game["batting_team_ref"]
    if not context.args or not context.args[0].isdigit():
        text = "🏏 <b>AVAILABLE BATTERS:</b>\n"
        for p in batting_team.get("players", []):
            if p.get("is_out"):
                status = "❌ (Out)"
            elif p.get("is_striker") or p.get("is_non_striker"):
                status = "🏏 (On Pitch)"
            else:
                status = "✅ (Available)"
            text += f"[{p.get('num', '?')}] {p['name']} - {status}\n"
        text += "\n👉 <i>Usage: /batting [number] to select.</i>"
        await update.message.reply_text(text, parse_mode="HTML")
        return

    if update.effective_user.id not in [batting_team.get("captain"), game.get("host_id")]:
        await update.message.reply_text("❌ Only the Host or Batting Team Captain can select the batter!")
        return

    p_num    = int(context.args[0])
    selected = next((p for p in batting_team.get("players", []) if p.get("num") == p_num), None)

    if not selected:
        await update.message.reply_text(f"❌ Player {p_num} not found in your team!")
        return
    if selected.get("is_out"):
        await update.message.reply_text(f"❌ {selected['name']} is already out! Select a different player.")
        return

    striker    = game.get("striker") or {}
    non_striker = game.get("non_striker") or {}
    if striker.get("id") == selected["id"] or non_striker.get("id") == selected["id"]:
        await update.message.reply_text(f"❌ {selected['name']} is already on the pitch!")
        return

    if game["waiting_for"] == "TEAM_OPENERS_BAT":
        if not game.get("striker"):
            game["striker"]        = selected
            selected["is_striker"] = True
            await update.message.reply_text(f"🏏 <b>{selected['name']}</b> selected as Striker!", parse_mode="HTML")
        elif not game.get("non_striker"):
            game["non_striker"]         = selected
            selected["is_non_striker"]  = True
            openers_gif = "https://media.giphy.com/media/hGJTJqTNaj0XXkLXZr/giphy.gif"
            caption_txt = (
                f"🏏 <b>{selected['name']}</b> selected as Non-Striker!\n\n"
                "Bowling Team Captain/Host, type /bowling to see bowlers or /bowling [num] to select opening bowler."
            )
            await send_media_safely(context, chat_id, openers_gif, caption_txt)
            game["waiting_for"] = "TEAM_BOWLER_SELECT"
    else:
        if not game.get("striker"):
            game["striker"]        = selected
            selected["is_striker"] = True
        elif not game.get("non_striker"):
            game["non_striker"]         = selected
            selected["is_non_striker"]  = True

        await update.message.reply_text(f"🏏 <b>{selected['name']}</b> walks out to the pitch!", parse_mode="HTML")
        if game.get("need_new_bowler"):
            game["need_new_bowler"] = False
            game["waiting_for"]     = "TEAM_BOWLER_SELECT"
            await update.message.reply_text(
                "Bowling Captain/Host, please select the next bowler using <code>/bowling [num]</code>.",
                parse_mode="HTML",
            )
        else:
            game["waiting_for"] = "BOWLER"
            await trigger_bowl(context, chat_id)


async def bowling_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM":
        await update.message.reply_text("❌ There is no active team match currently! This command is only for team matches.")
        return
    if game.get("state") != "PLAYING":
        await update.message.reply_text("❌ The match hasn't started yet!")
        return
    if game.get("waiting_for") in ["TEAM_OPENERS_BAT", "TEAM_BATTER_SELECT"]:
        await update.message.reply_text("❌ Batters not selected yet! Let the batting team select their batter(s) first.")
        return
    if game.get("waiting_for") != "TEAM_BOWLER_SELECT":
        await update.message.reply_text("❌ A bowler is already selected and bowling right now!")
        return

    bowling_team = game["bowling_team_ref"]
    if not context.args or not context.args[0].isdigit():
        text = "🥎 <b>AVAILABLE BOWLERS:</b>\n"
        for p in bowling_team.get("players", []):
            status = "✅ (Available)"
            if game.get("last_bowler_id") == p["id"]:
                status = "⏳ (Bowled Last Over)"
            cb = game.get("current_bowler") or {}
            if cb.get("id") == p["id"]:
                status = "🥎 (Bowling Now)"
            text += f"[{p.get('num', '?')}] {p['name']} - {p.get('balls_bowled', 0)//6}.{p.get('balls_bowled', 0)%6} Ov - {status}\n"
        text += "\n👉 <i>Usage: /bowling [number] to select.</i>"
        await update.message.reply_text(text, parse_mode="HTML")
        return

    if update.effective_user.id not in [bowling_team.get("captain"), game.get("host_id")]:
        await update.message.reply_text("❌ Only the Host or Bowling Team Captain can select the bowler!")
        return

    p_num    = int(context.args[0])
    selected = next((p for p in bowling_team.get("players", []) if p.get("num") == p_num), None)
    if not selected:
        await update.message.reply_text(f"❌ Player {p_num} not found in your team!")
        return
    if game.get("last_bowler_id") == selected["id"]:
        await update.message.reply_text("❌ A bowler cannot bowl two consecutive overs!")
        return

    game["current_bowler"] = selected
    game["waiting_for"]    = "BOWLER"
    await update.message.reply_text(f"🥎 <b>{selected['name']}</b> is handed the ball!", parse_mode="HTML")
    if game.get("innings_start_msg_pending"):
        game["innings_start_msg_pending"] = False
        await update.message.reply_text("🚨 <b>THE INNINGS HAS BEGUN!</b>", parse_mode="HTML")
    await trigger_bowl(context, chat_id)


async def userstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    target_user, target_username = get_user_from_mention(update)
    if not target_user and not target_username:
        target_user = update.effective_user
    if users_col is None:
        await msg.reply_text("❌ Database connection error.")
        return
    try:
        user_data = None
        if target_user:
            user_data = await users_col.find_one({"user_id": target_user.id})
        elif target_username:
            user_data = await users_col.find_one({"username": target_username})
        if not user_data:
            name = target_user.first_name if target_user else target_username
            await msg.reply_text(f"❌ Ek bhi match khela hai tune is bot se jo stats dekh raha? {name}.")
            return

        hs_runs  = user_data.get("highest_score", {}).get("runs", 0)
        hs_balls = user_data.get("highest_score", {}).get("balls", 0)
        total_runs   = user_data.get("total_runs", 0)
        balls_faced  = user_data.get("balls_faced", 0)
        sr           = (total_runs / balls_faced * 100) if balls_faced > 0 else 0
        balls_bowled = user_data.get("balls_bowled", 0)
        runs_conceded = user_data.get("runs_conceded", 0)
        overs        = balls_bowled // 6
        rem_balls    = balls_bowled % 6
        eco          = (runs_conceded / balls_bowled * 6) if balls_bowled > 0 else 0

        exp   = user_data.get("exp", 0)
        level = get_user_level(exp)
        next_level_name, exp_needed = get_next_level_info(exp)
        total_matches = user_data.get("team_matches", 0) + user_data.get("solo_matches", 0)
        outs  = max(1, total_matches - user_data.get("ducks", 0))
        avg   = total_runs / outs if total_runs > 0 else 0

        exp_line = (
            f"⭐ <b>EXP:</b> {exp} | Next: <b>{next_level_name}</b> (Need {exp_needed} more EXP)\n"
            if next_level_name
            else f"⭐ <b>EXP:</b> {exp} | 🏆 <b>MAX LEVEL REACHED!</b>\n"
        )

        stats_text  = f"📊 <b>{level} STATISTICS</b> 📊\n═══════════════════════════\n"
        stats_text += f"👤 <b>Name:</b> {user_data.get('first_name', 'Unknown')}\n🆔 <b>ID:</b> <code>{user_data.get('user_id', 'Unknown')}</code>\n{exp_line}┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        stats_text += f"🏏 <b>BATTING STATS</b>\n🔸 <b>Highest Score:</b> {hs_runs} ({hs_balls})\n🔸 <b>Total Runs:</b> {total_runs}\n🔸 <b>Batting Avg:</b> {avg:.2f} | <b>Strike Rate:</b> {sr:.2f}\n"
        stats_text += f"🔸 <b>6s:</b> {user_data.get('total_6s', 0)} | <b>4s:</b> {user_data.get('total_4s', 0)}\n🔸 <b>100s:</b> {user_data.get('centuries', 0)} | <b>50s:</b> {user_data.get('half_centuries', 0)}\n"
        stats_text += f"🔸 <b>Ducks 🦆:</b> {user_data.get('ducks', 0)}\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        stats_text += f"🥎 <b>BOWLING STATS</b>\n🔹 <b>Wickets:</b> {user_data.get('wickets', 0)}\n🔹 <b>Hat-Tricks:</b> {user_data.get('hat_tricks', 0)}\n"
        stats_text += f"🔹 <b>Overs Bowled:</b> {overs}.{rem_balls}\n🔹 <b>Economy:</b> {eco:.2f}\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        stats_text += f"🏆 <b>MATCH &amp; AWARDS</b>\n🔸 <b>Solo Matches:</b> {user_data.get('solo_matches', 0)}\n🔸 <b>Team Matches:</b> {user_data.get('team_matches', 0)}\n"
        stats_text += f"🔸 <b>MOTM Awards:</b> {user_data.get('motm', 0)}\n═══════════════════════════"

        stats_img = "https://res.cloudinary.com/dxgfxfoog/image/upload/v1777818873/file_00000000fa6871fa8d9b30faff9899ae_hbyn9j.png"
        await msg.reply_photo(photo=stats_img, caption=stats_text, parse_mode="HTML")
    except Exception as e:
        print(f"Error fetching stats: {e}")
        await msg.reply_text("❌ An error occurred while fetching stats.")


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("WEEKLY LEADERBOARD 📅",  callback_data="lb_weekly")],
        [InlineKeyboardButton("LIFETIME LEADERBOARD 🏆", callback_data="lb_lifetime")],
    ]
    await update.message.reply_text(
        "📊 <b>View our top performers!</b>\nSelect a leaderboard below:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ You ain't the owner of this bot biiichhh.")
        return
    message_to_send = update.message.reply_to_message
    text = None
    if not message_to_send:
        if not context.args:
            await update.message.reply_text("Usage: /broadcast <message> or reply to a message with /broadcast")
            return
        text = update.message.text.split(" ", 1)[1]
    if chats_col is None:
        await update.message.reply_text("Database not connected.")
        return
    success = 0; failed = 0
    status_msg = await update.message.reply_text("Broadcasting started... ⏳")
    async for chat in chats_col.find({}):
        cid = chat["chat_id"]
        try:
            if message_to_send:
                await context.bot.copy_message(chat_id=cid, from_chat_id=update.effective_chat.id, message_id=message_to_send.message_id)
            else:
                await context.bot.send_message(chat_id=cid, text=text, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await status_msg.edit_text(
        f"✅ <b>Broadcast finished!</b>\n\n📨 Sent: {success}\n❌ Failed: {failed}",
        parse_mode="HTML",
    )


async def botstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("Jaa jaake chaddhi badal le pehle owner command use karega.")
        return
    if chats_col is None:
        await update.message.reply_text("Database not connected.")
        return
    users_count  = await users_col.count_documents({})
    groups_count = await chats_col.count_documents({"type": {"$in": ["group", "supergroup"]}})
    await update.message.reply_text(
        f"📊 <b>Bot Statistics</b>\n\n👤 Total Users Interacted: {users_count}\n👥 Total Groups Present: {groups_count}",
        parse_mode="HTML",
    )


async def botgroups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("Sarpanch ji toh chal base.")
        return
    if chats_col is None:
        await update.message.reply_text("Database not connected.")
        return
    groups_cursor = chats_col.find({"type": {"$in": ["group", "supergroup"]}})
    groups = await groups_cursor.to_list(length=1000)
    if not groups:
        await update.message.reply_text("Bot is not in any groups right now.")
        return
    text = f"📊 <b>Bot Groups ({len(groups)}):</b>\n\n"
    for i, g in enumerate(groups, 1):
        title = g.get("title", "Unknown Group")
        text += f"{i}. {title} (<code>{g['chat_id']}</code>)\n"
    if len(text) > 4000:
        text = text[:4000] + "...\n[Truncated]"
    await update.message.reply_text(text, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🏏 Solo Game Guide",   callback_data="help_solo")],
        [InlineKeyboardButton("👥 Team Game Guide",   callback_data="help_team")],
        [InlineKeyboardButton("🎯 Yorker Rules",      callback_data="help_yorker")],
        [InlineKeyboardButton("⏳ AFK Penalties",     callback_data="help_afk")],
        [InlineKeyboardButton("📊 Commands List",     callback_data="help_commands")],
        [InlineKeyboardButton("⭐ Level System",      callback_data="help_levels")],
    ]
    await update.message.reply_text(
        "🏏 <b>ELITE CRICKET BOT — HELP CENTER</b> 🏆\n\n"
        "Welcome! Select a topic below to learn everything about the bot:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


async def spamfree_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_SPAMFREE_WAIT":
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can use the spamfree command!")
        return
    for job in context.job_queue.get_jobs_by_name(f"spamfree_{chat_id}"):
        job.schedule_removal()
    game["spamfree"] = True
    game["state"]    = "PLAYING"
    await update.message.reply_text(
        "🛡️ <b>SPAM-FREE MODE ACTIVATED!</b> Bowlers cannot bowl the same delivery more than twice in a row.\n\n"
        "Batting Captain/Host, please select your opening pair using:\n"
        "<code>/batting [number]</code> (do it twice).",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Bowling trigger
# ---------------------------------------------------------------------------

async def trigger_bowl(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING":
        return

    if game.get("mode") == "TEAM":
        bowler    = game.get("current_bowler")
        batter    = game.get("striker")
        over_info = (
            f"{game['bowling_team_ref']['balls_bowled'] // 6}."
            f"{game['bowling_team_ref']['balls_bowled'] % 6} / {game.get('target_overs', '?')}"
        )
    else:
        bowler    = game["players"][game["bowler_idx"]]
        batter    = game["players"][game["batter_idx"]]
        over_info = f"{game['balls_bowled']}/{game['spell']} balls"

    if bowler is None or batter is None:
        return

    if "active_bowlers" not in context.bot_data:
        context.bot_data["active_bowlers"] = {}
    context.bot_data["active_bowlers"][bowler["id"]] = chat_id

    bot_info     = await context.bot.get_me()
    url          = f"https://t.me/{bot_info.username}"
    free_hit_tag = "🚀 <b>FREE HIT ACTIVE!!</b>\n" if game.get("is_free_hit") else ""

    dm_text  = (
        f"🏏 <b>Match in Progress!</b>\n\n"
        f"🏏 Batter: <b>{batter['name']}</b> ({batter.get('runs', 0)} off {batter.get('balls_faced', 0)})\n"
        f"🥎 Over Status: {over_info}.\n\n"
        "👉 <b>Your Turn to Bowl!</b> Type a number from 1 to 6."
    )
    keyboard = []
    if not game.get("special_used_this_over"):
        keyboard.append([InlineKeyboardButton("🎯 Try for yorker 🎯", callback_data=f"special_{chat_id}")])

    dm_sent = False
    try:
        await context.bot.send_message(
            chat_id=bowler["id"], text=dm_text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            parse_mode="HTML",
        )
        dm_sent = True
    except Exception:
        pass

    if dm_sent:
        group_text = (
            f"{free_hit_tag}📊 <b>Status:</b>\n"
            f"🏏 <b>Batter:</b> {batter['name']} ({batter.get('runs', 0)} off {batter.get('balls_faced', 0)})\n"
            f"🥎 <b>Bowler:</b> {bowler['name']} (Over: {over_info})\n\n"
            f"👉 <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, check your DM to bowl! 🤫🥎"
        )
        group_kb = [[InlineKeyboardButton("Bowl Delivery 🥎", url=url)]]
    else:
        fallback_url = f"https://t.me/{bot_info.username}?start={chat_id}"
        group_text = (
            f"{free_hit_tag}📊 <b>Status:</b>\n"
            f"🏏 <b>Batter:</b> {batter['name']} ({batter.get('runs', 0)} off {batter.get('balls_faced', 0)})\n"
            f"🥎 <b>Bowler:</b> {bowler['name']} (Over: {over_info})\n\n"
            f"⚠️ <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, I couldn't DM you! "
            "Click below to start me, then bowl! 🤫🥎"
        )
        group_kb = [[InlineKeyboardButton("Start Bot & Bowl 🤖", url=fallback_url)]]

    await send_media_safely(context, chat_id, MEDIA["bowler_turn"], group_text, InlineKeyboardMarkup(group_kb))
    set_afk_timer(context, chat_id, bowler["id"], "BOWLER")


# ---------------------------------------------------------------------------
# Team innings management
# ---------------------------------------------------------------------------

async def process_team_innings_end(context, chat_id, game):
    if game.get("innings") == 1:
        game["innings"] = 2
        game["target"]  = game["batting_team_ref"]["score"] + 1

        # Swap batting and bowling sides
        temp                    = game["batting_team_ref"]
        game["batting_team_ref"] = game["bowling_team_ref"]
        game["bowling_team_ref"] = temp

        for p in game["team_a"]["players"] + game["team_b"]["players"]:
            p["is_striker"]    = False
            p["is_non_striker"] = False
            p["is_out"]        = False

        game["striker"]               = None
        game["non_striker"]           = None
        game["current_bowler"]        = None
        game["last_bowler_id"]        = None
        game["is_free_hit"]           = False
        game["special_used_this_over"] = False

        text = (
            f"🛑 <b>INNINGS BREAK! AB CHASE KARO !!</b> 🛑\n\n"
            f"🎯 Target for the Bowling team: <b>{game['target']} runs</b> in {game.get('target_overs', '?')} overs.\n\n"
            "Batting Captain/Host, please select your opening pair using:\n"
            "<code>/batting [number]</code> (do it twice)."
        )
        game["waiting_for"]             = "TEAM_OPENERS_BAT"
        game["innings_start_msg_pending"] = True
        await context.bot.send_message(chat_id, text, parse_mode="HTML")
    else:
        team_a_score = game["team_a"]["score"]
        team_b_score = game["team_b"]["score"]
        winning_team = None
        if team_a_score > team_b_score:
            winning_team = game["team_a"]["players"]
        elif team_b_score > team_a_score:
            winning_team = game["team_b"]["players"]
        if winning_team:
            for wp in winning_team:
                await update_user_db(wp["id"], {"exp": 40})

        try:
            await commit_player_stats(game)
        except Exception as e:
            print(f"Stats Error: {e}")

        game["state"] = "TEAM_FINISHED"
        await context.bot.send_message(chat_id, "🏁 <b>MATCH FINISHED!</b> 🏁", parse_mode="HTML")
        await trigger_full_scorecard_message(context, chat_id, game)
        await send_top_performers_message(context, chat_id, game)
        game["state"] = "NOT_PLAYING"


# ---------------------------------------------------------------------------
# Callback query handler
# ---------------------------------------------------------------------------

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    game    = context.bot_data.get(chat_id)
    if game is None:
        game = {"state": "NOT_PLAYING"}
        context.bot_data[chat_id] = game

    # ── Solo game ─────────────────────────────────────────────────────────
    if query.data == "solo_game":
        _lock_key = f"btn_{chat_id}_{query.message.message_id}"
        if context.bot_data.get(_lock_key):
            return
        context.bot_data[_lock_key] = True

        if game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
            try:
                await query.edit_message_caption(caption="❌ A match is already active or setting up in this group!", reply_markup=None)
            except Exception:
                pass
            context.bot_data.pop(_lock_key, None)
            return
        keyboard = [
            [InlineKeyboardButton("3 Balls 🥎", callback_data="spell_3")],
            [InlineKeyboardButton("6 Balls 🥎", callback_data="spell_6")],
        ]
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_photo(
            chat_id=chat_id,
            photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777720022/file_00000000483072079f73014e1bba1fde_l4thrv.png",
            caption="Select Spell Limit: ⚖️🏏",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data == "team_game":
        _lock_key = f"btn_{chat_id}_{query.message.message_id}"
        if context.bot_data.get(_lock_key):
            return
        context.bot_data[_lock_key] = True

        if game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
            try:
                await query.edit_message_caption(caption="❌ A match is already active or setting up in this group!", reply_markup=None)
            except Exception:
                pass
            context.bot_data.pop(_lock_key, None)
            return
        text = (
            "👥 <b>TEAM GAME MODE</b> 👥\n\n"
            "Form two teams, appoint captains, toss the coin, and clash in an epic T20-style showdown! 🏆🏏\n\n"
            "Who will take charge?"
        )
        kb = [
            [InlineKeyboardButton("HOST BANUNGA 👿", callback_data="host_banunga")],
            [InlineKeyboardButton("CANCEL ❌",        callback_data="cancel")],
        ]
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_photo(
            chat_id=chat_id,
            photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777720311/file_00000000332072078d00837e7d719f5e_ybg18b.png",
            caption=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif query.data == "host_banunga":
        _lock_key = f"btn_{chat_id}_{query.message.message_id}_host"
        if context.bot_data.get(_lock_key):
            try:
                await query.answer("👑 A host is already being set up!", show_alert=True)
            except Exception:
                pass
            return
        context.bot_data[_lock_key] = True

        if game.get("state") == "TEAM_SETUP_HOST":
            try:
                await query.answer("❌ A host has already been selected for this match!", show_alert=True)
            except Exception:
                pass
            context.bot_data.pop(_lock_key, None)
            return
        if is_user_playing_anywhere(context, user_id):
            try:
                await query.answer("❌ You are already in a game or in a queue in either this or another group.", show_alert=True)
            except Exception:
                await context.bot.send_message(chat_id, "❌ You are already in a game or in a queue in either this or another group.")
            return
        context.bot_data[chat_id] = {"state": "TEAM_SETUP_HOST", "host_id": user_id, "mode": "TEAM"}
        try:
            await query.edit_message_caption(
                caption=(
                    f"👑 <a href='tg://user?id={user_id}'>{update.effective_user.first_name}</a> is the Game Host!\n\n"
                    "Host, please send /create_team to open the team registration."
                ),
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass

    elif query.data == "join_team_a":
        if game.get("state") != "TEAM_JOINING":
            return
        if is_user_playing_anywhere(context, user_id):
            await context.bot.send_message(chat_id, "❌ You are already in a game or in a queue in either this or another group.")
            return

        lock_key = f"team_join_lock_{chat_id}"
        if lock_key not in context.bot_data:
            context.bot_data[lock_key] = asyncio.Lock()
        async with context.bot_data[lock_key]:
            in_a = any(p["id"] == user_id for p in game["team_a"]["players"])
            in_b = any(p["id"] == user_id for p in game["team_b"]["players"])
            if in_a or in_b:
                try:
                    await query.answer(f"⚠️ You are already in {'Team A 🔴' if in_a else 'Team B 🔵'}! Wait for the host to start.", show_alert=True)
                except Exception:
                    pass
                return
            username = update.effective_user.username.lower() if update.effective_user.username else None
            await init_user_db(user_id, update.effective_user.first_name, username)
            game["team_a"]["players"].append({
                "id": user_id, "name": update.effective_user.first_name, "username": username,
                "runs": 0, "balls_faced": 0, "wickets": 0, "conceded": 0,
                "balls_bowled": 0, "is_out": False, "match_4s": 0, "match_6s": 0,
            })

        await context.bot.send_message(chat_id, f"🔴 <b>{update.effective_user.first_name}</b> joined Team A!", parse_mode="HTML")
        if game.get("is_paused_waiting_players") and len(game["team_a"]["players"]) >= 2 and len(game["team_b"]["players"]) >= 2:
            game["is_paused_waiting_players"] = False
            await context.bot.send_message(chat_id, "✅ Minimum player requirement met! Resuming setup... ▶️")
            await trigger_team_captains(context, chat_id, game)

    elif query.data == "join_team_b":
        if game.get("state") != "TEAM_JOINING":
            return
        if is_user_playing_anywhere(context, user_id):
            await context.bot.send_message(chat_id, "❌ You are already in a game or in a queue in either this or another group.")
            return

        lock_key = f"team_join_lock_{chat_id}"
        if lock_key not in context.bot_data:
            context.bot_data[lock_key] = asyncio.Lock()
        async with context.bot_data[lock_key]:
            in_a = any(p["id"] == user_id for p in game["team_a"]["players"])
            in_b = any(p["id"] == user_id for p in game["team_b"]["players"])
            if in_a or in_b:
                try:
                    await query.answer(f"⚠️ You are already in {'Team A 🔴' if in_a else 'Team B 🔵'}! Wait for the host to start.", show_alert=True)
                except Exception:
                    pass
                return
            username = update.effective_user.username.lower() if update.effective_user.username else None
            await init_user_db(user_id, update.effective_user.first_name, username)
            game["team_b"]["players"].append({
                "id": user_id, "name": update.effective_user.first_name, "username": username,
                "runs": 0, "balls_faced": 0, "wickets": 0, "conceded": 0,
                "balls_bowled": 0, "is_out": False, "match_4s": 0, "match_6s": 0,
            })

        await context.bot.send_message(chat_id, f"🔵 <b>{update.effective_user.first_name}</b> joined Team B!", parse_mode="HTML")
        if game.get("is_paused_waiting_players") and len(game["team_a"]["players"]) >= 2 and len(game["team_b"]["players"]) >= 2:
            game["is_paused_waiting_players"] = False
            await context.bot.send_message(chat_id, "✅ Minimum player requirement met! Resuming setup... ▶️")
            await trigger_team_captains(context, chat_id, game)

    elif query.data in ["team_cap_a", "team_cap_b"]:
        if game.get("state") != "TEAM_CAPTAINS":
            return
        team_key = "team_a" if query.data == "team_cap_a" else "team_b"
        if not any(p["id"] == user_id for p in game[team_key]["players"]):
            try:
                await query.answer("You are not in this team!", show_alert=True)
            except Exception:
                pass
            return
        if game[team_key]["captain"]:
            try:
                await query.answer("Captain already selected!", show_alert=True)
            except Exception:
                pass
            return
        game[team_key]["captain"] = user_id
        await context.bot.send_message(
            chat_id,
            f"👑 <b>{update.effective_user.first_name}</b> is now Captain of "
            f"{'Team A 🔴' if team_key == 'team_a' else 'Team B 🔵'}!",
            parse_mode="HTML",
        )
        if game["team_a"]["captain"] and game["team_b"]["captain"]:
            game["state"]           = "TEAM_TOSS"
            toss_winner_team        = random.choice(["team_a", "team_b"])
            game["toss_winner_team"] = toss_winner_team
            cap_id   = game[toss_winner_team]["captain"]
            cap_name = next(p["name"] for p in game[toss_winner_team]["players"] if p["id"] == cap_id)
            kb = [[
                InlineKeyboardButton("Heads 🪙", callback_data="toss_heads"),
                InlineKeyboardButton("Tails 🪙", callback_data="toss_tails"),
            ]]
            toss_vid   = "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777819028/VID_20260503195638_lhif0h.mp4"
            caption_msg = f"🪙 <b>TOSS TIME!</b>\n<a href='tg://user?id={cap_id}'>{cap_name}</a>, call the toss!"
            await send_media_safely(context, chat_id, toss_vid, caption_msg, InlineKeyboardMarkup(kb))

    elif query.data in ["toss_heads", "toss_tails"]:
        if game.get("state") != "TEAM_TOSS":
            return
        if user_id != game[game["toss_winner_team"]]["captain"]:
            try:
                await query.answer("Only the designated captain can call the toss!", show_alert=True)
            except Exception:
                pass
            return
        won_toss = random.choice([True, False])
        if won_toss:
            game["state"] = "TEAM_TOSS_DECISION"
            winner_name   = "Team A 🔴" if game["toss_winner_team"] == "team_a" else "Team B 🔵"
            kb = [[
                InlineKeyboardButton("Bat 🏏",  callback_data="toss_bat"),
                InlineKeyboardButton("Bowl 🥎", callback_data="toss_bowl"),
            ]]
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id,
                f"🎉 <b>{winner_name}</b> won the toss! What will you do?",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="HTML",
            )
        else:
            game["state"]            = "TEAM_TOSS_DECISION"
            game["toss_winner_team"] = "team_b" if game["toss_winner_team"] == "team_a" else "team_a"
            cap_id   = game[game["toss_winner_team"]]["captain"]
            cap_name = next(p["name"] for p in game[game["toss_winner_team"]]["players"] if p["id"] == cap_id)
            winner_name = "Team A 🔴" if game["toss_winner_team"] == "team_a" else "Team B 🔵"
            kb = [[
                InlineKeyboardButton("Bat 🏏",  callback_data="toss_bat"),
                InlineKeyboardButton("Bowl 🥎", callback_data="toss_bowl"),
            ]]
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id,
                f"❌ You lost the toss!\n\n🎉 <b>{winner_name}</b> "
                f"(<a href='tg://user?id={cap_id}'>{cap_name}</a>) won the toss. What will they choose?",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="HTML",
            )

    elif query.data in ["toss_bat", "toss_bowl"]:
        if game.get("state") != "TEAM_TOSS_DECISION":
            return
        if user_id != game[game["toss_winner_team"]]["captain"]:
            try:
                await query.answer("Only the toss winning captain can decide!", show_alert=True)
            except Exception:
                pass
            return
        if query.data == "toss_bat":
            game["batting_team_ref"] = game[game["toss_winner_team"]]
            game["bowling_team_ref"] = game["team_b" if game["toss_winner_team"] == "team_a" else "team_a"]
            dec_text = "bat 🏏"
        else:
            game["bowling_team_ref"] = game[game["toss_winner_team"]]
            game["batting_team_ref"] = game["team_b" if game["toss_winner_team"] == "team_a" else "team_a"]
            dec_text = "bowl 🥎"

        game["state"] = "TEAM_OVERS"
        host_id   = game["host_id"]
        host_name = "Host"
        try:
            host_name = (await context.bot.get_chat_member(chat_id, host_id)).user.first_name
        except Exception:
            pass
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(chat_id, f"✅ The captain chose to {dec_text} first!")
        kb = [
            [InlineKeyboardButton(str(o), callback_data=f"tovers_{o}") for o in [3, 5, 10]],
            [InlineKeyboardButton(str(o), callback_data=f"tovers_{o}") for o in [15, 20, 25]],
        ]
        await context.bot.send_message(
            chat_id,
            f"<a href='tg://user?id={host_id}'>{host_name}</a> (Game Host), "
            "select the number of overs for this match:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML",
        )

    elif query.data.startswith("tovers_"):
        if game.get("state") != "TEAM_OVERS":
            return
        if user_id != game.get("host_id"):
            try:
                await query.answer("Only the host can select overs!", show_alert=True)
            except Exception:
                pass
            return
        overs = int(query.data.split("_")[1])
        game.update({
            "target_overs": overs,
            "state": "TEAM_SPAMFREE_WAIT",
            "innings": 1,
            "waiting_for": "TEAM_OPENERS_BAT",
            "is_free_hit": False,
            "special_used_this_over": False,
            "innings_start_msg_pending": True,
            "spamfree": False,
        })
        try:
            await query.edit_message_text(f"✅ Match set for <b>{overs} Overs</b> per side!", parse_mode="HTML", reply_markup=None)
        except Exception:
            pass

        host_id   = game["host_id"]
        host_name = "Host"
        try:
            member    = await context.bot.get_chat_member(chat_id, host_id)
            host_name = member.user.first_name
        except Exception:
            pass

        context.job_queue.run_once(spamfree_timeout, 15, data={"chat_id": chat_id}, name=f"spamfree_{chat_id}")
        await context.bot.send_message(
            chat_id,
            f"⚠️ <a href='tg://user?id={host_id}'>{host_name}</a>, you can make this game spam-free by clicking on /spamfree\n\n"
            "You have 15 seconds to decide. After 15 seconds if you do not /spamfree then spam is allowed and we proceed to the game!!",
            parse_mode="HTML",
        )

    elif query.data.startswith("spell_"):
        if context.bot_data.get(chat_id, {}).get("state") in ["JOINING", "PLAYING"]:
            try:
                await query.edit_message_caption(caption="❌ A match is already active or setting up in this group!", reply_markup=None)
            except Exception:
                pass
            return
        spell_len = int(query.data.split("_")[1])
        context.bot_data[chat_id] = {"state": "JOINING", "mode": "SOLO", "spell": spell_len, "players": []}
        try:
            await query.edit_message_caption(
                caption=(
                    f"🏏 <b>Queue Open!</b> (Spell: {spell_len} balls) ⚖️\n"
                    "👉 Type /join\n"
                    "👉 Type /leavesolo to exit queue\n"
                    "👉 Admin can type /startsolo"
                ),
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass

    elif query.data == "cancel":
        if game.get("state") == "PLAYING":
            try:
                await query.edit_message_caption(caption="❌ Match is already playing! Use /endmatch to stop it.", reply_markup=None)
            except Exception:
                pass
            return
        game["state"] = "NOT_PLAYING"
        for prefix in ["autostart_", "team_join_", "queueremind_"]:
            for job in context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}"):
                job.schedule_removal()
        try:
            await query.edit_message_caption(caption="Setup cancelled. 🏏❌", reply_markup=None)
        except Exception:
            pass

    elif query.data == "vote_host":
        if "host_votes" not in game:
            return
        if user_id in game["host_votes"]:
            try:
                await query.answer("You already voted!", show_alert=True)
            except Exception:
                pass
            return
        game["host_votes"].add(user_id)
        votes = len(game["host_votes"])
        if votes >= 4:
            game["host_id"] = game["host_vote_target"]
            try:
                await query.edit_message_text(
                    f"✅ Vote passed! Game Host successfully changed to <b>{game['host_vote_name']}</b>! 👑",
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except Exception:
                pass
        else:
            try:
                await query.edit_message_reply_markup(
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"Vote ✅ ({votes}/4)", callback_data="vote_host")]]))
            except Exception:
                pass

    elif query.data.startswith("endmatch_"):
        parts  = query.data.split("_")
        action = parts[1]
        targ_chat_id = int(parts[2])
        if not await is_admin(update.effective_chat, update.effective_user.id):
            await context.bot.send_message(chat_id, "❌ Only admins can click this!")
            return
        if action == "yes":
            game_ref = context.bot_data.get(targ_chat_id)
            if game_ref:
                try:
                    await commit_player_stats(game_ref)
                except Exception as e:
                    print(f"Error in stats: {e}")
                game_ref["state"] = "NOT_PLAYING"
                for prefix in ["autostart_", "team_join_", "queueremind_", "afk1_", "afk10_", "afk30_", "afk60_", "afk90_", "spamfree_"]:
                    try:
                        for job in context.job_queue.get_jobs_by_name(f"{prefix}{targ_chat_id}"):
                            job.schedule_removal()
                    except Exception:
                        pass
            try:
                await query.edit_message_text("🛑 <b>Match has been force-ended by an Admin.</b>", parse_mode="HTML", reply_markup=None)
            except Exception:
                pass
        elif action == "no":
            try:
                await query.edit_message_text("✅ Force-end cancelled. The match continues!", reply_markup=None)
            except Exception:
                pass

    elif query.data.startswith("special_"):
        group_id = int(query.data.split("_")[1])
        game     = context.bot_data.get(group_id)
        if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != "BOWLER":
            return
        if game.get("mode") == "SOLO":
            bowler = game["players"][game["bowler_idx"]]
            batter = game["players"][game["batter_idx"]]
        else:
            bowler = game.get("current_bowler")
            batter = game.get("striker")

        if bowler is None or batter is None:
            return
        if update.effective_user.id != bowler["id"] or game.get("special_used_this_over"):
            return
        if "active_bowlers" in context.bot_data and update.effective_user.id in context.bot_data["active_bowlers"]:
            del context.bot_data["active_bowlers"][update.effective_user.id]

        game["special_used_this_over"] = True
        clear_afk_timer(context, group_id)
        roll = random.randint(1, 100)

        if roll <= 60:
            try:
                await query.edit_message_text(
                    "Oops! Missed yorker and gave a <b>WIDE</b> ball! 1 extra run. You must bowl again.",
                    parse_mode="HTML", reply_markup=None,
                )
            except Exception:
                pass
            batter["runs"] = batter.get("runs", 0) + 1
            bowler["conceded"] = bowler.get("conceded", 0) + 1
            if game.get("mode") == "TEAM":
                game["batting_team_ref"]["score"] += 1
            await context.bot.send_message(group_id, "🚨 <b>WIDE BALL!</b> 1 extra run. Bowler must re-bowl! 🥎", parse_mode="HTML")
            await trigger_bowl(context, group_id)

        elif roll <= 80:
            try:
                await query.edit_message_text(
                    "Oops! Missed yorker and gave a <b>NO BALL!</b>\nKoi na kismat ki baat hai!",
                    parse_mode="HTML", reply_markup=None,
                )
            except Exception:
                pass
            game["current_bowl"] = "NO_BALL"
            game["waiting_for"]  = "BATTER"
            hit_opts = "1-6" if game.get("mode") == "SOLO" else "0-6"
            await send_media_safely(
                context, group_id, MEDIA["batter_turn"],
                f"🚨 Ball delivered!! 🥎💨\n👉 <a href='tg://user?id={batter['id']}'>{batter['name']}</a>, type {hit_opts} to hit! 🏏👇",
            )
            set_afk_timer(context, group_id, batter["id"], "BATTER")

        else:
            msg = "🎯 <b>Yorker pel diya bhai 😶‍🌫️</b> Let's see how the batter reacts...\n⚠️ If the batter chooses "
            msg += "0-3, they survive. " if game.get("mode") == "TEAM" else "1-3, they survive. "
            msg += "Otherwise, they are OUT! ☝️"
            try:
                await query.edit_message_text(msg, parse_mode="HTML", reply_markup=None)
            except Exception:
                pass
            game["current_bowl"] = "YORKER"
            game["waiting_for"]  = "BATTER"
            hit_opts = "1-6" if game.get("mode") == "SOLO" else "0-6"
            await send_media_safely(
                context, group_id, MEDIA["batter_turn"],
                f"🚨 Ball bowled! 🥎💨\n👉 <a href='tg://user?id={batter['id']}'>{batter['name']}</a>, type {hit_opts} to hit! 🏏👇",
            )
            set_afk_timer(context, group_id, batter["id"], "BATTER")

    elif query.data.startswith("help_"):
        topic   = query.data[5:]
        back_kb = [[InlineKeyboardButton("🔙 Back to Help", callback_data="help_main")]]

        if topic == "main":
            kb = [
                [InlineKeyboardButton("🏏 Solo Game Guide",  callback_data="help_solo")],
                [InlineKeyboardButton("👥 Team Game Guide",  callback_data="help_team")],
                [InlineKeyboardButton("🎯 Yorker Rules",     callback_data="help_yorker")],
                [InlineKeyboardButton("⏳ AFK Penalties",    callback_data="help_afk")],
                [InlineKeyboardButton("📊 Commands List",    callback_data="help_commands")],
                [InlineKeyboardButton("⭐ Level System",     callback_data="help_levels")],
            ]
            try:
                await query.edit_message_text(
                    "🏏 <b>ELITE CRICKET BOT — HELP CENTER</b> 🏆\n\n"
                    "Welcome! Select a topic below to learn everything about the bot:",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        elif topic == "solo":
            text = (
                "🏏 <b>SOLO GAME — HOW TO PLAY</b>\n\n"
                "1️⃣ Type <code>/start</code> in a group.\n"
                "2️⃣ Select <b>Solo Game 🏏</b> and choose spell (3 or 6 balls per turn).\n"
                "3️⃣ Players type <code>/join</code> to enter the queue.\n"
                "4️⃣ Admin types <code>/startsolo</code> or wait 70 seconds to auto-start.\n\n"
                "🎮 <b>Gameplay:</b>\n"
                "• Bowler receives a DM from the bot — type 1-6 to bowl secretly.\n"
                "• Batter types 1-6 in the group chat to hit.\n"
                "• <b>Same number = OUT! ☝️</b>\n"
                "• <b>Different number = Runs scored! 🏃‍♂️</b>\n\n"
                "🔁 Players rotate batting in queue order.\n"
                "📊 Use <code>/soloscore</code> to check live scorecard.\n"
                "🏆 Highest score earns the most EXP!"
            )
            try:
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_kb), parse_mode="HTML")
            except Exception:
                pass

        elif topic == "team":
            text = (
                "👥 <b>TEAM GAME — FULL GUIDE</b>\n\n"
                "1️⃣ Type <code>/start</code> → Select <b>Team Game 👥</b>.\n"
                "2️⃣ Someone clicks <b>HOST BANUNGA 👿</b> to become Game Host.\n"
                "3️⃣ Host types <code>/create_team</code> — team registration opens.\n"
                "4️⃣ Players click <b>Join Team A 🔴</b> or <b>Join Team B 🔵</b>.\n"
                "   (Min. 2 players per team required!)\n"
                "5️⃣ Each team selects a <b>Captain 👑</b> via button.\n"
                "6️⃣ Toss — winning captain calls Heads/Tails.\n"
                "7️⃣ Host picks number of overs (3 to 25).\n"
                "8️⃣ Host can activate <code>/spamfree</code> mode (15s window).\n\n"
                "🎮 <b>During Match:</b>\n"
                "• Batting Captain → <code>/batting [num]</code> to send batter out.\n"
                "• Bowling Captain → <code>/bowling [num]</code> to select bowler.\n"
                "• Bowler types 1-6 via DM | Batter types 0-6 in group.\n"
                "• Odd runs (1, 3, 5) → Strike rotates automatically! 🔄\n"
                "• End of overs → Innings break → Chasing team bats!\n\n"
                "📊 Use <code>/score</code> and <code>/teams</code> for live info.\n"
                "🏆 Team with more runs at the end wins!"
            )
            try:
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_kb), parse_mode="HTML")
            except Exception:
                pass

        elif topic == "yorker":
            text = (
                "🎯 <b>YORKER RULES</b>\n\n"
                "When it's your turn to bowl, click <b>🎯 Try for yorker</b> in the DM.\n"
                "⚠️ Can only be used <b>once per over</b>!\n\n"
                "🎲 <b>3 Possible Outcomes (random):</b>\n\n"
                "❌ <b>60% chance — WIDE BALL!</b>\n"
                "   Bowler missed. 1 extra run given. Must re-bowl that delivery.\n\n"
                "🚨 <b>20% chance — NO BALL!</b>\n"
                "   Batter hits freely. <b>Next ball is a FREE HIT 🚀</b>\n"
                "   (Batter cannot be out on a free hit!)\n\n"
                "🎯 <b>20% chance — YORKER ACTIVATED!</b>\n"
                "   Batter must pick a number to respond:\n"
                "   • <b>Solo Mode:</b> Type 1, 2, or 3 to survive | 4-6 = <b>OUT ☝️</b>\n"
                "   • <b>Team Mode:</b> Type 0, 1, 2, or 3 to survive | 4-6 = <b>OUT ☝️</b>\n\n"
                "💡 <i>Strategic tip: Use yorker when batter is on a high score!</i>"
            )
            try:
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_kb), parse_mode="HTML")
            except Exception:
                pass

        elif topic == "afk":
            text = (
                "⏳ <b>AFK PENALTIES</b>\n\n"
                "If you don't take your turn in time, here's what happens:\n\n"
                "⚠️ <b>10 seconds</b> — Warning #1: 50 seconds left to play!\n"
                "⚠️ <b>30 seconds</b> — Warning #2: 30 seconds left!\n"
                "❌ <b>60 seconds</b> — TIMEOUT! Penalty applied.\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🏏 <b>Solo Mode — AFK Player:</b>\n"
                "   Player is <b>eliminated</b> from the match.\n"
                "   If fewer than 2 players remain → match abandoned.\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "👥 <b>Team Mode — AFK Batter:</b>\n"
                "   Batter is given OUT. Team score <b>-5 runs</b>. 📉\n"
                "   Captain/Host must select the next batter.\n\n"
                "👥 <b>Team Mode — AFK Bowler:</b>\n"
                "   Batting team gets <b>+5 free runs</b>. 📈\n"
                "   Captain/Host must select a new bowler.\n\n"
                "💡 <i>Always stay active when it's your turn!</i>"
            )
            try:
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_kb), parse_mode="HTML")
            except Exception:
                pass

        elif topic == "commands":
            text = (
                "📊 <b>USEFUL COMMANDS LIST</b>\n\n"
                "🏏 <b>Solo Game:</b>\n"
                "<code>/start</code> — Start a new match\n"
                "<code>/join</code> — Join the solo queue\n"
                "<code>/leavesolo</code> — Leave the solo queue\n"
                "<code>/startsolo</code> — Force start match (Admin)\n"
                "<code>/soloscore</code> — View solo scorecard\n\n"
                "👥 <b>Team Game:</b>\n"
                "<code>/create_team</code> — Open registration (Host)\n"
                "<code>/batting [num]</code> — Select batter (Captain/Host)\n"
                "<code>/bowling [num]</code> — Select bowler (Captain/Host)\n"
                "<code>/teams</code> — View team rosters\n"
                "<code>/score</code> — View team scorecard\n"
                "<code>/spamfree</code> — Enable spam-free mode (Host)\n\n"
                "⚙️ <b>Management:</b>\n"
                "<code>/add a/b</code> — Add player to team (Host)\n"
                "<code>/remove</code> — Remove player from team (Host)\n"
                "<code>/changehost</code> — Transfer host role\n"
                "<code>/changecap a/b</code> — Change team captain (Host)\n"
                "<code>/changeover [n]</code> — Change total overs (1st innings only)\n"
                "<code>/rejoin</code> — Extend join timer by 30s (Host)\n"
                "<code>/endmatch</code> — Force end match (Admin)\n\n"
                "📈 <b>Stats &amp; Info:</b>\n"
                "<code>/userstats</code> — View your career stats\n"
                "<code>/leaderboard</code> — Weekly &amp; lifetime rankings\n"
                "<code>/help</code> — Open this help menu"
            )
            try:
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_kb), parse_mode="HTML")
            except Exception:
                pass

        elif topic == "levels":
            text = (
                "⭐ <b>LEVEL SYSTEM</b>\n\n"
                "Earn EXP by playing and performing well.\n"
                "Your level is shown in <code>/userstats</code>!\n\n"
                "🔰 <b>Newbie</b> — 0 to 999 EXP\n"
                "   Just getting started. Keep playing!\n\n"
                "⚡ <b>Pro</b> — 1,000 to 5,000 EXP\n"
                "   You're getting serious now!\n\n"
                "🌟 <b>Legendary</b> — 5,001 to 8,000 EXP\n"
                "   An elite performer feared by all!\n\n"
                "👑 <b>Unbeaten</b> — 8,001+ EXP\n"
                "   The pinnacle. Absolute royalty! 🏆\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "💰 <b>How to Earn EXP:</b>\n"
                "🏆 Win a solo match → <b>+60 EXP</b>\n"
                "🏆 Win a team match → <b>+40 EXP</b> per winner\n"
                "💯 Score a century (100+) → <b>+150 EXP</b>\n"
                "🏅 Score a half-century (50-99) → <b>+50 EXP</b>\n"
                "☝️ Take a wicket → <b>+20 EXP</b>\n"
                "🎩 Hat-trick (3 wickets in a row!) → <b>+1000 EXP</b>\n"
                "🌟 Player of the Match award → <b>Bonus EXP!</b>"
            )
            try:
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_kb), parse_mode="HTML")
            except Exception:
                pass

    elif query.data == "dm_stats":
        await userstats_command(update, context)

    elif query.data == "play_again":
        await start_command(update, context)

    elif query.data in ["lb_weekly", "lb_lifetime"]:
        if users_col is None:
            try:
                await query.edit_message_text("❌ Database not connected.")
            except Exception:
                pass
            return
        is_weekly  = query.data == "lb_weekly"
        run_field  = "weekly_runs"    if is_weekly else "total_runs"
        wkt_field  = "weekly_wickets" if is_weekly else "wickets"
        bf_field   = "weekly_balls_faced"  if is_weekly else "balls_faced"
        rc_field   = "weekly_conceded"     if is_weekly else "runs_conceded"
        bb_field   = "weekly_balls_bowled" if is_weekly else "balls_bowled"

        pipeline_bat = [
            {"$match": {run_field: {"$gt": 0}}},
            {"$addFields": {"sr": {"$cond": [
                {"$gt": [f"${bf_field}", 0]},
                {"$multiply": [{"$divide": [f"${run_field}", f"${bf_field}"]}, 100]},
                0,
            ]}}},
            {"$sort": {run_field: -1, "sr": -1}},
            {"$limit": 5},
        ]
        top_batters = await users_col.aggregate(pipeline_bat).to_list(5)

        pipeline_bowl = [
            {"$match": {wkt_field: {"$gt": 0}}},
            {"$addFields": {"eco": {"$cond": [
                {"$gt": [f"${bb_field}", 0]},
                {"$multiply": [{"$divide": [f"${rc_field}", f"${bb_field}"]}, 6]},
                999,
            ]}}},
            {"$sort": {wkt_field: -1, "eco": 1}},
            {"$limit": 5},
        ]
        top_bowlers = await users_col.aggregate(pipeline_bowl).to_list(5)

        if is_weekly and not top_batters and not top_bowlers:
            try:
                await query.edit_message_text("⏳ <b>Still fetching data...</b> Play some matches to get on the board!", parse_mode="HTML")
            except Exception:
                pass
            return

        text  = f"🏆 <b>{'WEEKLY' if is_weekly else 'LIFETIME'} LEADERBOARD</b> 🏆\n\n"
        text += "🏏 <b>TOP 5 BATTERS</b>\n"
        for i, b in enumerate(top_batters, 1):
            lvl   = get_user_level(b.get("exp", 0))
            text += f"{i}. {b.get('first_name', 'Unknown')} [{lvl}] - <b>{b.get(run_field, 0)} Runs</b> (SR: {b.get('sr', 0):.1f})\n"

        text += "\n🥎 <b>TOP 5 BOWLERS</b>\n"
        for i, b in enumerate(top_bowlers, 1):
            lvl   = get_user_level(b.get("exp", 0))
            text += f"{i}. {b.get('first_name', 'Unknown')} [{lvl}] - <b>{b.get(wkt_field, 0)} Wkts</b> (Eco: {b.get('eco', 0):.2f})\n"

        kb = [[InlineKeyboardButton("Back 🔙", callback_data="lb_back")]]
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
        except Exception:
            pass

    elif query.data == "lb_back":
        kb = [
            [InlineKeyboardButton("WEEKLY LEADERBOARD 📅",  callback_data="lb_weekly")],
            [InlineKeyboardButton("LIFETIME LEADERBOARD 🏆", callback_data="lb_lifetime")],
        ]
        try:
            await query.edit_message_text(
                "📊 <b>View our top performers!</b>\nSelect a leaderboard below:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="HTML",
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Text input handler (bowl via DM / bat in group)
# ---------------------------------------------------------------------------

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    if not user_input or not user_input.strip().lstrip("-").isdigit():
        return
    if not user_input.strip().isdigit():
        return
    val       = int(user_input.strip())
    chat_type = update.message.chat.type

    # ── Private DM — BOWLER input ─────────────────────────────────────────
    if chat_type == "private":
        user_id  = update.effective_user.id
        group_id = context.bot_data.get("active_bowlers", {}).get(user_id)
        if not group_id:
            return
        game = context.bot_data.get(group_id)
        if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != "BOWLER":
            return

        if game.get("mode") == "SOLO":
            bowler = game["players"][game["bowler_idx"]]
            batter = game["players"][game["batter_idx"]]
        else:
            bowler = game.get("current_bowler")
            batter = game.get("striker")

        if bowler is None or batter is None:
            return
        if user_id != bowler["id"]:
            return
        if val < 1 or val > 6:
            await update.message.reply_text("❌ Bowlers can only bowl numbers from 1 to 6!")
            return

        # Spam-free check
        if game.get("mode") == "TEAM" and game.get("spamfree"):
            last_balls = bowler.get("last_balls", [])
            if len(last_balls) >= 2 and last_balls[-1] == val and last_balls[-2] == val:
                await update.message.reply_text(
                    "⚠️ <b>SPAM FREE MODE ACTIVE:</b> You cannot bowl the same delivery more than 2 times in a row! "
                    "Choose a different delivery.",
                    parse_mode="HTML",
                )
                return
            bowler["last_balls"] = (last_balls + [val])[-2:]

        clear_afk_timer(context, group_id)
        game["current_bowl"] = val
        game["waiting_for"]  = "BATTER"
        if user_id in context.bot_data.get("active_bowlers", {}):
            del context.bot_data["active_bowlers"][user_id]

        # Build back-to-game link
        chat_url = None
        try:
            chat = await context.bot.get_chat(group_id)
            if chat.username:
                chat_url = f"https://t.me/{chat.username}"
            elif chat.invite_link:
                chat_url = chat.invite_link
            else:
                try:
                    chat_url = await chat.export_invite_link()
                except Exception:
                    pass
        except Exception:
            pass

        kb       = [[InlineKeyboardButton("Back to Game 🔙", url=chat_url)]] if chat_url else []
        hit_opts = "1-6" if game.get("mode") == "SOLO" else "0-6"
        await update.message.reply_text(
            f"Choice locked! 🔒 You bowled a <b>{val}</b>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb) if kb else None,
        )
        await send_media_safely(
            context, group_id, MEDIA["batter_turn"],
            f"🚨 Ball bowled! 🥎💨\n👉 <a href='tg://user?id={batter['id']}'>{batter['name']}</a>, type {hit_opts} to hit! 🏏👇",
        )
        set_afk_timer(context, group_id, batter["id"], "BATTER")
        return

    # ── Group chat — BATTER input ─────────────────────────────────────────
    chat_id = update.effective_chat.id
    game    = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != "BATTER":
        return

    if game.get("mode") == "SOLO":
        if val < 1 or val > 6:
            return
        batter = game["players"][game["batter_idx"]]
        bowler = game["players"][game["bowler_idx"]]
    else:
        if val < 0 or val > 6:
            return
        batter = game.get("striker")
        bowler = game.get("current_bowler")

    if batter is None or bowler is None:
        return
    if update.effective_user.id != batter["id"]:
        return

    hit_val = val
    game["waiting_for"] = "PROCESSING_BATTER"
    clear_afk_timer(context, chat_id)

    if hit_val == 4:
        batter["match_4s"] = batter.get("match_4s", 0) + 1
    elif hit_val == 6:
        batter["match_6s"] = batter.get("match_6s", 0) + 1

    bowl_val         = game["current_bowl"]
    is_free_hit      = game.get("is_free_hit", False)
    is_legal_delivery = True

    # ── NO BALL ───────────────────────────────────────────────────────────
    if bowl_val == "NO_BALL":
        is_legal_delivery = False
        bowler["consecutive_wickets"] = 0
        batter["balls_faced"] = batter.get("balls_faced", 0) + 1
        game["is_free_hit"]   = True
        old_runs = batter.get("runs", 0)
        batter["runs"]    = old_runs + hit_val + 1
        bowler["conceded"] = bowler.get("conceded", 0) + hit_val + 1
        if game.get("mode") == "TEAM":
            game["batting_team_ref"]["score"] += hit_val + 1

        result_text = (
            f"🚨 <b>IT WAS A NO BALL!</b> 1 penalty run.\n"
            f"🚀 <b>NEXT BALL WILL BE A FREE HIT!</b> 🚀\n\n"
            f"🏏 Batter hit: <b>{hit_val}</b>\n\n"
        )
        if hit_val == 0:
            result_text += f"🛡️ <b>Solid defense! Dot ball.</b> ({batter['name']}: {batter['runs']} off {batter['balls_faced']})"
        else:
            result_text += f"🏃‍♂️ <b>Great shot! {hit_val} runs!</b> 🔥 ({batter['name']}: {batter['runs']} off {batter['balls_faced']})"

        await send_media_safely(context, chat_id, MEDIA.get(hit_val, MEDIA[0]), result_text, reply_to_message_id=update.message.message_id)

        if old_runs < 100 and batter["runs"] >= 100:
            await update_user_db(batter["id"], {"exp": 150})
            await send_media_safely(context, chat_id, MEDIA["100"], f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> has smashed a glorious century!")
        elif old_runs < 50 and batter["runs"] >= 50:
            await update_user_db(batter["id"], {"exp": 50})
            await send_media_safely(context, chat_id, MEDIA["50"], f"🏏 <b>HALF-CENTURY! BRILLIANT INNINGS!</b> 💥🙌\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> reaches 50!")

        if game.get("mode") == "TEAM" and hit_val % 2 != 0:
            swap_strike(game)
            await context.bot.send_message(
                chat_id,
                f"🔄 Strike rotated! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!",
                parse_mode="HTML",
            )
        if game.get("mode") == "TEAM" and game.get("innings") == 2 and game["batting_team_ref"]["score"] >= game.get("target", 0):
            await process_team_innings_end(context, chat_id, game)
            return

    # ── YORKER ────────────────────────────────────────────────────────────
    elif bowl_val == "YORKER":
        batter["balls_faced"] = batter.get("balls_faced", 0) + 1
        bowler["balls_bowled"] = bowler.get("balls_bowled", 0) + 1
        if game.get("mode") == "SOLO":
            game["balls_bowled"] += 1
        if game.get("mode") == "TEAM":
            game["bowling_team_ref"]["balls_bowled"] += 1

        survives = hit_val in ([0, 1, 2, 3] if game.get("mode") == "TEAM" else [1, 2, 3])

        if not survives:
            if is_free_hit:
                game["is_free_hit"] = False
                bowler["consecutive_wickets"] = 0
                result_text = (
                    f"🥎 Bowler delivery: <b>YORKER</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                    f"💥 <b>BOWLED! BUT IT'S A FREE HIT!</b> 😅\n"
                    f"<a href='tg://user?id={batter['id']}'>{batter['name']}</a> survives and scores 0 runs!"
                )
                await send_media_safely(context, chat_id, MEDIA["batter_turn"], result_text, reply_to_message_id=update.message.message_id)
            else:
                bowler["wickets"] = bowler.get("wickets", 0) + 1
                await update_user_db(bowler["id"], {"exp": 20})
                result_text = (
                    f"🥎 Bowler delivery: <b>YORKER</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                    f"💥 <b>HOWZAT! OUT!</b> ☝️ {batter['name']} is bowled by a lethal yorker for {batter.get('runs', 0)}! 😔🚶‍♂️"
                )
                await send_media_safely(context, chat_id, MEDIA["yorker"], result_text, reply_to_message_id=update.message.message_id)
                if batter.get("runs", 0) == 0:
                    await send_media_safely(context, chat_id, MEDIA["duck"], f"🦆 <a href='tg://user?id={batter['id']}'>{batter['name']}</a> got a duck 🦆")

                bowler["consecutive_wickets"] = bowler.get("consecutive_wickets", 0) + 1
                if bowler["consecutive_wickets"] == 3:
                    bowler["consecutive_wickets"] = 0
                    await update_user_db(bowler["id"], {"hat_tricks": 1, "exp": 1000})
                    ht_vid = "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777819065/VID_20260503200210_rabpvn.mp4"
                    await send_media_safely(context, chat_id, ht_vid, f"🎩 <b>HAT-TRICK!</b> <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, you are a magician!! 🪄🔥")

                dismiss_batter(game, batter)
                if game.get("mode") == "TEAM":
                    game["batting_team_ref"]["wickets"] += 1
                    if game["batting_team_ref"]["wickets"] >= len(game["batting_team_ref"]["players"]) - 1:
                        await process_team_innings_end(context, chat_id, game)
                        return
                    game["waiting_for"] = "TEAM_BATTER_SELECT"
                    await context.bot.send_message(
                        chat_id,
                        "🏏 Captain/Host, type <code>/batting</code> to see batters list or <code>/batting [number]</code> to select the next batter.",
                        parse_mode="HTML",
                    )
                else:
                    game["batter_idx"] += 1
                    if game["batter_idx"] >= len(game["players"]):
                        await check_solo_winner_exp(game)
                        await commit_player_stats(game)
                        game["state"] = "NOT_PLAYING"
                        await trigger_full_scorecard_message(context, chat_id, game)
                        return
                    if game["batter_idx"] == game["bowler_idx"]:
                        game["bowler_idx"] = (game["bowler_idx"] + 1) % len(game["players"])
                        game["balls_bowled"] = 0
                        game["special_used_this_over"] = False
        else:
            bowler["consecutive_wickets"] = 0
            if is_free_hit:
                game["is_free_hit"] = False
            old_runs = batter.get("runs", 0)
            batter["runs"]    = old_runs + hit_val
            bowler["conceded"] = bowler.get("conceded", 0) + hit_val
            if game.get("mode") == "TEAM":
                game["batting_team_ref"]["score"] += hit_val

            result_text = (
                f"🥎 Bowler delivery: <b>YORKER</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                f"🏃‍♂️ <b>Great shot! Dug out the yorker for {hit_val} runs!</b> 🔥 "
                f"({batter['name']}: {batter['runs']} off {batter['balls_faced']})"
            )
            await send_media_safely(context, chat_id, MEDIA.get(hit_val, MEDIA[0]), result_text, reply_to_message_id=update.message.message_id)

            if old_runs < 100 and batter["runs"] >= 100:
                await update_user_db(batter["id"], {"exp": 150})
                await send_media_safely(context, chat_id, MEDIA["100"], f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> has smashed a glorious century!")
            elif old_runs < 50 and batter["runs"] >= 50:
                await update_user_db(batter["id"], {"exp": 50})
                await send_media_safely(context, chat_id, MEDIA["50"], f"🏏 <b>HALF-CENTURY! BRILLIANT INNINGS!</b> 💥🙌\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> reaches 50!")

            if game.get("mode") == "TEAM":
                if game.get("innings") == 2 and game["batting_team_ref"]["score"] >= game.get("target", 0):
                    await process_team_innings_end(context, chat_id, game)
                    return
                if hit_val % 2 != 0:
                    swap_strike(game)
                    await context.bot.send_message(
                        chat_id,
                        f"🔄 Strike rotated! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!",
                        parse_mode="HTML",
                    )

    # ── Normal delivery — SAME NUMBER = OUT ───────────────────────────────
    elif str(hit_val) == str(bowl_val):
        batter["balls_faced"] = batter.get("balls_faced", 0) + 1
        bowler["balls_bowled"] = bowler.get("balls_bowled", 0) + 1
        if game.get("mode") == "SOLO":
            game["balls_bowled"] += 1
        if game.get("mode") == "TEAM":
            game["bowling_team_ref"]["balls_bowled"] += 1

        if is_free_hit:
            game["is_free_hit"] = False
            bowler["consecutive_wickets"] = 0
            result_text = (
                f"🥎 Bowler delivery: <b>{bowl_val}</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                f"💥 <b>BOWLED! BUT IT'S A FREE HIT!</b> 😅\n"
                f"<a href='tg://user?id={batter['id']}'>{batter['name']}</a> survives and scores 0 runs!"
            )
            await send_media_safely(context, chat_id, MEDIA["batter_turn"], result_text, reply_to_message_id=update.message.message_id)
        else:
            bowler["wickets"] = bowler.get("wickets", 0) + 1
            await update_user_db(bowler["id"], {"exp": 20})
            result_text = (
                f"🥎 Bowler delivery: <b>{bowl_val}</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                f"💥 <b>HOWZAT! OUT!</b> ☝️ {batter['name']} is dismissed for {batter.get('runs', 0)}! 😔🤸🏻\n"
                f"{batter['name']} KOI NA HOTA HAI !!"
            )
            await send_media_safely(context, chat_id, MEDIA["out"], result_text, reply_to_message_id=update.message.message_id)
            if batter.get("runs", 0) == 0:
                await send_media_safely(context, chat_id, MEDIA["duck"], f"🦆 <a href='tg://user?id={batter['id']}'>{batter['name']}</a> got a duck 🦆")

            bowler["consecutive_wickets"] = bowler.get("consecutive_wickets", 0) + 1
            if bowler["consecutive_wickets"] == 3:
                bowler["consecutive_wickets"] = 0
                await update_user_db(bowler["id"], {"hat_tricks": 1, "exp": 1000})
                ht_vid = "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777819065/VID_20260503200210_rabpvn.mp4"
                await send_media_safely(context, chat_id, ht_vid, f"🎩 <b>HAT-TRICK!</b> <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, you are a magician!! 🪄🔥")

            dismiss_batter(game, batter)
            if game.get("mode") == "TEAM":
                game["batting_team_ref"]["wickets"] += 1
                if game["batting_team_ref"]["wickets"] >= len(game["batting_team_ref"]["players"]) - 1:
                    await process_team_innings_end(context, chat_id, game)
                    return
                game["waiting_for"] = "TEAM_BATTER_SELECT"
                await context.bot.send_message(
                    chat_id,
                    "🏏 Captain/Host, type <code>/batting</code> to see batters list or <code>/batting [number]</code> to select the next batter.",
                    parse_mode="HTML",
                )
            else:
                game["batter_idx"] += 1
                if game["batter_idx"] >= len(game["players"]):
                    await check_solo_winner_exp(game)
                    await commit_player_stats(game)
                    game["state"] = "NOT_PLAYING"
                    await trigger_full_scorecard_message(context, chat_id, game)
                    return
                if game["batter_idx"] == game["bowler_idx"]:
                    game["bowler_idx"] = (game["bowler_idx"] + 1) % len(game["players"])
                    game["balls_bowled"] = 0
                    game["special_used_this_over"] = False

    # ── Normal delivery — DIFFERENT NUMBER = RUNS ─────────────────────────
    else:
        bowler["consecutive_wickets"] = 0
        batter["balls_faced"]  = batter.get("balls_faced", 0) + 1
        bowler["balls_bowled"] = bowler.get("balls_bowled", 0) + 1
        if game.get("mode") == "SOLO":
            game["balls_bowled"] += 1
        if game.get("mode") == "TEAM":
            game["bowling_team_ref"]["balls_bowled"] += 1
        if is_free_hit:
            game["is_free_hit"] = False

        old_runs = batter.get("runs", 0)
        batter["runs"]    = old_runs + hit_val
        bowler["conceded"] = bowler.get("conceded", 0) + hit_val
        if game.get("mode") == "TEAM":
            game["batting_team_ref"]["score"] += hit_val

        if hit_val == 0:
            result_text = f"🏏 Batter hit: <b>{hit_val}</b>\n\n🛡️ <b>Solid defense! Dot ball.</b> ({batter['name']}: {batter['runs']} off {batter['balls_faced']})"
        else:
            result_text = f"🏏 Batter hit: <b>{hit_val}</b>\n\n🏃‍♂️ <b>Great shot! {hit_val} runs!</b> 🔥 ({batter['name']}: {batter['runs']} off {batter['balls_faced']})"

        await send_media_safely(context, chat_id, MEDIA.get(hit_val, MEDIA[0]), result_text, reply_to_message_id=update.message.message_id)

        if old_runs < 100 and batter["runs"] >= 100:
            await update_user_db(batter["id"], {"exp": 150})
            await send_media_safely(context, chat_id, MEDIA["100"], f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> has smashed a glorious century!")
        elif old_runs < 50 and batter["runs"] >= 50:
            await update_user_db(batter["id"], {"exp": 50})
            await send_media_safely(context, chat_id, MEDIA["50"], f"🏏 <b>HALF-CENTURY! BRILLIANT INNINGS!</b> 💥🙌\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> reaches 50!")

        if game.get("mode") == "TEAM":
            if game.get("innings") == 2 and game["batting_team_ref"]["score"] >= game.get("target", 0):
                await process_team_innings_end(context, chat_id, game)
                return
            if hit_val % 2 != 0:
                swap_strike(game)
                await context.bot.send_message(
                    chat_id,
                    f"🔄 Strike rotated! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!",
                    parse_mode="HTML",
                )

    # ── End-of-over check ─────────────────────────────────────────────────
    is_over_complete = False
    if is_legal_delivery:
        if game.get("mode") == "SOLO" and game.get("balls_bowled", 0) >= game.get("spell", 6):
            is_over_complete = True
        elif game.get("mode") == "TEAM":
            bb = game["bowling_team_ref"]["balls_bowled"]
            if bb > 0 and bb % 6 == 0:
                is_over_complete = True

    if is_over_complete:
        spell_text = f"🔁 <b>Over Completed!</b> 🛑 {bowler['name']} finished.\n"
        if game.get("mode") == "TEAM":
            swap_strike(game)
            game["last_bowler_id"]         = bowler["id"]
            game["special_used_this_over"] = False
            if game["bowling_team_ref"]["balls_bowled"] >= game.get("target_overs", 0) * 6:
                await process_team_innings_end(context, chat_id, game)
                return
            await trigger_full_scorecard_message(context, chat_id, game)
            team = game["batting_team_ref"]
            spell_text += f"\n📊 Score: {team['score']}/{team['wickets']}\n"
            if game.get("striker"):
                spell_text += f"🔄 Strike rotated for new over! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!\n"
            spell_text += "Bowling Captain/Host, select next bowler using <code>/bowling</code> to see list or <code>/bowling [num]</code>."
            await context.bot.send_message(chat_id, spell_text, parse_mode="HTML")
            if game.get("waiting_for") == "TEAM_BATTER_SELECT":
                game["need_new_bowler"] = True
            else:
                game["waiting_for"] = "TEAM_BOWLER_SELECT"
        else:
            await trigger_full_scorecard_message(context, chat_id, game)
            await context.bot.send_message(chat_id, spell_text, parse_mode="HTML")
            game["balls_bowled"]           = 0
            game["special_used_this_over"] = False
            game["bowler_idx"]             = (game["bowler_idx"] + 1) % len(game["players"])
            if game["bowler_idx"] == game["batter_idx"]:
                game["bowler_idx"] = (game["bowler_idx"] + 1) % len(game["players"])
            if game.get("state") == "PLAYING":
                game["waiting_for"] = "BOWLER"
    else:
        if game.get("state") == "PLAYING" and game.get("waiting_for") == "PROCESSING_BATTER":
            game["waiting_for"] = "BOWLER"

    if game.get("state") == "PLAYING" and game.get("waiting_for") == "BOWLER":
        await asyncio.sleep(0.3)
        await trigger_bowl(context, chat_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Starting ELITE CRICKET BOT Server...")
    print(f"Pillow available: {PIL_AVAILABLE}")

    app = Application.builder().token(TOKEN).concurrent_updates(True).build()

    app.add_handler(TypeHandler(Update, global_tracker), group=-1)
    app.add_handler(ChatMemberHandler(track_bot_kicks, ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_handler(CommandHandler("start",       start_command))
    app.add_handler(CommandHandler("join",        join_command))
    app.add_handler(CommandHandler("add",         add_command))
    app.add_handler(CommandHandler("remove",      remove_command))
    app.add_handler(CommandHandler("changehost",  changehost_command))
    app.add_handler(CommandHandler("changecap",   changecap_command))
    app.add_handler(CommandHandler("changeover",  changeover_command))
    app.add_handler(CommandHandler("create_team", create_team_command))
    app.add_handler(CommandHandler("rejoin",      rejoin_command))
    app.add_handler(CommandHandler("leavesolo",   leavesolo_command))
    app.add_handler(CommandHandler("startsolo",   startsolo_command))
    app.add_handler(CommandHandler("endmatch",    endmatch_command))
    app.add_handler(CommandHandler("soloscore",   soloscore_command))
    app.add_handler(CommandHandler("score",       teamscore_command))
    app.add_handler(CommandHandler("teams",       teams_command))
    app.add_handler(CommandHandler("batting",     batting_command))
    app.add_handler(CommandHandler("bowling",     bowling_command))
    app.add_handler(CommandHandler("userstats",   userstats_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("broadcast",   broadcast_command))
    app.add_handler(CommandHandler("botstats",    botstats_command))
    app.add_handler(CommandHandler("botgroups",   botgroups_command))
    app.add_handler(CommandHandler("spamfree",    spamfree_command))
    app.add_handler(CommandHandler("help",        help_command))

    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    if WEBHOOK_URL:
        clean_url = WEBHOOK_URL.rstrip("/")
        print(f"Starting Webhook on Port {PORT}...")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            webhook_url=f"{clean_url}/{TOKEN}",
        )
    else:
        print("WEBHOOK_URL not found. Falling back to Polling...")
        app.run_polling(poll_interval=0.1, timeout=10, drop_pending_updates=True)
