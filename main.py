import os
import io
import time
import random
import asyncio
import urllib.request
import urllib.error
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

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
TOKEN       = os.getenv("BOT_TOKEN")
MONGO_URI   = os.getenv("MONGO_URI")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT        = int(os.environ.get("PORT", "8080"))

OWNER_IDS = [8722613907, 8782578728, 8000127916]

SCOREBOARD_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scoreboard_template.png"
)
SCOREBOARD_TEMPLATE_URL = os.getenv(
    "SCOREBOARD_TEMPLATE_URL",
    "https://res.cloudinary.com/dxgfxfoog/image/upload/v1778123859/scoreboard_template.png"
)

# ---------------------------------------------------------------------------
# MongoDB — with explicit timeouts to prevent 30-second hangs
# ---------------------------------------------------------------------------
try:
    _mongo_client   = AsyncIOMotorClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=10000,
    )
    db              = _mongo_client["cricket_bot_db"]
    users_col       = db["users"]
    chats_col       = db["interacted_chats"]
    tournaments_col = db["tournaments"]
    tourteams_col   = db["tour_teams"]
except Exception as _e:
    print(f"MongoDB Connection Error: {_e}")
    users_col = chats_col = tournaments_col = tourteams_col = None

# Cache bot username so we never call get_me() on every ball
_BOT_USERNAME_CACHE: str | None = None

# ---------------------------------------------------------------------------
# Tiny helper — avoids all f-string backslash issues in Python < 3.12
# ---------------------------------------------------------------------------
def _men(uid, name) -> str:
    """Return an HTML Telegram user mention."""
    return f"<a href='tg://user?id={uid}'>{name}</a>"

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

SCOREBOARD_IMG   = "https://res.cloudinary.com/dxgfxfoog/image/upload/v1777876839/file_000000001fc07207a39f861ace603999_tjaafo.png"
TEAMS_ROSTER_IMG = "https://res.cloudinary.com/dxgfxfoog/image/upload/v1777706897/file_00000000c1947207ae83551202e6e003_f4o3y9.png"

# ---------------------------------------------------------------------------
# Commentary
# ---------------------------------------------------------------------------
HIT_COMMENTARY = {
    0: [
        "🛡️ DOT BALL! The bowler wins this battle — pressure is building!",
        "😤 Tight line and length! The batter had absolutely no answer!",
        "🔒 Beats the bat! The bowler is looking dangerous right now!",
        "😬 Played and missed! That was agonisingly close!",
        "🎯 Pinpoint accuracy! The batter is stuck in a web here!",
        "💪 Great delivery! The batter played and missed — bowler on top!",
        "🤫 Silence from the bat! The bowler wins the mind game!",
        "😅 Survived, but barely! That kept low and almost crept through!",
        "🧱 Defended well, but the bowler is absolutely controlling this spell!",
        "📉 Pressure mounting... The batter needs to find a way through!",
    ],
    1: [
        "🏃 Quick single! Smart cricket — keep rotating that strike!",
        "👣 One and running! Great awareness from the batter!",
        "🏏 Nudged away for one — keeping the scoreboard ticking nicely!",
        "1️⃣ Just a single, but in cricket every run is priceless!",
        "🔄 Good placement for one! Batter retains strike intelligently!",
        "📊 Sensible cricket — take the single, don't throw it away!",
        "🧠 One run, no fuss. Accumulate, accumulate, accumulate!",
    ],
    2: [
        "✌️ TWO RUNS! Brilliant placement through the gap!",
        "🏃‍♂️ Running hard between the wickets — 2 sweet runs!",
        "🎯 Found the gap! The fielders are scrambling!",
        "💨 Pushed through the covers — 2 beautiful runs picked up!",
        "2️⃣ Two! Great running and even better shot selection!",
    ],
    3: [
        "🔥 THREE RUNS! Brilliant running converts it!",
        "💪 Great effort — THREE taken! Excellent work between the wickets!",
        "3️⃣ Outstanding running! 3 runs — you can't ask for more!",
        "🏃 Superb athleticism between the wickets — 3 runs!",
    ],
    4: [
        "🏏 FOUR! 💥 Absolutely SMASHED through the covers! What a shot!",
        "🔥 BOUNDARY! The ball races to the fence — nobody could stop it!",
        "💥 FOUR! The fielder didn't even move — completely beaten!",
        "🎯 FOUR! Perfect placement, impossible to stop — textbook stroke!",
        "😍 FOUR! That is a BEAUTY of a shot — right out of the coaching manual!",
        "⚡ FOUR! The crowd is on their feet — what a moment!",
        "💨 FOUR! Screams through the infield — the fielders had no chance!",
        "🌟 What TIMING! FOUR! The bat did ALL the talking there!",
    ],
    5: [
        "5️⃣ FIVE RUNS! Incredible shot combined with brilliant running!",
        "💥 FIVE! Overthrows added insult to injury!",
        "😱 FIVEEE! That's extraordinary!",
    ],
    6: [
        "💥 SIX! 🚀 GONE! RIGHT OUT OF THE STADIUM — GONE FOR GOOD!",
        "🏏 MAXIMUM! 💥 The ball is STILL FLYING through the air!",
        "🔥 SIX! The bowler can only watch in pure AGONY as it clears the rope!",
        "🌟 SIXXXX! That's deep into the stands — what an INCREDIBLE hit!",
        "😱 SIX! Pure raw MUSCLE! The crowd has gone completely INSANE!",
        "🎯 MAXIMUM! Picked it up from outside off and LAUNCHED it into orbit!",
        "👑 SIX! That is absolutely DISRESPECTFUL to the bowling — MONSTROUS HIT!",
        "🚀 SIXXX! That has LEFT THE BUILDING! Absolutely RIDICULOUS power!",
        "💫 SIX! Over long-on! The batter is in total GODMODE!",
        "🎆 SIX! BOOM! It's fireworks time! What a MAGNIFICENT SHOT!",
    ],
}

# ---------------------------------------------------------------------------
# Scoreboard Pillow helpers
# ---------------------------------------------------------------------------
_SB = {
    "circle_cx": 768, "circle_cy": 205, "circle_r": 140,
    "team_a_score_cx": 453, "team_a_score_cy": 640,
    "team_a_overs_cx": 453, "team_a_overs_cy": 673,
    "team_b_score_cx": 1083, "team_b_score_cy": 640,
    "team_b_overs_cx": 1083, "team_b_overs_cy": 673,
    "bar_y": 900,
    "innings_cx": 192, "crr_cx": 576, "bowler_cx": 960, "batter_cx": 1344,
}
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
_template_cache: bytes | None = None


def _load_font(size: int):
    for path in _FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _get_template_bytes() -> bytes | None:
    global _template_cache
    if _template_cache is not None:
        return _template_cache
    if os.path.exists(SCOREBOARD_TEMPLATE_PATH):
        try:
            with open(SCOREBOARD_TEMPLATE_PATH, "rb") as f:
                _template_cache = f.read()
            return _template_cache
        except Exception:
            pass
    try:
        req = urllib.request.Request(SCOREBOARD_TEMPLATE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            _template_cache = resp.read()
        return _template_cache
    except Exception as exc:
        print(f"[scoreboard] template download failed: {exc}")
    return None


async def _fetch_group_photo_bytes(context, chat_id: int) -> bytes | None:
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


def _draw_centered_text(draw, cx, cy, text, font, fill=(255, 255, 255), shadow=True):
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = cx - w // 2, cy - h // 2
    if shadow:
        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 180))
    draw.text((x, y), text, font=font, fill=fill)


async def generate_team_scoreboard_image(context, chat_id: int, game: dict) -> bytes | None:
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
        group_photo_bytes = await _fetch_group_photo_bytes(context, chat_id)
        if group_photo_bytes:
            try:
                gp = Image.open(io.BytesIO(group_photo_bytes)).convert("RGBA")
                r  = _SB["circle_r"]
                gp = gp.resize((r * 2, r * 2), Image.LANCZOS)
                mask = Image.new("L", (r * 2, r * 2), 0)
                m_draw = ImageDraw.Draw(mask)
                m_draw.ellipse((0, 0, r * 2, r * 2), fill=255)
                img.paste(gp, (_SB["circle_cx"] - r, _SB["circle_cy"] - r), mask)
            except Exception:
                _draw_centered_text(draw, _SB["circle_cx"], _SB["circle_cy"], "LIVE", circle_font, fill=(255, 215, 0))
        else:
            _draw_centered_text(draw, _SB["circle_cx"], _SB["circle_cy"], "LIVE", circle_font, fill=(255, 215, 0))

        a_score = f"{team_a.get('score', 0)}/{team_a.get('wickets', 0)}"
        a_balls = team_b.get("balls_bowled", 0)
        a_ov, a_bl = divmod(a_balls, 6)
        _draw_centered_text(draw, _SB["team_a_score_cx"], _SB["team_a_score_cy"], a_score, score_font)
        _draw_centered_text(draw, _SB["team_a_overs_cx"], _SB["team_a_overs_cy"], f"{a_ov}.{a_bl} Ov", overs_font, fill=(200, 220, 255))

        b_score = f"{team_b.get('score', 0)}/{team_b.get('wickets', 0)}"
        b_balls = team_a.get("balls_bowled", 0)
        b_ov, b_bl = divmod(b_balls, 6)
        _draw_centered_text(draw, _SB["team_b_score_cx"], _SB["team_b_score_cy"], b_score, score_font)
        _draw_centered_text(draw, _SB["team_b_overs_cx"], _SB["team_b_overs_cy"], f"{b_ov}.{b_bl} Ov", overs_font, fill=(200, 220, 255))

        innings_txt = "1st Innings" if game.get("innings", 1) == 1 else "2nd Innings"
        bat_team   = game.get("batting_team_ref", {})
        bowl_team  = game.get("bowling_team_ref", {})
        b_bowled   = bowl_team.get("balls_bowled", 0)
        crr_txt    = f"{bat_team.get('score', 0) / b_bowled * 6:.2f}" if b_bowled > 0 else "0.00"

        all_players = team_a.get("players", []) + team_b.get("players", [])
        best_bowler_txt = "N/A"
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
        best_batter_txt = "N/A"
        best_batter = max(all_players, key=lambda p: p.get("runs", 0), default=None)
        if best_batter and best_batter.get("runs", 0) > 0:
            best_batter_txt = (
                f"{best_batter['name'][:10]}\n"
                f"{best_batter['runs']}({best_batter['balls_faced']})"
            )

        gold = (255, 215, 0)
        _draw_centered_text(draw, _SB["innings_cx"], _SB["bar_y"], innings_txt, bar_font, fill=gold)
        _draw_centered_text(draw, _SB["crr_cx"],     _SB["bar_y"], crr_txt,     bar_font, fill=gold)
        _draw_centered_text(draw, _SB["bowler_cx"],  _SB["bar_y"], best_bowler_txt, bar_font, fill=gold)
        _draw_centered_text(draw, _SB["batter_cx"],  _SB["bar_y"], best_batter_txt, bar_font, fill=gold)

        img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf.getvalue()
    except Exception as exc:
        print(f"[scoreboard] image error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def get_user_level(exp: int) -> str:
    if exp < 1000:   return "Newbie 🔰"
    if exp <= 5000:  return "Pro ⚡"
    if exp <= 8000:  return "Legendary 🌟"
    return "Unbeaten 👑"


def get_next_level_info(exp: int):
    if exp < 1000:   return "Pro ⚡", 1000 - exp
    if exp <= 5000:  return "Legendary 🌟", 5001 - exp
    if exp <= 8000:  return "Unbeaten 👑", 8001 - exp
    return None, 0


async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if chats_col is not None and update.effective_chat:
        try:
            title = update.effective_chat.title or "Private/Unknown"
            await chats_col.update_one(
                {"chat_id": update.effective_chat.id},
                {"$set": {"chat_id": update.effective_chat.id,
                          "type": update.effective_chat.type, "title": title}},
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
            await chats_col.update_one(
                {"chat_id": chat.id},
                {"$set": {"chat_id": chat.id, "type": chat.type,
                          "title": chat.title or "Group"}},
                upsert=True,
            )


async def send_media_safely(context, chat_id, media_url, caption,
                             reply_markup=None, reply_to_message_id=None):
    """Send a video/gif with a hard 5-second timeout then fall back to text."""
    try:
        if media_url.endswith(".gif") or "giphy.com" in media_url:
            await asyncio.wait_for(
                context.bot.send_animation(
                    chat_id=chat_id, animation=media_url, caption=caption,
                    parse_mode="HTML", reply_markup=reply_markup,
                    reply_to_message_id=reply_to_message_id,
                    read_timeout=4, write_timeout=4,
                ),
                timeout=5,
            )
        else:
            await asyncio.wait_for(
                context.bot.send_video(
                    chat_id=chat_id, video=media_url, caption=caption,
                    parse_mode="HTML", reply_markup=reply_markup,
                    reply_to_message_id=reply_to_message_id,
                    read_timeout=4, write_timeout=4,
                ),
                timeout=5,
            )
    except Exception:
        fallback = f"<a href='{media_url}'>&#8205;</a>{caption}"
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=fallback, parse_mode="HTML",
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
                read_timeout=4, write_timeout=4,
            )
        except Exception as e2:
            print(f"[media] fallback failed: {e2}")


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
            "batting_innings": 0, "dismissals": 0,
        })
    else:
        upd = {}
        if user.get("first_name") != first_name:
            upd["first_name"] = first_name
        if username and user.get("username") != username:
            upd["username"] = username
        if upd:
            await users_col.update_one({"user_id": user_id}, {"$set": upd})


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
        players = (
            game.get("team_a", {}).get("players", [])
            + game.get("team_b", {}).get("players", [])
        )
    for p in players:
        runs        = p.get("runs", 0)
        balls_faced = p.get("balls_faced", 0)
        await update_highest_score(p["id"], runs, balls_faced)
        updates = {
            "total_runs": runs, "balls_faced": balls_faced,
            "balls_bowled": p.get("balls_bowled", 0),
            "runs_conceded": p.get("conceded", 0),
            "wickets": p.get("wickets", 0),
            "total_4s": p.get("match_4s", 0),
            "total_6s": p.get("match_6s", 0),
            "weekly_runs": runs, "weekly_balls_faced": balls_faced,
            "weekly_balls_bowled": p.get("balls_bowled", 0),
            "weekly_conceded": p.get("conceded", 0),
            "weekly_wickets": p.get("wickets", 0),
        }
        if balls_faced > 0:
            updates["batting_innings"] = 1
            if p.get("is_out", False):
                updates["dismissals"] = 1
        if runs == 0 and p.get("is_out", False) and balls_faced > 0:
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
        score = p.get("runs", 0) + p.get("wickets", 0) * 15 - p.get("conceded", 0) * 0.5
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
        return any(a.user.id == user_id for a in admins)
    except Exception:
        try:
            member = await chat.get_member(user_id)
            return member.status in ["administrator", "creator"]
        except Exception:
            return False


def get_next_num(players):
    nums = {p["num"] for p in players if "num" in p}
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
        if any(p.get("id") == user_id for p in data.get("team_a", {}).get("players", [])):
            return True
        if any(p.get("id") == user_id for p in data.get("team_b", {}).get("players", [])):
            return True
    return False


def get_user_from_mention(update):
    target_user = target_username = None
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    else:
        for entity in (update.message.entities or []):
            if entity.type == "text_mention":
                target_user = entity.user
                break
            elif entity.type == "mention":
                target_username = (
                    update.message.text[entity.offset:entity.offset + entity.length]
                    .lstrip("@").lower()
                )
                break
    return target_user, target_username


def dismiss_batter(game, batter):
    batter["is_out"] = True
    batter["is_striker"] = False
    batter["is_non_striker"] = False
    if game.get("striker") and game["striker"]["id"] == batter["id"]:
        game["striker"] = None
    if game.get("non_striker") and game["non_striker"]["id"] == batter["id"]:
        game["non_striker"] = None


def swap_strike(game):
    st = game.get("striker")
    ns = game.get("non_striker")
    if st and ns:
        game["striker"] = ns
        game["non_striker"] = st
        game["striker"]["is_striker"] = True
        game["striker"]["is_non_striker"] = False
        game["non_striker"]["is_striker"] = False
        game["non_striker"]["is_non_striker"] = True
    elif st and not ns:
        game["non_striker"] = st
        game["striker"] = None
        game["non_striker"]["is_non_striker"] = True
        game["non_striker"]["is_striker"] = False
    elif ns and not st:
        game["striker"] = ns
        game["non_striker"] = None
        game["striker"]["is_striker"] = True
        game["striker"]["is_non_striker"] = False


# ---------------------------------------------------------------------------
# Cricbuzz-style Scorecard
# ---------------------------------------------------------------------------

def _fmt_sr(runs, balls):
    return f"{runs / balls * 100:.1f}" if balls > 0 else "0.0"

def _fmt_eco(conceded, balls_bowled):
    return f"{conceded / balls_bowled * 6:.2f}" if balls_bowled > 0 else "0.00"

def _fmt_overs(balls):
    return f"{balls // 6}.{balls % 6}"


