import os
import io
import time
import random
import asyncio
import urllib.request
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
    _mongo_client   = AsyncIOMotorClient(MONGO_URI)
    db              = _mongo_client["cricket_bot_db"]
    users_col       = db["users"]
    chats_col       = db["interacted_chats"]
    tournaments_col = db["tournaments"]
    tourteams_col   = db["tour_teams"]
except Exception as e:
    print(f"MongoDB Connection Error: {e}")
    users_col       = None
    chats_col       = None
    tournaments_col = None
    tourteams_col   = None

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
    "circle_cx": 768,  "circle_cy": 205,  "circle_r": 140,

    # Team A — score text centre, overs text centre
    "team_a_score_cx": 453, "team_a_score_cy": 640,
    "team_a_overs_cx": 453, "team_a_overs_cy": 673,

    # Team B — score text centre, overs text centre
    "team_b_score_cx": 1083, "team_b_score_cy": 640,
    "team_b_overs_cx": 1083, "team_b_overs_cy": 673,

    # Bottom bar value rows  (one y for all four)
    "bar_y":          900,
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
    """Return raw bytes of the template PNG (cached after first load)."""
    global _template_cache
    if _template_cache is not None:
        return _template_cache

    # 1. Try local file first
    if os.path.exists(SCOREBOARD_TEMPLATE_PATH):
        try:
            with open(SCOREBOARD_TEMPLATE_PATH, "rb") as f:
                _template_cache = f.read()
            return _template_cache
        except Exception as exc:
            print(f"[scoreboard] Failed to read local template: {exc}")

    # 2. Try remote URL
    try:
        req = urllib.request.Request(
            SCOREBOARD_TEMPLATE_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            _template_cache = resp.read()
        return _template_cache
    except Exception as exc:
        print(f"[scoreboard] Failed to download template: {exc}")

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

    template_bytes = await asyncio.to_thread(_get_template_bytes)
    if template_bytes is None:
        return None

    try:
        img = Image.open(io.BytesIO(template_bytes)).convert("RGBA")
        draw = ImageDraw.Draw(img)

        score_font  = _load_font(58)
        overs_font  = _load_font(36)
        bar_font    = _load_font(34)
        circle_font = _load_font(40)

        team_a = game.get("team_a", {})
        team_b = game.get("team_b", {})

        # ── Circle area: group photo or "LIVE" text ──────────────────────
        group_photo_bytes = await _fetch_group_photo_bytes(context, chat_id)
        if group_photo_bytes:
            try:
                gp = Image.open(io.BytesIO(group_photo_bytes)).convert("RGBA")
                r  = _SB["circle_r"]
                gp = gp.resize((r * 2, r * 2), Image.LANCZOS)

                # Create a circular mask
                mask = Image.new("L", (r * 2, r * 2), 0)
                m_draw = ImageDraw.Draw(mask)
                m_draw.ellipse((0, 0, r * 2, r * 2), fill=255)

                cx = _SB["circle_cx"] - r
                cy = _SB["circle_cy"] - r
                img.paste(gp, (cx, cy), mask)
            except Exception:
                _draw_centered_text(draw, _SB["circle_cx"], _SB["circle_cy"],
                                    "LIVE", circle_font, fill=(255, 215, 0))
        else:
            _draw_centered_text(draw, _SB["circle_cx"], _SB["circle_cy"],
                                "LIVE", circle_font, fill=(255, 215, 0))

        # ── Team A score ──────────────────────────────────────────────────
        a_score   = f"{team_a.get('score', 0)}/{team_a.get('wickets', 0)}"
        a_balls   = team_b.get("balls_bowled", 0)          # Team B bowled → Team A batted
        a_ov, a_bl = divmod(a_balls, 6)
        a_overs   = f"{a_ov}.{a_bl} Ov"

        _draw_centered_text(draw, _SB["team_a_score_cx"], _SB["team_a_score_cy"],
                            a_score, score_font, fill=(255, 255, 255))
        _draw_centered_text(draw, _SB["team_a_overs_cx"], _SB["team_a_overs_cy"],
                            a_overs, overs_font, fill=(200, 220, 255))

        # ── Team B score ──────────────────────────────────────────────────
        b_score   = f"{team_b.get('score', 0)}/{team_b.get('wickets', 0)}"
        b_balls   = team_a.get("balls_bowled", 0)          # Team A bowled → Team B batted
        b_ov, b_bl = divmod(b_balls, 6)
        b_overs   = f"{b_ov}.{b_bl} Ov"

        _draw_centered_text(draw, _SB["team_b_score_cx"], _SB["team_b_score_cy"],
                            b_score, score_font, fill=(255, 255, 255))
        _draw_centered_text(draw, _SB["team_b_overs_cx"], _SB["team_b_overs_cy"],
                            b_overs, overs_font, fill=(200, 220, 255))

        # ── Bottom bar ────────────────────────────────────────────────────
        innings_num = game.get("innings", 1)
        innings_txt = f"{'1st' if innings_num == 1 else '2nd'} Innings"

        # Current Run Rate
        bat_team  = game.get("batting_team_ref", {})
        bowl_team = game.get("bowling_team_ref", {})
        b_bowled  = bowl_team.get("balls_bowled", 0)
        if b_bowled > 0:
            crr = (bat_team.get("score", 0) / b_bowled) * 6
            crr_txt = f"{crr:.2f}"
        else:
            crr_txt = "0.00"

        # Best Bowler across both teams
        all_players = (
            team_a.get("players", []) + team_b.get("players", [])
        )
        best_bowler_txt = "N/A"
        if all_players:
            best_bowler = max(
                (p for p in all_players if p.get("balls_bowled", 0) > 0),
                key=lambda p: p.get("wickets", 0) * 100 - p.get("conceded", 0),
                default=None,
            )
            if best_bowler:
                best_bowler_txt = (
                    f"{best_bowler['name'][:10]}\n"
                    f"{best_bowler['wickets']}W/{best_bowler['conceded']}R"
                )

        # Best Batter across both teams
        best_batter_txt = "N/A"
        if all_players:
            best_batter = max(
                all_players,
                key=lambda p: p.get("runs", 0),
                default=None,
            )
            if best_batter and best_batter.get("runs", 0) > 0:
                best_batter_txt = (
                    f"{best_batter['name'][:10]}\n"
                    f"{best_batter['runs']}({best_batter.get('balls_faced', 0)})"
                )

        bar_y    = _SB["bar_y"]
        bar_gold = (255, 215, 0)

        _draw_centered_text(draw, _SB["innings_cx"], bar_y,
                            innings_txt, bar_font, fill=bar_gold)
        _draw_centered_text(draw, _SB["crr_cx"], bar_y,
                            crr_txt, bar_font, fill=bar_gold)
        _draw_centered_text(draw, _SB["bowler_cx"], bar_y,
                            best_bowler_txt, bar_font, fill=bar_gold)
        _draw_centered_text(draw, _SB["batter_cx"], bar_y,
                            best_batter_txt, bar_font, fill=bar_gold)

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


def get_batting_title(sr: float) -> str:
    if sr >= 300:
        return "⚡ Power Hitter"
    elif sr >= 250:
        return "🏏 Classical Batter"
    elif sr >= 200:
        return "🐢 Tuk-Tuk Player"
    else:
        return "😬 Kalank"


def get_bowling_title(eco: float) -> str:
    if eco < 13:
        return "🌪️ SWING KING"
    elif eco < 16:
        return "🎩 GOOGLY MASTER"
    elif eco < 20:
        return "👍 GOOD BOWLER"
    elif eco < 25:
        return "😐 DECENT BOWLER"
    else:
        return "💩 HAGGU BOWLER"




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


async def update_best_spell(user_id, wickets, runs):
    """Update best bowling spell (6-ball over) if this one is better.
    Better = more wickets; on tie, fewer runs conceded wins.
    """
    if users_col is None:
        return
    user    = await users_col.find_one({"user_id": user_id})
    current = (user or {}).get("best_spell", {"wickets": 0, "runs": 9999})
    cur_w   = current.get("wickets", 0)
    cur_r   = current.get("runs", 9999)
    if wickets > cur_w or (wickets == cur_w and runs < cur_r):
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"best_spell": {"wickets": wickets, "runs": runs}}},
            upsert=True,
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
        runs        = p.get("runs", 0)
        balls_faced = p.get("balls_faced", 0)
        wickets     = p.get("wickets", 0)
        hat_tricks  = p.get("hat_tricks", 0)

        await update_highest_score(p["id"], runs, balls_faced)

        updates = {
            "total_runs": runs,
            "balls_faced": balls_faced,
            "balls_bowled": p.get("balls_bowled", 0),
            "runs_conceded": p.get("conceded", 0),
            "wickets": wickets,
            "total_4s": p.get("match_4s", 0),
            "total_6s": p.get("match_6s", 0),
            "weekly_runs": runs,
            "weekly_balls_faced": balls_faced,
            "weekly_balls_bowled": p.get("balls_bowled", 0),
            "weekly_conceded": p.get("conceded", 0),
            "weekly_wickets": wickets,
        }

        # Batting milestones
        if runs == 0 and p.get("is_out", False):
            updates["ducks"] = 1
        if runs >= 100:
            updates["centuries"] = 1
            updates["exp"] = 150          # Century EXP reward
        elif runs >= 50:
            updates["half_centuries"] = 1
            updates["exp"] = 50           # Half-century EXP reward

        # Bowling milestones EXP
        if wickets > 0:
            updates["exp"] = updates.get("exp", 0) + (wickets * 20)  # +20 EXP per wicket

        # Hat-trick EXP
        if hat_tricks > 0:
            updates["hat_tricks"] = hat_tricks
            updates["exp"] = updates.get("exp", 0) + (hat_tricks * 1000)

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
    """Generate a clean, easy-to-read team scorecard."""
    state = game.get("state", "")

    lines = []
    lines.append("🏆 <b>MATCH SCORECARD</b> 🏆")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ── 2nd-innings chase info ─────────────────────────────────────────────
    if game.get("innings") == 2 and state != "TEAM_FINISHED":
        target      = game.get("target", 0)
        bat_score   = game.get("batting_team_ref", {}).get("score", 0)
        runs_needed = max(0, target - bat_score)
        total_balls = game.get("target_overs", 0) * 6
        balls_used  = game.get("bowling_team_ref", {}).get("balls_bowled", 0)
        balls_rem   = max(0, total_balls - balls_used)
        overs_rem   = balls_rem / 6 if balls_rem > 0 else 0
        rrr         = runs_needed / overs_rem if overs_rem > 0 else 0.0
        overs_rem_fmt = f"{balls_rem // 6}.{balls_rem % 6}"
        lines.append("")
        lines.append(f"🎯 <b>Target:</b> {target}")
        lines.append(
            f"   Need <b>{runs_needed}</b> runs in <b>{overs_rem_fmt}</b> overs"
        )
        lines.append(f"   Required Rate: <b>{rrr:.2f}</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ── Per-team block ─────────────────────────────────────────────────────
    for team_key, label, flag in [
        ("team_a", "TEAM A", "🔴"),
        ("team_b", "TEAM B", "🔵"),
    ]:
        team = game.get(team_key)
        if not team:
            continue

        opp_key      = "team_b" if team_key == "team_a" else "team_a"
        opp_team     = game.get(opp_key, {})
        played_balls = opp_team.get("balls_bowled", 0)
        played_ov, rem_b = divmod(played_balls, 6)
        total_ov_played  = played_ov + (rem_b / 6)
        rr = (team["score"] / total_ov_played) if total_ov_played > 0 else 0.0

        lines.append("")
        lines.append(
            f"{flag} <b>{label}</b>  —  "
            f"<b>{team['score']}/{team['wickets']}</b>  "
            f"({played_ov}.{rem_b} Ov)  RR: {rr:.2f}"
        )
        lines.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")

        # Batters
        bat_rows = []
        for p in team.get("players", []):
            faced = p.get("balls_faced", 0)
            if faced > 0 or p.get("is_striker") or p.get("is_non_striker") or p.get("is_out"):
                runs = p.get("runs", 0)
                sr   = (runs / faced * 100) if faced > 0 else 0.0
                if p.get("is_striker"):
                    status_icon = "🏏"
                elif p.get("is_non_striker"):
                    status_icon = "↔️"
                elif p.get("is_out"):
                    status_icon = "❌"
                else:
                    status_icon = "  "
                bat_rows.append(
                    f"  {status_icon} {p['name'][:13]:<14}"
                    f"<b>{runs}</b>({faced})  SR:{sr:.0f}"
                )

        if bat_rows:
            lines.append("🏏 <i>Batting</i>")
            lines.extend(bat_rows)

        # Bowlers
        bowl_rows = []
        for p in team.get("players", []):
            bb = p.get("balls_bowled", 0)
            if bb > 0:
                p_ov, p_bl = divmod(bb, 6)
                eco        = (p["conceded"] / bb) * 6
                spells     = p.get("spells", [])
                spell_str  = "  <i>(" + "  ".join(spells) + ")</i>" if spells else ""
                bowl_rows.append(
                    f"  🎯 {p['name'][:13]:<14}"
                    f"{p_ov}.{p_bl}Ov  "
                    f"<b>{p.get('wickets',0)}W/{p.get('conceded',0)}R</b>"
                    f"  Eco:{eco:.1f}"
                    f"{spell_str}"
                )

        if bowl_rows:
            lines.append("🥎 <i>Bowling</i>")
            lines.extend(bowl_rows)

    # ── Result ─────────────────────────────────────────────────────────────
    if state == "TEAM_FINISHED":
        team_a_score = game.get("team_a", {}).get("score", 0)
        team_b_score = game.get("team_b", {}).get("score", 0)

        if team_a_score > team_b_score:
            bat_ref = game.get("batting_team_ref", {})
            if bat_ref is game.get("team_a") and game.get("innings") == 2:
                wl = (len(game["team_a"]["players"]) - 1) - game["team_a"]["wickets"]
                result_str = f"🎉 <b>Team A 🔴 WINS by {wl} wickets!</b>"
            else:
                result_str = f"🎉 <b>Team A 🔴 WINS by {team_a_score - team_b_score} runs!</b>"
        elif team_b_score > team_a_score:
            bat_ref = game.get("batting_team_ref", {})
            if bat_ref is game.get("team_b") and game.get("innings") == 2:
                wl = (len(game["team_b"]["players"]) - 1) - game["team_b"]["wickets"]
                result_str = f"🎉 <b>Team B 🔵 WINS by {wl} wickets!</b>"
            else:
                result_str = f"🎉 <b>Team B 🔵 WINS by {team_b_score - team_a_score} runs!</b>"
        else:
            result_str = "🤝 <b>IT'S A TIE!</b> 🤝"

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(result_str)

    return "\n".join(lines)


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
    lines = [
        "🌟 <b>TOP PERFORMERS</b> 🌟",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for team_key, flag, label in [("team_a", "🔴", "TEAM A"), ("team_b", "🔵", "TEAM B")]:
        team = game.get(team_key)
        if not team or not team.get("players"):
            continue

        best_batter = max(team["players"], key=lambda x: x.get("runs", 0))
        best_bowler = max(
            team["players"],
            key=lambda x: x.get("wickets", 0) * 100 - x.get("conceded", 0),
        )

        bb_faced = best_batter.get("balls_faced", 0)
        batter_sr = (best_batter.get("runs", 0) / bb_faced * 100) if bb_faced > 0 else 0.0

        b_ov, b_bl = divmod(best_bowler.get("balls_bowled", 0), 6)
        bb_bowled  = best_bowler.get("balls_bowled", 0)
        bowler_eco = (best_bowler.get("conceded", 0) / bb_bowled * 6) if bb_bowled > 0 else 0.0

        lines.append("")
        lines.append(f"{flag} <b>{label}</b>")
        lines.append(
            f"  🏏 Best Batter:  <b>{best_batter['name']}</b>\n"
            f"       {best_batter.get('runs', 0)} runs off {bb_faced} balls"
            f"  (SR: {batter_sr:.0f})"
        )
        lines.append(
            f"  🥎 Best Bowler:  <b>{best_bowler['name']}</b>\n"
            f"       {best_bowler.get('wickets', 0)}W / {best_bowler.get('conceded', 0)}R"
            f"  in {b_ov}.{b_bl} Ov  (Eco: {bowler_eco:.1f})"
        )

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    await context.bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")


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
    waiting = game.get("waiting_for", "") if game else ""
    role_match = (waiting == role) or (role == "BATTER" and waiting == "PROCESSING_BATTER")
    if not game or game.get("state") != "PLAYING" or not role_match:
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
    waiting = game.get("waiting_for", "") if game else ""
    role_match = (waiting == role) or (role == "BATTER" and waiting == "PROCESSING_BATTER")
    if not game or game.get("state") != "PLAYING" or not role_match:
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
    waiting = game.get("waiting_for", "") if game else ""
    role_match = (waiting == role) or (role == "BATTER" and waiting == "PROCESSING_BATTER")
    if not game or game.get("state") != "PLAYING" or not role_match:
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
    waiting = game.get("waiting_for", "") if game else ""
    role_match = (waiting == role) or (role == "BATTER" and waiting == "PROCESSING_BATTER")
    if not game or game.get("state") != "PLAYING" or not role_match:
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
    waiting = game.get("waiting_for", "") if game else ""
    role_match = (waiting == role) or (role == "BATTER" and waiting == "PROCESSING_BATTER")
    if not game or game.get("state") != "PLAYING" or not role_match:
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
    waiting = game.get("waiting_for", "") if game else ""
    role_match = (waiting == role) or (role == "BATTER" and waiting == "PROCESSING_BATTER")
    if not game or game.get("state") != "PLAYING" or not role_match:
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
    await context.bot.send_message(
        chat_id,
        "⏰ <b>Team joining is now CLOSED!</b> ⏰\n\n"
        "🔒 No more players can join via buttons.\n"
        "👉 Host, if you need to add more players now, use the <code>/add</code> command to add them manually!",
        parse_mode="HTML",
    )
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

    # Track who initiated /start so only that user can pick the game mode
    game["start_initiator_id"] = update.effective_user.id
    # Reset mode-selection lock so a fresh /start always gets a clean lock
    lock_key = f"mode_select_lock_{chat_id}"
    context.bot_data[lock_key] = asyncio.Lock()

    welcome_text = (
        "Welcome to the <b>ELITE CRICKET BOT</b> Arena! 🏆\n"
        "Join our official community at @eclplays. 🏏\n\n"
        "🔥 <b>A tournament is currently going on! Register via @eclregisbot</b> 🔥\n\n"
        "Choose your mode: 👇"
    )
    keyboard = [
        [InlineKeyboardButton("🏏 Solo Game",    callback_data="solo_game"),
         InlineKeyboardButton("👥 Team Game",    callback_data="team_game")],
        [InlineKeyboardButton("🏆 Tournaments",  callback_data="tournaments"),
         InlineKeyboardButton("❌ Cancel",        callback_data="cancel")],
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

    # Block removal of currently active batter/bowler while match is live
    if game.get("state") == "PLAYING":
        active_ids = set()
        if game.get("striker"):
            active_ids.add(game["striker"]["id"])
        if game.get("non_striker"):
            active_ids.add(game["non_striker"]["id"])
        if game.get("current_bowler"):
            active_ids.add(game["current_bowler"]["id"])
        check_id = target_user.id if target_user else None
        if check_id and check_id in active_ids:
            await update.message.reply_text(
                "⚠️ <b>Cannot remove an active player!</b>\n"
                "You cannot remove the current striker, non-striker, or bowler while the match is in progress! ❌",
                parse_mode="HTML",
            )
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
        total_runs    = user_data.get("total_runs", 0)
        balls_faced   = user_data.get("balls_faced", 0)
        sr            = (total_runs / balls_faced * 100) if balls_faced > 0 else 0
        balls_bowled  = user_data.get("balls_bowled", 0)
        runs_conceded = user_data.get("runs_conceded", 0)
        overs         = balls_bowled // 6
        rem_balls     = balls_bowled % 6
        eco           = (runs_conceded / balls_bowled * 6) if balls_bowled > 0 else 0

        exp   = user_data.get("exp", 0)
        level = get_user_level(exp)
        next_level_name, exp_needed = get_next_level_info(exp)

        total_matches = user_data.get("team_matches", 0) + user_data.get("solo_matches", 0)
        avg = (total_runs / total_matches) if total_matches > 0 else 0

        bat_title  = get_batting_title(sr)
        bowl_title = get_bowling_title(eco) if balls_bowled > 0 else "—"

        exp_next = (
            f"Next: <b>{next_level_name}</b>  ({exp_needed} EXP away)"
            if next_level_name else "<b>MAX LEVEL REACHED!</b> 👑"
        )

        bs    = user_data.get("best_spell", {})
        bs_w  = bs.get("wickets", 0)
        bs_r  = bs.get("runs",    0)
        bs_str = f"<b>{bs_w}W / {bs_r}R</b>" if bs else "—"

        D = "┄"
        stats_text = (
            f"╔══════════ 📊 <b>PLAYER STATS</b> ══════════╗\n"
            f"\n"
            f"  👤  <b>{user_data.get('first_name', 'Unknown')}</b>\n"
            f"  🆔  <code>#{user_data.get('user_id', '—')}</code>\n"
            f"  🏅  <b>{level}</b>\n"
            f"\n"
            f"╠{'═'*38}╣\n"
            f"  🏏  <b>BATTING</b>  ·  <i>{bat_title}</i>\n"
            f"  {D*36}\n"
            f"  Highest Score  →  <b>{hs_runs}</b> ({hs_balls} balls)\n"
            f"  Total Runs     →  <b>{total_runs:,}</b>\n"
            f"  Average / SR   →  <b>{avg:.1f}</b>  /  <b>{sr:.1f}</b>\n"
            f"  Sixes / Fours  →  <b>{user_data.get('total_6s', 0)}</b>  /  <b>{user_data.get('total_4s', 0)}</b>\n"
            f"  100s  /  50s   →  <b>{user_data.get('centuries', 0)}</b>  /  <b>{user_data.get('half_centuries', 0)}</b>\n"
            f"  Ducks          →  <b>{user_data.get('ducks', 0)}</b> 🦆\n"
            f"\n"
            f"╠{'═'*38}╣\n"
            f"  🥎  <b>BOWLING</b>  ·  <i>{bowl_title}</i>\n"
            f"  {D*36}\n"
            f"  Wickets        →  <b>{user_data.get('wickets', 0)}</b>\n"
            f"  Hat-Tricks     →  <b>{user_data.get('hat_tricks', 0)}</b>\n"
            f"  Overs / Eco    →  <b>{overs}.{rem_balls}</b>  /  <b>{eco:.2f}</b>\n"
            f"  Best Spell     →  {bs_str}\n"
            f"\n"
            f"╠{'═'*38}╣\n"
            f"  🏆  <b>CAREER</b>\n"
            f"  {D*36}\n"
            f"  Solo Matches   →  <b>{user_data.get('solo_matches', 0)}</b>\n"
            f"  Team Matches   →  <b>{user_data.get('team_matches', 0)}</b>\n"
            f"  MOTM Awards    →  <b>{user_data.get('motm', 0)}</b>\n"
            f"\n"
            f"  ⭐  EXP: <b>{exp:,}</b>  ·  {exp_next}\n"
            f"╚{'═'*38}╝"
        )

        stats_img = "https://res.cloudinary.com/dxgfxfoog/image/upload/v1777818873/file_00000000fa6871fa8d9b30faff9899ae_hbyn9j.png"
        try:
            await msg.reply_photo(photo=stats_img, caption=stats_text, parse_mode="HTML")
        except Exception:
            await msg.reply_text(stats_text, parse_mode="HTML")
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
    loyals_count = await chats_col.count_documents({"type": "private"})
    await update.message.reply_text(
        f"📊 <b>Bot Statistics</b>\n\n"
        f"👤 Total Users Interacted: {users_count}\n"
        f"👥 Total Groups Present: {groups_count}\n"
        f"💌 Bot Loyals (DM Users): {loyals_count}",
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

    # ── Per-user-per-message dedup — prevents any user from getting a
    #    double response by spam-clicking the same button on the same message
    msg_id = query.message.message_id if query.message else 0
    cb_once_key = f"cbonce_{msg_id}_{user_id}_{query.data}"
    if context.bot_data.get(cb_once_key):
        return
    context.bot_data[cb_once_key] = True

    game    = context.bot_data.get(chat_id)
    if game is None:
        game = {"state": "NOT_PLAYING"}
        context.bot_data[chat_id] = game

    # ── Solo game ─────────────────────────────────────────────────────────
    if query.data == "solo_game":
        # Non-initiators are rejected immediately — no lock needed
        if user_id != game.get("start_initiator_id"):
            try:
                await query.answer("⚠️ Only the person who typed /start can choose the game mode!", show_alert=True)
            except Exception:
                pass
            return
        # Lock prevents the initiator from triggering this twice at the same time
        lock_key = f"mode_select_lock_{chat_id}"
        if lock_key not in context.bot_data:
            context.bot_data[lock_key] = asyncio.Lock()
        mode_lock = context.bot_data[lock_key]
        if mode_lock.locked():
            try:
                await query.answer("⚠️ Already processing your selection!", show_alert=True)
            except Exception:
                pass
            return
        async with mode_lock:
            # Re-check state inside the lock to catch any race
            if game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
                try:
                    await query.answer("❌ A match is already active or setting up!", show_alert=True)
                except Exception:
                    pass
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
        # Non-initiators are rejected immediately
        if user_id != game.get("start_initiator_id"):
            try:
                await query.answer("⚠️ Only the person who typed /start can choose the game mode!", show_alert=True)
            except Exception:
                pass
            return
        # Lock prevents the initiator from triggering this twice at the same time
        lock_key = f"mode_select_lock_{chat_id}"
        if lock_key not in context.bot_data:
            context.bot_data[lock_key] = asyncio.Lock()
        mode_lock = context.bot_data[lock_key]
        if mode_lock.locked():
            try:
                await query.answer("⚠️ Already processing your selection!", show_alert=True)
            except Exception:
                pass
            return
        async with mode_lock:
            # Re-check state inside the lock to catch any race
            if game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
                try:
                    await query.answer("❌ A match is already active or setting up!", show_alert=True)
                except Exception:
                    pass
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
        if game.get("state") == "TEAM_SETUP_HOST":
            try:
                await query.answer("❌ A host has already been selected for this match!", show_alert=True)
            except Exception:
                pass
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
        await context.bot.send_message(
            chat_id,
            f"✅ <b>{update.effective_user.first_name}</b> joined <b>Team A 🔴</b>! "
            f"(A: {len(game['team_a']['players'])} | B: {len(game['team_b']['players'])})",
            parse_mode="HTML",
        )

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
        await context.bot.send_message(
            chat_id,
            f"✅ <b>{update.effective_user.first_name}</b> joined <b>Team B 🔵</b>! "
            f"(A: {len(game['team_a']['players'])} | B: {len(game['team_b']['players'])})",
            parse_mode="HTML",
        )

    elif query.data in ["team_cap_a", "team_cap_b"]:
        team_key  = "team_a" if query.data == "team_cap_a" else "team_b"
        team_name = "Team A 🔴" if query.data == "team_cap_a" else "Team B 🔵"
        team      = game.get(team_key, {})
        if not any(p["id"] == user_id for p in team.get("players", [])):
            try:
                await query.answer(f"⚠️ You are not in {team_name}!", show_alert=True)
            except Exception:
                pass
            return
        if team.get("captain"):
            try:
                await query.answer(f"⚠️ {team_name} already has a Captain!", show_alert=True)
            except Exception:
                pass
            return
        team["captain"] = user_id
        cap_name = update.effective_user.first_name
        await context.bot.send_message(
            chat_id,
            f"👑 <b>{cap_name}</b> is the Captain of {team_name}!",
            parse_mode="HTML",
        )
        if game.get("team_a", {}).get("captain") and game.get("team_b", {}).get("captain"):
            await start_toss(context, chat_id, game)

    elif query.data in ["toss_heads", "toss_tails"]:
        toss_caller_id = game.get("toss_caller_id")
        if user_id != toss_caller_id:
            try:
                await query.answer("⚠️ Only the toss caller can choose!", show_alert=True)
            except Exception:
                pass
            return
        result     = random.choice(["heads", "tails"])
        toss_won   = (query.data == result)
        caller_name = update.effective_user.first_name

        if toss_won:
            game["toss_winner_id"] = user_id
            game["toss_winner_name"] = caller_name
            kb = [[
                InlineKeyboardButton("BAT FIRST 🏏", callback_data="toss_bat"),
                InlineKeyboardButton("BOWL FIRST 🥎", callback_data="toss_bowl"),
            ]]
            await context.bot.send_message(
                chat_id,
                f"🪙 The coin lands on <b>{result.upper()}</b>!\n\n"
                f"🎉 <b>{caller_name}</b> wins the toss!\n"
                "Choose your preference:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="HTML",
            )
        else:
            loser_team_key  = "team_a" if any(p["id"] == user_id for p in game.get("team_a", {}).get("players", [])) else "team_b"
            winner_team_key = "team_b" if loser_team_key == "team_a" else "team_a"
            winner_cap_id   = game.get(winner_team_key, {}).get("captain")
            winner_cap      = next((p for p in game.get(winner_team_key, {}).get("players", []) if p["id"] == winner_cap_id), None)
            winner_name     = winner_cap["name"] if winner_cap else "Other team"
            game["toss_winner_id"]   = winner_cap_id
            game["toss_winner_name"] = winner_name
            kb = [[
                InlineKeyboardButton("BAT FIRST 🏏", callback_data="toss_bat"),
                InlineKeyboardButton("BOWL FIRST 🥎", callback_data="toss_bowl"),
            ]]
            await context.bot.send_message(
                chat_id,
                f"🪙 The coin lands on <b>{result.upper()}</b>!\n\n"
                f"😔 <b>{caller_name}</b> loses the toss.\n"
                f"🎉 <b>{winner_name}</b> wins the toss!\n"
                "Choose your preference:",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode="HTML",
            )

    elif query.data in ["toss_bat", "toss_bowl"]:
        toss_winner_id = game.get("toss_winner_id")
        if user_id != toss_winner_id:
            try:
                await query.answer("⚠️ Only the toss winner can choose!", show_alert=True)
            except Exception:
                pass
            return
        winner_in_a = any(p["id"] == user_id for p in game.get("team_a", {}).get("players", []))
        bat_first_key  = "team_a" if (
            (query.data == "toss_bat" and winner_in_a) or
            (query.data == "toss_bowl" and not winner_in_a)
        ) else "team_b"
        bowl_first_key = "team_b" if bat_first_key == "team_a" else "team_a"

        game["batting_team_ref"]  = game[bat_first_key]
        game["bowling_team_ref"]  = game[bowl_first_key]
        game["innings"]           = 1
        game["is_free_hit"]       = False
        game["special_used_this_over"] = False
        game["last_bowler_id"]    = None

        bat_label  = "Team A 🔴" if bat_first_key  == "team_a" else "Team B 🔵"
        bowl_label = "Team A 🔴" if bowl_first_key == "team_a" else "Team B 🔵"

        target_overs_kb = [
            [InlineKeyboardButton("2 Overs", callback_data="overs_2"),
             InlineKeyboardButton("3 Overs", callback_data="overs_3")],
            [InlineKeyboardButton("5 Overs", callback_data="overs_5"),
             InlineKeyboardButton("10 Overs", callback_data="overs_10")],
            [InlineKeyboardButton("20 Overs", callback_data="overs_20")],
        ]
        await context.bot.send_message(
            chat_id,
            f"🏏 <b>{bat_label}</b> will bat first.\n"
            f"🥎 <b>{bowl_label}</b> will bowl first.\n\n"
            f"Host, select the number of overs per side:",
            reply_markup=InlineKeyboardMarkup(target_overs_kb),
            parse_mode="HTML",
        )

    elif query.data.startswith("overs_"):
        if user_id != game.get("host_id"):
            try:
                await query.answer("⚠️ Only the Host can select overs!", show_alert=True)
            except Exception:
                pass
            return
        overs_count = int(query.data.split("_")[1])
        game["target_overs"] = overs_count
        try:
            await query.message.delete()
        except Exception:
            pass

        await context.bot.send_message(
            chat_id,
            f"⚙️ <b>{overs_count} overs per side!</b>\n\n"
            "Do you want to enable SPAM-FREE mode? (Bowlers can't repeat the same delivery twice in a row)\n\n"
            "Host, type <code>/spamfree</code> to enable, OR wait 30 seconds to skip it.",
            parse_mode="HTML",
        )
        game["state"] = "TEAM_SPAMFREE_WAIT"
        context.job_queue.run_once(spamfree_timeout, 30, data={"chat_id": chat_id}, name=f"spamfree_{chat_id}")

    elif query.data == "cancel":
        game["state"] = "NOT_PLAYING"
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(chat_id, "❌ Match setup cancelled.")

    elif query.data.startswith("spell_"):
        spell = int(query.data.split("_")[1])
        if game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
            try:
                await query.answer("❌ A match is already running!", show_alert=True)
            except Exception:
                pass
            return
        if user_id != game.get("start_initiator_id"):
            try:
                await query.answer("⚠️ Only the person who started can choose the spell!", show_alert=True)
            except Exception:
                pass
            return
        context.bot_data[chat_id] = {
            "state": "JOINING", "mode": "SOLO", "players": [],
            "spell": spell, "batter_idx": 0, "bowler_idx": 1,
            "balls_bowled": 0, "special_used_this_over": False, "is_free_hit": False,
            "start_initiator_id": user_id,
        }
        game = context.bot_data[chat_id]
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=SCOREBOARD_IMG,
            caption=(
                f"🏏 <b>SOLO MATCH LOBBY OPEN!</b>\n\n"
                f"Spell: <b>{spell} Balls</b> per bowler per batter.\n\n"
                f"Type /join to enter! You have <b>70 seconds</b>. ⏳"
            ),
            parse_mode="HTML",
        )

    elif query.data.startswith("special_"):
        grp_id = int(query.data.split("_")[1])
        grp_game = context.bot_data.get(grp_id)
        if not grp_game or grp_game.get("state") != "PLAYING":
            return
        if grp_game.get("special_used_this_over"):
            try:
                await query.answer("⚠️ Yorker already used this over!", show_alert=True)
            except Exception:
                pass
            return
        if grp_game.get("mode") == "SOLO":
            bowler = grp_game["players"][grp_game["bowler_idx"]]
        else:
            bowler = grp_game.get("current_bowler")
        if not bowler or user_id != bowler["id"]:
            try:
                await query.answer("⚠️ It's not your turn to bowl!", show_alert=True)
            except Exception:
                pass
            return
        grp_game["special_used_this_over"] = True
        grp_game["yorker_pending"]         = True
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await context.bot.send_message(
            grp_id,
            f"🎯 <b>{bowler['name']}</b> is attempting a YORKER! 🎯\n"
            "Now send your delivery number (1-6) to complete it!",
            parse_mode="HTML",
        )

    elif query.data.startswith("endmatch_yes_"):
        grp_id   = int(query.data.split("_")[2])
        grp_game = context.bot_data.get(grp_id)
        if not grp_game or grp_game.get("state") in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
            try:
                await query.edit_message_text("❌ No active match to end.")
            except Exception:
                pass
            return
        if not await is_admin(update.effective_chat, user_id):
            try:
                await query.answer("❌ Only admins can end the match!", show_alert=True)
            except Exception:
                pass
            return
        clear_afk_timer(context, grp_id)
        grp_game["state"] = "NOT_PLAYING"
        try:
            await query.edit_message_text("✅ Match force-ended by admin.")
        except Exception:
            pass
        await context.bot.send_message(grp_id, "🛑 <b>Match has been force-ended by an admin!</b>", parse_mode="HTML")

    elif query.data.startswith("endmatch_no_"):
        try:
            await query.edit_message_text("✅ Match continues. Cancel dismissed.")
        except Exception:
            pass

    elif query.data == "vote_host":
        vote_target = game.get("host_vote_target")
        vote_name   = game.get("host_vote_name")
        if not vote_target:
            return
        if "host_votes" not in game:
            game["host_votes"] = set()
        if user_id in game["host_votes"]:
            try:
                await query.answer("⚠️ You already voted!", show_alert=True)
            except Exception:
                pass
            return
        all_players = (
            game.get("team_a", {}).get("players", []) +
            game.get("team_b", {}).get("players", [])
        )
        if not any(p["id"] == user_id for p in all_players):
            try:
                await query.answer("⚠️ Only active players can vote!", show_alert=True)
            except Exception:
                pass
            return
        game["host_votes"].add(user_id)
        count = len(game["host_votes"])
        if count >= 4:
            game["host_id"] = vote_target
            game.pop("host_vote_target", None)
            game.pop("host_vote_name",   None)
            game.pop("host_votes",       None)
            try:
                await query.edit_message_text(
                    f"✅ <b>{vote_name}</b> is the new Game Host! (4/4 votes reached)",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            kb = [[InlineKeyboardButton(f"Vote ✅ ({count}/4)", callback_data="vote_host")]]
            try:
                await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
            except Exception:
                pass

    elif query.data == "dm_stats":
        target_user = update.effective_user
        if users_col is None:
            try:
                await context.bot.send_message(chat_id=user_id, text="❌ Database connection error.")
            except Exception:
                pass
            return
        try:
            user_data = await users_col.find_one({"user_id": target_user.id})
            if not user_data:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"❌ Ek bhi match khela hai tune is bot se jo stats dekh raha? {target_user.first_name}.",
                )
                return
            hs_runs  = user_data.get("highest_score", {}).get("runs", 0)
            hs_balls = user_data.get("highest_score", {}).get("balls", 0)
            total_runs    = user_data.get("total_runs", 0)
            balls_faced   = user_data.get("balls_faced", 0)
            sr            = (total_runs / balls_faced * 100) if balls_faced > 0 else 0
            balls_bowled  = user_data.get("balls_bowled", 0)
            runs_conceded = user_data.get("runs_conceded", 0)
            overs         = balls_bowled // 6
            rem_balls     = balls_bowled % 6
            eco           = (runs_conceded / balls_bowled * 6) if balls_bowled > 0 else 0
            exp           = user_data.get("exp", 0)
            level         = get_user_level(exp)
            next_level_name, exp_needed = get_next_level_info(exp)
            total_matches = user_data.get("team_matches", 0) + user_data.get("solo_matches", 0)
            avg = (total_runs / total_matches) if total_matches > 0 else 0
            bat_title  = get_batting_title(sr)
            bowl_title = get_bowling_title(eco) if balls_bowled > 0 else "—"
            exp_next = (
                f"Next: <b>{next_level_name}</b>  ({exp_needed} EXP away)"
                if next_level_name else "<b>MAX LEVEL REACHED!</b> 👑"
            )
            bs    = user_data.get("best_spell", {})
            bs_w  = bs.get("wickets", 0)
            bs_r  = bs.get("runs",    0)
            bs_str = f"<b>{bs_w}W / {bs_r}R</b>" if bs else "—"

            D = "┄"
            stats_text = (
                f"╔══════════ 📊 <b>PLAYER STATS</b> ══════════╗\n"
                f"\n"
                f"  👤  <b>{user_data.get('first_name', 'Unknown')}</b>\n"
                f"  🆔  <code>#{user_data.get('user_id', '—')}</code>\n"
                f"  🏅  <b>{level}</b>\n"
                f"\n"
                f"╠{'═'*38}╣\n"
                f"  🏏  <b>BATTING</b>  ·  <i>{bat_title}</i>\n"
                f"  {D*36}\n"
                f"  Highest Score  →  <b>{hs_runs}</b> ({hs_balls} balls)\n"
                f"  Total Runs     →  <b>{total_runs:,}</b>\n"
                f"  Average / SR   →  <b>{avg:.1f}</b>  /  <b>{sr:.1f}</b>\n"
                f"  Sixes / Fours  →  <b>{user_data.get('total_6s', 0)}</b>  /  <b>{user_data.get('total_4s', 0)}</b>\n"
                f"  100s  /  50s   →  <b>{user_data.get('centuries', 0)}</b>  /  <b>{user_data.get('half_centuries', 0)}</b>\n"
                f"  Ducks          →  <b>{user_data.get('ducks', 0)}</b> 🦆\n"
                f"\n"
                f"╠{'═'*38}╣\n"
                f"  🥎  <b>BOWLING</b>  ·  <i>{bowl_title}</i>\n"
                f"  {D*36}\n"
                f"  Wickets        →  <b>{user_data.get('wickets', 0)}</b>\n"
                f"  Hat-Tricks     →  <b>{user_data.get('hat_tricks', 0)}</b>\n"
                f"  Overs / Eco    →  <b>{overs}.{rem_balls}</b>  /  <b>{eco:.2f}</b>\n"
                f"  Best Spell     →  {bs_str}\n"
                f"\n"
                f"╠{'═'*38}╣\n"
                f"  🏆  <b>CAREER</b>\n"
                f"  {D*36}\n"
                f"  Solo Matches   →  <b>{user_data.get('solo_matches', 0)}</b>\n"
                f"  Team Matches   →  <b>{user_data.get('team_matches', 0)}</b>\n"
                f"  MOTM Awards    →  <b>{user_data.get('motm', 0)}</b>\n"
                f"\n"
                f"  ⭐  EXP: <b>{exp:,}</b>  ·  {exp_next}\n"
                f"╚{'═'*38}╝"
            )
            stats_img = "https://res.cloudinary.com/dxgfxfoog/image/upload/v1777818873/file_00000000fa6871fa8d9b30faff9899ae_hbyn9j.png"
            await context.bot.send_photo(chat_id=user_id, photo=stats_img, caption=stats_text, parse_mode="HTML")
        except Exception as e:
            try:
                await context.bot.send_message(chat_id=user_id, text="❌ An error occurred while fetching stats.")
            except Exception:
                pass

    elif query.data == "play_again":
        # Cannot call start_command directly because update.message is None in a callback context
        play_game = context.bot_data.get(chat_id)
        if play_game is None:
            play_game = {"state": "NOT_PLAYING"}
            context.bot_data[chat_id] = play_game
        if play_game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
            try:
                await query.answer("❌ A match is already active in this group!", show_alert=True)
            except Exception:
                pass
            return
        play_game["start_initiator_id"] = user_id
        # Reset mode-selection lock so buttons work cleanly after play again
        pa_lock_key = f"mode_select_lock_{chat_id}"
        context.bot_data[pa_lock_key] = asyncio.Lock()
        welcome_text = (
            "Welcome to the <b>ELITE CRICKET BOT</b> Arena! 🏆\n"
            "Join our official community at @eclplays. 🏏\n\n"
            "🔥 <b>A tournament is currently going on! Register via @eclregisbot</b> 🔥\n\n"
            "Choose your mode: 👇"
        )
        keyboard = [
            [InlineKeyboardButton("🏏 Solo Game",    callback_data="solo_game"),
             InlineKeyboardButton("👥 Team Game",    callback_data="team_game")],
            [InlineKeyboardButton("🏆 Tournaments",  callback_data="tournaments"),
             InlineKeyboardButton("❌ Cancel",        callback_data="cancel")],
        ]
        await context.bot.send_photo(
            chat_id=chat_id,
            photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777690770/IMG_20260502_082816_001_t0wejv.jpg",
            caption=welcome_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

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

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        text  = f"🏆 <b>{'WEEKLY' if is_weekly else 'LIFETIME'} LEADERBOARD</b> 🏆\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        text += "🏏 <b>TOP BATTERS</b>\n"
        for i, b in enumerate(top_batters):
            lvl   = get_user_level(b.get("exp", 0))
            medal = medals[i] if i < len(medals) else f"{i+1}."
            text += f"{medal} {b.get('first_name', 'Unknown')}  [{lvl}]\n"
            text += f"    <b>{b.get(run_field, 0):,} Runs</b>  ·  SR: {b.get('sr', 0):.1f}\n"

        text += "\n🥎 <b>TOP BOWLERS</b>\n"
        for i, b in enumerate(top_bowlers):
            lvl   = get_user_level(b.get("exp", 0))
            medal = medals[i] if i < len(medals) else f"{i+1}."
            text += f"{medal} {b.get('first_name', 'Unknown')}  [{lvl}]\n"
            text += f"    <b>{b.get(wkt_field, 0)} Wkts</b>  ·  Eco: {b.get('eco', 0):.2f}\n"

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

    elif query.data.startswith("help_"):
        topic   = query.data.split("_", 1)[1]
        back_kb = [[InlineKeyboardButton("Back 🔙", callback_data="help_back")]]

        if topic == "back":
            kb = [
                [InlineKeyboardButton("🏏 Solo Game Guide",   callback_data="help_solo")],
                [InlineKeyboardButton("👥 Team Game Guide",   callback_data="help_team")],
                [InlineKeyboardButton("🎯 Yorker Rules",      callback_data="help_yorker")],
                [InlineKeyboardButton("⏳ AFK Penalties",     callback_data="help_afk")],
                [InlineKeyboardButton("📊 Commands List",     callback_data="help_commands")],
                [InlineKeyboardButton("⭐ Level System",      callback_data="help_levels")],
            ]
            try:
                await query.edit_message_text(
                    "🏏 <b>ELITE CRICKET BOT — HELP CENTER</b> 🏆\n\nWelcome! Select a topic below:",
                    reply_markup=InlineKeyboardMarkup(kb),
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return

        elif topic == "solo":
            text = (
                "🏏 <b>SOLO GAME GUIDE</b>\n\n"
                "A free-for-all cricket battle where every player bats AND bowls!\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📋 <b>How It Works:</b>\n"
                "1. Host types /start → Select <b>Solo Game</b>\n"
                "2. Choose spell (3 or 6 balls per over)\n"
                "3. Players type /join to enter (70s window)\n"
                "4. Players take turns batting against each other\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🥎 <b>Bowling (Private):</b>\n"
                "   Bowler gets a DM — send a number 1-6\n"
                "   Each player bowls one over per batter\n\n"
                "🏏 <b>Batting (In Group):</b>\n"
                "   Batter types a number 1-6 in the group\n"
                "   If your number ≠ bowler's → runs scored!\n"
                "   If your number = bowler's → OUT! 🏏\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🏆 Player with the most runs WINS!"
            )
            try:
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_kb), parse_mode="HTML")
            except Exception:
                pass

        elif topic == "team":
            text = (
                "👥 <b>TEAM GAME GUIDE</b>\n\n"
                "Full T20-style team match with innings, overs, and tactics!\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📋 <b>Setup Steps:</b>\n"
                "1. /start → Team Game → Become Host\n"
                "2. /create_team → Players join Team A or B\n"
                "3. Captains are selected by team members\n"
                "4. Host wins toss → chooses bat/bowl\n"
                "5. Host selects number of overs\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🏏 <b>During the Match:</b>\n"
                "   Captain/Host selects batters with /batting [num]\n"
                "   Captain/Host selects bowlers with /bowling [num]\n"
                "   Bowler DMs delivery (1-6) privately\n"
                "   Batter sends their shot (1-6) in the group\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🏆 Team with the highest score wins!"
            )
            try:
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(back_kb), parse_mode="HTML")
            except Exception:
                pass

        elif topic == "yorker":
            text = (
                "🎯 <b>YORKER RULES</b>\n\n"
                "A special delivery that can dismiss the batter instantly!\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📋 <b>How to Use:</b>\n"
                "   Bowler clicks <b>Try for yorker</b> button in their DM\n"
                "   Then sends any number 1-6 as usual\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "⚡ <b>Outcomes:</b>\n"
                "   ✅ Batter's number ≠ bowler's → Batter scores <b>normally</b>\n"
                "   ❌ Batter's number = bowler's → <b>CLEAN BOWLED!</b> (Always OUT, even on Free Hit)\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "⚠️ <b>Limits:</b>\n"
                "   Only 1 yorker attempt per over allowed.\n"
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

    elif query.data == "tournaments":
        try:
            await query.answer(
                "🏆 Tournaments are under maintenance!\nCheck back soon. 🔧",
                show_alert=True,
            )
        except Exception:
            pass

    elif query.data == "reg_confirm_yes":
        reg_data = context.user_data.get("reg_data")
        if not reg_data:
            try:
                await query.edit_message_text("❌ Registration data lost. Please /register again.")
            except Exception:
                pass
            return
        if tourteams_col is None:
            try:
                await query.edit_message_text("❌ Database not connected.")
            except Exception:
                pass
            return
        team_num = await tourteams_col.count_documents({}) + 1
        reg_data["team_number"] = team_num
        reg_data["registered_by"] = user_id
        await tourteams_col.insert_one(reg_data)
        summary = (
            f"✅ <b>NEW TEAM REGISTERED!</b>\n\n"
            f"🔢 Team No: <b>{team_num}</b>\n"
            f"🏏 Team: <b>{reg_data.get('team_name')}</b>\n"
            f"👑 Captain: {reg_data.get('captain')}\n"
            f"🥈 Vice-Captain: {reg_data.get('vc')}\n"
            f"🌟 Retention 1: {reg_data.get('ret1')}\n"
            f"🌟 Retention 2: {reg_data.get('ret2')}\n"
            f"👤 Registered by: <a href='tg://user?id={user_id}'>{update.effective_user.first_name}</a>"
        )
        for oid in OWNER_IDS:
            try:
                if reg_data.get("logo_file_id"):
                    await context.bot.send_photo(
                        chat_id=oid,
                        photo=reg_data["logo_file_id"],
                        caption=summary,
                        parse_mode="HTML",
                    )
                else:
                    await context.bot.send_message(chat_id=oid, text=summary, parse_mode="HTML")
            except Exception:
                pass
        context.user_data.pop("reg_data", None)
        context.user_data.pop("reg_state", None)
        try:
            await query.edit_message_text(
                f"✅ <b>Registration Submitted!</b>\n\n"
                f"Your team <b>{reg_data.get('team_name')}</b> has been assigned number <b>{team_num}</b>.\n"
                f"Owners will confirm your registration shortly. 🙏",
                parse_mode="HTML",
            )
        except Exception:
            pass

    elif query.data == "reg_confirm_no":
        context.user_data.pop("reg_data", None)
        context.user_data.pop("reg_state", None)
        try:
            await query.edit_message_text("❌ Registration cancelled. You can /register again anytime.")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Text input handler (bowl via DM / bat in group)
# ---------------------------------------------------------------------------

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip() if update.message and update.message.text else ""
    chat_type  = update.message.chat.type if update.message else "private"

    # ── Private DM — Registration flow ────────────────────────────────────
    if chat_type == "private":
        reg_state = context.user_data.get("reg_state")
        if reg_state and reg_state not in ("confirm",):
            reg_data = context.user_data.setdefault("reg_data", {})
            text = user_input

            if reg_state == "team_name":
                if not text:
                    await update.message.reply_text("❌ Team name cannot be empty. Please send your team name:")
                    return
                reg_data["team_name"] = text
                context.user_data["reg_state"] = "logo"
                await update.message.reply_text(
                    f"✅ Team Name: <b>{text}</b>\n\nStep 2️⃣\n"
                    "🖼️ Now send your <b>Team Logo</b> (send as a photo):",
                    parse_mode="HTML",
                )
                return

            elif reg_state == "logo":
                await update.message.reply_text("📸 Please <b>send a photo</b> as your team logo, not text!", parse_mode="HTML")
                return

            elif reg_state == "captain":
                if not text:
                    await update.message.reply_text("❌ Captain cannot be empty. Send captain @username or name:")
                    return
                # Check if this player is already in another team
                if tourteams_col is not None:
                    existing = await tourteams_col.find_one({
                        "$or": [{"captain": text}, {"vc": text}, {"ret1": text}, {"ret2": text}]
                    })
                    if existing:
                        await update.message.reply_text(
                            f"⚠️ <b>{text}</b> is already registered in another team! Please choose a different player.",
                            parse_mode="HTML",
                        )
                        return
                reg_data["captain"] = text
                context.user_data["reg_state"] = "vc"
                await update.message.reply_text(
                    f"✅ Captain: <b>{text}</b>\n\nStep 5️⃣\n"
                    "🥈 Send the <b>Vice-Captain's @username</b>.\n(If no username, send their full name)",
                    parse_mode="HTML",
                )
                return

            elif reg_state == "vc":
                if not text:
                    await update.message.reply_text("❌ Vice-Captain cannot be empty. Send VC @username or name:")
                    return
                if tourteams_col is not None:
                    existing = await tourteams_col.find_one({
                        "$or": [{"captain": text}, {"vc": text}, {"ret1": text}, {"ret2": text}]
                    })
                    if existing:
                        await update.message.reply_text(
                            f"⚠️ <b>{text}</b> is already registered in another team!",
                            parse_mode="HTML",
                        )
                        return
                if text == reg_data.get("captain"):
                    await update.message.reply_text("⚠️ VC cannot be the same as Captain!")
                    return
                reg_data["vc"] = text
                context.user_data["reg_state"] = "ret1"
                await update.message.reply_text(
                    f"✅ Vice-Captain: <b>{text}</b>\n\nStep 6️⃣\n"
                    "🌟 Send <b>Retention 1</b> @username.\n(If no username, send their full name)",
                    parse_mode="HTML",
                )
                return

            elif reg_state == "ret1":
                if not text:
                    await update.message.reply_text("❌ Retention 1 cannot be empty. Send @username or name:")
                    return
                if tourteams_col is not None:
                    existing = await tourteams_col.find_one({
                        "$or": [{"captain": text}, {"vc": text}, {"ret1": text}, {"ret2": text}]
                    })
                    if existing:
                        await update.message.reply_text(
                            f"⚠️ <b>{text}</b> is already registered in another team!",
                            parse_mode="HTML",
                        )
                        return
                already = [reg_data.get("captain"), reg_data.get("vc")]
                if text in already:
                    await update.message.reply_text("⚠️ Retention 1 cannot be the same as Captain or VC!")
                    return
                reg_data["ret1"] = text
                context.user_data["reg_state"] = "ret2"
                await update.message.reply_text(
                    f"✅ Retention 1: <b>{text}</b>\n\nStep 7️⃣\n"
                    "🌟 Send <b>Retention 2</b> @username.\n(If no username, send their full name)",
                    parse_mode="HTML",
                )
                return

            elif reg_state == "ret2":
                if not text:
                    await update.message.reply_text("❌ Retention 2 cannot be empty. Send @username or name:")
                    return
                if tourteams_col is not None:
                    existing = await tourteams_col.find_one({
                        "$or": [{"captain": text}, {"vc": text}, {"ret1": text}, {"ret2": text}]
                    })
                    if existing:
                        await update.message.reply_text(
                            f"⚠️ <b>{text}</b> is already registered in another team!",
                            parse_mode="HTML",
                        )
                        return
                already = [reg_data.get("captain"), reg_data.get("vc"), reg_data.get("ret1")]
                if text in already:
                    await update.message.reply_text("⚠️ Retention 2 cannot be the same as Captain, VC, or Retention 1!")
                    return
                reg_data["ret2"] = text
                context.user_data["reg_state"] = "confirm"
                summary = (
                    f"📋 <b>CONFIRM YOUR REGISTRATION</b>\n\n"
                    f"🏏 Team: <b>{reg_data.get('team_name')}</b>\n"
                    f"👑 Captain: {reg_data.get('captain')}\n"
                    f"🥈 Vice-Captain: {reg_data.get('vc')}\n"
                    f"🌟 Retention 1: {reg_data.get('ret1')}\n"
                    f"🌟 Retention 2: {reg_data.get('ret2')}\n\n"
                    "Is everything correct?"
                )
                kb = [
                    [InlineKeyboardButton("Confirm ✅", callback_data="reg_confirm_yes")],
                    [InlineKeyboardButton("Cancel ❌",  callback_data="reg_confirm_no")],
                ]
                if reg_data.get("logo_file_id"):
                    await update.message.reply_photo(
                        photo=reg_data["logo_file_id"],
                        caption=summary,
                        reply_markup=InlineKeyboardMarkup(kb),
                        parse_mode="HTML",
                    )
                else:
                    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
                return
        return  # Ignore other DM text

    # ── Group — Batting input ──────────────────────────────────────────────
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    game    = context.bot_data.get(chat_id)

    if not game or game.get("state") != "PLAYING":
        return

    if not user_input.isdigit() or int(user_input) not in range(1, 7):
        return

    shot = int(user_input)

    if game.get("mode") == "TEAM":
        striker = game.get("striker")
        if not striker or striker["id"] != user_id:
            return
        if game.get("waiting_for") not in ["BATTER", "PROCESSING_BATTER"]:
            return
        if game.get("waiting_for") == "PROCESSING_BATTER":
            return
        game["waiting_for"] = "PROCESSING_BATTER"
        clear_afk_timer(context, chat_id)
        await process_team_ball(context, chat_id, game, shot)
    else:
        batter = game["players"][game["batter_idx"]]
        if user_id != batter["id"]:
            return
        if game.get("waiting_for") not in ["BATTER", "PROCESSING_BATTER"]:
            return
        if game.get("waiting_for") == "PROCESSING_BATTER":
            return
        game["waiting_for"] = "PROCESSING_BATTER"
        clear_afk_timer(context, chat_id)
        await process_solo_ball(context, chat_id, game, shot)


# ---------------------------------------------------------------------------
# Bowler DM handler
# ---------------------------------------------------------------------------

async def handle_bowler_dm(context: ContextTypes.DEFAULT_TYPE, user_id: int, delivery: int):
    active_bowlers = context.bot_data.get("active_bowlers", {})
    chat_id = active_bowlers.get(user_id)
    if not chat_id:
        return

    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != "BOWLER":
        return

    if game.get("mode") == "TEAM":
        bowler = game.get("current_bowler")
    else:
        bowler = game["players"][game["bowler_idx"]]

    if not bowler or bowler["id"] != user_id:
        return

    game["waiting_for"] = "BATTER"
    game["last_delivery"] = delivery
    clear_afk_timer(context, chat_id)

    if game.get("mode") == "TEAM":
        await send_team_delivery_to_group(context, chat_id, game, bowler, delivery)
    else:
        await send_solo_delivery_to_group(context, chat_id, game, bowler, delivery)


async def send_team_delivery_to_group(context, chat_id, game, bowler, delivery):
    striker = game.get("striker")
    if not striker:
        return
    free_hit = game.get("is_free_hit", False)
    fh_tag   = "🚀 <b>FREE HIT!</b> " if free_hit else ""
    batter_over = (
        f"{game['bowling_team_ref']['balls_bowled'] // 6}."
        f"{game['bowling_team_ref']['balls_bowled'] % 6}"
        f" / {game.get('target_overs', '?')}"
    )
    text = (
        f"{fh_tag}🥎 <b>{bowler['name']}</b> bowls → "
        f"🏏 <b>{striker['name']}</b>\n\n"
        f"Over: {batter_over}\n"
        f"📊 Score: <b>{game['batting_team_ref']['score']}/{game['batting_team_ref']['wickets']}</b>\n\n"
        f"<b>{striker['name']}</b>, send your shot (1-6)! 🏏"
    )
    await context.bot.send_message(chat_id, text, parse_mode="HTML")
    set_afk_timer(context, chat_id, striker["id"], "BATTER")


async def send_solo_delivery_to_group(context, chat_id, game, bowler, delivery):
    batter = game["players"][game["batter_idx"]]
    text   = (
        f"🥎 <b>{bowler['name']}</b> is bowling to <b>{batter['name']}</b>!\n\n"
        f"Ball {game['balls_bowled'] + 1} of {game['spell']}\n\n"
        f"<b>{batter['name']}</b>, send your shot (1-6)! 🏏"
    )
    await context.bot.send_message(chat_id, text, parse_mode="HTML")
    set_afk_timer(context, chat_id, batter["id"], "BATTER")


# ---------------------------------------------------------------------------
# Ball processing — SOLO
# ---------------------------------------------------------------------------

async def process_solo_ball(context, chat_id, game, shot):
    bowler   = game["players"][game["bowler_idx"]]
    batter   = game["players"][game["batter_idx"]]
    delivery = game.get("last_delivery", 0)

    is_yorker  = game.get("yorker_pending", False)
    game["yorker_pending"] = False
    is_out     = (shot == delivery)

    if is_yorker and is_out:
        batter["is_out"] = True
        await send_media_safely(context, chat_id, MEDIA["yorker"],
            f"🎯 <b>YORKER! CLEAN BOWLED!</b> 🎯\n{batter['name']} is OUT for {batter.get('runs',0)}!")
        bowler["wickets"] = bowler.get("wickets", 0) + 1
        bowler["balls_bowled"] = bowler.get("balls_bowled", 0) + 1
        batter["balls_faced"]  = batter.get("balls_faced", 0) + 1
        await advance_solo_batter(context, chat_id, game)
        return

    if is_out and not game.get("is_free_hit"):
        batter["is_out"] = True
        media = MEDIA["out"]
        caption = (
            f"💥 <b>OUT!</b> {batter['name']} is dismissed for <b>{batter.get('runs',0)}</b> runs!\n"
            f"🥎 {bowler['name']} takes the wicket!"
        )
        if batter.get("runs", 0) == 0:
            media   = MEDIA["duck"]
            caption = f"🦆 <b>DUCK!</b> {batter['name']} is out for <b>0</b>! Quack quack!"
        await send_media_safely(context, chat_id, media, caption)
        bowler["wickets"]      = bowler.get("wickets", 0) + 1
        bowler["balls_bowled"] = bowler.get("balls_bowled", 0) + 1
        batter["balls_faced"]  = batter.get("balls_faced", 0) + 1
        await advance_solo_batter(context, chat_id, game)
        return

    # Runs scored
    if is_out and game.get("is_free_hit"):
        runs = shot  # On free hit same number = runs, not out
    else:
        runs = shot

    batter["runs"]         = batter.get("runs", 0) + runs
    batter["balls_faced"]  = batter.get("balls_faced", 0) + 1
    bowler["conceded"]     = bowler.get("conceded", 0) + runs
    bowler["balls_bowled"] = bowler.get("balls_bowled", 0) + 1
    game["balls_bowled"]   = game.get("balls_bowled", 0) + 1

    if runs == 4:
        batter["match_4s"] = batter.get("match_4s", 0) + 1
    elif runs == 6:
        batter["match_6s"] = batter.get("match_6s", 0) + 1

    game["is_free_hit"] = False

    milestone_media = None
    if batter.get("runs", 0) >= 100 and (batter["runs"] - runs) < 100:
        milestone_media = MEDIA["100"]
    elif batter.get("runs", 0) >= 50 and (batter["runs"] - runs) < 50:
        milestone_media = MEDIA["50"]

    media_key = runs if runs in MEDIA else 1
    caption   = (
        f"🏏 <b>{batter['name']}</b> hits a <b>{runs}</b>!\n"
        f"Score: <b>{batter.get('runs',0)}</b> ({batter.get('balls_faced',0)} balls)"
    )

    if milestone_media:
        await send_media_safely(context, chat_id, milestone_media, caption)
    else:
        await send_media_safely(context, chat_id, MEDIA[media_key], caption)

    if game["balls_bowled"] >= game["spell"]:
        await rotate_solo_bowler(context, chat_id, game)
    else:
        game["waiting_for"] = "BOWLER"
        await trigger_bowl(context, chat_id)


async def advance_solo_batter(context, chat_id, game):
    game["batter_idx"] += 1
    if game["batter_idx"] >= len(game["players"]):
        await check_solo_winner_exp(game)
        await commit_player_stats(game)
        game["state"] = "NOT_PLAYING"
        await context.bot.send_message(chat_id, "🏁 <b>MATCH FINISHED!</b> 🏁", parse_mode="HTML")
        await trigger_full_scorecard_message(context, chat_id, game)
        return
    game["balls_bowled"]          = 0
    game["special_used_this_over"] = False
    available_bowlers = [i for i in range(len(game["players"])) if i != game["batter_idx"]]
    if available_bowlers:
        game["bowler_idx"] = random.choice(available_bowlers)
    game["waiting_for"] = "BOWLER"
    await trigger_bowl(context, chat_id)


async def rotate_solo_bowler(context, chat_id, game):
    batter = game["players"][game["batter_idx"]]
    bowler = game["players"][game["bowler_idx"]]
    overs, balls = divmod(bowler.get("balls_bowled", 0), 6)
    eco = (bowler["conceded"] / bowler["balls_bowled"]) * 6 if bowler.get("balls_bowled", 0) > 0 else 0
    await update_best_spell(bowler["id"], bowler.get("wickets", 0), bowler.get("conceded", 0))

    remaining = [
        i for i in range(len(game["players"]))
        if i != game["batter_idx"] and i != game["bowler_idx"]
    ]
    if remaining:
        game["bowler_idx"]            = random.choice(remaining)
        game["balls_bowled"]          = 0
        game["special_used_this_over"] = False
        game["waiting_for"]           = "BOWLER"
        await trigger_bowl(context, chat_id)
    else:
        game["batter_idx"] += 1
        if game["batter_idx"] >= len(game["players"]):
            await check_solo_winner_exp(game)
            await commit_player_stats(game)
            game["state"] = "NOT_PLAYING"
            await context.bot.send_message(chat_id, "🏁 <b>MATCH FINISHED!</b> 🏁", parse_mode="HTML")
            await trigger_full_scorecard_message(context, chat_id, game)
            return
        game["balls_bowled"]          = 0
        game["special_used_this_over"] = False
        available_bowlers = [i for i in range(len(game["players"])) if i != game["batter_idx"]]
        if available_bowlers:
            game["bowler_idx"] = random.choice(available_bowlers)
        game["waiting_for"] = "BOWLER"
        await trigger_bowl(context, chat_id)


# ---------------------------------------------------------------------------
# Ball processing — TEAM
# ---------------------------------------------------------------------------

async def process_team_ball(context, chat_id, game, shot):
    striker  = game.get("striker")
    bowler   = game.get("current_bowler")
    delivery = game.get("last_delivery", 0)

    if not striker or not bowler:
        game["waiting_for"] = "BOWLER"
        return

    is_yorker = game.get("yorker_pending", False)
    game["yorker_pending"] = False
    is_free_hit = game.get("is_free_hit", False)
    is_out      = (shot == delivery)

    game["bowling_team_ref"]["balls_bowled"] = game["bowling_team_ref"].get("balls_bowled", 0) + 1
    bowler["balls_bowled"] = bowler.get("balls_bowled", 0) + 1
    striker["balls_faced"] = striker.get("balls_faced", 0) + 1

    if is_yorker and is_out:
        dismiss_batter(game, striker)
        bowler["wickets"] = bowler.get("wickets", 0) + 1
        game["batting_team_ref"]["wickets"] = game["batting_team_ref"].get("wickets", 0) + 1
        await send_media_safely(context, chat_id, MEDIA["yorker"],
            f"🎯 <b>YORKER! CLEAN BOWLED!</b>\n{striker['name']} is OUT for {striker.get('runs',0)}!")
        await after_team_wicket(context, chat_id, game, bowler)
        return

    if is_out and not is_free_hit:
        dismiss_batter(game, striker)
        bowler["wickets"] = bowler.get("wickets", 0) + 1
        game["batting_team_ref"]["wickets"] = game["batting_team_ref"].get("wickets", 0) + 1

        hat_trick_key = f"hat_{bowler['id']}_{chat_id}"
        consecutive   = context.bot_data.get(hat_trick_key, 0) + 1
        context.bot_data[hat_trick_key] = consecutive
        if consecutive >= 3:
            bowler["hat_tricks"] = bowler.get("hat_tricks", 0) + 1
            context.bot_data[hat_trick_key] = 0
            await context.bot.send_message(chat_id, f"🎩 <b>HAT-TRICK!</b> {bowler['name']} takes 3 wickets in a row! 🎩", parse_mode="HTML")

        media = MEDIA["out"]
        caption = (
            f"💥 <b>OUT!</b> {striker['name']} dismissed for <b>{striker.get('runs',0)}</b>!\n"
            f"🥎 {bowler['name']} takes the wicket!"
        )
        if striker.get("runs", 0) == 0:
            media   = MEDIA["duck"]
            caption = f"🦆 <b>DUCK!</b> {striker['name']} is out for <b>0</b>!"
        await send_media_safely(context, chat_id, media, caption)
        await after_team_wicket(context, chat_id, game, bowler)
        return

    # Clear hat-trick counter on non-dismissal
    hat_trick_key = f"hat_{bowler['id']}_{chat_id}"
    context.bot_data[hat_trick_key] = 0

    # Runs
    if is_out and is_free_hit:
        runs = shot
    else:
        runs = shot

    game["is_free_hit"] = False
    striker["runs"]              = striker.get("runs", 0) + runs
    game["batting_team_ref"]["score"] = game["batting_team_ref"].get("score", 0) + runs
    bowler["conceded"]           = bowler.get("conceded", 0) + runs

    if runs == 4:
        striker["match_4s"] = striker.get("match_4s", 0) + 1
    elif runs == 6:
        striker["match_6s"] = striker.get("match_6s", 0) + 1

    milestone_media = None
    new_runs = striker.get("runs", 0)
    if new_runs >= 100 and (new_runs - runs) < 100:
        milestone_media = MEDIA["100"]
    elif new_runs >= 50 and (new_runs - runs) < 50:
        milestone_media = MEDIA["50"]

    caption = (
        f"🏏 <b>{striker['name']}</b> hits a <b>{runs}</b>!\n"
        f"Score: {striker.get('runs',0)} ({striker.get('balls_faced',0)}) | "
        f"Team: <b>{game['batting_team_ref']['score']}/{game['batting_team_ref']['wickets']}</b>"
    )
    if game.get("innings") == 2:
        target    = game.get("target", 0)
        remaining = target - game["batting_team_ref"]["score"]
        caption  += f"\nNeed: <b>{max(0, remaining)}</b> more"

    media_key = runs if runs in MEDIA else 1
    if milestone_media:
        await send_media_safely(context, chat_id, milestone_media, caption)
    else:
        await send_media_safely(context, chat_id, MEDIA[media_key], caption)

    # Spamfree tracking
    if game.get("spamfree"):
        spam_key  = f"spam_{chat_id}"
        last_two  = context.bot_data.get(spam_key, [])
        last_two.append(delivery)
        if len(last_two) > 2:
            last_two = last_two[-2:]
        context.bot_data[spam_key] = last_two

    # Check win condition for 2nd innings
    if game.get("innings") == 2 and game["batting_team_ref"]["score"] >= game.get("target", 0):
        await process_team_innings_end(context, chat_id, game)
        return

    # Check over completion
    balls_in_over = game["bowling_team_ref"]["balls_bowled"] % 6
    if balls_in_over == 0:
        await end_team_over(context, chat_id, game, bowler)
        return

    swap_strike(game)
    game["waiting_for"] = "BOWLER"
    await trigger_bowl(context, chat_id)


async def after_team_wicket(context, chat_id, game, bowler):
    max_wickets = len(game["batting_team_ref"]["players"]) - 1
    if game["batting_team_ref"]["wickets"] >= max_wickets:
        await process_team_innings_end(context, chat_id, game)
        return

    balls_in_over = game["bowling_team_ref"]["balls_bowled"] % 6
    if balls_in_over == 0:
        await end_team_over(context, chat_id, game, bowler)
        return

    game["waiting_for"]    = "TEAM_BATTER_SELECT"
    game["need_new_bowler"] = False
    await context.bot.send_message(
        chat_id,
        "🏏 Captain/Host, please select the next batter using <code>/batting [number]</code>.",
        parse_mode="HTML",
    )


async def end_team_over(context, chat_id, game, bowler):
    game["last_bowler_id"]        = bowler["id"]
    game["special_used_this_over"] = False
    game["is_free_hit"]           = False

    ov, bl = divmod(game["bowling_team_ref"]["balls_bowled"], 6)
    eco    = (bowler["conceded"] / bowler["balls_bowled"] * 6) if bowler.get("balls_bowled") else 0
    spell_summary = f"{bowler.get('wickets',0)}W/{bowler.get('conceded',0)}R Eco:{eco:.1f}"
    bowler.setdefault("spells", []).append(spell_summary)
    await update_best_spell(bowler["id"], bowler.get("wickets", 0), bowler.get("conceded", 0))

    await context.bot.send_message(
        chat_id,
        f"✅ <b>Over {ov} Complete!</b>\n"
        f"Score: <b>{game['batting_team_ref']['score']}/{game['batting_team_ref']['wickets']}</b>\n\n"
        "Bowling Captain/Host, please select the next bowler using <code>/bowling [number]</code>.",
        parse_mode="HTML",
    )

    if game.get("innings") == 1 and ov >= game.get("target_overs", 99):
        await process_team_innings_end(context, chat_id, game)
        return

    swap_strike(game)
    game["waiting_for"] = "TEAM_BOWLER_SELECT"


# ---------------------------------------------------------------------------
# Toss
# ---------------------------------------------------------------------------

async def start_toss(context, chat_id, game):
    team_a_cap_id = game.get("team_a", {}).get("captain")
    team_b_cap_id = game.get("team_b", {}).get("captain")
    if not team_a_cap_id or not team_b_cap_id:
        return

    # The team_a captain calls the toss
    game["toss_caller_id"] = team_a_cap_id
    caller = next((p for p in game.get("team_a", {}).get("players", []) if p["id"] == team_a_cap_id), None)
    caller_name = caller["name"] if caller else "Team A Captain"

    kb = [[
        InlineKeyboardButton("HEADS 🪙", callback_data="toss_heads"),
        InlineKeyboardButton("TAILS 🪙", callback_data="toss_tails"),
    ]]
    await context.bot.send_message(
        chat_id,
        f"🪙 <b>TOSS TIME!</b> 🪙\n\n"
        f"<a href='tg://user?id={team_a_cap_id}'>{caller_name}</a> (Team A Captain) calls the toss!\n"
        "Choose Heads or Tails:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Tournament commands
# ---------------------------------------------------------------------------

async def tournament_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only command.")
        return
    await update.message.reply_text(
        "🏆 <b>TOURNAMENT PANEL</b>\n\n"
        "Available commands:\n"
        "<code>/regisopen</code> — Open registrations\n"
        "<code>/regisclose</code> — Close registrations\n"
        "<code>/tourteams</code> — List registered teams\n"
        "<code>/allteams</code> — Full details of all teams\n"
        "<code>/deleteteam [num]</code> — Delete a team by number",
        parse_mode="HTML",
    )


async def regisopen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only command.")
        return
    context.bot_data["registration_open"] = True
    await update.message.reply_text(
        "✅ <b>REGISTRATION IS NOW OPEN!</b>\n\n"
        "Players can DM the bot and use /register to register their team. 🏏",
        parse_mode="HTML",
    )


async def regisclose_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only command.")
        return
    context.bot_data["registration_open"] = False
    await update.message.reply_text(
        "🔒 <b>REGISTRATION IS NOW CLOSED!</b>\n\n"
        "No more teams can register at this time.",
        parse_mode="HTML",
    )


async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("📩 Please DM the bot to register your team!")
        return
    if not context.bot_data.get("registration_open"):
        await update.message.reply_text("🔒 Registrations are currently <b>CLOSED</b>. Stay tuned!", parse_mode="HTML")
        return
    if tourteams_col is None:
        await update.message.reply_text("❌ Database not connected.")
        return
    context.user_data["reg_state"] = "team_name"
    context.user_data["reg_data"]  = {}
    await update.message.reply_text(
        "🏏 <b>TEAM REGISTRATION</b> 🏏\n\n"
        "Let's get your team registered! Step 1️⃣\n\n"
        "📝 Please send your <b>Team Name</b>:",
        parse_mode="HTML",
    )


async def tourteams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only command.")
        return
    if tourteams_col is None:
        await update.message.reply_text("❌ Database not connected.")
        return
    teams = await tourteams_col.find({}).sort("team_number", 1).to_list(length=200)
    if not teams:
        await update.message.reply_text("📋 No teams registered yet.")
        return
    text = "📋 <b>REGISTERED TEAMS</b>\n\n"
    for t in teams:
        text += f"<b>#{t.get('team_number', '?')}</b> — {t.get('team_name', 'Unknown')}\n"
    if len(text) > 4000:
        text = text[:4000] + "\n...[Truncated]"
    await update.message.reply_text(text, parse_mode="HTML")


async def deleteteam_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only command.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /deleteteam <team number>\nExample: /deleteteam 3")
        return
    if tourteams_col is None:
        await update.message.reply_text("❌ Database not connected.")
        return
    team_num = int(context.args[0])
    team = await tourteams_col.find_one({"team_number": team_num})
    if not team:
        await update.message.reply_text(f"❌ No team found with number <b>{team_num}</b>.", parse_mode="HTML")
        return
    await tourteams_col.delete_one({"team_number": team_num})
    await update.message.reply_text(
        f"🗑️ Team <b>#{team_num} — {team.get('team_name', 'Unknown')}</b> has been deleted from the tournament.",
        parse_mode="HTML",
    )


async def allteams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only command.")
        return
    if tourteams_col is None:
        await update.message.reply_text("❌ Database not connected.")
        return
    teams = await tourteams_col.find({}).sort("team_number", 1).to_list(length=200)
    if not teams:
        await update.message.reply_text("📋 No teams registered yet.")
        return
    for t in teams:
        text = (
            f"🏏 <b>Team #{t.get('team_number', '?')}: {t.get('team_name', 'Unknown')}</b>\n\n"
            f"👑 Captain: {t.get('captain', 'N/A')}\n"
            f"🥈 Vice-Captain: {t.get('vc', 'N/A')}\n"
            f"🌟 Retention 1: {t.get('ret1', 'N/A')}\n"
            f"🌟 Retention 2: {t.get('ret2', 'N/A')}\n"
        )
        try:
            if t.get("logo_file_id"):
                await update.message.reply_photo(photo=t["logo_file_id"], caption=text, parse_mode="HTML")
            else:
                await update.message.reply_text(text, parse_mode="HTML")
        except Exception:
            await update.message.reply_text(text, parse_mode="HTML")
        await asyncio.sleep(0.2)


# ---------------------------------------------------------------------------
# Registration photo input handler
# ---------------------------------------------------------------------------

async def handle_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if context.user_data.get("reg_state") != "logo":
        return
    photo = update.message.photo[-1]
    context.user_data["reg_data"]["logo_file_id"] = photo.file_id
    context.user_data["reg_state"] = "captain"
    await update.message.reply_text(
        "✅ Logo received!\n\nStep 4️⃣\n👑 Send the <b>Captain's @username</b>.\n"
        "(If no username, send their full name)",
        parse_mode="HTML",
    )


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
    app.add_handler(CommandHandler("tournament",  tournament_command))
    app.add_handler(CommandHandler("regisopen",   regisopen_command))
    app.add_handler(CommandHandler("regisclose",  regisclose_command))
    app.add_handler(CommandHandler("register",    register_command))
    app.add_handler(CommandHandler("tourteams",   tourteams_command))
    app.add_handler(CommandHandler("allteams",    allteams_command))
    app.add_handler(CommandHandler("deleteteam",  deleteteam_command))

    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, handle_photo_input))
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