def generate_scorecard(game):
    if game.get("mode") == "TEAM":
        return generate_team_scorecard(game)

    players    = game.get("players", [])
    batter_idx = game.get("batter_idx", 0)
    bowler_idx = game.get("bowler_idx", 0)
    state      = game.get("state", "")

    text = (
        "🏟️ ━━━━━━━━━━━━━━━━━━━━━━━━━ 🏟️\n"
        "          📊 <b>SOLO SCORECARD</b>\n"
        "🏟️ ━━━━━━━━━━━━━━━━━━━━━━━━━ 🏟️\n\n"
        "🏏 <b>BATTING</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "<code>Batter            R    B   4s  6s     SR</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    for i, p in enumerate(players):
        runs  = p.get("runs", 0)
        bf    = p.get("balls_faced", 0)
        sr    = _fmt_sr(runs, bf)
        fours = p.get("match_4s", 0)
        sixes = p.get("match_6s", 0)
        if p.get("is_out"):
            emoji, note = "❌", "out"
        elif state == "PLAYING" and i == batter_idx:
            emoji, note = "🏏", "batting ●"
        elif bf > 0:
            emoji, note = "✅", "not out"
        else:
            emoji, note = "⏳", "yet to bat"
        text += (
            f"\n{emoji} <b>{p['name']}</b>  <i>({note})</i>\n"
            f"<code>   R:{str(runs).rjust(4)}  B:{str(bf).rjust(3)}  "
            f"4s:{str(fours).rjust(2)}  6s:{str(sixes).rjust(2)}  SR:{sr.rjust(6)}</code>\n"
        )
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    text += (
        "🥎 <b>BOWLING</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "<code>Bowler            O    R    W    ECO</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    for i, p in enumerate(players):
        bb = p.get("balls_bowled", 0)
        if bb == 0:
            continue
        conceded = p.get("conceded", 0)
        wkts     = p.get("wickets", 0)
        eco      = _fmt_eco(conceded, bb)
        ov_str   = _fmt_overs(bb)
        is_cur   = state == "PLAYING" and i == bowler_idx
        bowl_tag = "  🎯 <i>bowling</i>" if is_cur else ""
        text += (
            f"\n{'🎯' if is_cur else '🥎'} <b>{p['name']}</b>{bowl_tag}\n"
            f"<code>   O:{ov_str.rjust(4)}  R:{str(conceded).rjust(4)}  "
            f"W:{str(wkts).rjust(2)}  ECO:{eco.rjust(5)}</code>\n"
        )
        spells = list(p.get("bowling_spells", []))
        if is_cur and p.get("_spell_balls0") is not None:
            _lb = bb - p["_spell_balls0"]
            _lr = conceded - p.get("_spell_runs0", 0)
            _lw = wkts - p.get("_spell_wkts0", 0)
            if _lb > 0:
                spells.append({"b": _lb, "r": _lr, "w": _lw, "live": True})
        if spells:
            parts = [
                f"Sp{idx}{'●' if s.get('live') else ''}:{_fmt_overs(s['b'])}ov·{s['r']}R·{s['w']}W"
                for idx, s in enumerate(spells, 1)
            ]
            text += f"   📋 {' | '.join(parts)}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    return text


def generate_team_scorecard(game):
    state          = game.get("state", "")
    is_playing     = state == "PLAYING"
    striker        = game.get("striker") or {}
    non_striker    = game.get("non_striker") or {}
    current_bowler = game.get("current_bowler") or {}

    text = (
        "🏟️ ━━━━━━━━━━━━━━━━━━━━━━━━━━━ 🏟️\n"
        "           🏆 <b>MATCH SCORECARD</b>\n"
        "🏟️ ━━━━━━━━━━━━━━━━━━━━━━━━━━━ 🏟️\n\n"
    )

    if game.get("innings") == 2 and state != "TEAM_FINISHED":
        target      = game.get("target", 0)
        bat_score   = game.get("batting_team_ref", {}).get("score", 0)
        runs_needed = target - bat_score
        balls_rem   = (game.get("target_overs", 0) * 6) - game.get("bowling_team_ref", {}).get("balls_bowled", 0)
        overs_left  = balls_rem / 6 if balls_rem > 0 else 0
        rrr         = (runs_needed / overs_left) if overs_left > 0 else 0.0
        text += (
            f"🎯  Target: <b>{target}</b>  ·  Need <b>{max(0, runs_needed)}</b> in <b>{balls_rem}</b> balls\n"
            f"📈  RRR: <b>{rrr:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

    for team_key, team_label in [("team_a", "🔴 TEAM A"), ("team_b", "🔵 TEAM B")]:
        team = game.get(team_key)
        if not team:
            continue
        opp_team     = game.get("team_b" if team_key == "team_a" else "team_a", {})
        played_balls = opp_team.get("balls_bowled", 0)
        p_ov, p_rem  = divmod(played_balls, 6)
        total_ov     = p_ov + (p_rem / 6)
        rr           = (team["score"] / total_ov) if total_ov > 0 else 0.0

        text += (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎖️  <b>{team_label}</b>  —  "
            f"<b>{team['score']}/{team['wickets']}</b>  "
            f"({_fmt_overs(played_balls)} Ov)  RR: <b>{rr:.2f}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

        bat_players = [
            p for p in team.get("players", [])
            if p.get("balls_faced", 0) > 0 or p.get("is_striker")
            or p.get("is_non_striker") or p.get("is_out")
        ]
        if bat_players:
            text += (
                "\n🏏 <b>BATTING</b>\n"
                "<code>Batter            R    B   4s  6s     SR</code>\n"
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            )
            for p in bat_players:
                runs  = p.get("runs", 0)
                bf    = p.get("balls_faced", 0)
                sr    = _fmt_sr(runs, bf)
                fours = p.get("match_4s", 0)
                sixes = p.get("match_6s", 0)
                if p.get("is_out"):
                    bat_emoji, bat_note = "❌", "out"
                elif is_playing and p.get("id") == striker.get("id"):
                    bat_emoji, bat_note = "⚡", "on strike ●"
                elif is_playing and p.get("id") == non_striker.get("id"):
                    bat_emoji, bat_note = "🏃", "non-striker"
                else:
                    bat_emoji = "✅"
                    bat_note  = "not out" if bf > 0 else "yet to bat"
                text += (
                    f"\n{bat_emoji} <b>{p['name']}</b>  <i>({bat_note})</i>\n"
                    f"<code>   R:{str(runs).rjust(4)}  B:{str(bf).rjust(3)}  "
                    f"4s:{str(fours).rjust(2)}  6s:{str(sixes).rjust(2)}  SR:{sr.rjust(6)}</code>\n"
                )
            text += "\n"

        bowl_players = [p for p in team.get("players", []) if p.get("balls_bowled", 0) > 0]
        if bowl_players:
            text += (
                "🥎 <b>BOWLING</b>\n"
                "<code>Bowler            O    R    W    ECO</code>\n"
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            )
            for p in bowl_players:
                bb       = p["balls_bowled"]
                conceded = p.get("conceded", 0)
                wkts     = p.get("wickets", 0)
                eco      = _fmt_eco(conceded, bb)
                ov_str   = _fmt_overs(bb)
                is_cur   = is_playing and p.get("id") == current_bowler.get("id")
                bowl_tag = "  🎯 <i>bowling</i>" if is_cur else ""
                text += (
                    f"\n{'🎯' if is_cur else '🥎'} <b>{p['name']}</b>{bowl_tag}\n"
                    f"<code>   O:{ov_str.rjust(4)}  R:{str(conceded).rjust(4)}  "
                    f"W:{str(wkts).rjust(2)}  ECO:{eco.rjust(5)}</code>\n"
                )
                spells = list(p.get("bowling_spells", []))
                if is_cur and p.get("_spell_balls0") is not None:
                    _lb = bb - p["_spell_balls0"]
                    _lr = conceded - p.get("_spell_runs0", 0)
                    _lw = wkts - p.get("_spell_wkts0", 0)
                    if _lb > 0:
                        spells.append({"b": _lb, "r": _lr, "w": _lw, "live": True})
                if spells:
                    parts = [
                        f"Sp{idx}{'●' if s.get('live') else ''}:{_fmt_overs(s['b'])}ov·{s['r']}R·{s['w']}W"
                        for idx, s in enumerate(spells, 1)
                    ]
                    text += f"   📋 {' | '.join(parts)}\n"
            text += "\n"
        text += "\n"

    if state == "TEAM_FINISHED":
        ta = game.get("team_a", {}).get("score", 0)
        tb = game.get("team_b", {}).get("score", 0)
        if ta > tb:
            result_str = f"🎉 <b>Team A 🔴 WINS by {ta - tb} runs!</b>\n"
        elif tb > ta:
            result_str = f"🎉 <b>Team B 🔵 WINS by {tb - ta} runs!</b>\n"
        else:
            result_str = "🤝 <b>IT'S A TIE!</b> 🤝\n"
        text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{result_str}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    return text


def get_potm(game):
    best = get_potm_data(game)
    if best:
        bid = best["id"]
        return (
            f"\n🏅 <b>PLAYER OF THE MATCH: {_men(bid, best['name'])}</b> 🏅\n"
            "Here is your reward, take this 💋\n"
        )
    return ""


def generate_teams_message(game):
    text       = "🏟️ <b>TEAMS ROSTER</b> 🏟️\n\n"
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
                    if p.get("is_out"):         status = " - (Out)"
                    elif p.get("is_striker"):   status = " - (On Strike)"
                    elif p.get("is_non_striker"): status = " - (Non Striker)"
                    else:                       status = " - (Available)"
                elif team_dict is bowl_team:
                    cb = game.get("current_bowler") or {}
                    if cb.get("id") == p["id"]: status = " - (Bowling)"
            pid, pname = p["id"], p["name"]
            text += f" {p.get('num', i)}. {_men(pid, pname)}{cap}<i>{status}</i>\n"
        text += "\n"
    return text


# ---------------------------------------------------------------------------
# Scorecard sender
# ---------------------------------------------------------------------------

async def trigger_full_scorecard_message(context, chat_id, game_data):
    scorecard  = generate_scorecard(game_data)
    potm_text  = get_potm(game_data) if game_data.get("state") in ["NOT_PLAYING", "TEAM_FINISHED"] else ""
    final_text = f"{scorecard}{potm_text}"

    markup = None
    if game_data.get("state") in ["NOT_PLAYING", "TEAM_FINISHED"]:
        global _BOT_USERNAME_CACHE
        if not _BOT_USERNAME_CACHE:
            try:
                bi = await asyncio.wait_for(context.bot.get_me(), timeout=4)
                _BOT_USERNAME_CACHE = bi.username
            except Exception:
                _BOT_USERNAME_CACHE = "cricketbot"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("PLAY AGAIN 🔄", callback_data="play_again")],
            [InlineKeyboardButton(
                "ADD IN GROUP ➕",
                url=f"https://t.me/{_BOT_USERNAME_CACHE}?startgroup=true"
            )],
        ])

    MAX_CAPTION = 1024
    use_sep = len(final_text) > MAX_CAPTION

    if game_data.get("mode") == "TEAM":
        img_bytes = None
        try:
            img_bytes = await asyncio.wait_for(
                generate_team_scoreboard_image(context, chat_id, game_data),
                timeout=10,
            )
        except Exception:
            pass
        photo = io.BytesIO(img_bytes) if img_bytes else SCOREBOARD_IMG
        try:
            if use_sep:
                await context.bot.send_photo(chat_id, photo=photo,
                                             caption="📊 <b>TEAM SCORECARD</b> — see details below.",
                                             parse_mode="HTML")
                await context.bot.send_message(chat_id, text=final_text,
                                               parse_mode="HTML", reply_markup=markup)
            else:
                await context.bot.send_photo(chat_id, photo=photo,
                                             caption=final_text, parse_mode="HTML",
                                             reply_markup=markup)
            return
        except Exception:
            pass
        # fallback text
        await context.bot.send_message(chat_id, text=final_text, parse_mode="HTML", reply_markup=markup)
    else:
        try:
            if use_sep:
                await context.bot.send_photo(chat_id, photo=SCOREBOARD_IMG,
                                             caption="📊 <b>SCORECARD</b> — see details below.",
                                             parse_mode="HTML")
                await context.bot.send_message(chat_id, text=final_text,
                                               parse_mode="HTML", reply_markup=markup)
            else:
                await context.bot.send_photo(chat_id, photo=SCOREBOARD_IMG,
                                             caption=final_text, parse_mode="HTML",
                                             reply_markup=markup)
        except Exception:
            await context.bot.send_message(chat_id, text=final_text,
                                           parse_mode="HTML", reply_markup=markup)


async def send_top_performers_message(context, chat_id, game):
    text = "🌟 <b>TOP PERFORMERS OF THE MATCH</b> 🌟\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for team_key, team_name in [("team_a", "🔴 TEAM A"), ("team_b", "🔵 TEAM B")]:
        team = game.get(team_key)
        if not team or not team.get("players"):
            continue
        best_batter = max(team["players"], key=lambda x: x.get("runs", 0))
        best_bowler = max(team["players"],
                          key=lambda x: x.get("wickets", 0) * 100 - x.get("conceded", 0))
        b_ov, b_bl  = divmod(best_bowler.get("balls_bowled", 0), 6)
        text += (
            f"\n<b>{team_name}</b>\n"
            f"🏏 <b>Best Batter:</b> {best_batter['name'][:15]} ➜ "
            f"<b>{best_batter.get('runs', 0)}</b> ({best_batter.get('balls_faced', 0)})\n"
            f"🥎 <b>Best Bowler:</b> {best_bowler['name'][:15]} ➜ "
            f"<b>{best_bowler.get('wickets', 0)}W</b> for {best_bowler.get('conceded', 0)}R "
            f"({b_ov}.{b_bl} Ov)\n"
        )
    text += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
    await context.bot.send_message(chat_id, text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# Duck message
# ---------------------------------------------------------------------------

async def send_duck_message(context, chat_id, players):
    ducks = [
        p for p in players
        if p.get("runs", 0) == 0 and p.get("is_out", False) and p.get("balls_faced", 0) > 0
    ]
    if not ducks:
        return
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "😬 <b>USERS WHO SHOULD RETIRE</b> 😬\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    for p in ducks:
        uname = ""
        if users_col is not None:
            try:
                u = await users_col.find_one({"user_id": p["id"]}, {"username": 1})
                if u and u.get("username"):
                    uname = f" (@{u['username']})"
            except Exception:
                pass
        pid = p["id"]
        text += f"🦆 {_men(pid, p['name'])}{uname}\n"
    text += "\n<i>Better luck next time! 🏏</i>"
    try:
        await context.bot.send_message(chat_id, text, parse_mode="HTML")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Praise #1 ranked player — called as fire-and-forget task
# ---------------------------------------------------------------------------

async def maybe_praise_rank1(context, chat_id, game, player, role):
    if users_col is None:
        return
    praise_key = f"_praised_{player['id']}_{role}"
    if game.get(praise_key):
        return
    game[praise_key] = True

    praises = []
    try:
        pid = player["id"]
        top_run = await users_col.find_one({"total_runs": {"$gt": 0}}, sort=[("total_runs", -1)])
        if top_run and top_run.get("user_id") == pid:
            praises.append("🏃 <b>All-Time Runs Leader</b>")
        if role == "BOWLER":
            top_wkt = await users_col.find_one({"wickets": {"$gt": 0}}, sort=[("wickets", -1)])
            if top_wkt and top_wkt.get("user_id") == pid:
                praises.append("🥎 <b>All-Time Wickets Leader</b>")
    except Exception:
        return

    if praises:
        role_emoji = "🏏" if role == "BATTER" else "🥎"
        praise_str = " & ".join(praises)
        pid = player["id"]
        try:
            await context.bot.send_message(
                chat_id,
                f"👑 <b>LEGEND HAS ARRIVED!</b> 👑\n\n"
                f"{role_emoji} {_men(pid, player['name'])} "
                f"is the {praise_str} in the Hall of Fame! 🌟\n"
                "All eyes are on them! Can they deliver today? 🔥",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# AFK system
# ---------------------------------------------------------------------------

def set_afk_timer(context, chat_id, user_id, role):
    clear_afk_timer(context, chat_id)
    game = context.bot_data.get(chat_id)
    if not game:
        return
    afk_fn = (team_afk_warning_10, team_afk_warning_30, team_afk_timeout) if game.get("mode") == "TEAM" \
             else (afk_warning_start, afk_warning_30, afk_timeout)
    data = {"chat_id": chat_id, "user_id": user_id, "role": role}
    context.job_queue.run_once(afk_fn[0], 10,  data=data, name=f"afk10_{chat_id}")
    context.job_queue.run_once(afk_fn[1], 30,  data=data, name=f"afk30_{chat_id}")
    context.job_queue.run_once(afk_fn[2], 60,  data=data, name=f"afk60_{chat_id}")


def clear_afk_timer(context, chat_id):
    for prefix in ["afk10_", "afk30_", "afk60_"]:
        for job in context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}"):
            job.schedule_removal()


async def check_solo_winner_exp(game):
    if game.get("mode") == "SOLO" and game.get("players"):
        best = max(game["players"], key=lambda x: x.get("runs", 0))
        await update_user_db(best["id"], {"exp": 60})


def _role_matches(game, role, waiting):
    return (waiting == role) or (role == "BATTER" and waiting == "PROCESSING_BATTER")


async def afk_warning_start(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or not _role_matches(game, role, game.get("waiting_for", "")):
        return
    player = next((p for p in game.get("players", []) if p["id"] == user_id), None)
    if not player:
        return
    pid = player["id"]
    await context.bot.send_message(
        chat_id,
        f"⚠️ {_men(pid, player['name'])}, it is your turn! You have <b>50 seconds</b> to play. ⏳",
        parse_mode="HTML",
    )


async def afk_warning_30(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or not _role_matches(game, role, game.get("waiting_for", "")):
        return
    player = next((p for p in game.get("players", []) if p["id"] == user_id), None)
    if not player:
        return
    pid = player["id"]
    await context.bot.send_message(
        chat_id,
        f"⚠️ {_men(pid, player['name'])}, HURRY UP! You only have <b>30 seconds</b> left! ⏰",
        parse_mode="HTML",
    )


async def afk_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or not _role_matches(game, role, game.get("waiting_for", "")):
        return
    player = next((p for p in game.get("players", []) if p["id"] == user_id), None)
    if not player:
        return
    await context.bot.send_message(
        chat_id,
        f"⏳ <b>TIME'S UP!</b> {player['name']} was AFK for 60 seconds and has been ELIMINATED! ❌",
        parse_mode="HTML",
    )
    game["players"] = [p for p in game["players"] if p["id"] != user_id]
    if len(game["players"]) < 2:
        await commit_player_stats(game)
        game["state"] = "NOT_PLAYING"
        await context.bot.send_message(chat_id, "Not enough players left! Match abandoned. 🛑")
        return
    if game["batter_idx"] >= len(game["players"]):
        await check_solo_winner_exp(game)
        await commit_player_stats(game)
        game["state"] = "NOT_PLAYING"
        await context.bot.send_message(chat_id, "🏁 <b>MATCH FINISHED!</b> 🏁", parse_mode="HTML")
        await trigger_full_scorecard_message(context, chat_id, game)
        return
    available = [i for i in range(len(game["players"])) if i != game["batter_idx"]]
    if not available:
        await commit_player_stats(game)
        game["state"] = "NOT_PLAYING"
        return
    game["bowler_idx"]            = random.choice(available)
    game["waiting_for"]           = "BOWLER"
    game["balls_bowled"]          = 0
    game["special_used_this_over"] = False
    await trigger_bowl(context, chat_id)


async def team_afk_warning_10(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or not _role_matches(game, role, game.get("waiting_for", "")):
        return
    all_players = game.get("team_a", {}).get("players", []) + game.get("team_b", {}).get("players", [])
    player = next((p for p in all_players if p["id"] == user_id), None)
    if not player:
        return
    pid = player["id"]
    await context.bot.send_message(
        chat_id,
        f"⚠️ {_men(pid, player['name'])}, you have been AFK! <b>50 more seconds</b> left. ⏳",
        parse_mode="HTML",
    )


async def team_afk_warning_30(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or not _role_matches(game, role, game.get("waiting_for", "")):
        return
    all_players = game.get("team_a", {}).get("players", []) + game.get("team_b", {}).get("players", [])
    player = next((p for p in all_players if p["id"] == user_id), None)
    if not player:
        return
    pid = player["id"]
    await context.bot.send_message(
        chat_id,
        f"⚠️ {_men(pid, player['name'])}, HURRY UP! <b>30 seconds</b> left! ⏰",
        parse_mode="HTML",
    )


async def team_afk_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or not _role_matches(game, role, game.get("waiting_for", "")):
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
            f"⏳ <b>TIME'S UP!</b> {player['name']} was AFK! ❌\n📉 <b>PENALTY:</b> -5 Runs. OUT!",
            parse_mode="HTML",
        )
        if game["batting_team_ref"]["wickets"] >= len(game["batting_team_ref"]["players"]) - 1:
            await process_team_innings_end(context, chat_id, game)
            return
        game["waiting_for"] = "TEAM_BATTER_SELECT"
        await context.bot.send_message(
            chat_id, "🏏 Captain/Host, select the next batter using <code>/batting [number]</code>.",
            parse_mode="HTML",
        )
    elif role == "BOWLER":
        game["batting_team_ref"]["score"] += 5
        player["conceded"] = player.get("conceded", 0) + 5
        await context.bot.send_message(
            chat_id,
            f"⏳ <b>TIME'S UP!</b> {player['name']} timed out! ❌\n📈 <b>PENALTY:</b> +5 Runs!\n"
            "Captain/Host, select a NEW bowler using <code>/bowling [number]</code>.",
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
        f"35 seconds left to join. (Total: {len(game['players'])}) 🏏",
        parse_mode="HTML",
    )


async def auto_start_match(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
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
        if len(game["players"]) > 1:
            _fb = game["players"][1]
            _fb["_spell_balls0"] = _fb.get("balls_bowled", 0)
            _fb["_spell_runs0"]  = _fb.get("conceded", 0)
            _fb["_spell_wkts0"]  = _fb.get("wickets", 0)
        await context.bot.send_message(
            chat_id, "⏳ <b>70 seconds are up! THE MATCH AUTO-STARTS NOW!</b> 🚨", parse_mode="HTML",
        )
        await trigger_bowl(context, chat_id)
    else:
        game["state"] = "NOT_PLAYING"
        await context.bot.send_message(
            chat_id, "⏳ <b>Not enough players!</b> Match setup abandoned. 🛑", parse_mode="HTML",
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
        "Who will lead the teams? Members click your team's button to become Captain! ⚡",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def team_join_timeout(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
    game    = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_JOINING":
        return
    if len(game["team_a"]["players"]) < 2 or len(game["team_b"]["players"]) < 2:
        game["is_paused_waiting_players"] = True
        await context.bot.send_message(
            chat_id,
            "⏳ Time's up! But we need at least 2 players in each team! The queue is paused. ⏸️\n"
            "Once both teams have 2 players, setup will automatically proceed!",
            parse_mode="HTML",
        )
        return
    await trigger_team_captains(context, chat_id, game)


async def spamfree_timeout(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
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
    global _BOT_USERNAME_CACHE

    if chat_type != "private":
        current_time = time.time()
        cooldown = context.bot_data.get(f"start_cooldown_{chat_id}", 0)
        if current_time < cooldown:
            rem = int(cooldown - current_time)
            await update.message.reply_text(f"⏳ Cooldown! Try again in {rem}s.")
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
                    bowler = (
                        game["players"][game["bowler_idx"]]
                        if game.get("mode") == "SOLO"
                        else game.get("current_bowler")
                    )
                    if bowler and update.effective_user.id == bowler["id"]:
                        keyboard = []
                        if not game.get("special_used_this_over") and game.get("mode") != "TEAM":
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

        if not _BOT_USERNAME_CACHE:
            try:
                bi = await asyncio.wait_for(context.bot.get_me(), timeout=4)
                _BOT_USERNAME_CACHE = bi.username
            except Exception:
                _BOT_USERNAME_CACHE = "cricketbot"

        kb_private = [
            [InlineKeyboardButton("ADD IN GROUP TO PLAY ➕", url=f"https://t.me/{_BOT_USERNAME_CACHE}?startgroup=true")],
            [InlineKeyboardButton("STATS 📊", callback_data="dm_stats"),
             InlineKeyboardButton("RANKINGS 🏆", callback_data="dm_rankings")],
            [InlineKeyboardButton("Support Group 💬", url="https://t.me/eclplays")],
            [InlineKeyboardButton("Contact Developer 👨‍💻", url="https://t.me/xrztz")],
        ]
        await update.message.reply_photo(
            photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777818831/file_00000000677c71fa8d7d9caa8a1b3cc9_k7l0au.png",
            caption=(
                "🏏 <b>PLAY LIVE CRICKET INSIDE TELEGRAM</b>\n\n"
                "⚡ Real-time matches\n🏆 Compete with friends\n🎯 Become LEGEND 👑\n\nReady to dominate?"
            ),
            reply_markup=InlineKeyboardMarkup(kb_private),
            parse_mode="HTML",
        )
        return

    game = context.bot_data.get(chat_id)
    if game is None:
        game = {"state": "NOT_PLAYING"}
        context.bot_data[chat_id] = game

    if game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
        await update.message.reply_text("❌ A match is already active! Use /endmatch first.")
        return

    game["start_initiator_id"] = update.effective_user.id
    context.bot_data[f"mode_select_lock_{chat_id}"] = asyncio.Lock()

    keyboard = [
        [InlineKeyboardButton("🏏 Solo Game",   callback_data="solo_game"),
         InlineKeyboardButton("👥 Team Game",   callback_data="team_game")],
        [InlineKeyboardButton("🏆 Tournaments", callback_data="tournaments"),
         InlineKeyboardButton("❌ Cancel",       callback_data="cancel")],
    ]
    await update.message.reply_photo(
        photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777690770/IMG_20260502_082816_001_t0wejv.jpg",
        caption=(
            "Welcome to the <b>ELITE CRICKET BOT</b> Arena! 🏆\n"
            "Join our official community at @eclplays. 🏏\n\n"
            "🔥 <b>A tournament is currently going on! Register via @eclregisbot</b> 🔥\n\n"
            "Choose your mode: 👇"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def create_team_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_SETUP_HOST":
        await update.message.reply_text("❌ No team game setup active! Click 'Team Game' in /start first.")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can create teams!")
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
        "Players, choose your sides! 10 seconds to join. ⏳\n"
        "<b>(Host: /rejoin to extend 30s | /add | /remove)</b>",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


async def changecap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM":
        await update.message.reply_text("❌ No active team match!")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can change captains!")
        return
    if not context.args or context.args[0].lower() not in ["a", "b"]:
        await update.message.reply_text("Usage: /changecap a OR /changecap b")
        return
    team_key = f"team_{context.args[0].lower()}"
    target_user, target_username = get_user_from_mention(update)
    target_player = None
    if target_user:
        target_player = next((p for p in game[team_key]["players"] if p["id"] == target_user.id), None)
    elif target_username:
        target_player = next((p for p in game[team_key]["players"] if p.get("username") == target_username), None)
    if not target_player:
        await update.message.reply_text(f"❌ User not found in Team {context.args[0].upper()}!")
        return
    game[team_key]["captain"] = target_player["id"]
    await update.message.reply_text(f"✅ Team {context.args[0].upper()} captain changed to {target_player['name']}!")


async def rejoin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game    = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_JOINING" or update.effective_user.id != game.get("host_id"):
        return
    for job in context.job_queue.get_jobs_by_name(f"team_join_{chat_id}"):
        job.schedule_removal()
    context.job_queue.run_once(team_join_timeout, 30, data={"chat_id": chat_id}, name=f"team_join_{chat_id}")
    await update.message.reply_text("⏳ <b>Registration Extended!</b> 30 more seconds to join! 👥", parse_mode="HTML")


async def changeover_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM" or game.get("state") != "PLAYING":
        await update.message.reply_text("❌ No active team match!")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can change overs!")
        return
    if game.get("innings") != 1:
        await update.message.reply_text("❌ Can only change overs during 1st innings!")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /changeover [number]")
        return
    new_overs    = int(context.args[0])
    played_overs = game["bowling_team_ref"]["balls_bowled"] // 6
    if new_overs <= played_overs:
        await update.message.reply_text(f"❌ Match has already crossed {played_overs} overs!")
        return
    game["target_overs"] = new_overs
    await update.message.reply_text(f"✅ Overs updated to <b>{new_overs}</b>!", parse_mode="HTML")


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM":
        await update.message.reply_text("❌ No active team match setup!")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can add players!")
        return
    if not context.args or context.args[0].lower() not in ["a", "b"]:
        await update.message.reply_text("Usage: /add a OR /add b")
        return
    team_key = f"team_{context.args[0].lower()}"
    target_user, target_username = get_user_from_mention(update)
    if not target_user and target_username and users_col is not None:
        db_user = await users_col.find_one({"username": target_username})
        if db_user:
            class DummyUser:
                def __init__(self, uid, fname, uname):
                    self.id = uid; self.first_name = fname
                    self.username = uname; self.is_bot = False
            target_user = DummyUser(db_user["user_id"], db_user["first_name"], db_user["username"])
    if not target_user:
        await update.message.reply_text("❌ Please reply to a user's message or use @username (must have played before)!")
        return
    if target_user.is_bot:
        await update.message.reply_text("❌ Cannot add a bot!")
        return
    if is_user_playing_anywhere(context, target_user.id):
        await update.message.reply_text("❌ User is already in a game.")
        return
    in_a = any(p["id"] == target_user.id for p in game["team_a"]["players"])
    in_b = any(p["id"] == target_user.id for p in game["team_b"]["players"])
    if in_a or in_b:
        await update.message.reply_text(f"❌ {target_user.first_name} is already in a team!")
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
    team_name = "TEAM A 🔴" if context.args[0].lower() == "a" else "TEAM B 🔵"
    await update.message.reply_text(
        f"✅ <b>{target_user.first_name}</b> added to {team_name}!", parse_mode="HTML",
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
        await update.message.reply_text("❌ No active team match setup!")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can remove players!")
        return
    target_user, target_username = get_user_from_mention(update)
    if not target_user and not target_username:
        await update.message.reply_text("❌ Reply to a user's message or tag their @username!")
        return
    removed = False; target_name = ""
    for team_key in ["team_a", "team_b"]:
        for p in list(game[team_key]["players"]):
            if (target_user and p["id"] == target_user.id) or \
               (target_username and p.get("username") == target_username):
                striker = game.get("striker") or {}
                ns      = game.get("non_striker") or {}
                if p["id"] in {striker.get("id"), ns.get("id")}:
                    await update.message.reply_text(
                        f"❌ Cannot remove <b>{p['name']}</b> — they are currently batting!",
                        parse_mode="HTML",
                    )
                    return
                target_name = p["name"]
                game[team_key]["players"].remove(p)
                for i, pr in enumerate(game[team_key]["players"], 1):
                    pr["num"] = i
                removed = True
                break
    if removed:
        await update.message.reply_text(f"✅ <b>{target_name}</b> removed from their team! 🚪", parse_mode="HTML")
    else:
        name_str = target_user.first_name if target_user else target_username
        await update.message.reply_text(f"❌ {name_str} is not in any team!")


async def changehost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM" or game.get("state") in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
        await update.message.reply_text("❌ No active team match!")
        return
    user_id = update.effective_user.id
    is_host = (user_id == game.get("host_id"))
    in_game = (
        any(p["id"] == user_id for p in game.get("team_a", {}).get("players", []))
        or any(p["id"] == user_id for p in game.get("team_b", {}).get("players", []))
    )
    if not (is_host or in_game):
        await update.message.reply_text("⚠️ Only the Host or active players can use this!")
        return
    target_user, target_username = get_user_from_mention(update)
    if not target_user and target_username and users_col is not None:
        db_user = await users_col.find_one({"username": target_username})
        if db_user:
            class DummyUser:
                def __init__(self, uid, fname, uname):
                    self.id = uid; self.first_name = fname
                    self.username = uname; self.is_bot = False
            target_user = DummyUser(db_user["user_id"], db_user["first_name"], db_user["username"])
    if not target_user:
        await update.message.reply_text("❌ Reply to user or use @username (must have played before)!")
        return
    if target_user.is_bot:
        await update.message.reply_text("❌ A bot cannot be the Host!")
        return
    if is_host:
        game["host_id"] = target_user.id
        await update.message.reply_text(
            f"✅ Host privileges transferred to <b>{target_user.first_name}</b>! 👑",
            parse_mode="HTML",
        )
    else:
        game["host_vote_target"] = target_user.id
        game["host_vote_name"]   = target_user.first_name
        game["host_votes"]       = set()
        kb = [[InlineKeyboardButton("Vote ✅ (0/4)", callback_data="vote_host")]]
        await update.message.reply_text(
            f"🗳️ Vote to change host to <b>{target_user.first_name}</b>! 4 votes required.",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML",
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
        await update.message.reply_text("❌ You are already in a game or queue.")
        return
    if any(p["id"] == user.id for p in game.get("players", [])):
        await update.message.reply_text(f"⚠️ <b>{user.first_name}</b>, you are ALREADY in the queue! ⏳", parse_mode="HTML")
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
        timer_msg = "\n⏳ <i>Auto-start in 70 seconds!</i>"
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
        await update.message.reply_text("❌ Match already started! You can't leave now.")
        return
    if game.get("state") == "JOINING":
        user_id = update.effective_user.id
        if any(p["id"] == user_id for p in game.get("players", [])):
            game["players"] = [p for p in game["players"] if p["id"] != user_id]
            await update.message.reply_text(
                f"👋 <b>{update.effective_user.first_name}</b> left the queue. (Total: {len(game['players'])}) 👥",
                parse_mode="HTML",
            )
            if not game["players"]:
                for pfx in ["autostart_", "queueremind_"]:
                    for job in context.job_queue.get_jobs_by_name(f"{pfx}{chat_id}"):
                        job.schedule_removal()
                await update.message.reply_text("Queue is empty! Timer stopped.")
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
    for pfx in ["autostart_", "queueremind_"]:
        for job in context.job_queue.get_jobs_by_name(f"{pfx}{chat_id}"):
            job.schedule_removal()
    game.update({
        "state": "PLAYING", "waiting_for": "BOWLER",
        "batter_idx": 0, "bowler_idx": 1,
        "balls_bowled": 0, "special_used_this_over": False, "is_free_hit": False,
    })
    if len(game["players"]) > 1:
        _fb = game["players"][1]
        _fb["_spell_balls0"] = _fb.get("balls_bowled", 0)
        _fb["_spell_runs0"]  = _fb.get("conceded", 0)
        _fb["_spell_wkts0"]  = _fb.get("wickets", 0)
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
        await update.message.reply_text("❌ No active match to end!")
        return
    keyboard = [
        [InlineKeyboardButton("Yes, End Match ✅", callback_data=f"endmatch_yes_{chat_id}")],
        [InlineKeyboardButton("Cancel ❌",          callback_data=f"endmatch_no_{chat_id}")],
    ]
    await update.message.reply_text(
        "⚠️ <b>Admin Action:</b> Sure you want to force-end the match?",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML",
    )


async def soloscore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "SOLO" or game.get("state") in ["NOT_PLAYING", None]:
        await update.message.reply_text("❌ No active solo match!")
        return
    await trigger_full_scorecard_message(context, chat_id, game)


async def teamscore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM" or game.get("state") in ["NOT_PLAYING", None]:
        await update.message.reply_text("❌ No active team match!")
        return
    await trigger_full_scorecard_message(context, chat_id, game)


async def teams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM" or game.get("state") in ["NOT_PLAYING", "TEAM_SETUP_HOST"]:
        await update.message.reply_text("❌ No active team match!")
        return
    roster = generate_teams_message(game)
    await update.message.reply_photo(photo=TEAMS_ROSTER_IMG, caption=roster, parse_mode="HTML")


async def batting_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM":
        await update.message.reply_text("❌ Team matches only.")
        return
    if game.get("state") != "PLAYING":
        await update.message.reply_text("❌ Match hasn't started yet!")
        return
    if game.get("waiting_for") not in ["TEAM_OPENERS_BAT", "TEAM_BATTER_SELECT"]:
        await update.message.reply_text("❌ Batters are already on the pitch!")
        return
    batting_team = game["batting_team_ref"]
    if not context.args or not context.args[0].isdigit():
        text = "🏏 <b>AVAILABLE BATTERS:</b>\n"
        for p in batting_team.get("players", []):
            if p.get("is_out"):                      status = "❌ (Out)"
            elif p.get("is_striker") or p.get("is_non_striker"): status = "🏏 (On Pitch)"
            else:                                    status = "✅ (Available)"
            text += f"[{p.get('num', '?')}] {p['name']} - {status}\n"
        text += "\n👉 <i>Usage: /batting [number]</i>"
        await update.message.reply_text(text, parse_mode="HTML")
        return
    if update.effective_user.id not in [batting_team.get("captain"), game.get("host_id")]:
        await update.message.reply_text("❌ Only the Host or Batting Captain can select the batter!")
        return
    p_num    = int(context.args[0])
    selected = next((p for p in batting_team.get("players", []) if p.get("num") == p_num), None)
    if not selected:
        await update.message.reply_text(f"❌ Player {p_num} not found in your team!")
        return
    if selected.get("is_out"):
        await update.message.reply_text(f"❌ {selected['name']} is already out!")
        return
    striker    = game.get("striker") or {}
    ns         = game.get("non_striker") or {}
    if selected["id"] in {striker.get("id"), ns.get("id")}:
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
            await send_media_safely(
                context, chat_id, openers_gif,
                f"🏏 <b>{selected['name']}</b> selected as Non-Striker!\n\n"
                "Bowling Captain/Host, type /bowling [num] to select the opening bowler.",
            )
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
                "Bowling Captain/Host, select the next bowler using <code>/bowling [num]</code>.",
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
        await update.message.reply_text("❌ Team matches only.")
        return
    if game.get("state") != "PLAYING":
        await update.message.reply_text("❌ Match hasn't started yet!")
        return
    if game.get("waiting_for") in ["TEAM_OPENERS_BAT", "TEAM_BATTER_SELECT"]:
        await update.message.reply_text("❌ Batters not selected yet!")
        return
    if game.get("waiting_for") != "TEAM_BOWLER_SELECT":
        await update.message.reply_text("❌ A bowler is already bowling!")
        return
    bowling_team = game["bowling_team_ref"]
    if not context.args or not context.args[0].isdigit():
        text = "🥎 <b>AVAILABLE BOWLERS:</b>\n"
        for p in bowling_team.get("players", []):
            status = "✅ (Available)"
            if game.get("last_bowler_id") == p["id"]: status = "⏳ (Bowled Last Over)"
            cb = game.get("current_bowler") or {}
            if cb.get("id") == p["id"]:              status = "🥎 (Bowling Now)"
            text += f"[{p.get('num', '?')}] {p['name']} - {p.get('balls_bowled', 0)//6}.{p.get('balls_bowled', 0)%6} Ov - {status}\n"
        text += "\n👉 <i>Usage: /bowling [number]</i>"
        await update.message.reply_text(text, parse_mode="HTML")
        return
    if update.effective_user.id not in [bowling_team.get("captain"), game.get("host_id")]:
        await update.message.reply_text("❌ Only the Host or Bowling Captain can select the bowler!")
        return
    p_num    = int(context.args[0])
    selected = next((p for p in bowling_team.get("players", []) if p.get("num") == p_num), None)
    if not selected:
        await update.message.reply_text(f"❌ Player {p_num} not found!")
        return
    if game.get("last_bowler_id") == selected["id"]:
        await update.message.reply_text("❌ A bowler cannot bowl two consecutive overs!")
        return
    game["current_bowler"] = selected
    game["waiting_for"]    = "BOWLER"
    selected["_spell_balls0"] = selected.get("balls_bowled", 0)
    selected["_spell_runs0"]  = selected.get("conceded", 0)
    selected["_spell_wkts0"]  = selected.get("wickets", 0)
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

        batting_innings = user_data.get("batting_innings", 0)
        dismissals      = user_data.get("dismissals", 0)
        avg = total_runs / dismissals if dismissals > 0 else (float(total_runs) if batting_innings > 0 else 0.0)

        exp   = user_data.get("exp", 0)
        level = get_user_level(exp)
        next_level_name, exp_needed = get_next_level_info(exp)
        exp_line = (
            f"⭐ <b>EXP:</b> {exp} | Next: <b>{next_level_name}</b> (Need {exp_needed} more EXP)\n"
            if next_level_name
            else f"⭐ <b>EXP:</b> {exp} | 🏆 <b>MAX LEVEL REACHED!</b>\n"
        )
        st = (
            f"📊 <b>{level} STATISTICS</b> 📊\n══════════════════════\n"
            f"👤 <b>Name:</b> {user_data.get('first_name', 'Unknown')}\n"
            f"🆔 <b>ID:</b> <code>{user_data.get('user_id', 'Unknown')}</code>\n"
            f"{exp_line}┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"🏏 <b>BATTING STATS</b>\n"
            f"🔸 <b>Highest Score:</b> {hs_runs} ({hs_balls})\n"
            f"🔸 <b>Total Runs:</b> {total_runs}\n"
            f"🔸 <b>Batting Avg:</b> {avg:.2f}\n"
            f"🔸 <b>Strike Rate:</b> {sr:.2f}\n"
            f"🔸 <b>6s:</b> {user_data.get('total_6s', 0)} | <b>4s:</b> {user_data.get('total_4s', 0)}\n"
            f"🔸 <b>100s:</b> {user_data.get('centuries', 0)} | <b>50s:</b> {user_data.get('half_centuries', 0)}\n"
            f"🔸 <b>Ducks 🦆:</b> {user_data.get('ducks', 0)}\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"🥎 <b>BOWLING STATS</b>\n"
            f"🔹 <b>Wickets:</b> {user_data.get('wickets', 0)}\n"
            f"🔹 <b>Hat-Tricks:</b> {user_data.get('hat_tricks', 0)}\n"
            f"🔹 <b>Overs Bowled:</b> {overs}.{rem_balls}\n"
            f"🔹 <b>Economy:</b> {eco:.2f}\n"
            f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
            f"🏆 <b>MATCH &amp; AWARDS</b>\n"
            f"🔸 <b>Solo Matches:</b> {user_data.get('solo_matches', 0)}\n"
            f"🔸 <b>Team Matches:</b> {user_data.get('team_matches', 0)}\n"
            f"🔸 <b>Batting Innings:</b> {batting_innings}\n"
            f"🔸 <b>MOTM Awards:</b> {user_data.get('motm', 0)}\n"
            f"══════════════════════"
        )
        stats_img = "https://res.cloudinary.com/dxgfxfoog/image/upload/v1777818873/file_00000000fa6871fa8d9b30faff9899ae_hbyn9j.png"
        await msg.reply_photo(photo=stats_img, caption=st, parse_mode="HTML")
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
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML",
    )


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ You ain't the owner of this bot.")
        return
    message_to_send = update.message.reply_to_message
    text = None
    if not message_to_send:
        if not context.args:
            await update.message.reply_text("Usage: /broadcast <message> or reply to a message")
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
                await context.bot.copy_message(chat_id=cid, from_chat_id=update.effective_chat.id,
                                               message_id=message_to_send.message_id)
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
        await update.message.reply_text("❌ Owner only.")
        return
    if users_col is None:
        await update.message.reply_text("Database not connected.")
        return
    users_count, groups_count, loyals_count = await asyncio.gather(
        users_col.count_documents({}),
        chats_col.count_documents({"type": {"$in": ["group", "supergroup"]}}),
        chats_col.count_documents({"type": "private"}),
    )
    await update.message.reply_text(
        f"📊 <b>Bot Statistics</b>\n\n"
        f"👤 Total Users: {users_count}\n"
        f"👥 Total Groups: {groups_count}\n"
        f"💌 Bot Loyals (DM): {loyals_count}",
        parse_mode="HTML",
    )


async def botgroups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only.")
        return
    if chats_col is None:
        await update.message.reply_text("Database not connected.")
        return
    groups = await chats_col.find({"type": {"$in": ["group", "supergroup"]}}).to_list(1000)
    if not groups:
        await update.message.reply_text("Bot is not in any groups right now.")
        return
    text = f"📊 <b>Bot Groups ({len(groups)}):</b>\n\n"
    for i, g in enumerate(groups, 1):
        text += f"{i}. {g.get('title', 'Unknown')} (<code>{g['chat_id']}</code>)\n"
    if len(text) > 4000:
        text = text[:4000] + "...\n[Truncated]"
    await update.message.reply_text(text, parse_mode="HTML")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🏏 Solo Game Guide",  callback_data="help_solo")],
        [InlineKeyboardButton("👥 Team Game Guide",  callback_data="help_team")],
        [InlineKeyboardButton("🎯 Yorker Rules",     callback_data="help_yorker")],
        [InlineKeyboardButton("⏳ AFK Penalties",    callback_data="help_afk")],
        [InlineKeyboardButton("📊 Commands List",    callback_data="help_commands")],
        [InlineKeyboardButton("⭐ Level System",     callback_data="help_levels")],
    ]
    await update.message.reply_text(
        "🏏 <b>ELITE CRICKET BOT — HELP CENTER</b> 🏆\n\nSelect a topic below:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML",
    )


async def spamfree_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_SPAMFREE_WAIT":
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can use /spamfree!")
        return
    for job in context.job_queue.get_jobs_by_name(f"spamfree_{chat_id}"):
        job.schedule_removal()
    game["spamfree"] = True
    game["state"]    = "PLAYING"
    await update.message.reply_text(
        "🛡️ <b>SPAM-FREE MODE ACTIVATED!</b>\n\n"
        "Batting Captain/Host, select your opening pair:\n"
        "<code>/batting [number]</code> (do it twice).",
        parse_mode="HTML",
    )


async def resetweekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only command to reset weekly leaderboard to zero."""
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only command.")
        return
    if users_col is None:
        await update.message.reply_text("❌ Database not connected.")
        return
    await users_col.update_many(
        {},
        {"$set": {
            "weekly_runs": 0, "weekly_wickets": 0, "weekly_conceded": 0,
            "weekly_balls_bowled": 0, "weekly_balls_faced": 0,
        }},
    )
    await update.message.reply_text(
        "✅ <b>Weekly leaderboard RESET!</b> 🔄\n\nAll weekly stats are now 0. Fresh week begins! 🏏",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Bowling trigger — no blocking DB calls in the hot path
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

    # ── Fire-and-forget — never blocks gameplay ─────────────────────────
    asyncio.create_task(maybe_praise_rank1(context, chat_id, game, batter, "BATTER"))
    asyncio.create_task(maybe_praise_rank1(context, chat_id, game, bowler, "BOWLER"))

    if "active_bowlers" not in context.bot_data:
        context.bot_data["active_bowlers"] = {}
    context.bot_data["active_bowlers"][bowler["id"]] = chat_id

    # Cache bot username — one-time API call, then reused forever
    global _BOT_USERNAME_CACHE
    if not _BOT_USERNAME_CACHE:
        try:
            bi = await asyncio.wait_for(context.bot.get_me(), timeout=4)
            _BOT_USERNAME_CACHE = bi.username
        except Exception:
            _BOT_USERNAME_CACHE = "cricketbot"
    url = f"https://t.me/{_BOT_USERNAME_CACHE}"

    free_hit_tag = "🚀 <b>FREE HIT ACTIVE!!</b>\n" if game.get("is_free_hit") else ""
    bat_runs = batter.get("runs", 0)
    bat_bf   = batter.get("balls_faced", 0)
    bid, bname = batter["id"], batter["name"]
    wid, wname = bowler["id"], bowler["name"]

    dm_text = (
        f"🏏 <b>Match in Progress!</b>\n\n"
        f"🏏 Batter: <b>{bname}</b> ({bat_runs} off {bat_bf})\n"
        f"🥎 Over Status: {over_info}.\n\n"
        "👉 <b>Your Turn to Bowl!</b> Type a number from 1 to 6."
    )
    keyboard = []
    if not game.get("special_used_this_over") and game.get("mode") != "TEAM":
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
            f"🏏 <b>Batter:</b> {bname} ({bat_runs} off {bat_bf})\n"
            f"🥎 <b>Bowler:</b> {wname} (Over: {over_info})\n\n"
            f"👉 {_men(wid, wname)}, check your DM to bowl! 🤫🥎"
        )
        group_kb = [[InlineKeyboardButton("Bowl Delivery 🥎", url=url)]]
    else:
        fallback_url = f"https://t.me/{_BOT_USERNAME_CACHE}?start={chat_id}"
        group_text = (
            f"{free_hit_tag}📊 <b>Status:</b>\n"
            f"🏏 <b>Batter:</b> {bname} ({bat_runs} off {bat_bf})\n"
            f"🥎 <b>Bowler:</b> {wname} (Over: {over_info})\n\n"
            f"⚠️ {_men(wid, wname)}, I couldn't DM you! Click below to start me, then bowl! 🤫🥎"
        )
        group_kb = [[InlineKeyboardButton("Start Bot & Bowl 🤖", url=fallback_url)]]

    await send_media_safely(context, chat_id, MEDIA["bowler_turn"], group_text, InlineKeyboardMarkup(group_kb))
    set_afk_timer(context, chat_id, bowler["id"], "BOWLER")


# ---------------------------------------------------------------------------
# Team innings management
# ---------------------------------------------------------------------------

async def process_team_innings_end(context, chat_id, game):
    if game.get("innings") == 1:
        batting_players = game.get("batting_team_ref", {}).get("players", [])
        await send_duck_message(context, chat_id, batting_players)

        game["innings"] = 2
        game["target"]  = game["batting_team_ref"]["score"] + 1

        temp = game["batting_team_ref"]
        game["batting_team_ref"] = game["bowling_team_ref"]
        game["bowling_team_ref"] = temp

        for p in game.get("team_a", {}).get("players", []) + game.get("team_b", {}).get("players", []):
            p["is_striker"] = False
            p["is_non_striker"] = False
            p["is_out"] = False

        game.update({
            "striker": None, "non_striker": None, "current_bowler": None,
            "last_bowler_id": None, "is_free_hit": False, "special_used_this_over": False,
        })
        game["waiting_for"]             = "TEAM_OPENERS_BAT"
        game["innings_start_msg_pending"] = True
        await context.bot.send_message(
            chat_id,
            f"🛑 <b>INNINGS BREAK! AB CHASE KARO !!</b> 🛑\n\n"
            f"🎯 Target: <b>{game['target']} runs</b> in {game.get('target_overs', '?')} overs.\n\n"
            "Batting Captain/Host, select your opening pair:\n"
            "<code>/batting [number]</code> (do it twice).",
            parse_mode="HTML",
        )
    else:
        batting_players = game.get("batting_team_ref", {}).get("players", [])
        await send_duck_message(context, chat_id, batting_players)

        ta = game.get("team_a", {}).get("score", 0)
        tb = game.get("team_b", {}).get("score", 0)
        if ta > tb:
            for wp in game.get("team_a", {}).get("players", []):
                await update_user_db(wp["id"], {"exp": 40})
        elif tb > ta:
            for wp in game.get("team_b", {}).get("players", []):
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
# Ranking helpers
# ---------------------------------------------------------------------------

async def _send_ranking(query, user_id: int, title: str, field: str, label: str):
    if users_col is None:
        try:
            await query.edit_message_text("❌ Database not connected.")
        except Exception:
            pass
        return

    # Fetch leaderboard and total registered count in parallel
    docs, total_registered = await asyncio.gather(
        users_col.find({field: {"$gt": 0}}).sort(field, -1).to_list(500),
        users_col.count_documents({}),
    )
    top             = docs[:10]
    total_with_data = len(docs)

    requester = await users_col.find_one({"user_id": user_id})
    my_rank   = None
    if requester and requester.get(field, 0) > 0:
        my_rank = next((i + 1 for i, d in enumerate(docs) if d.get("user_id") == user_id), None)

    medals    = ["🥇", "🥈", "🥉"]
    req_name  = requester.get("first_name", "You") if requester else "You"
    req_uname = f" (@{requester['username']})" if requester and requester.get("username") else ""

    header = (
        f"🏆 <b>{title}</b>\n"
        f"👥 <b>{total_registered}</b> total registered  |  "
        f"<b>{total_with_data}</b> have data here\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if my_rank:
        header += (
            f"👤 <b>{req_name}</b>{req_uname}\n"
            f"📍 Your Rank: <b>#{my_rank}</b> / {total_with_data} players with data  "
            f"({total_registered} total registered)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    if not top:
        lines = "😶 No one has recorded a score here yet!"
    else:
        lines = ""
        for i, p in enumerate(top):
            name   = p.get("first_name", "Player")
            uname  = f" (@{p['username']})" if p.get("username") else ""
            value  = p.get(field, 0)
            medal  = medals[i] if i < 3 else f"<b>#{i+1}</b>"
            is_you = " ← You" if p.get("user_id") == user_id else ""
            lines += f"{medal} <b>{name}</b>{uname} — <b>{value}</b> {label}{is_you}\n"

    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="rank_main")]])
    try:
        await query.edit_message_text(
            f"{header}{lines}\n━━━━━━━━━━━━━━━━━━━━━━━━\n🏏 <i>Keep playing to climb the ranks!</i>",
            reply_markup=back_kb, parse_mode="HTML",
        )
    except Exception:
        pass


async def _send_sr_ranking(query, user_id: int):
    if users_col is None:
        try:
            await query.edit_message_text("❌ Database not connected.")
        except Exception:
            pass
        return

    docs, total_registered = await asyncio.gather(
        users_col.find({
            "$expr": {"$gte": [
                {"$add": [{"$ifNull": ["$solo_matches", 0]}, {"$ifNull": ["$team_matches", 0]}]},
                10,
            ]}
        }).to_list(500),
        users_col.count_documents({}),
    )
    docs.sort(
        key=lambda x: (x.get("total_runs", 0) / max(x.get("balls_faced", 1), 1)) * 100,
        reverse=True,
    )
    top             = docs[:10]
    total_with_data = len(docs)

    requester = await users_col.find_one({"user_id": user_id})
    my_rank   = None
    if requester:
        my_rank = next((i + 1 for i, d in enumerate(docs) if d.get("user_id") == user_id), None)

    medals    = ["🥇", "🥈", "🥉"]
    req_name  = requester.get("first_name", "You") if requester else "You"
    req_uname = f" (@{requester['username']})" if requester and requester.get("username") else ""

    header = (
        f"🏆 <b>⚡ STRIKE RATE RANKING</b> (min 10 matches)\n"
        f"👥 <b>{total_registered}</b> total registered  |  "
        f"<b>{total_with_data}</b> qualify (10+ matches)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if my_rank:
        header += (
            f"👤 <b>{req_name}</b>{req_uname}\n"
            f"📍 Your SR Rank: <b>#{my_rank}</b> / {total_with_data} qualifiers  "
            f"({total_registered} total registered)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    if not top:
        lines = "😶 Not enough data yet! Need at least 10 matches."
    else:
        lines = ""
        for i, p in enumerate(top):
            name   = p.get("first_name", "Player")
            uname  = f" (@{p['username']})" if p.get("username") else ""
            sr     = (p.get("total_runs", 0) / max(p.get("balls_faced", 1), 1)) * 100
            medal  = medals[i] if i < 3 else f"<b>#{i+1}</b>"
            is_you = " ← You" if p.get("user_id") == user_id else ""
            lines += f"{medal} <b>{name}</b>{uname} — <b>SR: {sr:.1f}</b>{is_you}\n"

    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="rank_main")]])
    try:
        await query.edit_message_text(
            f"{header}{lines}\n━━━━━━━━━━━━━━━━━━━━━━━━\n🏏 <i>Keep playing to climb the ranks!</i>",
            reply_markup=back_kb, parse_mode="HTML",
        )
    except Exception:
        pass


async def _send_most_runs_in_match_ranking(query, user_id: int):
    if users_col is None:
        try:
            await query.edit_message_text("❌ Database not connected.")
        except Exception:
            pass
        return

    docs, total_registered = await asyncio.gather(
        users_col.find({"highest_score.runs": {"$gt": 0}}).sort("highest_score.runs", -1).to_list(500),
        users_col.count_documents({}),
    )
    top             = docs[:10]
    total_with_data = len(docs)

    requester = await users_col.find_one({"user_id": user_id})
    my_rank   = None
    if requester and requester.get("highest_score", {}).get("runs", 0) > 0:
        my_rank = next((i + 1 for i, d in enumerate(docs) if d.get("user_id") == user_id), None)

    medals    = ["🥇", "🥈", "🥉"]
    req_name  = requester.get("first_name", "You") if requester else "You"
    req_uname = f" (@{requester['username']})" if requester and requester.get("username") else ""

    header = (
        f"🏆 <b>🏆 MOST RUNS IN A MATCH — TOP 10</b>\n"
        f"👥 <b>{total_registered}</b> total registered  |  "
        f"<b>{total_with_data}</b> have a high score\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if my_rank:
        my_hs = requester.get("highest_score", {})
        header += (
            f"👤 <b>{req_name}</b>{req_uname}\n"
            f"📍 Your Rank: <b>#{my_rank}</b> / {total_with_data} players  "
            f"({total_registered} total registered)\n"
            f"   Best Score: {my_hs.get('runs', 0)} ({my_hs.get('balls', 0)} balls)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    if not top:
        lines = "😶 No one has recorded a high score yet!"
    else:
        lines = ""
        for i, p in enumerate(top):
            name   = p.get("first_name", "Player")
            uname  = f" (@{p['username']})" if p.get("username") else ""
            hs     = p.get("highest_score", {})
            runs   = hs.get("runs", 0)
            balls  = hs.get("balls", 0)
            medal  = medals[i] if i < 3 else f"<b>#{i+1}</b>"
            is_you = " ← You" if p.get("user_id") == user_id else ""
            lines += f"{medal} <b>{name}</b>{uname} — <b>{runs} runs</b> ({balls} balls){is_you}\n"

    back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="rank_main")]])
    try:
        await query.edit_message_text(
            f"{header}{lines}\n━━━━━━━━━━━━━━━━━━━━━━━━\n🏏 <i>Keep playing to climb the ranks!</i>",
            reply_markup=back_kb, parse_mode="HTML",
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Callback query handler
# ---------------------------------------------------------------------------

RANK_KB = [
    [InlineKeyboardButton("🦆 Duck Ranking",       callback_data="rank_ducks"),
     InlineKeyboardButton("💥 Sixes Ranking",      callback_data="rank_sixes")],
    [InlineKeyboardButton("🥎 Wickets Ranking",    callback_data="rank_wickets"),
     InlineKeyboardButton("🏃 Total Runs",         callback_data="rank_runs")],
    [InlineKeyboardButton("⚡ Strike Rate",        callback_data="rank_sr"),
     InlineKeyboardButton("🎩 Hat-tricks",         callback_data="rank_hattricks")],
    [InlineKeyboardButton("💯 Centuries",          callback_data="rank_centuries"),
     InlineKeyboardButton("🌟 Half-Centuries",     callback_data="rank_fifties")],
    [InlineKeyboardButton("🏆 Most Runs in Match", callback_data="rank_most_runs_match")],
]
RANK_HEADER = (
    "🏆 <b>WELCOME TO THE HALL OF FAME!</b> 🏆\n\n"
    "This is where legends are remembered.\n"
    "🌟 Select a category to see the Top 10:"
)


async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    _NO_DEDUP = {
        "rank_main", "rank_ducks", "rank_sixes", "rank_wickets",
        "rank_runs", "rank_sr", "rank_hattricks", "rank_centuries",
        "rank_fifties", "rank_most_runs_match",
        "lb_weekly", "lb_lifetime", "lb_back",
        "help_main", "help_solo", "help_team", "help_yorker",
        "help_afk", "help_commands", "help_levels",
        "dm_rankings", "dm_stats",
    }
    if query.data not in _NO_DEDUP:
        dedup_key = f"btn_{chat_id}_{user_id}_{query.data}_{query.message.message_id if query.message else 0}"
        if context.bot_data.get(dedup_key):
            return
        context.bot_data[dedup_key] = True
        async def _clear_dedup():
            await asyncio.sleep(3)
            context.bot_data.pop(dedup_key, None)
        asyncio.create_task(_clear_dedup())

    game = context.bot_data.get(chat_id)

    # ── cancel ────────────────────────────────────────────────────────────
    if query.data == "cancel":
        if game:
            game["state"] = "NOT_PLAYING"
        try:
            await query.edit_message_caption(caption="❌ <b>Setup cancelled.</b>", parse_mode="HTML")
        except Exception:
            try:
                await query.edit_message_text("❌ <b>Setup cancelled.</b>", parse_mode="HTML")
            except Exception:
                pass

    # ── solo_game ─────────────────────────────────────────────────────────
    elif query.data == "solo_game":
        lock_key = f"mode_select_lock_{chat_id}"
        lock = context.bot_data.get(lock_key) or asyncio.Lock()
        context.bot_data[lock_key] = lock
        if lock.locked():
            return
        async with lock:
            game = context.bot_data.get(chat_id)
            if not game or game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
                return
            if user_id != game.get("start_initiator_id"):
                try:
                    await query.answer("❌ Only the player who typed /start can choose the mode!", show_alert=True)
                except Exception:
                    pass
                return
            game.update({
                "state": "JOINING", "mode": "SOLO", "players": [],
                "batter_idx": 0, "bowler_idx": 1,
                "balls_bowled": 0, "is_free_hit": False, "special_used_this_over": False,
            })
            kb = [[
                InlineKeyboardButton("3 Balls", callback_data="spell_3"),
                InlineKeyboardButton("6 Balls", callback_data="spell_6"),
            ]]
            try:
                await query.edit_message_caption(
                    caption="⚾ <b>Solo Mode Selected!</b>\n\nChoose the spell size (balls per turn):",
                    reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML",
                )
            except Exception:
                try:
                    await query.edit_message_text(
                        "⚾ <b>Solo Mode Selected!</b>\n\nChoose the spell size (balls per turn):",
                        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML",
                    )
                except Exception:
                    pass

    # ── spell selection ───────────────────────────────────────────────────
    elif query.data in ["spell_3", "spell_6"]:
        if not game or game.get("state") != "JOINING":
            return
        spell = 3 if query.data == "spell_3" else 6
        game["spell"] = spell
        user = update.effective_user
        username = user.username.lower() if user.username else None
        await init_user_db(user.id, user.first_name, username)
        if not any(p["id"] == user.id for p in game.get("players", [])):
            game["players"].append({
                "id": user.id, "name": user.first_name, "username": username,
                "runs": 0, "conceded": 0, "wickets": 0,
                "balls_bowled": 0, "balls_faced": 0, "match_4s": 0, "match_6s": 0,
            })
        try:
            await query.edit_message_caption(
                caption=(
                    f"✅ <b>Solo Game set to {spell} balls per spell!</b>\n\n"
                    f"{user.first_name} is in the queue! (1 player)\n\n"
                    "⏳ 70 seconds to join! Type <code>/join</code> to enter!\n"
                    "Auto-starts in 70 seconds!"
                ),
                parse_mode="HTML",
            )
        except Exception:
            try:
                await query.edit_message_text(
                    f"✅ <b>Solo Game set to {spell} balls per spell!</b>\n\n"
                    f"{user.first_name} is in the queue! (1 player)\n\n"
                    "⏳ 70 seconds to join! Type <code>/join</code> to enter!",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        context.job_queue.run_once(auto_start_match, 70, data={"chat_id": chat_id}, name=f"autostart_{chat_id}")
        context.job_queue.run_repeating(queue_reminder, interval=35, first=35, data={"chat_id": chat_id}, name=f"queueremind_{chat_id}")

    # ── team_game ─────────────────────────────────────────────────────────
    elif query.data == "team_game":
        lock_key = f"mode_select_lock_{chat_id}"
        lock = context.bot_data.get(lock_key) or asyncio.Lock()
        context.bot_data[lock_key] = lock
        if lock.locked():
            return
        async with lock:
            game = context.bot_data.get(chat_id)
            if not game or game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
                return
            if user_id != game.get("start_initiator_id"):
                try:
                    await query.answer("❌ Only the player who typed /start can choose the mode!", show_alert=True)
                except Exception:
                    pass
                return
            game.update({
                "state": "TEAM_SETUP_HOST", "mode": "TEAM",
                "team_a": None, "team_b": None, "host_id": None,
                "innings": 1, "target": 0, "target_overs": 0,
                "batting_team_ref": None, "bowling_team_ref": None,
                "striker": None, "non_striker": None, "current_bowler": None,
                "last_bowler_id": None, "is_free_hit": False, "special_used_this_over": False,
            })
            kb = [[InlineKeyboardButton("HOST BANUNGA 👿", callback_data="become_host")]]
            try:
                await query.edit_message_caption(
                    caption=(
                        "👥 <b>Team Mode Selected!</b>\n\n"
                        "One person must become the <b>Game Host</b> 👿\n\n"
                        "Click the button below to become the Host!"
                    ),
                    reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML",
                )
            except Exception:
                try:
                    await query.edit_message_text(
                        "👥 <b>Team Mode Selected!</b>\n\nOne person must become the Game Host 👿",
                        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML",
                    )
                except Exception:
                    pass

    # ── become_host ───────────────────────────────────────────────────────
    elif query.data == "become_host":
        if not game or game.get("state") != "TEAM_SETUP_HOST":
            return
        if game.get("host_id"):
            try:
                await query.answer("A host has already been chosen!", show_alert=True)
            except Exception:
                pass
            return
        game["host_id"] = user_id
        user = update.effective_user
        username = user.username.lower() if user.username else None
        await init_user_db(user.id, user.first_name, username)
        try:
            await query.edit_message_caption(
                caption=(
                    f"👑 <b>{user.first_name}</b> is the Game Host!\n\n"
                    "Host, type <code>/create_team</code> to open team registration!"
                ),
                parse_mode="HTML",
            )
        except Exception:
            try:
                await query.edit_message_text(
                    f"👑 <b>{user.first_name}</b> is the Game Host!\n\nType <code>/create_team</code>!",
                    parse_mode="HTML",
                )
            except Exception:
                pass

    # ── join_team_a / join_team_b ─────────────────────────────────────────
    elif query.data in ["join_team_a", "join_team_b"]:
        if not game or game.get("state") != "TEAM_JOINING":
            return
        team_key = "team_a" if query.data == "join_team_a" else "team_b"
        opp_key  = "team_b" if team_key == "team_a" else "team_a"
        if any(p["id"] == user_id for p in game[team_key]["players"]):
            try:
                await query.answer("You are already in this team!", show_alert=True)
            except Exception:
                pass
            return
        if any(p["id"] == user_id for p in game[opp_key]["players"]):
            try:
                await query.answer("You are already in the other team!", show_alert=True)
            except Exception:
                pass
            return
        if is_user_playing_anywhere(context, user_id):
            try:
                await query.answer("You are already playing in another game!", show_alert=True)
            except Exception:
                pass
            return
        user = update.effective_user
        username = user.username.lower() if user.username else None
        await init_user_db(user.id, user.first_name, username)
        game[team_key]["players"].append({
            "id": user_id, "name": user.first_name, "username": username,
            "runs": 0, "balls_faced": 0, "wickets": 0, "conceded": 0,
            "balls_bowled": 0, "is_out": False, "match_4s": 0, "match_6s": 0,
        })
        team_label = "Team A 🔴" if team_key == "team_a" else "Team B 🔵"
        try:
            await query.answer(f"✅ Joined {team_label}!", show_alert=False)
        except Exception:
            pass
        await context.bot.send_message(
            chat_id,
            f"✅ <b>{user.first_name}</b> joined {team_label}! "
            f"(A: {len(game['team_a']['players'])} | B: {len(game['team_b']['players'])})",
            parse_mode="HTML",
        )
        if game.get("is_paused_waiting_players"):
            if len(game["team_a"]["players"]) >= 2 and len(game["team_b"]["players"]) >= 2:
                game["is_paused_waiting_players"] = False
                await context.bot.send_message(chat_id, "✅ Minimum player requirement met! Resuming setup... ▶️")
                await trigger_team_captains(context, chat_id, game)

    # ── team captains ─────────────────────────────────────────────────────
    elif query.data in ["team_cap_a", "team_cap_b"]:
        if not game or game.get("state") != "TEAM_CAPTAINS":
            return
        team_key = "team_a" if query.data == "team_cap_a" else "team_b"
        if not any(p["id"] == user_id for p in game[team_key]["players"]):
            try:
                await query.answer("❌ You are not in this team!", show_alert=True)
            except Exception:
                pass
            return
        if game[team_key]["captain"]:
            try:
                await query.answer("This team already has a captain!", show_alert=True)
            except Exception:
                pass
            return
        game[team_key]["captain"] = user_id
        team_label = "Team A 🔴" if team_key == "team_a" else "Team B 🔵"
        user = update.effective_user
        await context.bot.send_message(chat_id, f"👑 <b>{user.first_name}</b> is now Captain of {team_label}!", parse_mode="HTML")
        if game["team_a"]["captain"] and game["team_b"]["captain"]:
            a_cap = next(p for p in game["team_a"]["players"] if p["id"] == game["team_a"]["captain"])
            a_cap_id = a_cap["id"]
            kb = [[
                InlineKeyboardButton("HEADS 🪙", callback_data="toss_heads"),
                InlineKeyboardButton("TAILS 🪙", callback_data="toss_tails"),
            ]]
            await context.bot.send_message(
                chat_id,
                f"🪙 <b>TOSS TIME!</b>\n\n"
                f"{_men(a_cap_id, a_cap['name'])} (Team A Captain), call the toss!",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML",
            )
            game["state"] = "TEAM_TOSS"

    # ── toss ──────────────────────────────────────────────────────────────
    elif query.data in ["toss_heads", "toss_tails"]:
        if not game or game.get("state") != "TEAM_TOSS":
            return
        a_cap_id = game["team_a"]["captain"]
        if user_id != a_cap_id:
            try:
                await query.answer("Only Team A Captain calls the toss!", show_alert=True)
            except Exception:
                pass
            return
        call   = "Heads" if query.data == "toss_heads" else "Tails"
        result = random.choice(["Heads", "Tails"])
        won    = (call == result)
        winner_team = "team_a" if won else "team_b"
        winner_cap_id = game[winner_team]["captain"]
        winner_name   = next(p["name"] for p in game[winner_team]["players"] if p["id"] == winner_cap_id)
        game["toss_winner_team"] = winner_team
        kb = [[
            InlineKeyboardButton("🏏 BAT FIRST",   callback_data="bat_first"),
            InlineKeyboardButton("🥎 BOWL FIRST",  callback_data="bowl_first"),
        ]]
        try:
            await query.edit_message_text(
                f"🪙 <b>TOSS RESULT!</b>\n\n"
                f"Call: <b>{call}</b> | Result: <b>{result}</b>\n\n"
                f"{'✅ CORRECT!' if won else '❌ Wrong call!'}\n\n"
                f"🏆 <b>{winner_name}</b>'s team wins the toss!\n"
                f"{_men(winner_cap_id, winner_name)}, choose to Bat or Bowl first:",
                reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML",
            )
        except Exception:
            pass

    # ── bat_first / bowl_first ────────────────────────────────────────────
    elif query.data in ["bat_first", "bowl_first"]:
        if not game or game.get("state") != "TEAM_TOSS":
            return
        winner_team   = game.get("toss_winner_team")
        winner_cap_id = game[winner_team]["captain"]
        if user_id != winner_cap_id:
            try:
                await query.answer("Only the toss winner can make this choice!", show_alert=True)
            except Exception:
                pass
            return
        loser_team = "team_b" if winner_team == "team_a" else "team_a"
        if query.data == "bat_first":
            game["batting_team_ref"]  = game[winner_team]
            game["bowling_team_ref"]  = game[loser_team]
        else:
            game["batting_team_ref"]  = game[loser_team]
            game["bowling_team_ref"]  = game[winner_team]
        choice_txt = "BAT FIRST 🏏" if query.data == "bat_first" else "BOWL FIRST 🥎"
        host_id = game["host_id"]
        kb_overs = [
            [InlineKeyboardButton(f"{n} Overs", callback_data=f"set_overs_{n}") for n in [3, 5, 7]],
            [InlineKeyboardButton(f"{n} Overs", callback_data=f"set_overs_{n}") for n in [10, 15, 20]],
            [InlineKeyboardButton("25 Overs", callback_data="set_overs_25")],
        ]
        try:
            await query.edit_message_text(
                f"✅ Chose to <b>{choice_txt}</b>!\n\n"
                f"🎯 {_men(host_id, 'Host')}, select the number of overs:",
                reply_markup=InlineKeyboardMarkup(kb_overs), parse_mode="HTML",
            )
        except Exception:
            pass
        game["state"] = "TEAM_OVERS_SELECT"

    # ── set_overs ─────────────────────────────────────────────────────────
    elif query.data.startswith("set_overs_"):
        if not game or game.get("state") != "TEAM_OVERS_SELECT":
            return
        if user_id != game.get("host_id"):
            try:
                await query.answer("Only the Host can set the overs!", show_alert=True)
            except Exception:
                pass
            return
        overs = int(query.data.split("_")[-1])
        game["target_overs"] = overs
        game["state"]        = "TEAM_SPAMFREE_WAIT"
        try:
            await query.edit_message_text(
                f"✅ <b>{overs} overs</b> per side!\n\n"
                "🛡️ Host: Type <code>/spamfree</code> within 15s to enable spam-free mode.\n"
                "Otherwise the game starts normally after 15 seconds.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        context.job_queue.run_once(spamfree_timeout, 15, data={"chat_id": chat_id}, name=f"spamfree_{chat_id}")

    # ── vote_host ─────────────────────────────────────────────────────────
    elif query.data == "vote_host":
        if not game:
            return
        game.setdefault("host_votes", set())
        in_team = (
            any(p["id"] == user_id for p in game.get("team_a", {}).get("players", []))
            or any(p["id"] == user_id for p in game.get("team_b", {}).get("players", []))
        )
        if not in_team:
            try:
                await query.answer("Only active players can vote!", show_alert=True)
            except Exception:
                pass
            return
        game["host_votes"].add(user_id)
        count = len(game["host_votes"])
        if count >= 4:
            game["host_id"] = game["host_vote_target"]
            try:
                await query.edit_message_text(
                    f"✅ <b>{game['host_vote_name']}</b> is now the new Game Host! (4/4 votes)",
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

    # ── endmatch yes/no ───────────────────────────────────────────────────
    elif query.data.startswith("endmatch_yes_"):
        target_chat = int(query.data.split("_")[-1])
        tgame = context.bot_data.get(target_chat)
        if tgame and tgame.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
            clear_afk_timer(context, target_chat)
            for pfx in ["autostart_", "queueremind_", "team_join_", "spamfree_"]:
                for job in context.job_queue.get_jobs_by_name(f"{pfx}{target_chat}"):
                    job.schedule_removal()
            try:
                await commit_player_stats(tgame)
            except Exception:
                pass
            tgame["state"] = "NOT_PLAYING"
            await context.bot.send_message(target_chat, "🛑 <b>Match force-ended by admin!</b>", parse_mode="HTML")
            await trigger_full_scorecard_message(context, target_chat, tgame)
        try:
            await query.edit_message_text("✅ Match ended.", parse_mode="HTML")
        except Exception:
            pass

    elif query.data.startswith("endmatch_no_"):
        try:
            await query.edit_message_text("❌ End match cancelled.")
        except Exception:
            pass

    # ── special / yorker ──────────────────────────────────────────────────
    elif query.data.startswith("special_"):
        group_id = int(query.data.split("_")[1])
        tgame    = context.bot_data.get(group_id)
        if not tgame or tgame.get("state") != "PLAYING" or tgame.get("waiting_for") != "BOWLER":
            return
        bowler = tgame["players"][tgame["bowler_idx"]] if tgame.get("mode") == "SOLO" else tgame.get("current_bowler")
        batter = tgame["players"][tgame["batter_idx"]] if tgame.get("mode") == "SOLO" else tgame.get("striker")
        if bowler is None or batter is None:
            return
        if update.effective_user.id != bowler["id"] or tgame.get("special_used_this_over"):
            return
        if "active_bowlers" in context.bot_data and update.effective_user.id in context.bot_data["active_bowlers"]:
            del context.bot_data["active_bowlers"][update.effective_user.id]
        tgame["special_used_this_over"] = True
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
            batter["runs"]     = batter.get("runs", 0) + 1
            bowler["conceded"] = bowler.get("conceded", 0) + 1
            if tgame.get("mode") == "TEAM":
                tgame["batting_team_ref"]["score"] += 1
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
            tgame["current_bowl"] = "NO_BALL"
            tgame["waiting_for"]  = "BATTER"
            hit_opts = "1-6" if tgame.get("mode") == "SOLO" else "0-6"
            bat_id, bat_name = batter["id"], batter["name"]
            await send_media_safely(
                context, group_id, MEDIA["batter_turn"],
                f"🚨 Ball delivered!! 🥎💨\n👉 {_men(bat_id, bat_name)}, type {hit_opts} to hit! 🏏👇",
            )
            set_afk_timer(context, group_id, batter["id"], "BATTER")
        else:
            try:
                await query.edit_message_text(
                    "🎯 <b>Yorker pel diya bhai 😶‍🌫️</b>\n"
                    f"⚠️ Type {'0-3' if tgame.get('mode') == 'TEAM' else '1-3'} to survive, "
                    "otherwise OUT! ☝️",
                    parse_mode="HTML", reply_markup=None,
                )
            except Exception:
                pass
            tgame["current_bowl"] = "YORKER"
            tgame["waiting_for"]  = "BATTER"
            hit_opts = "1-6" if tgame.get("mode") == "SOLO" else "0-6"
            bat_id, bat_name = batter["id"], batter["name"]
            await send_media_safely(
                context, group_id, MEDIA["batter_turn"],
                f"🚨 Ball bowled! 🥎💨\n👉 {_men(bat_id, bat_name)}, type {hit_opts} to hit! 🏏👇",
            )
            set_afk_timer(context, group_id, batter["id"], "BATTER")

    # ── help pages ────────────────────────────────────────────────────────
    elif query.data.startswith("help_"):
        topic   = query.data[5:]
        back_kb = [[InlineKeyboardButton("🔙 Back to Help", callback_data="help_main")]]
        pages = {
            "main": (
                "🏏 <b>ELITE CRICKET BOT — HELP CENTER</b> 🏆\n\nSelect a topic below:",
                [
                    [InlineKeyboardButton("🏏 Solo Game Guide",  callback_data="help_solo")],
                    [InlineKeyboardButton("👥 Team Game Guide",  callback_data="help_team")],
                    [InlineKeyboardButton("🎯 Yorker Rules",     callback_data="help_yorker")],
                    [InlineKeyboardButton("⏳ AFK Penalties",    callback_data="help_afk")],
                    [InlineKeyboardButton("📊 Commands List",    callback_data="help_commands")],
                    [InlineKeyboardButton("⭐ Level System",     callback_data="help_levels")],
                ],
            ),
            "solo": (
                "🏏 <b>SOLO GAME — HOW TO PLAY</b>\n\n"
                "1️⃣ /start → Solo Game → choose spell (3 or 6 balls).\n"
                "2️⃣ Players type /join to enter.\n"
                "3️⃣ Admin types /startsolo or wait 70 seconds.\n\n"
                "🎮 <b>Gameplay:</b>\n"
                "• Bowler types 1-6 via DM secretly.\n"
                "• Batter types 1-6 in group.\n"
                "• <b>Same number = OUT! ☝️</b>\n"
                "• <b>Different = Runs! 🏃‍♂️</b>\n\n"
                "📊 /soloscore for live scorecard.\n"
                "🏆 Highest score earns most EXP!",
                back_kb,
            ),
            "team": (
                "👥 <b>TEAM GAME — FULL GUIDE</b>\n\n"
                "1️⃣ /start → Team Game.\n"
                "2️⃣ Someone clicks HOST BANUNGA 👿.\n"
                "3️⃣ Host types /create_team — registration opens.\n"
                "4️⃣ Players join Team A or Team B.\n"
                "5️⃣ Each team picks a Captain 👑.\n"
                "6️⃣ Toss → choose overs → optional /spamfree.\n\n"
                "🎮 <b>During Match:</b>\n"
                "• /batting [num] — send batter out.\n"
                "• /bowling [num] — select bowler.\n"
                "• Bowler types 1-6 via DM | Batter types 0-6 in group.\n"
                "• Odd runs → Strike rotates! 🔄",
                back_kb,
            ),
            "yorker": (
                "🎯 <b>YORKER RULES</b>\n\n"
                "Click 🎯 Try for yorker in DM. Only once per over!\n\n"
                "🎲 <b>Outcomes:</b>\n"
                "❌ 60% — WIDE BALL: 1 extra run, re-bowl.\n"
                "🚨 20% — NO BALL: Batter hits freely. Next = FREE HIT 🚀\n"
                "🎯 20% — YORKER ACTIVATED!\n"
                "   • Solo: 1-3 = survive | 4-6 = OUT\n"
                "   • Team: 0-3 = survive | 4-6 = OUT",
                back_kb,
            ),
            "afk": (
                "⏳ <b>AFK PENALTIES</b>\n\n"
                "⚠️ 10 seconds — Warning #1.\n"
                "⚠️ 30 seconds — Warning #2.\n"
                "❌ 60 seconds — TIMEOUT!\n\n"
                "🏏 <b>Solo:</b> Player eliminated.\n"
                "👥 <b>Team Batter AFK:</b> OUT + -5 runs.\n"
                "👥 <b>Team Bowler AFK:</b> +5 free runs to batting team.",
                back_kb,
            ),
            "commands": (
                "📊 <b>COMMANDS LIST</b>\n\n"
                "🏏 <b>Solo:</b> /start /join /leavesolo /startsolo /soloscore\n"
                "👥 <b>Team:</b> /create_team /batting /bowling /teams /score /spamfree\n"
                "⚙️ <b>Mgmt:</b> /add /remove /changehost /changecap /changeover /rejoin /endmatch\n"
                "📈 <b>Stats:</b> /userstats /leaderboard /ranking /help\n"
                "👑 <b>Owner:</b> /resetweekly /broadcast /botstats /botgroups",
                back_kb,
            ),
            "levels": (
                "⭐ <b>LEVEL SYSTEM</b>\n\n"
                "🔰 Newbie — 0-999 EXP\n"
                "⚡ Pro — 1,000-5,000 EXP\n"
                "🌟 Legendary — 5,001-8,000 EXP\n"
                "👑 Unbeaten — 8,001+ EXP\n\n"
                "💰 <b>How to Earn EXP:</b>\n"
                "🏆 Win solo → +60 EXP\n"
                "🏆 Win team → +40 EXP\n"
                "💯 Century → +150 EXP\n"
                "🌟 50+ → +50 EXP\n"
                "☝️ Wicket → +20 EXP\n"
                "🎩 Hat-trick → +1000 EXP",
                back_kb,
            ),
        }
        page = pages.get(topic)
        if page:
            text_content, kb_content = page
            try:
                await query.edit_message_text(
                    text_content,
                    reply_markup=InlineKeyboardMarkup(kb_content),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    # ── tournaments ───────────────────────────────────────────────────────
    elif query.data == "tournaments":
        try:
            await query.answer("🏆 Tournaments are under maintenance! Check back soon. 🔧", show_alert=True)
        except Exception:
            pass

    # ── registration confirm/cancel ───────────────────────────────────────
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
        reg_data["team_number"]   = team_num
        reg_data["registered_by"] = user_id
        await tourteams_col.insert_one(reg_data)
        summary = (
            f"✅ <b>NEW TEAM REGISTERED!</b>\n\n"
            f"🔢 Team No: <b>{team_num}</b>\n"
            f"🏏 Team: <b>{reg_data.get('team_name')}</b>\n"
            f"👑 Captain: {reg_data.get('captain')}\n"
            f"🥈 VC: {reg_data.get('vc')}\n"
            f"🌟 R1: {reg_data.get('ret1')}\n"
            f"🌟 R2: {reg_data.get('ret2')}\n"
            f"👤 Registered by: {_men(user_id, update.effective_user.first_name)}"
        )
        for oid in OWNER_IDS:
            try:
                if reg_data.get("logo_file_id"):
                    await context.bot.send_photo(chat_id=oid, photo=reg_data["logo_file_id"],
                                                 caption=summary, parse_mode="HTML")
                else:
                    await context.bot.send_message(chat_id=oid, text=summary, parse_mode="HTML")
            except Exception:
                pass
        context.user_data.pop("reg_data", None)
        context.user_data.pop("reg_state", None)
        try:
            await query.edit_message_text(
                f"✅ <b>Registration Submitted!</b>\n\nTeam <b>{reg_data.get('team_name')}</b> "
                f"assigned number <b>{team_num}</b>. Owners will confirm shortly. 🙏",
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

    # ── dm_stats ──────────────────────────────────────────────────────────
    elif query.data == "dm_stats":
        if users_col is None:
            return
        try:
            user_data = await users_col.find_one({"user_id": user_id})
            if not user_data:
                await context.bot.send_message(user_id, "❌ No stats found. Play a match first!")
                return
            hs_runs  = user_data.get("highest_score", {}).get("runs", 0)
            hs_balls = user_data.get("highest_score", {}).get("balls", 0)
            total_runs    = user_data.get("total_runs", 0)
            balls_faced   = user_data.get("balls_faced", 0)
            sr            = (total_runs / balls_faced * 100) if balls_faced > 0 else 0
            balls_bowled  = user_data.get("balls_bowled", 0)
            runs_conceded = user_data.get("runs_conceded", 0)
            overs, rem_balls = balls_bowled // 6, balls_bowled % 6
            eco             = (runs_conceded / balls_bowled * 6) if balls_bowled > 0 else 0
            exp             = user_data.get("exp", 0)
            level           = get_user_level(exp)
            next_level_name, exp_needed = get_next_level_info(exp)
            batting_innings = user_data.get("batting_innings", 0)
            dismissals      = user_data.get("dismissals", 0)
            avg = total_runs / dismissals if dismissals > 0 else (float(total_runs) if batting_innings > 0 else 0.0)
            exp_line = (
                f"⭐ <b>EXP:</b> {exp} | Next: <b>{next_level_name}</b> (Need {exp_needed} more EXP)\n"
                if next_level_name
                else f"⭐ <b>EXP:</b> {exp} | 🏆 <b>MAX LEVEL REACHED!</b>\n"
            )
            st = (
                f"📊 <b>{level} STATISTICS</b> 📊\n══════════════════════\n"
                f"👤 <b>Name:</b> {user_data.get('first_name', 'Unknown')}\n"
                f"🆔 <b>ID:</b> <code>{user_data.get('user_id', 'Unknown')}</code>\n"
                f"{exp_line}┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                f"🏏 <b>BATTING STATS</b>\n"
                f"🔸 <b>Highest Score:</b> {hs_runs} ({hs_balls})\n"
                f"🔸 <b>Total Runs:</b> {total_runs}\n"
                f"🔸 <b>Batting Avg:</b> {avg:.2f}\n"
                f"🔸 <b>Strike Rate:</b> {sr:.2f}\n"
                f"🔸 <b>6s:</b> {user_data.get('total_6s', 0)} | <b>4s:</b> {user_data.get('total_4s', 0)}\n"
                f"🔸 <b>100s:</b> {user_data.get('centuries', 0)} | <b>50s:</b> {user_data.get('half_centuries', 0)}\n"
                f"🔸 <b>Ducks:</b> {user_data.get('ducks', 0)}\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                f"🥎 <b>BOWLING STATS</b>\n"
                f"🔹 <b>Wickets:</b> {user_data.get('wickets', 0)}\n"
                f"🔹 <b>Hat-Tricks:</b> {user_data.get('hat_tricks', 0)}\n"
                f"🔹 <b>Overs Bowled:</b> {overs}.{rem_balls}\n"
                f"🔹 <b>Economy:</b> {eco:.2f}\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
                f"🏆 <b>MATCH &amp; AWARDS</b>\n"
                f"🔸 <b>Solo Matches:</b> {user_data.get('solo_matches', 0)}\n"
                f"🔸 <b>Team Matches:</b> {user_data.get('team_matches', 0)}\n"
                f"🔸 <b>Batting Innings:</b> {batting_innings}\n"
                f"🔸 <b>MOTM Awards:</b> {user_data.get('motm', 0)}\n══════════════════════"
            )
            stats_img = "https://res.cloudinary.com/dxgfxfoog/image/upload/v1777818873/file_00000000fa6871fa8d9b30faff9899ae_hbyn9j.png"
            await context.bot.send_photo(chat_id=user_id, photo=stats_img, caption=st, parse_mode="HTML")
        except Exception:
            pass

    # ── play_again ────────────────────────────────────────────────────────
    elif query.data == "play_again":
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
        context.bot_data[f"mode_select_lock_{chat_id}"] = asyncio.Lock()
        keyboard = [
            [InlineKeyboardButton("🏏 Solo Game",   callback_data="solo_game"),
             InlineKeyboardButton("👥 Team Game",   callback_data="team_game")],
            [InlineKeyboardButton("🏆 Tournaments", callback_data="tournaments"),
             InlineKeyboardButton("❌ Cancel",       callback_data="cancel")],
        ]
        await context.bot.send_photo(
            chat_id=chat_id,
            photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777690770/IMG_20260502_082816_001_t0wejv.jpg",
            caption=(
                "Welcome to the <b>ELITE CRICKET BOT</b> Arena! 🏆\n"
                "Join our official community at @eclplays. 🏏\n\n"
                "🔥 <b>A tournament is currently going on! Register via @eclregisbot</b> 🔥\n\n"
                "Choose your mode: 👇"
            ),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    # ── weekly / lifetime leaderboard ─────────────────────────────────────
    elif query.data in ["lb_weekly", "lb_lifetime"]:
        if users_col is None:
            try:
                await query.edit_message_text("❌ Database not connected.")
            except Exception:
                pass
            return
        is_weekly = query.data == "lb_weekly"
        run_field = "weekly_runs"    if is_weekly else "total_runs"
        wkt_field = "weekly_wickets" if is_weekly else "wickets"
        bf_field  = "weekly_balls_faced"  if is_weekly else "balls_faced"
        rc_field  = "weekly_conceded"     if is_weekly else "runs_conceded"
        bb_field  = "weekly_balls_bowled" if is_weekly else "balls_bowled"

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
        top_batters, top_bowlers, total_registered, requester = await asyncio.gather(
            users_col.aggregate(pipeline_bat).to_list(5),
            users_col.aggregate(pipeline_bowl).to_list(5),
            users_col.count_documents({}),
            users_col.find_one({"user_id": user_id}),
        )

        if is_weekly and not top_batters and not top_bowlers:
            try:
                await query.edit_message_text("⏳ <b>No weekly data yet!</b> Play some matches! 🏏", parse_mode="HTML")
            except Exception:
                pass
            return

        req_name  = requester.get("first_name", "You") if requester else "You"
        req_uname = f" (@{requester['username']})" if requester and requester.get("username") else ""
        my_run_val = requester.get(run_field, 0) if requester else 0
        my_wkt_val = requester.get(wkt_field, 0) if requester else 0

        my_runs_rank = my_wkt_rank = None
        if my_run_val > 0:
            my_runs_rank = await users_col.count_documents({run_field: {"$gt": my_run_val}}) + 1
        if my_wkt_val > 0:
            my_wkt_rank = await users_col.count_documents({wkt_field: {"$gt": my_wkt_val}}) + 1

        text = (
            f"🏆 <b>{'WEEKLY' if is_weekly else 'LIFETIME'} LEADERBOARD</b> 🏆\n"
            f"👥 <b>{total_registered}</b> total players registered\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        if my_runs_rank or my_wkt_rank:
            text += f"👤 <b>{req_name}</b>{req_uname}\n"
            if my_runs_rank:
                text += f"🏃 Runs Rank: <b>#{my_runs_rank}</b> / {total_registered}"
            if my_wkt_rank:
                text += f"  🥎 Wickets Rank: <b>#{my_wkt_rank}</b> / {total_registered}"
            text += "\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        text += "🏏 <b>TOP 5 BATTERS</b>\n"
        for i, b in enumerate(top_batters):
            lvl   = get_user_level(b.get("exp", 0))
            name  = b.get("first_name", "Unknown")
            uname = f" (@{b['username']})" if b.get("username") else ""
            sr_v  = b.get("sr", 0)
            text += f"{medals[i]} <b>{name}</b>{uname} [{lvl}]\n   ➜ <b>{b.get(run_field, 0)} Runs</b>  SR: {sr_v:.1f}\n"

        text += "\n🥎 <b>TOP 5 BOWLERS</b>\n"
        for i, b in enumerate(top_bowlers):
            lvl   = get_user_level(b.get("exp", 0))
            name  = b.get("first_name", "Unknown")
            uname = f" (@{b['username']})" if b.get("username") else ""
            eco_v = b.get("eco", 0)
            text += f"{medals[i]} <b>{name}</b>{uname} [{lvl}]\n   ➜ <b>{b.get(wkt_field, 0)} Wkts</b>  Eco: {eco_v:.2f}\n"

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
                reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML",
            )
        except Exception:
            pass

    # ── Hall of Fame rankings ─────────────────────────────────────────────
    elif query.data == "rank_main":
        try:
            await query.edit_message_text(RANK_HEADER, reply_markup=InlineKeyboardMarkup(RANK_KB), parse_mode="HTML")
        except Exception:
            pass

    elif query.data == "rank_ducks":
        await _send_ranking(query, user_id, "🦆 DUCK RANKING — TOP 10", "ducks", "🦆")
    elif query.data == "rank_sixes":
        await _send_ranking(query, user_id, "💥 SIXES RANKING — TOP 10", "total_6s", "💥")
    elif query.data == "rank_wickets":
        await _send_ranking(query, user_id, "🥎 WICKETS RANKING — TOP 10", "wickets", "🥎 wkts")
    elif query.data == "rank_runs":
        await _send_ranking(query, user_id, "🏃 MOST RUNS — TOP 10", "total_runs", "🏃 runs")
    elif query.data == "rank_sr":
        await _send_sr_ranking(query, user_id)
    elif query.data == "rank_hattricks":
        await _send_ranking(query, user_id, "🎩 HAT-TRICK RANKING — TOP 10", "hat_tricks", "🎩")
    elif query.data == "rank_centuries":
        await _send_ranking(query, user_id, "💯 CENTURIES RANKING — TOP 10", "centuries", "💯")
    elif query.data == "rank_fifties":
        await _send_ranking(query, user_id, "🌟 HALF-CENTURIES RANKING — TOP 10", "half_centuries", "🌟")
    elif query.data == "rank_most_runs_match":
        await _send_most_runs_in_match_ranking(query, user_id)

    elif query.data == "dm_rankings":
        try:
            await query.message.reply_text(RANK_HEADER, reply_markup=InlineKeyboardMarkup(RANK_KB), parse_mode="HTML")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Text input handler
# ---------------------------------------------------------------------------

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip() if update.message and update.message.text else ""
    chat_type  = update.message.chat.type if update.message else "private"

    # ── Private DM — Registration flow ───────────────────────────────────
    if chat_type == "private":
        reg_state = context.user_data.get("reg_state")
        if reg_state and reg_state not in ("confirm",):
            reg_data = context.user_data.setdefault("reg_data", {})
            text = user_input
            if reg_state == "team_name":
                if not text:
                    await update.message.reply_text("❌ Team name cannot be empty.")
                    return
                reg_data["team_name"] = text
                context.user_data["reg_state"] = "logo"
                await update.message.reply_text(
                    f"✅ Team Name: <b>{text}</b>\n\nStep 2️⃣\n🖼️ Send your <b>Team Logo</b> (as a photo):",
                    parse_mode="HTML",
                )
                return
            elif reg_state == "logo":
                await update.message.reply_text("📸 Please <b>send a photo</b> as your team logo!", parse_mode="HTML")
                return
            elif reg_state == "captain":
                if not text:
                    await update.message.reply_text("❌ Captain cannot be empty.")
                    return
                if tourteams_col is not None:
                    existing = await tourteams_col.find_one(
                        {"$or": [{"captain": text}, {"vc": text}, {"ret1": text}, {"ret2": text}]}
                    )
                    if existing:
                        await update.message.reply_text(f"⚠️ <b>{text}</b> is already registered!", parse_mode="HTML")
                        return
                reg_data["captain"] = text
                context.user_data["reg_state"] = "vc"
                await update.message.reply_text(f"✅ Captain: <b>{text}</b>\n\nStep 5️⃣\n🥈 Send <b>Vice-Captain's @username</b>.", parse_mode="HTML")
                return
            elif reg_state == "vc":
                if not text or text == reg_data.get("captain"):
                    await update.message.reply_text("❌ VC cannot be empty or same as Captain.")
                    return
                if tourteams_col is not None:
                    existing = await tourteams_col.find_one(
                        {"$or": [{"captain": text}, {"vc": text}, {"ret1": text}, {"ret2": text}]}
                    )
                    if existing:
                        await update.message.reply_text(f"⚠️ <b>{text}</b> is already registered!", parse_mode="HTML")
                        return
                reg_data["vc"] = text
                context.user_data["reg_state"] = "ret1"
                await update.message.reply_text(f"✅ VC: <b>{text}</b>\n\nStep 6️⃣\n🌟 Send <b>Retention 1</b> @username.", parse_mode="HTML")
                return
            elif reg_state == "ret1":
                if not text or text in [reg_data.get("captain"), reg_data.get("vc")]:
                    await update.message.reply_text("❌ Invalid. Cannot duplicate Captain/VC.")
                    return
                if tourteams_col is not None:
                    existing = await tourteams_col.find_one(
                        {"$or": [{"captain": text}, {"vc": text}, {"ret1": text}, {"ret2": text}]}
                    )
                    if existing:
                        await update.message.reply_text(f"⚠️ <b>{text}</b> is already registered!", parse_mode="HTML")
                        return
                reg_data["ret1"] = text
                context.user_data["reg_state"] = "ret2"
                await update.message.reply_text(f"✅ Retention 1: <b>{text}</b>\n\nStep 7️⃣\n🌟 Send <b>Retention 2</b> @username.", parse_mode="HTML")
                return
            elif reg_state == "ret2":
                already = [reg_data.get("captain"), reg_data.get("vc"), reg_data.get("ret1")]
                if not text or text in already:
                    await update.message.reply_text("❌ Invalid. Cannot duplicate previous choices.")
                    return
                if tourteams_col is not None:
                    existing = await tourteams_col.find_one(
                        {"$or": [{"captain": text}, {"vc": text}, {"ret1": text}, {"ret2": text}]}
                    )
                    if existing:
                        await update.message.reply_text(f"⚠️ <b>{text}</b> is already registered!", parse_mode="HTML")
                        return
                reg_data["ret2"] = text
                context.user_data["reg_state"] = "confirm"
                summary = (
                    f"📋 <b>CONFIRM YOUR REGISTRATION</b>\n\n"
                    f"🏏 <b>Team Name:</b> {reg_data.get('team_name')}\n"
                    f"👑 <b>Captain:</b> {reg_data.get('captain')}\n"
                    f"🥈 <b>VC:</b> {reg_data.get('vc')}\n"
                    f"🌟 <b>R1:</b> {reg_data.get('ret1')}\n"
                    f"🌟 <b>R2:</b> {reg_data.get('ret2')}\n\n"
                    f"{'🖼️ Logo: Uploaded ✅' if reg_data.get('logo_file_id') else '🖼️ Logo: Not provided'}\n\n"
                    "Everything correct? Tap <b>Confirm</b> to submit!"
                )
                kb = [
                    [InlineKeyboardButton("✅ Confirm", callback_data="reg_confirm_yes"),
                     InlineKeyboardButton("❌ Cancel",  callback_data="reg_confirm_no")],
                ]
                if reg_data.get("logo_file_id"):
                    await update.message.reply_photo(
                        photo=reg_data["logo_file_id"], caption=summary,
                        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML",
                    )
                else:
                    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
                return

    if not user_input or not user_input.lstrip("-").isdigit() or not user_input.isdigit():
        return
    val = int(user_input)

    # ── Private DM — BOWLER input ─────────────────────────────────────────
    if chat_type == "private":
        user_id  = update.effective_user.id
        group_id = context.bot_data.get("active_bowlers", {}).get(user_id)
        if not group_id:
            return
        game = context.bot_data.get(group_id)
        if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != "BOWLER":
            return
        bowler = game["players"][game["bowler_idx"]] if game.get("mode") == "SOLO" else game.get("current_bowler")
        batter = game["players"][game["batter_idx"]] if game.get("mode") == "SOLO" else game.get("striker")
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
                    "⚠️ <b>SPAM FREE MODE:</b> You cannot bowl the same delivery 3 times in a row!",
                    parse_mode="HTML",
                )
                return
            bowler["last_balls"] = (last_balls + [val])[-2:]

        clear_afk_timer(context, group_id)
        game["current_bowl"] = val
        game["waiting_for"]  = "BATTER"
        if user_id in context.bot_data.get("active_bowlers", {}):
            del context.bot_data["active_bowlers"][user_id]

        chat_url = None
        try:
            chat = await context.bot.get_chat(group_id)
            if chat.username:
                chat_url = f"https://t.me/{chat.username}"
            elif chat.invite_link:
                chat_url = chat.invite_link
        except Exception:
            pass

        kb = [[InlineKeyboardButton("Back to Game 🔙", url=chat_url)]] if chat_url else []
        await update.message.reply_text(
            f"Choice locked! 🔒 You bowled a <b>{val}</b>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(kb) if kb else None,
        )
        hit_opts = "1-6" if game.get("mode") == "SOLO" else "0-6"
        bat_id, bat_name = batter["id"], batter["name"]
        await send_media_safely(
            context, group_id, MEDIA["batter_turn"],
            f"🚨 Ball bowled! 🥎💨\n👉 {_men(bat_id, bat_name)}, type {hit_opts} to hit! 🏏👇",
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

    bowl_val    = game["current_bowl"]
    is_free_hit = game.get("is_free_hit", False)
    bid, bname  = batter["id"], batter["name"]
    wid, wname  = bowler["id"], bowler["name"]

    # ── NO BALL ───────────────────────────────────────────────────────────
    if bowl_val == "NO_BALL":
        bowler["consecutive_wickets"] = 0
        batter["balls_faced"]  = batter.get("balls_faced", 0) + 1
        game["is_free_hit"]    = True
        old_runs               = batter.get("runs", 0)
        batter["runs"]         = old_runs + hit_val + 1
        bowler["conceded"]     = bowler.get("conceded", 0) + hit_val + 1
        if game.get("mode") == "TEAM":
            game["batting_team_ref"]["score"] += hit_val + 1

        result_text = (
            f"🚨 <b>IT WAS A NO BALL!</b> 1 penalty run.\n"
            f"🚀 <b>NEXT BALL WILL BE A FREE HIT!</b> 🚀\n\n"
            f"🏏 Batter hit: <b>{hit_val}</b>\n\n"
        )
        if hit_val == 0:
            result_text += f"🛡️ <b>Dot ball.</b> ({bname}: {batter['runs']} off {batter['balls_faced']})"
        else:
            result_text += f"🏃‍♂️ <b>{hit_val} runs!</b> 🔥 ({bname}: {batter['runs']} off {batter['balls_faced']})"

        await send_media_safely(context, chat_id, MEDIA.get(hit_val, MEDIA[0]), result_text,
                                reply_to_message_id=update.message.message_id)
        if hit_val > 0:
            try:
                await context.bot.send_message(chat_id, random.choice(HIT_COMMENTARY.get(hit_val, HIT_COMMENTARY[1])), parse_mode="HTML")
            except Exception:
                pass

        if old_runs < 100 and batter["runs"] >= 100:
            await update_user_db(bid, {"exp": 150})
            await send_media_safely(context, chat_id, MEDIA["100"], f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥\n{_men(bid, bname)} has smashed a glorious century!")
        elif old_runs < 50 and batter["runs"] >= 50:
            await update_user_db(bid, {"exp": 50})
            await send_media_safely(context, chat_id, MEDIA["50"], f"🏏 <b>HALF-CENTURY!</b> 💥\n{_men(bid, bname)} reaches 50!")

        if game.get("mode") == "TEAM":
            if hit_val % 2 != 0:
                swap_strike(game)
                try:
                    s = game.get("striker") or {}
                    sid = s.get("id", 0)
                    sname = s.get("name", "")
                    await context.bot.send_message(
                        chat_id, f"🔄 Strike rotated! 🏏 {_men(sid, sname)} is now on strike!", parse_mode="HTML",
                    )
                except Exception:
                    pass
            if game.get("innings") == 2 and game["batting_team_ref"]["score"] >= game.get("target", 0):
                await process_team_innings_end(context, chat_id, game)
                return

    # ── YORKER ────────────────────────────────────────────────────────────
    elif bowl_val == "YORKER":
        batter["balls_faced"]  = batter.get("balls_faced", 0) + 1
        bowler["balls_bowled"] = bowler.get("balls_bowled", 0) + 1
        if game.get("mode") == "SOLO":
            game["balls_bowled"] += 1
        if game.get("mode") == "TEAM":
            game["bowling_team_ref"]["balls_bowled"] += 1

        survives = hit_val in ([0, 1, 2, 3] if game.get("mode") == "TEAM" else [1, 2, 3])
        old_runs = batter.get("runs", 0)

        if not survives:
            if is_free_hit:
                game["is_free_hit"] = False
                bowler["consecutive_wickets"] = 0
                result_text = (
                    f"🥎 Bowler: <b>YORKER</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                    f"💥 <b>BOWLED! BUT IT'S A FREE HIT!</b> 😅\n{_men(bid, bname)} survives and scores 0 runs!"
                )
                await send_media_safely(context, chat_id, MEDIA["batter_turn"], result_text,
                                        reply_to_message_id=update.message.message_id)
            else:
                bowler["wickets"] = bowler.get("wickets", 0) + 1
                await update_user_db(wid, {"exp": 20})
                result_text = (
                    f"🥎 Bowler: <b>YORKER</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                    f"💥 <b>HOWZAT! OUT! ❌</b> ☝️ {bname} is bowled for {batter.get('runs', 0)}! 😔"
                )
                await send_media_safely(context, chat_id, MEDIA["yorker"], result_text,
                                        reply_to_message_id=update.message.message_id)
                if batter.get("runs", 0) == 0:
                    await send_media_safely(context, chat_id, MEDIA["duck"], f"🦆 {_men(bid, bname)} got a duck 🦆")

                _yorker_praise = [
                    f"🎯 What a YORKER! {_men(wid, wname)} is an absolute SNIPER! 🔥",
                    f"💥 LETHAL YORKER from {_men(wid, wname)}! A toe-crusher of the highest order!",
                    f"🏆 {_men(wid, wname)} delivers the PERFECT yorker! The batter had NO chance!",
                    f"⚡ That yorker from {_men(wid, wname)} was utterly UNPLAYABLE! 🌟",
                ]
                try:
                    await context.bot.send_message(chat_id, random.choice(_yorker_praise), parse_mode="HTML")
                except Exception:
                    pass

                bowler["consecutive_wickets"] = bowler.get("consecutive_wickets", 0) + 1
                if bowler["consecutive_wickets"] == 3:
                    bowler["consecutive_wickets"] = 0
                    await update_user_db(wid, {"hat_tricks": 1, "exp": 1000})
                    ht_vid = "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777819065/VID_20260503200210_rabpvn.mp4"
                    await send_media_safely(context, chat_id, ht_vid, f"🎩 <b>HAT-TRICK!</b> {_men(wid, wname)}, you are a magician!! 🪄🔥")

                dismiss_batter(game, batter)
                if game.get("mode") == "TEAM":
                    game["batting_team_ref"]["wickets"] += 1
                    if game["batting_team_ref"]["wickets"] >= len(game["batting_team_ref"]["players"]) - 1:
                        await process_team_innings_end(context, chat_id, game)
                        return
                    game["waiting_for"] = "TEAM_BATTER_SELECT"
                    await context.bot.send_message(
                        chat_id, "🏏 Captain/Host, type <code>/batting [number]</code> to select the next batter.",
                        parse_mode="HTML",
                    )
                else:
                    game["batter_idx"] += 1
                    if game["batter_idx"] >= len(game["players"]):
                        await check_solo_winner_exp(game)
                        await commit_player_stats(game)
                        await send_duck_message(context, chat_id, game.get("players", []))
                        game["state"] = "NOT_PLAYING"
                        await trigger_full_scorecard_message(context, chat_id, game)
                        return
                    if game["batter_idx"] == game["bowler_idx"]:
                        game["bowler_idx"]             = (game["bowler_idx"] + 1) % len(game["players"])
                        game["balls_bowled"]           = 0
                        game["special_used_this_over"] = False
        else:
            bowler["consecutive_wickets"] = 0
            result_text = (
                f"🥎 Bowler: <b>YORKER</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                f"😮‍💨 <b>SURVIVED the YORKER!</b> 0 runs.\n"
                f"({bname}: {batter.get('runs', 0)} off {batter.get('balls_faced', 0)})"
            )
            await send_media_safely(context, chat_id, MEDIA["batter_turn"], result_text,
                                    reply_to_message_id=update.message.message_id)
            if game.get("mode") == "TEAM":
                if game.get("innings") == 2 and game["batting_team_ref"]["score"] >= game.get("target", 0):
                    await process_team_innings_end(context, chat_id, game)
                    return
                if hit_val % 2 != 0:
                    swap_strike(game)
                    try:
                        s = game.get("striker") or {}
                        sid = s.get("id", 0)
                        sname = s.get("name", "")
                        await context.bot.send_message(
                            chat_id, f"🔄 Strike rotated! 🏏 {_men(sid, sname)} is now on strike!", parse_mode="HTML",
                        )
                    except Exception:
                        pass

        if old_runs < 100 and batter.get("runs", 0) >= 100:
            await update_user_db(bid, {"exp": 150})
            await send_media_safely(context, chat_id, MEDIA["100"], f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥\n{_men(bid, bname)} has smashed a glorious century!")
        elif old_runs < 50 and batter.get("runs", 0) >= 50:
            await update_user_db(bid, {"exp": 50})
            await send_media_safely(context, chat_id, MEDIA["50"], f"🏏 <b>HALF-CENTURY!</b> 💥\n{_men(bid, bname)} reaches 50!")

        if game.get("mode") == "TEAM":
            if game.get("innings") == 2 and game["batting_team_ref"]["score"] >= game.get("target", 0):
                await process_team_innings_end(context, chat_id, game)
                return

    # ── Normal delivery ───────────────────────────────────────────────────
    elif str(hit_val) == str(bowl_val):
        # OUT (unless free hit)
        batter["balls_faced"]  = batter.get("balls_faced", 0) + 1
        bowler["balls_bowled"] = bowler.get("balls_bowled", 0) + 1
        if game.get("mode") == "SOLO":
            game["balls_bowled"] += 1
        if game.get("mode") == "TEAM":
            game["bowling_team_ref"]["balls_bowled"] += 1

        if is_free_hit:
            game["is_free_hit"] = False
            bowler["consecutive_wickets"] = 0
            result_text = (
                f"🥎 Bowler: <b>{bowl_val}</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                f"💥 <b>BOWLED! BUT IT'S A FREE HIT!</b> 😅\n{_men(bid, bname)} survives — scores 0 runs!"
            )
            await send_media_safely(context, chat_id, MEDIA["batter_turn"], result_text,
                                    reply_to_message_id=update.message.message_id)
        else:
            bowler["wickets"] = bowler.get("wickets", 0) + 1
            await update_user_db(wid, {"exp": 20})
            result_text = (
                f"🥎 Bowler: <b>{bowl_val}</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                f"💥 <b>HOWZAT! OUT! ❌</b> ☝️ {bname} dismissed for {batter.get('runs', 0)}! 😔\n"
                f"{bname} KOI NA HOTA HAI !!"
            )
            await send_media_safely(context, chat_id, MEDIA["out"], result_text,
                                    reply_to_message_id=update.message.message_id)
            if batter.get("runs", 0) == 0:
                await send_media_safely(context, chat_id, MEDIA["duck"], f"🦆 {_men(bid, bname)} got a duck 🦆")

            _fielding_pool = []
            if game.get("mode") == "TEAM":
                _fielding_pool = [p for p in game.get("bowling_team_ref", {}).get("players", []) if p["id"] != wid]
            else:
                _fielding_pool = [p for p in game.get("players", []) if p["id"] not in {bid, wid}]
            if _fielding_pool:
                _catcher = random.choice(_fielding_pool)
                cid, cname = _catcher["id"], _catcher["name"]
                _catch_lines = [
                    f"🧤 CAUGHT! {_men(cid, cname)} takes a STUNNING catch! 🌟",
                    f"😱 {_men(cid, cname)} dives to his right and holds on! SCREAMER! 🎯",
                    f"🏆 WORLDCLASS fielding from {_men(cid, cname)}! UNBELIEVABLE! 👏",
                    f"💪 {_men(cid, cname)} takes the catch and the team goes WILD! 🔥",
                ]
                try:
                    await context.bot.send_message(chat_id, random.choice(_catch_lines), parse_mode="HTML")
                except Exception:
                    pass

            _bowler_lines = [
                f"🏆 {_men(wid, wname)} is absolutely ROLLING! What a wicket! 🔥",
                f"🥎 {_men(wid, wname)} gets the breakthrough! 💪",
                f"😤 {_men(wid, wname)} outthought the batter! Pure bowling genius! 🎯",
                f"⚡ Wicket for {_men(wid, wname)}! Absolutely unplayable delivery! 💥",
            ]
            try:
                await context.bot.send_message(chat_id, random.choice(_bowler_lines), parse_mode="HTML")
            except Exception:
                pass

            bowler["consecutive_wickets"] = bowler.get("consecutive_wickets", 0) + 1
            if bowler["consecutive_wickets"] == 3:
                bowler["consecutive_wickets"] = 0
                await update_user_db(wid, {"hat_tricks": 1, "exp": 1000})
                ht_vid = "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777819065/VID_20260503200210_rabpvn.mp4"
                await send_media_safely(context, chat_id, ht_vid, f"🎩 <b>HAT-TRICK!</b> {_men(wid, wname)}, you are a magician!! 🪄🔥")

            dismiss_batter(game, batter)
            if game.get("mode") == "TEAM":
                game["batting_team_ref"]["wickets"] += 1
                if game["batting_team_ref"]["wickets"] >= len(game["batting_team_ref"]["players"]) - 1:
                    await process_team_innings_end(context, chat_id, game)
                    return
                game["waiting_for"] = "TEAM_BATTER_SELECT"
                await context.bot.send_message(
                    chat_id, "🏏 Captain/Host, type <code>/batting [number]</code> to select the next batter.",
                    parse_mode="HTML",
                )
            else:
                game["batter_idx"] += 1
                if game["batter_idx"] >= len(game["players"]):
                    await check_solo_winner_exp(game)
                    await commit_player_stats(game)
                    await send_duck_message(context, chat_id, game.get("players", []))
                    game["state"] = "NOT_PLAYING"
                    await trigger_full_scorecard_message(context, chat_id, game)
                    return
                if game["batter_idx"] == game["bowler_idx"]:
                    game["bowler_idx"]             = (game["bowler_idx"] + 1) % len(game["players"])
                    game["balls_bowled"]           = 0
                    game["special_used_this_over"] = False

    # ── RUNS scored ───────────────────────────────────────────────────────
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
        batter["runs"]     = old_runs + hit_val
        bowler["conceded"] = bowler.get("conceded", 0) + hit_val
        if game.get("mode") == "TEAM":
            game["batting_team_ref"]["score"] += hit_val

        if hit_val == 0:
            result_text = f"🏏 Batter hit: <b>0</b>\n\n🛡️ <b>Solid defense! Dot ball.</b> ({bname}: {batter['runs']} off {batter['balls_faced']})"
        else:
            result_text = f"🏏 Batter hit: <b>{hit_val}</b>\n\n🏃‍♂️ <b>Great shot! {hit_val} runs!</b> 🔥 ({bname}: {batter['runs']} off {batter['balls_faced']})"

        await send_media_safely(context, chat_id, MEDIA.get(hit_val, MEDIA[0]), result_text,
                                reply_to_message_id=update.message.message_id)
        if hit_val > 0:
            try:
                await context.bot.send_message(chat_id, random.choice(HIT_COMMENTARY.get(hit_val, HIT_COMMENTARY[1])), parse_mode="HTML")
            except Exception:
                pass

        if old_runs < 100 and batter["runs"] >= 100:
            await update_user_db(bid, {"exp": 150})
            await send_media_safely(context, chat_id, MEDIA["100"], f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥\n{_men(bid, bname)} has smashed a glorious century!")
        elif old_runs < 50 and batter["runs"] >= 50:
            await update_user_db(bid, {"exp": 50})
            await send_media_safely(context, chat_id, MEDIA["50"], f"🏏 <b>HALF-CENTURY!</b> 💥\n{_men(bid, bname)} reaches 50!")

        if game.get("mode") == "TEAM":
            if game.get("innings") == 2 and game["batting_team_ref"]["score"] >= game.get("target", 0):
                await process_team_innings_end(context, chat_id, game)
                return
            if hit_val % 2 != 0:
                swap_strike(game)
                try:
                    s = game.get("striker") or {}
                    sid = s.get("id", 0)
                    sname = s.get("name", "")
                    await context.bot.send_message(
                        chat_id, f"🔄 Strike rotated! 🏏 {_men(sid, sname)} is now on strike!", parse_mode="HTML",
                    )
                except Exception:
                    pass

    # ── End-of-over check ─────────────────────────────────────────────────
    is_legal = (bowl_val not in ["NO_BALL"])
    is_over  = False
    if is_legal:
        if game.get("mode") == "SOLO" and game.get("balls_bowled", 0) >= game.get("spell", 6):
            is_over = True
        elif game.get("mode") == "TEAM":
            bb = game["bowling_team_ref"]["balls_bowled"]
            if bb > 0 and bb % 6 == 0:
                is_over = True

    if is_over:
        spell_text = f"🔁 <b>Over Completed!</b> 🛑 {wname} finished.\n"
        if game.get("mode") == "TEAM":
            _sb = bowler.get("balls_bowled", 0) - bowler.get("_spell_balls0", 0)
            _sr = bowler.get("conceded", 0)     - bowler.get("_spell_runs0", 0)
            _sw = bowler.get("wickets", 0)      - bowler.get("_spell_wkts0", 0)
            if _sb > 0:
                bowler.setdefault("bowling_spells", []).append({"b": _sb, "r": _sr, "w": _sw})
            for k in ("_spell_balls0", "_spell_runs0", "_spell_wkts0"):
                bowler.pop(k, None)
            swap_strike(game)
            game["last_bowler_id"]         = wid
            game["special_used_this_over"] = False
            if game["bowling_team_ref"]["balls_bowled"] >= game.get("target_overs", 0) * 6:
                await process_team_innings_end(context, chat_id, game)
                return
            await trigger_full_scorecard_message(context, chat_id, game)
            team = game["batting_team_ref"]
            spell_text += f"\n📊 Score: {team['score']}/{team['wickets']}\n"
            s = game.get("striker") or {}
            if s:
                sid, sname = s.get("id", 0), s.get("name", "")
                spell_text += f"🔄 Strike rotated for new over! 🏏 {_men(sid, sname)} is now on strike!\n"
            spell_text += "Bowling Captain/Host, select next bowler using <code>/bowling [num]</code>."
            await context.bot.send_message(chat_id, spell_text, parse_mode="HTML")
            if game.get("waiting_for") == "TEAM_BATTER_SELECT":
                game["need_new_bowler"] = True
            else:
                game["waiting_for"] = "TEAM_BOWLER_SELECT"
        else:
            _sb = bowler.get("balls_bowled", 0) - bowler.get("_spell_balls0", 0)
            _sr = bowler.get("conceded", 0)     - bowler.get("_spell_runs0", 0)
            _sw = bowler.get("wickets", 0)      - bowler.get("_spell_wkts0", 0)
            if _sb > 0:
                bowler.setdefault("bowling_spells", []).append({"b": _sb, "r": _sr, "w": _sw})
            for k in ("_spell_balls0", "_spell_runs0", "_spell_wkts0"):
                bowler.pop(k, None)
            await trigger_full_scorecard_message(context, chat_id, game)
            await context.bot.send_message(chat_id, spell_text, parse_mode="HTML")
            game["balls_bowled"]           = 0
            game["special_used_this_over"] = False
            game["bowler_idx"]             = (game["bowler_idx"] + 1) % len(game["players"])
            if game["bowler_idx"] == game["batter_idx"]:
                game["bowler_idx"] = (game["bowler_idx"] + 1) % len(game["players"])
            _nb = game["players"][game["bowler_idx"]]
            _nb["_spell_balls0"] = _nb.get("balls_bowled", 0)
            _nb["_spell_runs0"]  = _nb.get("conceded", 0)
            _nb["_spell_wkts0"]  = _nb.get("wickets", 0)
            if game.get("state") == "PLAYING":
                game["waiting_for"] = "BOWLER"
    else:
        if game.get("state") == "PLAYING" and game.get("waiting_for") == "PROCESSING_BATTER":
            game["waiting_for"] = "BOWLER"

    if game.get("state") == "PLAYING" and game.get("waiting_for") == "BOWLER":
        await _maybe_send_chase_message(context, chat_id, game)
        await trigger_bowl(context, chat_id)


async def _maybe_send_chase_message(context, chat_id, game):
    if game.get("mode") != "TEAM" or game.get("innings") != 2:
        return
    target      = game.get("target", 0)
    bat_score   = game.get("batting_team_ref", {}).get("score", 0)
    runs_needed = target - bat_score
    if runs_needed <= 0 or runs_needed >= 30:
        return
    balls_bowled  = game.get("bowling_team_ref", {}).get("balls_bowled", 0)
    total_balls   = game.get("target_overs", 0) * 6
    balls_remaining = total_balls - balls_bowled
    if balls_remaining <= 0:
        return
    overs_full  = balls_remaining // 6
    balls_extra = balls_remaining % 6
    overs_text  = f"{overs_full}.{balls_extra} overs" if balls_extra > 0 else f"{overs_full} overs"
    await context.bot.send_message(
        chat_id,
        f"🎯 <b>{runs_needed} runs needed off {balls_remaining} balls ({overs_text})!</b> 🏃‍♂️",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# /ranking command
# ---------------------------------------------------------------------------

async def ranking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(RANK_HEADER, reply_markup=InlineKeyboardMarkup(RANK_KB), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Tournament management commands (owner only)
# ---------------------------------------------------------------------------

async def tournament_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /tournament <Name>")
        return
    if tournaments_col is None:
        await update.message.reply_text("❌ Database not connected.")
        return
    name = " ".join(context.args)
    if await tournaments_col.find_one({"name": name}):
        await update.message.reply_text(f"⚠️ Tournament <b>{name}</b> already exists!", parse_mode="HTML")
        return
    await tournaments_col.insert_one({"name": name, "created_by": update.effective_user.id, "registration_open": False, "teams": []})
    await update.message.reply_text(f"🏆 Tournament <b>{name}</b> created! Use /regisopen to open registrations.", parse_mode="HTML")


async def regisopen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only.")
        return
    context.bot_data["registration_open"] = True
    await update.message.reply_text("✅ <b>REGISTRATION IS NOW OPEN!</b> Players can /register to register their team.", parse_mode="HTML")


async def regisclose_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only.")
        return
    context.bot_data["registration_open"] = False
    await update.message.reply_text("🔒 <b>REGISTRATION IS NOW CLOSED!</b>", parse_mode="HTML")


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
        "🏏 <b>TEAM REGISTRATION</b> 🏏\n\nStep 1️⃣\n📝 Send your <b>Team Name</b>:", parse_mode="HTML",
    )


async def tourteams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only.")
        return
    if tourteams_col is None:
        await update.message.reply_text("❌ Database not connected.")
        return
    teams = await tourteams_col.find({}).sort("team_number", 1).to_list(200)
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
        await update.message.reply_text("❌ Owner only.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /deleteteam <team number>")
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
    await update.message.reply_text(f"🗑️ Team <b>#{team_num} — {team.get('team_name', 'Unknown')}</b> deleted.", parse_mode="HTML")


async def allteams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Owner only.")
        return
    if tourteams_col is None:
        await update.message.reply_text("❌ Database not connected.")
        return
    teams = await tourteams_col.find({}).sort("team_number", 1).to_list(200)
    if not teams:
        await update.message.reply_text("📋 No teams registered yet.")
        return
    for t in teams:
        text = (
            f"🏏 <b>Team #{t.get('team_number', '?')}: {t.get('team_name', 'Unknown')}</b>\n\n"
            f"👑 Captain: {t.get('captain', 'N/A')}\n"
            f"🥈 VC: {t.get('vc', 'N/A')}\n"
            f"🌟 R1: {t.get('ret1', 'N/A')}\n"
            f"🌟 R2: {t.get('ret2', 'N/A')}\n"
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
# Photo input handler (registration logo)
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
        "✅ Logo received!\n\nStep 4️⃣\n👑 Send the <b>Captain's @username</b>.\n(If no username, send their full name)",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Starting ELITE CRICKET BOT...")
    print(f"Pillow available: {PIL_AVAILABLE}")

    app = Application.builder().token(TOKEN).concurrent_updates(True).build()

    app.add_handler(TypeHandler(Update, global_tracker), group=-1)
    app.add_handler(ChatMemberHandler(track_bot_kicks, ChatMemberHandler.MY_CHAT_MEMBER))

    cmds = [
        ("start",        start_command),
        ("join",         join_command),
        ("add",          add_command),
        ("remove",       remove_command),
        ("changehost",   changehost_command),
        ("changecap",    changecap_command),
        ("changeover",   changeover_command),
        ("create_team",  create_team_command),
        ("rejoin",       rejoin_command),
        ("leavesolo",    leavesolo_command),
        ("startsolo",    startsolo_command),
        ("endmatch",     endmatch_command),
        ("soloscore",    soloscore_command),
        ("score",        teamscore_command),
        ("teams",        teams_command),
        ("batting",      batting_command),
        ("bowling",      bowling_command),
        ("userstats",    userstats_command),
        ("leaderboard",  leaderboard_command),
        ("broadcast",    broadcast_command),
        ("botstats",     botstats_command),
        ("botgroups",    botgroups_command),
        ("spamfree",     spamfree_command),
        ("help",         help_command),
        ("ranking",      ranking_command),
        ("resetweekly",  resetweekly_command),
        ("tournament",   tournament_command),
        ("regisopen",    regisopen_command),
        ("regisclose",   regisclose_command),
        ("register",     register_command),
        ("tourteams",    tourteams_command),
        ("allteams",     allteams_command),
        ("deleteteam",   deleteteam_command),
    ]
    for cmd, handler in cmds:
        app.add_handler(CommandHandler(cmd, handler))

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
        print("WEBHOOK_URL not set. Falling back to Polling...")
        app.run_polling(poll_interval=0.0, timeout=10, drop_pending_updates=True)
