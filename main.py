import os
import time
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ChatMemberHandler, filters, ContextTypes, TypeHandler
from motor.motor_asyncio import AsyncIOMotorClient

# Environment variables
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") 
PORT = int(os.environ.get("PORT", "8080")) 

OWNER_IDS = [8722613907, 8782578728, 8000127916]

# MongoDB Setup
try:
    client = AsyncIOMotorClient(MONGO_URI)
    db = client['cricket_bot_db']
    users_col = db['users']
    chats_col = db['interacted_chats']
except Exception as e:
    print(f"MongoDB Connection Error: {e}")
    users_col = None
    chats_col = None

MEDIA = {
    'batter_turn': 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777818927/VID_20260503195533_zt4tux.mp4',
    'bowler_turn': 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777694389/VID_20260502092829_np7h5d.mp4',
    'out': 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777641612/1777641553346_zexrt4.mp4',
    'duck': 'https://media.giphy.com/media/krewXUB6LBja/giphy.gif', 
    '50': 'https://media.giphy.com/media/07oir8PhvSReDNpNi7/giphy.gif',
    '100': 'https://media.giphy.com/media/pR0jymbIr7HrrpISUW/giphy.gif',
    'yorker': 'https://media.giphy.com/media/2CUJFvoRXDrUeG1mOS/giphy.gif',
    0: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777717596/VID_20260502_155429_102_xtppvn.mp4',
    1: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642218/animation.gif_1_u1ksyt.mp4',
    2: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642586/VID_20260501_190546_668_tdnzth.mp4',
    3: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642484/VID_20260501_190413_260_cylqql.mp4',
    4: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777644250/VID_20260501_193031_696_quwh5m.mp4',
    5: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642378/VID_20260501_190216_576_yonoc2.mp4',
    6: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777818980/VID_20260503195551_qcyvct.mp4'
}

SCOREBOARD_IMG = 'https://res.cloudinary.com/dxgfxfoog/image/upload/v1777876839/file_000000001fc07207a39f861ace603999_tjaafo.png'
TEAMS_ROSTER_IMG = 'https://res.cloudinary.com/dxgfxfoog/image/upload/v1777706897/file_00000000c1947207ae83551202e6e003_f4o3y9.png'

async def global_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if chats_col is not None and update.effective_chat:
        try:
            title = update.effective_chat.title if update.effective_chat.title else "Private/Unknown"
            await chats_col.update_one(
                {"chat_id": update.effective_chat.id},
                {"$set": {"chat_id": update.effective_chat.id, "type": update.effective_chat.type, "title": title}},
                upsert=True
            )
        except Exception:
            pass

async def track_bot_kicks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result: return
    chat = result.chat
    if result.new_chat_member.status in ["left", "kicked"]:
        if chats_col is not None:
            await chats_col.delete_one({"chat_id": chat.id})
    elif result.new_chat_member.status in ["member", "administrator"]:
        if chats_col is not None:
            title = chat.title if chat.title else "Group"
            await chats_col.update_one({"chat_id": chat.id}, {"$set": {"chat_id": chat.id, "type": chat.type, "title": title}}, upsert=True)

async def send_media_safely(context, chat_id, media_url, caption, reply_markup=None, reply_to_message_id=None):
    try:
        if media_url.endswith(".gif") or "giphy.com" in media_url:
            await context.bot.send_animation(chat_id=chat_id, animation=media_url, caption=caption, parse_mode="HTML", reply_markup=reply_markup, reply_to_message_id=reply_to_message_id, read_timeout=20, write_timeout=20)
        else:
            await context.bot.send_video(chat_id=chat_id, video=media_url, caption=caption, parse_mode="HTML", reply_markup=reply_markup, reply_to_message_id=reply_to_message_id, read_timeout=20, write_timeout=20)
    except Exception as e:
        print(f"Failed to send media {media_url}: {e}. Using fallback.")
        fallback_caption = f"<a href='{media_url}'>&#8205;</a>{caption}"
        try:
            await context.bot.send_message(chat_id=chat_id, text=fallback_caption, parse_mode="HTML", reply_markup=reply_markup, reply_to_message_id=reply_to_message_id)
        except Exception as e2:
            print(f"Fallback failed: {e2}")

async def init_user_db(user_id, first_name, username):
    if users_col is None: return
    user = await users_col.find_one({"user_id": user_id})
    if not user:
        await users_col.insert_one({
            "user_id": user_id, "first_name": first_name, "username": username,
            "highest_score": {"runs": 0, "balls": 0}, "total_runs": 0, "balls_faced": 0,
            "solo_matches": 0, "team_matches": 0, "total_6s": 0, "total_4s": 0,
            "centuries": 0, "half_centuries": 0, "ducks": 0, "balls_bowled": 0,
            "runs_conceded": 0, "wickets": 0, "motm": 0, "hat_tricks": 0
        })

async def update_user_db(user_id, updates):
    if users_col is None: return
    await users_col.update_one({"user_id": user_id}, {"$inc": updates}, upsert=True)

async def update_highest_score(user_id, runs, balls):
    if users_col is None: return
    user = await users_col.find_one({"user_id": user_id})
    if user and runs > user.get("highest_score", {}).get("runs", 0):
        await users_col.update_one({"user_id": user_id}, {"$set": {"highest_score": {"runs": runs, "balls": balls}}})

async def update_match_played(players, mode):
    if users_col is None: return
    field = "solo_matches" if mode == "SOLO" else "team_matches"
    for p in players: await update_user_db(p["id"], {field: 1})

async def commit_player_stats(game):
    if users_col is None: return
    if game.get("mode") != "TEAM": players = game.get("players", [])
    else:
        team_a = game.get("team_a", {}).get("players", [])
        team_b = game.get("team_b", {}).get("players", [])
        players = team_a + team_b
    
    for p in players:
        runs = p.get("runs", 0)
        balls_faced = p.get("balls_faced", 0)
        await update_highest_score(p["id"], runs, balls_faced)
        updates = {
            "total_runs": runs, "balls_faced": balls_faced, "balls_bowled": p.get("balls_bowled", 0),
            "runs_conceded": p.get("conceded", 0), "wickets": p.get("wickets", 0),
            "total_4s": p.get("match_4s", 0), "total_6s": p.get("match_6s", 0),
        }
        if runs == 0 and p.get("is_out", False): updates["ducks"] = 1
        if runs >= 100:
            updates["centuries"] = 1
            updates["half_centuries"] = 1
        elif runs >= 50: updates["half_centuries"] = 1
        await update_user_db(p["id"], updates)
        
    await update_match_played(players, game.get("mode", "SOLO"))
    potm = get_potm_data(game)
    if potm: await update_user_db(potm["id"], {"motm": 1})

def get_potm_data(game):
    best_player = None
    best_score = -999
    if game.get("mode") != "TEAM": players = game.get("players", [])
    else: players = game.get("team_a", {}).get("players", []) + game.get("team_b", {}).get("players", [])
    
    for p in players:
        score = p.get("runs", 0) + (p.get("wickets", 0) * 15) - (p.get("conceded", 0) * 0.5)
        if score > best_score:
            best_score = score
            best_player = p
    return best_player

async def is_admin(chat, user_id):
    try:
        admins = await chat.get_administrators()
        for admin in admins:
            if admin.user.id == user_id: return True
        return False
    except Exception:
        try:
            member = await chat.get_member(user_id)
            return member.status in ["administrator", "creator"]
        except Exception: return False

def get_next_num(players):
    nums = [p["num"] for p in players if "num" in p]
    i = 1
    while i in nums: i += 1
    return i

def is_user_playing_anywhere(context, user_id):
    for cid, data in context.bot_data.items():
        if isinstance(data, dict) and data.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
            if any(p.get("id") == user_id for p in data.get("players", [])): return True
            if "team_a" in data and any(p.get("id") == user_id for p in data.get("team_a", {}).get("players", [])): return True
            if "team_b" in data and any(p.get("id") == user_id for p in data.get("team_b", {}).get("players", [])): return True
    return False

def get_user_from_mention(update):
    target_user = None
    target_username = None
    if update.message.reply_to_message: target_user = update.message.reply_to_message.from_user
    else:
        for entity in update.message.entities:
            if entity.type == "text_mention":
                target_user = entity.user
                break
            elif entity.type == "mention":
                target_username = update.message.text[entity.offset:entity.offset+entity.length].lstrip("@").lower()
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

def generate_scorecard(game):
    if game.get("mode") == "TEAM": return generate_team_scorecard(game)
    text = "📊 <b>SOLO SCORECARD</b> 📊\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for p in game["players"]:
        overs, balls = divmod(p["balls_bowled"], 6)
        eco = (p["conceded"] / p["balls_bowled"]) * 6 if p["balls_bowled"] > 0 else 0.00
        text += f"👤 <b>{p['name']}</b>\n  🏏 Bat: <b>{p['runs']}</b> ({p['balls_faced']})\n"
        text += f"  🥎 Bowl: <b>{p['wickets']}</b>W | {p['conceded']}R | {overs}.{balls} Ov (Eco: {eco:.1f})\n┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
    return text


def generate_team_scorecard(game):
    text = "🏆 <b>MATCH SCORECARD</b> 🏆
━━━━━━━━━━━━━━━━━━━━━━
"
    
    if game.get("innings") == 2 and game.get("state") != "TEAM_FINISHED":
        target = game["target"]
        runs_needed = target - game["batting_team_ref"]["score"]
        balls_rem = (game["target_overs"] * 6) - game["bowling_team_ref"]["balls_bowled"]
        overs_left = balls_rem / 6
        rrr = (runs_needed / overs_left) if overs_left > 0 else 0.0
        
        text += f"🎯 <b>Target:</b> {target} | Need <b>{max(0, runs_needed)}</b> runs in <b>{balls_rem}</b> balls.
"
        text += f"📈 <b>Required Run Rate (RRR):</b> {rrr:.2f}
━━━━━━━━━━━━━━━━━━━━━━
"
        
    for team_key, team_name in [("team_a", "🔴 TEAM A"), ("team_b", "🔵 TEAM B")]:
        team = game.get(team_key)
        if not team: continue
        
        opp_team = game.get("team_b" if team_key == "team_a" else "team_a")
        played_balls = opp_team["balls_bowled"] if opp_team else 0
        played_overs, rem_balls = divmod(played_balls, 6)
        total_overs_played = played_overs + (rem_balls / 6)
        rr = (team["score"] / total_overs_played) if total_overs_played > 0 else 0.0
        
        text += f"🎖️ <b>{team_name}</b> ➜ <b>{team['score']}/{team['wickets']}</b> <i>({played_overs}.{rem_balls} Ov)</i> | <b>RR: {rr:.2f}</b>

"
        
        batters_txt = ""
        for p in team["players"]:
            if p["balls_faced"] > 0 or p.get("is_striker") or p.get("is_non_striker") or p.get("is_out"):
                status = "❌" if p.get("is_out") else "🏏"
                sr = (p["runs"] / p["balls_faced"] * 100) if p["balls_faced"] > 0 else 0.0
                batters_txt += f"  {status} {p['name'][:12]} ➜ <b>{p['runs']}</b> ({p['balls_faced']}) [SR: {sr:.1f}]
"
        if batters_txt: text += f"<i>Batters:</i>
{batters_txt}
"
            
        bowlers_txt = ""
        for p in team["players"]:
            if p["balls_bowled"] > 0:
                p_ov, p_bl = divmod(p["balls_bowled"], 6)
                eco = (p["conceded"] / p["balls_bowled"]) * 6
                bowlers_txt += f"  🥎 {p['name'][:12]} ➜ {p_ov}.{p_bl} Ov | <b>{p['conceded']}R</b> | <b>{p['wickets']}W</b> [Eco: {eco:.1f}]
"
        if bowlers_txt: text += f"<i>Bowlers:</i>
{bowlers_txt}"
        text += "━━━━━━━━━━━━━━━━━━━━━━
"
        
    if game["state"] == "TEAM_FINISHED":
        team_a_score = game["team_a"]["score"]
        team_b_score = game["team_b"]["score"]
        
        if team_a_score > team_b_score:
            if game["batting_team_ref"] == game["team_a"] and game["innings"] == 2:
                wickets_left = (len(game["team_a"]["players"]) - 1) - game["team_a"]["wickets"]
                result_str = f"🎉 <b>Team A 🔴 WINS by {wickets_left} wickets!</b>
"
            else:
                run_diff = team_a_score - team_b_score
                result_str = f"🎉 <b>Team A 🔴 WINS by {run_diff} runs!</b>
"
        elif team_b_score > team_a_score:
             if game["batting_team_ref"] == game["team_b"] and game["innings"] == 2:
                wickets_left = (len(game["team_b"]["players"]) - 1) - game["team_b"]["wickets"]
                result_str = f"🎉 <b>Team B 🔵 WINS by {wickets_left} wickets!</b>
"
             else:
                run_diff = team_b_score - team_a_score
                result_str = f"🎉 <b>Team B 🔵 WINS by {run_diff} runs!</b>
"
        else:
            result_str = "🤝 <b>IT'S A TIE!</b> 🤝
"

        text += result_str + "━━━━━━━━━━━━━━━━━━━━━━
"
    return text

def get_potm(game):
    best_player = get_potm_data(game)
    if best_player: return f"
🏅 <b>PLAYER OF THE MATCH: <a href='tg://user?id={best_player['id']}'>{best_player['name']}</a></b> 🏅
Here is your reward, take this 💋
"
    return ""

def generate_teams_message(game):
    text = "🏟️ <b>TEAMS ROSTER</b> 🏟️

"
    is_playing = game.get("state") == "PLAYING"
    bat_team = game.get("batting_team_ref", {}) if is_playing else {}
    bowl_team = game.get("bowling_team_ref", {}) if is_playing else {}
    
    for team_key, team_dict in [("team_a", game.get("team_a", {})), ("team_b", game.get("team_b", {}))]:
        team_name = "🔴 <b>TEAM A</b>" if team_key == "team_a" else "🔵 <b>TEAM B</b>"
        text += f"{team_name}
"
        
        for i, p in enumerate(team_dict.get("players", []), 1):
            cap = " (C) 👑" if team_dict.get("captain") == p["id"] else ""
            status = ""
            if is_playing:
                if team_dict == bat_team:
                    if p.get("is_out"): status = " - (Out)"
                    elif p.get("is_striker"): status = " - (On Strike)"
                    elif p.get("is_non_striker"): status = " - (On Non Strike)"
                    else: status = " - (Available)"
                elif team_dict == bowl_team:
                    cb = game.get("current_bowler", {})
                    if cb and cb.get("id") == p["id"]: status = " - (Bowling)"
            
            text += f" {p.get('num', i)}. <a href='tg://user?id={p['id']}'>{p['name']}</a>{cap}<i>{status}</i>
"
        text += "
"
    return text

def set_afk_timer(context, chat_id, user_id, role):
    clear_afk_timer(context, chat_id)
    game = context.bot_data.get(chat_id)
    if not game: return
    
    if game.get("mode") == "TEAM":
        context.job_queue.run_once(team_afk_warning_10, 10, data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk10_{chat_id}")
        context.job_queue.run_once(team_afk_warning_30, 30, data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk30_{chat_id}")
        context.job_queue.run_once(team_afk_timeout, 60, data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk60_{chat_id}")
    else:
        context.job_queue.run_once(afk_warning_start, 10, data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk10_{chat_id}")
        context.job_queue.run_once(afk_warning_30, 30, data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk30_{chat_id}")
        context.job_queue.run_once(afk_timeout, 60, data={"chat_id": chat_id, "user_id": user_id, "role": role}, name=f"afk60_{chat_id}")

def clear_afk_timer(context, chat_id):
    for prefix in ["afk1_", "afk10_", "afk30_", "afk60_", "afk90_"]:
        jobs = context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}")
        for job in jobs: job.schedule_removal()

async def afk_warning_start(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role: return
    player = next((p for p in game["players"] if p["id"] == user_id), None)
    if not player: return
    await context.bot.send_message(chat_id, f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, it is your turn! You have <b>50 seconds</b> to play. ⏳", parse_mode="HTML")

async def afk_warning_30(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role: return
    player = next((p for p in game["players"] if p["id"] == user_id), None)
    if not player: return
    await context.bot.send_message(chat_id, f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, HURRY UP! You only have <b>30 seconds</b> left to play! ⏰", parse_mode="HTML")

async def afk_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role: return
    
    player = next((p for p in game["players"] if p["id"] == user_id), None)
    if not player: return
        
    await context.bot.send_message(chat_id, f"⏳ <b>TIME'S UP!</b> {player['name']} was AFK for 60 seconds and has been ELIMINATED! ❌", parse_mode="HTML")
    
    elim_idx = next((i for i, p in enumerate(game["players"]) if p["id"] == user_id), -1)
    if elim_idx == -1: return
    game["players"] = [p for p in game["players"] if p["id"] != user_id]
        
    if len(game["players"]) < 2:
        await commit_player_stats(game)
        game["state"] = "NOT_PLAYING"
        await context.bot.send_message(chat_id, "Not enough players left! Match abandoned. 🛑", parse_mode="HTML")
        return
        
    if elim_idx < game["batter_idx"]: game["batter_idx"] -= 1
    
    if game["batter_idx"] >= len(game["players"]):
        await commit_player_stats(game)
        game["state"] = "NOT_PLAYING"
        await context.bot.send_message(chat_id, "🏁 <b>MATCH FINISHED!</b> 🏁", parse_mode="HTML")
        await trigger_full_scorecard_message(context, chat_id, game)
        return
        
    available_bowlers = [i for i in range(len(game["players"])) if i != game["batter_idx"]]
    if available_bowlers: game["bowler_idx"] = random.choice(available_bowlers)
    else:
         await commit_player_stats(game)
         game["state"] = "NOT_PLAYING"
         await context.bot.send_message(chat_id, "Not enough players left! Match abandoned. 🛑", parse_mode="HTML")
         return
         
    game["waiting_for"] = "BOWLER"
    game["balls_bowled"] = 0
    game["special_used_this_over"] = False
    await trigger_bowl(context, chat_id)

async def team_afk_warning_10(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role: return
    player = next((p for p in game["team_a"]["players"] + game["team_b"]["players"] if p["id"] == user_id), None)
    if not player: return
    await context.bot.send_message(chat_id, f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, you have been AFK! You have <b>50 more seconds</b> left to play. ⏳", parse_mode="HTML")

async def team_afk_warning_30(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role: return
    player = next((p for p in game["team_a"]["players"] + game["team_b"]["players"] if p["id"] == user_id), None)
    if not player: return
    await context.bot.send_message(chat_id, f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, HURRY UP! You only have <b>30 seconds</b> left to play! ⏰", parse_mode="HTML")

async def team_afk_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data["chat_id"], job.data["user_id"], job.data["role"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING" or game.get("waiting_for") != role: return
    
    player = next((p for p in game["team_a"]["players"] + game["team_b"]["players"] if p["id"] == user_id), None)
    if not player: return
    
    if role == "BATTER":
        dismiss_batter(game, player)
        game["batting_team_ref"]["score"] -= 5
        player["runs"] -= 5
        game["batting_team_ref"]["wickets"] += 1
        await context.bot.send_message(chat_id, f"⏳ <b>TIME'S UP!</b> {player['name']} was AFK for 60 seconds! ❌
📉 <b>PENALTY:</b> -5 Runs to the team and batter! They are OUT!", parse_mode="HTML")
        if game["batting_team_ref"]["wickets"] >= len(game["batting_team_ref"]["players"]) - 1:
            await process_team_innings_end(context, chat_id, game)
            return
        game["waiting_for"] = "TEAM_BATTER_SELECT"
        await context.bot.send_message(chat_id, f"🏏 Captain/Host, please select the next batter using <code>/batting [number]</code>.", parse_mode="HTML")
    elif role == "BOWLER":
        game["batting_team_ref"]["score"] += 5
        player["conceded"] += 5
        game["waiting_for"] = "TEAM_BOWLER_SELECT"
        game["last_bowler_id"] = player["id"]
        await context.bot.send_message(chat_id, f"⏳ <b>TIME'S UP!</b> {player['name']} timed out! ❌
📈 <b>PENALTY:</b> +5 Runs to Batting Team!
Captain/Host, please select a NEW bowler to continue the over using <code>/bowling [number]</code>.", parse_mode="HTML")

async def queue_reminder(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "JOINING" or game.get("mode") != "SOLO":
        context.job.schedule_removal()
        return
    await context.bot.send_message(chat_id, f"⏳ <b>Queue is open!</b> Type /join to enter the match! There are 35 seconds left to join. (Total: {len(game['players'])}) 🏏", parse_mode="HTML")

async def auto_start_match(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]
    jobs = context.job_queue.get_jobs_by_name(f"queueremind_{chat_id}")
    for j in jobs: j.schedule_removal()
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "JOINING": return
    if len(game["players"]) >= 2:
        game.update({"state": "PLAYING", "waiting_for": "BOWLER", "batter_idx": 0, "bowler_idx": 1, "balls_bowled": 0, "special_used_this_over": False, "is_free_hit": False})
        await context.bot.send_message(chat_id, "⏳ <b>70 seconds are up! THE MATCH AUTO-STARTS NOW!</b> 🚨
Let's head to the pitch! 🏟️", parse_mode="HTML")
        await trigger_bowl(context, chat_id)
    else:
        game["state"] = "NOT_PLAYING"
        await context.bot.send_message(chat_id, "⏳ <b>70 seconds are up, but there are not enough players!</b> Match setup abandoned. 🛑", parse_mode="HTML")

async def trigger_team_captains(context, chat_id, game):
    game["state"] = "TEAM_CAPTAINS"
    for team_key in ["team_a", "team_b"]:
        random.shuffle(game[team_key]["players"])
        for idx, p in enumerate(game[team_key]["players"], 1): p["num"] = idx
    roster = generate_teams_message(game)
    await context.bot.send_photo(chat_id, photo=TEAMS_ROSTER_IMG, caption=roster, parse_mode="HTML")
    kb = [[InlineKeyboardButton("Team A Captain 👑", callback_data="team_cap_a"), InlineKeyboardButton("Team B Captain 👑", callback_data="team_cap_b")]]
    await context.bot.send_message(chat_id, "Who will lead the teams? Members click your team's button to become the Captain! ⚡", reply_markup=InlineKeyboardMarkup(kb))

async def team_join_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_JOINING": return
    if len(game["team_a"]["players"]) < 2 or len(game["team_b"]["players"]) < 2:
        game["is_paused_waiting_players"] = True
        await context.bot.send_message(chat_id, "⏳ Time's up! But we need at least 2 players in each team! The queue is paused. ⏸️
Once both teams have 2 players, the setup will automatically proceed!", parse_mode="HTML")
        return
    await trigger_team_captains(context, chat_id, game)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_type = update.message.chat.type
    chat_id = update.effective_chat.id
    
    if chat_type != 'private':
        current_time = time.time()
        cooldown = context.bot_data.get(f'start_cooldown_{chat_id}', 0)
        if current_time < cooldown:
            rem = int(cooldown - current_time)
            await update.message.reply_text(f"⏳ Start command is under cooldown! Try again after {rem} seconds.")
            return
        context.bot_data[f'start_cooldown_{chat_id}'] = current_time + 5

    if chat_type == "private":
        if context.args:
            try:
                group_id = int(context.args[0])
                if "active_bowlers" not in context.bot_data: context.bot_data["active_bowlers"] = {}
                context.bot_data["active_bowlers"][update.effective_user.id] = group_id
                
                game = context.bot_data.get(group_id)
                if game and game["state"] == "PLAYING" and game.get("waiting_for") == "BOWLER":
                    if game.get("mode") == "SOLO": bowler = game["players"][game["bowler_idx"]]
                    else: bowler = game["current_bowler"]
                        
                    if bowler and update.effective_user.id == bowler["id"]:
                        keyboard = []
                        if not game.get("special_used_this_over"): keyboard.append([InlineKeyboardButton("🎯 Try for yorker 🎯", callback_data=f"special_{group_id}")])
                        await update.message.reply_text(f"🥎 <b>Your Turn to Bowl!</b>
Type 1-6 or Try for yorker! 🤔👇", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None, parse_mode="HTML")
                        return
                    else:
                        await update.message.reply_text("It is not your turn to bowl right now! 🚫🏏")
                        return
            except ValueError: pass
                
        welcome_private = "<b>Welcome to ELITE CRICKET BOT! 🏏</b>

Step into the ultimate Telegram Cricket experience! Whether you want to practice your skills in Solo Mode or clash with rivals in a full-fledged Team T20 match, this bot brings the stadium to your screen."
        kb_private = [[InlineKeyboardButton("Contact Developer 👨‍💻", url="https://t.me/xrztz")], [InlineKeyboardButton("Support Group 💬", url="https://t.me/eclplays")], [InlineKeyboardButton("Play Cricket 🏏", url="https://t.me/eclplays")]]
        await update.message.reply_photo(photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777818831/file_00000000677c71fa8d7d9caa8a1b3cc9_k7l0au.png", caption=welcome_private, reply_markup=InlineKeyboardMarkup(kb_private), parse_mode="HTML")
        return

    game = context.bot_data.get(chat_id)
    if game is None:
        game = {"state": "NOT_PLAYING"}
        context.bot_data[chat_id] = game

    if game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
        await update.message.reply_text("❌ A match is already active in this group! Finish it or ask an admin to /endmatch first.")
        return
        
    welcome_text = "Welcome to the <b>ELITE CRICKET BOT</b> Arena! 🏆
Join our official community at @eclplays. 🏏

🔥 <b>A tournament is currently going on! Register via @eclregisbot</b> 🔥

Choose your mode: 👇"
    keyboard = [[InlineKeyboardButton("Solo Game 🏏", callback_data="solo_game")], [InlineKeyboardButton("Team Game 👥", callback_data="team_game")], [InlineKeyboardButton("Cancel ❌", callback_data="cancel")]]
    await update.message.reply_photo(photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777690770/IMG_20260502_082816_001_t0wejv.jpg", caption=welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def create_team_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_SETUP_HOST": 
        await update.message.reply_text("❌ No team game setup is active! Click 'Team Game' in /start first.")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can create the teams!")
        return
        
    game["state"] = "TEAM_JOINING"
    game["is_paused_waiting_players"] = False
    game["team_a"] = {"players": [], "captain": None, "score": 0, "wickets": 0, "balls_bowled": 0}
    game["team_b"] = {"players": [], "captain": None, "score": 0, "wickets": 0, "balls_bowled": 0}
    
    kb = [[InlineKeyboardButton("Join Team A 🔴", callback_data="join_team_a"), InlineKeyboardButton("Join Team B 🔵", callback_data="join_team_b")]]
    context.job_queue.run_once(team_join_timeout, 10, data={"chat_id": chat_id}, name=f"team_join_{chat_id}")
    await update.message.reply_text("⚔️ <b>TEAM REGISTRATION OPEN!</b> ⚔️

Players, choose your sides! You have 10 seconds to join. ⏳
<b>(Host can type /rejoin to extend 30s or use /add or /remove)</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def changecap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM":
        await update.message.reply_text("❌ No active team match right now!")
        return
    if update.effective_user.id != game.get("host_id"):
        await update.message.reply_text("❌ Only the Game Host can change captains!")
        return
    if game.get("state") in ["TEAM_SETUP_HOST", "TEAM_JOINING", "TEAM_CAPTAINS"] and (not game.get("team_a", {}).get("captain") or not game.get("team_b", {}).get("captain")):
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
    if target_user: target_player = next((p for p in game[team_key]["players"] if p["id"] == target_user.id), None)
    elif target_username: target_player = next((p for p in game[team_key]["players"] if p.get("username") == target_username), None)
                
    if not target_player:
        await update.message.reply_text(f"❌ User not found in Team {team_choice.upper()}! Make sure to reply to their message or tag them correctly.")
        return
    game[team_key]["captain"] = target_player["id"]
    await update.message.reply_text(f"✅ Team {team_choice.upper()} captain changed to {target_player['name']}!")

async def rejoin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "TEAM_JOINING": return
    if update.effective_user.id != game.get("host_id"): return
    jobs = context.job_queue.get_jobs_by_name(f"team_join_{chat_id}")
    for job in jobs: job.schedule_removal()
    context.job_queue.run_once(team_join_timeout, 30, data={"chat_id": chat_id}, name=f"team_join_{chat_id}")
    await update.message.reply_text("⏳ <b>Registration Extended!</b> 30 more seconds to join the teams! 👥", parse_mode="HTML")

async def changeover_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
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
        
    new_overs = int(context.args[0])
    current_balls = game["bowling_team_ref"]["balls_bowled"]
    played_overs = current_balls // 6
    
    if new_overs <= played_overs:
        await update.message.reply_text(f"❌ The match has already crossed {played_overs} overs! The new target must be greater than {played_overs} overs.")
        return
        
    game["target_overs"] = new_overs
    await update.message.reply_text(f"✅ <b>Overs updated!</b> The match is now set for <b>{new_overs} overs</b> per side.", parse_mode="HTML")

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
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
    
    if not target_user and target_username:
        if users_col is not None:
            db_user = await users_col.find_one({"username": target_username})
            if db_user:
                class DummyUser:
                    def __init__(self, uid, fname, uname):
                        self.id = uid
                        self.first_name = fname
                        self.username = uname
                        self.is_bot = False
                target_user = DummyUser(db_user['user_id'], db_user['first_name'], db_user['username'])

    if not target_user:
        await update.message.reply_text("❌ Please reply to a user's message or make sure they have played before if using @username!")
        return
    if target_user.is_bot:
        await update.message.reply_text("❌ You cannot add a bot to the team!")
        return
    if is_user_playing_anywhere(context, target_user.id):
        await update.message.reply_text("❌ User is already in a game or in a queue in either this or other group")
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
    new_player = {"id": target_user.id, "name": target_user.first_name, "username": username, "runs": 0, "balls_faced": 0, "wickets": 0, "conceded": 0, "balls_bowled": 0, "is_out": False, "match_4s": 0, "match_6s": 0}
    if game.get("state") != "TEAM_JOINING": new_player["num"] = get_next_num(game[team_key]["players"])
    game[team_key]["players"].append(new_player)
    team_name = "TEAM A 🔴" if team_choice == "a" else "TEAM B 🔵"
    await update.message.reply_text(f"✅ <b>{target_user.first_name}</b> has been manually added to {team_name} by the Host! 👥", parse_mode="HTML")
    
    if game.get("is_paused_waiting_players"):
        if len(game["team_a"]["players"]) >= 2 and len(game["team_b"]["players"]) >= 2:
            game["is_paused_waiting_players"] = False
            await context.bot.send_message(chat_id, "✅ Minimum player requirement met! Resuming setup... ▶️")
            await trigger_team_captains(context, chat_id, game)

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
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
        
    removed = False
    target_name = ""
    for team_key in ["team_a", "team_b"]:
        for p in list(game[team_key]["players"]):
            if (target_user and p["id"] == target_user.id) or (target_username and p.get("username") == target_username):
                target_name = p["name"]
                game[team_key]["players"].remove(p)
                removed = True
                for i, p_rem in enumerate(game[team_key]["players"], 1): p_rem["num"] = i
                break
                
    if removed: await update.message.reply_text(f"✅ <b>{target_name}</b> has been successfully removed from their team! Numbers updated. 🚪", parse_mode="HTML")
    else: await update.message.reply_text(f"❌ {target_user.first_name if target_user else target_username} is not in any team!")

async def changehost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM" or game.get("state") in ["NOT_PLAYING", None, "TEAM_FINISHED"]: 
        await update.message.reply_text("❌ No active team match to change host!")
        return

    user_id = update.effective_user.id
    is_host = (user_id == game.get("host_id"))
    in_team_a = False
    in_team_b = False
    if "team_a" in game and "players" in game["team_a"]:
        in_team_a = any(p["id"] == user_id for p in game["team_a"]["players"])
    if "team_b" in game and "players" in game["team_b"]:
        in_team_b = any(p["id"] == user_id for p in game["team_b"]["players"])
        
    if not (is_host or in_team_a or in_team_b):
        await update.message.reply_text("⚠️ Warning: Only the Game Host or active players in Team A/B can use this command!")
        return
        
    target_user, target_username = get_user_from_mention(update)
    if not target_user and target_username:
        if users_col is not None:
            db_user = await users_col.find_one({"username": target_username})
            if db_user:
                class DummyUser:
                    def __init__(self, uid, fname, uname):
                        self.id = uid; self.first_name = fname; self.username = uname; self.is_bot = False
                target_user = DummyUser(db_user['user_id'], db_user['first_name'], db_user['username'])
                
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
        game["host_vote_name"] = target_user.first_name
        game["host_votes"] = set()
        kb = [[InlineKeyboardButton("Vote ✅ (0/4)", callback_data="vote_host")]]
        await update.message.reply_text(f"🗳️ Vote initiated to change host to <b>{target_user.first_name}</b>!
4 votes required.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private": return
    chat_id = update.effective_chat.id
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "JOINING":
        await update.message.reply_text("No match is open for joining! Type /start ❌🏏")
        return
    user = update.effective_user
    if is_user_playing_anywhere(context, user.id):
        await update.message.reply_text("❌ you are already in a game or in a queue in either this or other group")
        return
    if any(p["id"] == user.id for p in game["players"]):
        await update.message.reply_text(f"⚠️ <b>{user.first_name}</b>, you are ALREADY in the queue! Please wait for the match to start. ⏳🧍‍♂️", parse_mode="HTML")
        return

    username = user.username.lower() if user.username else None
    await init_user_db(user.id, user.first_name, username)
    game["players"].append({"id": user.id, "name": user.first_name, "username": username, "runs": 0, "conceded": 0, "wickets": 0, "balls_bowled": 0, "balls_faced": 0, "match_4s": 0, "match_6s": 0})
    
    timer_msg = ""
    if len(game["players"]) == 1:
        context.job_queue.run_once(auto_start_match, 70, data={"chat_id": chat_id}, name=f"autostart_{chat_id}")
        context.job_queue.run_repeating(queue_reminder, interval=35, first=35, data={"chat_id": chat_id}, name=f"queueremind_{chat_id}")
        timer_msg = "
⏳ <i>Auto-start timer initiated: Match begins in 70 seconds!</i>"
        
    await update.message.reply_text(f"✅ <b>{user.first_name}</b> joined! (Total: {len(game['players'])}) 👥{timer_msg}", parse_mode="HTML")

async def leavesolo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
    game = context.bot_data.get(chat_id)
    if not game: return
    if game.get("state") == "PLAYING":
        await update.message.reply_text("❌ The match has already started! You can't leave now.")
        return
    if game.get("state") == "JOINING":
        user_id = update.effective_user.id
        player = next((p for p in game["players"] if p["id"] == user_id), None)
        if player:
            game["players"] = [p for p in game["players"] if p["id"] != user_id]
            await update.message.reply_text(f"👋 <b>{update.effective_user.first_name}</b> has left the queue. (Total: {len(game['players'])}) 👥", parse_mode="HTML")
            if len(game["players"]) == 0:
                for prefix in ["autostart_", "queueremind_"]:
                    jobs = context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}")
                    for job in jobs: job.schedule_removal()
                await update.message.reply_text("Queue is empty! 🏏 Timer stopped.")
        else: await update.message.reply_text("You are not in the queue! ❌")

async def startsolo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.message.chat.type == "private": return
    if not await is_admin(update.effective_chat, update.effective_user.id):
        await update.message.reply_text("❌ Only group admins can start the match manually!")
        return
    game = context.bot_data.get(chat_id)
    if not game or game["state"] != "JOINING": return
    if len(game["players"]) < 2:
        await update.message.reply_text("We need at least 2 players! 👥🏏")
        return
    for prefix in ["autostart_", "queueremind_"]:
        jobs = context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}")
        for job in jobs: job.schedule_removal()
    game.update({"state": "PLAYING", "waiting_for": "BOWLER", "batter_idx": 0, "bowler_idx": 1, "balls_bowled": 0, "special_used_this_over": False, "is_free_hit": False})
    await update.message.reply_text(" <b>THE MATCH HAS BEGUN!</b> ", parse_mode="HTML")
    await trigger_bowl(context, chat_id)

async def endmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
    if not await is_admin(update.effective_chat, update.effective_user.id):
        await update.message.reply_text("❌ Only group admins can end the match!")
        return
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
        await update.message.reply_text("❌ There is no active match to end!")
        return
    keyboard = [[InlineKeyboardButton("Yes, End Match ✅", callback_data=f"endmatch_yes_{chat_id}")], [InlineKeyboardButton("Cancel ❌", callback_data=f"endmatch_no_{chat_id}")]]
    await update.message.reply_text("⚠️ <b>Admin Action:</b> Are you sure you want to force-end the current match?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def soloscore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "SOLO" or game.get("state") in ["NOT_PLAYING", None]:
        await update.message.reply_text("❌ No active solo match is currently being played!")
        return
    await trigger_full_scorecard_message(context, chat_id, game)

async def teamscore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM" or game.get("state") in ["NOT_PLAYING", None]:
        await update.message.reply_text("❌ No active team match is currently being played!")
        return
    await trigger_full_scorecard_message(context, chat_id, game)

async def teams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM" or game.get("state") in ["NOT_PLAYING", "TEAM_SETUP_HOST", "TEAM_JOINING"]:
        await update.message.reply_text("❌ No active team match right now!")
        return
    roster = generate_teams_message(game)
    await update.message.reply_photo(photo=TEAMS_ROSTER_IMG, caption=roster, parse_mode="HTML")

async def batting_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
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
        text = "🏏 <b>AVAILABLE BATTERS:</b>
"
        for p in batting_team["players"]:
            status = "❌ (Out)" if p.get("is_out") else ("🏏 (On Pitch)" if p.get("is_striker") or p.get("is_non_striker") else "✅ (Available)")
            text += f"[{p.get('num', '?')}] {p['name']} - {status}
"
        text += "
👉 <i>Usage: /batting [number] to select.</i>"
        await update.message.reply_text(text, parse_mode="HTML")
        return

    if update.effective_user.id not in [batting_team["captain"], game["host_id"]]: 
        await update.message.reply_text("❌ Only the Host or Batting Team Captain can select the batter!")
        return
        
    p_num = int(context.args[0])
    selected = next((p for p in batting_team["players"] if p.get("num") == p_num), None)
    
    if not selected:
        await update.message.reply_text(f"❌ Player {p_num} not found in your team!")
        return
    if selected.get("is_out"):
        await update.message.reply_text(f"❌ {selected['name']} is already out! Select a different player.")
        return
    
    st = game.get("striker") or {}
    ns = game.get("non_striker") or {}
    if st.get("id") == selected["id"] or ns.get("id") == selected["id"]:
        await update.message.reply_text(f"❌ {selected['name']} is already on the pitch!")
        return
        
    if game["waiting_for"] == "TEAM_OPENERS_BAT":
        if not game.get("striker"):
            game["striker"] = selected
            selected["is_striker"] = True
            await update.message.reply_text(f"🏏 <b>{selected['name']}</b> selected as Striker!", parse_mode="HTML")
        elif not game.get("non_striker"):
            game["non_striker"] = selected
            selected["is_non_striker"] = True
            openers_gif = "https://media.giphy.com/media/hGJTJqTNaj0XXkLXZr/giphy.gif"
            caption_txt = f"🏏 <b>{selected['name']}</b> selected as Non-Striker!

Bowling Team Captain/Host, type /bowling to see bowlers or /bowling [num] to select opening bowler."
            await send_media_safely(context, chat_id, openers_gif, caption_txt)
            game["waiting_for"] = "TEAM_BOWLER_SELECT"
    else:
        if not game.get("striker"):
            game["striker"] = selected
            selected["is_striker"] = True
        elif not game.get("non_striker"):
            game["non_striker"] = selected
            selected["is_non_striker"] = True
            
        await update.message.reply_text(f"🏏 <b>{selected['name']}</b> walks out to the pitch!", parse_mode="HTML")
        if game.get("need_new_bowler"):
            game["need_new_bowler"] = False
            game["waiting_for"] = "TEAM_BOWLER_SELECT"
            await update.message.reply_text("Bowling Captain/Host, please select the next bowler using <code>/bowling [num]</code>.", parse_mode="HTML")
        else:
            game["waiting_for"] = "BOWLER"
            await trigger_bowl(context, chat_id)

async def bowling_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private": return
    game = context.bot_data.get(chat_id)
    if not game or game.get("mode") != "TEAM":
        await update.message.reply_text("❌ There is no active team match currently! This command is only for team matches.")
        return
    if game.get("state") != "PLAYING": 
        await update.message.reply_text("❌ The match hasn't started yet!")
        return
        
    if game.get("waiting_for") in ["TEAM_OPENERS_BAT", "TEAM_BATTER_SELECT"]: 
        await update.message.reply_text("❌ Batters not selected yet warning! Let the batting team select their batter(s) first.")
        return
        
    if game.get("waiting_for") != "TEAM_BOWLER_SELECT": 
        await update.message.reply_text("❌ A bowler is already selected and bowling right now!")
        return
    
    bowling_team = game["bowling_team_ref"]
    if not context.args or not context.args[0].isdigit():
        text = "🥎 <b>AVAILABLE BOWLERS:</b>
"
        for p in bowling_team["players"]:
            status = "✅ (Available)"
            if game.get("last_bowler_id") == p["id"]: status = "⏳ (Bowled Last Over)"
            cb = game.get("current_bowler") or {}
            if cb.get("id") == p["id"]: status = "🥎 (Bowling Now)"
            text += f"[{p.get('num', '?')}] {p['name']} - {p['balls_bowled']//6}.{p['balls_bowled']%6} Ov - {status}
"
        text += "
👉 <i>Usage: /bowling [number] to select.</i>"
        await update.message.reply_text(text, parse_mode="HTML")
        return

    if update.effective_user.id not in [bowling_team["captain"], game["host_id"]]: 
        await update.message.reply_text("❌ Only the Host or Bowling Team Captain can select the bowler!")
        return
        
    p_num = int(context.args[0])
    selected = next((p for p in bowling_team["players"] if p.get("num") == p_num), None)
    
    if not selected:
        await update.message.reply_text(f"❌ Player {p_num} not found in your team!")
        return
    if game.get("last_bowler_id") == selected["id"]:
        await update.message.reply_text("❌ A bowler cannot bowl two consecutive overs!")
        return
        
    game["current_bowler"] = selected
    game["waiting_for"] = "BOWLER"
    
    await update.message.reply_text(f"🥎 <b>{selected['name']}</b> is handed the ball!", parse_mode="HTML")
    if game.get("innings_start_msg_pending"):
        game["innings_start_msg_pending"] = False
        await update.message.reply_text("🚨 <b>THE INNINGS HAS BEGUN!</b>", parse_mode="HTML")
    await trigger_bowl(context, chat_id)

async def trigger_full_scorecard_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, game_data):
    scorecard = generate_scorecard(game_data)
    potm = get_potm(game_data) if game_data.get("state") in ["NOT_PLAYING", "TEAM_FINISHED"] else ""
    final_caption = f"{scorecard}{potm}"
    await context.bot.send_photo(chat_id=chat_id, photo=SCOREBOARD_IMG, caption=final_caption, parse_mode="HTML")

async def send_top_performers_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, game):
    text = "🌟 <b>TOP PERFORMERS OF THE MATCH</b> 🌟
━━━━━━━━━━━━━━━━━━━━━━
"
    
    for team_key, team_name in [("team_a", "🔴 TEAM A"), ("team_b", "🔵 TEAM B")]:
        team = game.get(team_key)
        if not team or not team.get("players"): continue
        
        best_batter = max(team["players"], key=lambda x: x["runs"])
        best_bowler = max(team["players"], key=lambda x: x["wickets"] * 100 - x["conceded"])
        
        text += f"
<b>{team_name}</b>
"
        text += f"🏏 <b>Best Batter:</b> {best_batter['name'][:15]} ➜ <b>{best_batter['runs']}</b> ({best_batter['balls_faced']})
"
        b_ov, b_bl = divmod(best_bowler["balls_bowled"], 6)
        text += f"🥎 <b>Best Bowler:</b> {best_bowler['name'][:15]} ➜ <b>{best_bowler['wickets']}W</b> for {best_bowler['conceded']}R ({b_ov}.{b_bl} Ov)
"
        
    text += "
━━━━━━━━━━━━━━━━━━━━━━
"
    await context.bot.send_message(chat_id, text, parse_mode="HTML")

async def trigger_bowl(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    game = context.bot_data.get(chat_id)
    if not game or game.get("state") != "PLAYING": return
    
    if game.get("mode") == "TEAM":
        bowler = game["current_bowler"]
        batter = game["striker"]
        over_info = f"{game['bowling_team_ref']['balls_bowled'] // 6}.{game['bowling_team_ref']['balls_bowled'] % 6} / {game['target_overs']}"
    else:
        bowler = game["players"][game["bowler_idx"]]
        batter = game["players"][game["batter_idx"]]
        over_info = f"{game['balls_bowled']}/{game['spell']} balls"
    
    if "active_bowlers" not in context.bot_data: context.bot_data["active_bowlers"] = {}
    context.bot_data["active_bowlers"][bowler["id"]] = chat_id
    
    bot_info = await context.bot.get_me()
    url = f"https://t.me/{bot_info.username}"
    free_hit_tag = "🚀 <b>FREE HIT ACTIVE!!</b>
" if game.get("is_free_hit") else ""
    
    dm_text = f"🏏 <b>Match in Progress!</b>

🏏 Batter: <b>{batter['name']}</b> ({batter['runs']} off {batter['balls_faced']})
🥎 Over Status: {over_info}.

👉 <b>Your Turn to Bowl!</b> Type a number from 1 to 6."
    keyboard = []
    if not game.get("special_used_this_over"): keyboard.append([InlineKeyboardButton("🎯 Try for yorker 🎯", callback_data=f"special_{chat_id}")])
        
    dm_sent = False
    try:
        await context.bot.send_message(chat_id=bowler["id"], text=dm_text, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None, parse_mode="HTML")
        dm_sent = True
    except Exception: pass
        
    if dm_sent:
        group_text = f"{free_hit_tag}📊 <b>Status:</b>
🏏 <b>Batter:</b> {batter['name']} ({batter['runs']} off {batter['balls_faced']})
🥎 <b>Bowler:</b> {bowler['name']} (Over: {over_info})

👉 <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, check your DM to bowl! 🤫🥎"
        group_kb = [[InlineKeyboardButton("Bowl Delivery 🥎", url=url)]]
    else:
        fallback_url = f"https://t.me/{bot_info.username}?start={chat_id}"
        group_text = f"{free_hit_tag}📊 <b>Status:</b>
🏏 <b>Batter:</b> {batter['name']} ({batter['runs']} off {batter['balls_faced']})
🥎 <b>Bowler:</b> {bowler['name']} (Over: {over_info})

⚠️ <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, I couldn't DM you! Click below to start me, then bowl! 🤫🥎"
        group_kb = [[InlineKeyboardButton("Start Bot & Bowl 🤖", url=fallback_url)]]
        
    await send_media_safely(context, chat_id, MEDIA["bowler_turn"], group_text, InlineKeyboardMarkup(group_kb))
    set_afk_timer(context, chat_id, bowler["id"], "BOWLER")

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

async def process_team_innings_end(context, chat_id, game):
    if game["innings"] == 1:
        game["innings"] = 2
        game["target"] = game["batting_team_ref"]["score"] + 1
        
        temp = game["batting_team_ref"]
        game["batting_team_ref"] = game["bowling_team_ref"]
        game["bowling_team_ref"] = temp
        
        for p in game["team_a"]["players"] + game["team_b"]["players"]:
            p["is_striker"] = False
            p["is_non_striker"] = False
            p["is_out"] = False
        
        game["striker"] = None
        game["non_striker"] = None
        game["current_bowler"] = None
        game["last_bowler_id"] = None
        game["is_free_hit"] = False
        game["special_used_this_over"] = False
        
        text = f"🛑 <b>INNINGS BREAK! AB CHASE KARO !! </b> 🛑

🎯 Target for the Bowling team: <b>{game['target']} runs</b> in {game['target_overs']} overs.

"
        text += "Batting Captain/Host, please select your opening pair using:
<code>/batting [number]</code> (do it twice)."
        game["waiting_for"] = "TEAM_OPENERS_BAT"
        game["innings_start_msg_pending"] = True
        
        await context.bot.send_message(chat_id, text, parse_mode="HTML")
    else:
        try:
            await commit_player_stats(game)
        except Exception as e:
            print(f"Stats Error: {e}")
        game["state"] = "TEAM_FINISHED"
        await context.bot.send_message(chat_id, "🏁 <b>MATCH FINISHED!</b> 🏁", parse_mode="HTML")
        await trigger_full_scorecard_message(context, chat_id, game)
        await send_top_performers_message(context, chat_id, game)
        game["state"] = "NOT_PLAYING"

async def userstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    target_user, target_username = get_user_from_mention(update)
    if not target_user and not target_username: target_user = update.effective_user
    if users_col is None:
        await update.message.reply_text("❌ Database connection error.")
        return
    try:
        user_data = None
        if target_user: user_data = await users_col.find_one({"user_id": target_user.id})
        elif target_username: user_data = await users_col.find_one({"username": target_username})
        if not user_data:
             name = target_user.first_name if target_user else target_username
             await update.message.reply_text(f"❌ Ek bhi match khela hai tune is bot se jo stats dekh raha ? {name}.")
             return

        hs_runs = user_data.get("highest_score", {}).get("runs", 0)
        hs_balls = user_data.get("highest_score", {}).get("balls", 0)
        total_runs = user_data.get("total_runs", 0)
        balls_faced = user_data.get("balls_faced", 0)
        sr = (total_runs / balls_faced * 100) if balls_faced > 0 else 0
        balls_bowled = user_data.get("balls_bowled", 0)
        runs_conceded = user_data.get("runs_conceded", 0)
        overs = balls_bowled // 6
        rem_balls = balls_bowled % 6
        eco = (runs_conceded / balls_bowled * 6) if balls_bowled > 0 else 0

        stats_text = f"📊 <b>PLAYER STATISTICS</b> 📊
═══════════════════════════
"
        stats_text += f"👤 <b>Name:</b> {user_data.get('first_name', 'Unknown')}
🆔 <b>ID:</b> <code>{user_data.get('user_id', 'Unknown')}</code>
┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈
"
        stats_text += f"🏏 <b>BATTING STATS</b>
🔸 <b>Highest Score:</b> {hs_runs} ({hs_balls})
🔸 <b>Total Runs:</b> {total_runs}
🔸 <b>Strike Rate:</b> {sr:.2f}
"
        stats_text += f"🔸 <b>6s:</b> {user_data.get('total_6s', 0)} | <b>4s:</b> {user_data.get('total_4s', 0)}
🔸 <b>100s:</b> {user_data.get('centuries', 0)} | <b>50s:</b> {user_data.get('half_centuries', 0)}
"
        stats_text += f"🔸 <b>Ducks 🦆:</b> {user_data.get('ducks', 0)}
┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈
"
        stats_text += f"🥎 <b>BOWLING STATS</b>
🔹 <b>Wickets:</b> {user_data.get('wickets', 0)}
🔹 <b>Hat-Tricks:</b> {user_data.get('hat_tricks', 0)}
"
        stats_text += f"🔹 <b>Overs Bowled:</b> {overs}.{rem_balls}
🔹 <b>Economy:</b> {eco:.2f}
┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈
"
        stats_text += f"🏆 <b>MATCH & AWARDS</b>
🔸 <b>Solo Matches:</b> {user_data.get('solo_matches', 0)}
🔸 <b>Team Matches:</b> {user_data.get('team_matches', 0)}
"
        stats_text += f"🔸 <b>MOTM Awards:</b> {user_data.get('motm', 0)}
═══════════════════════════"
        stats_img = "https://res.cloudinary.com/dxgfxfoog/image/upload/v1777818873/file_00000000fa6871fa8d9b30faff9899ae_hbyn9j.png"
        await update.message.reply_photo(photo=stats_img, caption=stats_text, parse_mode="HTML")
    except Exception as e:
         print(f"Error fetching stats: {e}")
         await update.message.reply_text("❌ An error occurred while fetching stats.")

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
        text = update.message.text.split(' ', 1)[1]
    if chats_col is None:
        await update.message.reply_text("Database not connected.")
        return
    success = 0; failed = 0
    status_msg = await update.message.reply_text("Broadcasting started... ⏳")
    async for chat in chats_col.find({}):
        chat_id = chat["chat_id"]
        try:
            if message_to_send: await context.bot.copy_message(chat_id=chat_id, from_chat_id=update.effective_chat.id, message_id=message_to_send.message_id)
            else: await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except Exception: failed += 1
    await status_msg.edit_text(f"✅ <b>Broadcast finished!</b>

📨 Sent: {success}
❌ Failed: {failed}", parse_mode="HTML")

async def botstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("Jaa jaake chaddhi badal le pehle owner command use kareg.")
        return
    if chats_col is None:
        await update.message.reply_text("Database not connected.")
        return
    users_count = await chats_col.count_documents({"type": "private"})
    groups_count = await chats_col.count_documents({"type": {"$in": ["group", "supergroup"]}})
    await update.message.reply_text(f"📊 <b>Bot Statistics</b>

👤 Total Users Interacted: {users_count}
👥 Total Groups Present: {groups_count}", parse_mode="HTML")

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
        
    text = f"📊 <b>Bot Groups ({len(groups)}):</b>

"
    for i, g in enumerate(groups, 1):
        title = g.get('title', 'Unknown Group')
        text += f"{i}. {title} (<code>{g['chat_id']}</code>)
"
        
    if len(text) > 4000:
        text = text[:4000] + "...
[Truncated]"
        
    await update.message.reply_text(text, parse_mode="HTML")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try: await query.answer() 
    except Exception: pass
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    game = context.bot_data.get(chat_id)
    if game is None:
        game = {"state": "NOT_PLAYING"}
        context.bot_data[chat_id] = game

    if query.data == "solo_game":
        if game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
            try: await query.edit_message_caption(caption="❌ A match is already active or setting up in this group!", reply_markup=None)
            except: pass
            return
        keyboard = [[InlineKeyboardButton("3 Balls 🥎", callback_data="spell_3")], [InlineKeyboardButton("6 Balls 🥎", callback_data="spell_6")]]
        try: await query.message.delete()
        except: pass
        await context.bot.send_photo(chat_id=chat_id, photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777720022/file_00000000483072079f73014e1bba1fde_l4thrv.png", caption="Select Spell Limit: ⚖️🏏", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "team_game":
        if game.get("state") not in ["NOT_PLAYING", None, "TEAM_FINISHED"]:
            try: await query.edit_message_caption(caption="❌ A match is already active or setting up in this group!", reply_markup=None)
            except: pass
            return
        text = "👥 <b>TEAM GAME MODE</b> 👥

Form two teams, appoint captains, toss the coin, and clash in an epic T20-style showdown! 🏆🏏

Who will take charge?"
        kb = [[InlineKeyboardButton("HOST BANUNGA 👿", callback_data="host_banunga")], [InlineKeyboardButton("CANCEL ❌", callback_data="cancel")]]
        try: await query.message.delete()
        except: pass
        await context.bot.send_photo(chat_id=chat_id, photo="https://res.cloudinary.com/dxgfxfoog/image/upload/v1777720311/file_00000000332072078d00837e7d719f5e_ybg18b.png", caption=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "host_banunga":
        if is_user_playing_anywhere(context, user_id):
            try: await query.answer("❌ you are already in a game or in a queue in either this or other group", show_alert=True)
            except: await context.bot.send_message(chat_id, "❌ you are already in a game or in a queue in either this or other group")
            return
        context.bot_data[chat_id] = {"state": "TEAM_SETUP_HOST", "host_id": user_id, "mode": "TEAM"}
        try: await query.edit_message_caption(caption=f"👑 <a href='tg://user?id={user_id}'>{update.effective_user.first_name}</a> is the Game Host!

Host, please send /create_team to open the team registration.", parse_mode="HTML", reply_markup=None)
        except Exception: pass

    elif query.data == "join_team_a":
        if game.get("state") != "TEAM_JOINING": return
        if is_user_playing_anywhere(context, user_id):
            await context.bot.send_message(chat_id, "❌ you are already in a game or in a queue in either this or other group")
            return
        in_a = any(p["id"] == user_id for p in game["team_a"]["players"])
        in_b = any(p["id"] == user_id for p in game["team_b"]["players"])
        if in_a or in_b:
            team_name = "Team A 🔴" if in_a else "Team B 🔵"
            try: await query.answer(f"⚠️ You are already in {team_name}! Wait for the host to start.", show_alert=True)
            except: pass
            return
        username = update.effective_user.username.lower() if update.effective_user.username else None
        await init_user_db(user_id, update.effective_user.first_name, username)
        game["team_a"]["players"].append({"id": user_id, "name": update.effective_user.first_name, "username": username, "runs": 0, "balls_faced": 0, "wickets": 0, "conceded": 0, "balls_bowled": 0, "is_out": False, "match_4s": 0, "match_6s": 0})
        await context.bot.send_message(chat_id, f"🔴 <b>{update.effective_user.first_name}</b> joined Team A!", parse_mode="HTML")
        if game.get("is_paused_waiting_players") and len(game["team_a"]["players"]) >= 2 and len(game["team_b"]["players"]) >= 2:
            game["is_paused_waiting_players"] = False
            await context.bot.send_message(chat_id, "✅ Minimum player requirement met! Resuming setup... ▶️")
            await trigger_team_captains(context, chat_id, game)

    elif query.data == "join_team_b":
        if game.get("state") != "TEAM_JOINING": return
        if is_user_playing_anywhere(context, user_id):
            await context.bot.send_message(chat_id, "❌ you are already in a game or in a queue in either this or other group")
            return
        in_a = any(p["id"] == user_id for p in game["team_a"]["players"])
        in_b = any(p["id"] == user_id for p in game["team_b"]["players"])
        if in_a or in_b:
            team_name = "Team A 🔴" if in_a else "Team B 🔵"
            try: await query.answer(f"⚠️ You are already in {team_name}! Wait for the host to start.", show_alert=True)
            except: pass
            return
        username = update.effective_user.username.lower() if update.effective_user.username else None
        await init_user_db(user_id, update.effective_user.first_name, username)
        game["team_b"]["players"].append({"id": user_id, "name": update.effective_user.first_name, "username": username, "runs": 0, "balls_faced": 0, "wickets": 0, "conceded": 0, "balls_bowled": 0, "is_out": False, "match_4s": 0, "match_6s": 0})
        await context.bot.send_message(chat_id, f"🔵 <b>{update.effective_user.first_name}</b> joined Team B!", parse_mode="HTML")
        if game.get("is_paused_waiting_players") and len(game["team_a"]["players"]) >= 2 and len(game["team_b"]["players"]) >= 2:
            game["is_paused_waiting_players"] = False
            await context.bot.send_message(chat_id, "✅ Minimum player requirement met! Resuming setup... ▶️")
            await trigger_team_captains(context, chat_id, game)

    elif query.data in ["team_cap_a", "team_cap_b"]:
        if game.get("state") != "TEAM_CAPTAINS": return
        team_key = "team_a" if query.data == "team_cap_a" else "team_b"
        if not any(p["id"] == user_id for p in game[team_key]["players"]):
            try: await query.answer("You are not in this team!", show_alert=True)
            except: pass
            return
        if game[team_key]["captain"]:
            try: await query.answer("Captain already selected!", show_alert=True)
            except: pass
            return
        game[team_key]["captain"] = user_id
        await context.bot.send_message(chat_id, f"👑 <b>{update.effective_user.first_name}</b> is now Captain of {'Team A 🔴' if team_key == 'team_a' else 'Team B 🔵'}!", parse_mode="HTML")
        if game["team_a"]["captain"] and game["team_b"]["captain"]:
            if game.get("state") == "TEAM_CAPTAINS":
                game["state"] = "TEAM_TOSS"
                toss_winner_team = random.choice(["team_a", "team_b"])
                game["toss_winner_team"] = toss_winner_team
                cap_id = game[toss_winner_team]["captain"]
                cap_name = next(p["name"] for p in game[toss_winner_team]["players"] if p["id"] == cap_id)
                kb = [[InlineKeyboardButton("Heads 🪙", callback_data="toss_heads"), InlineKeyboardButton("Tails 🪙", callback_data="toss_tails")]]
                toss_vid = "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777819028/VID_20260503195638_lhif0h.mp4"
                caption_msg = f"🪙 <b>TOSS TIME!</b>
<a href='tg://user?id={cap_id}'>{cap_name}</a>, call the toss!"
                await send_media_safely(context, chat_id, toss_vid, caption_msg, InlineKeyboardMarkup(kb))

    elif query.data in ["toss_heads", "toss_tails"]:
        if game.get("state") != "TEAM_TOSS": return
        if user_id != game[game["toss_winner_team"]]["captain"]:
            try: await query.answer("Only the designated captain can call the toss!", show_alert=True)
            except: pass
            return
        won_toss = random.choice([True, False])
        if won_toss:
            game["state"] = "TEAM_TOSS_DECISION"
            winner_team_name = "Team A 🔴" if game["toss_winner_team"] == "team_a" else "Team B 🔵"
            kb = [[InlineKeyboardButton("Bat 🏏", callback_data="toss_bat"), InlineKeyboardButton("Bowl 🥎", callback_data="toss_bowl")]]
            try: await query.message.delete()
            except Exception: pass
            await context.bot.send_message(chat_id, text=f"🎉 <b>{winner_team_name}</b> won the toss! What will you do?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        else:
            game["state"] = "TEAM_TOSS_DECISION"
            game["toss_winner_team"] = "team_b" if game["toss_winner_team"] == "team_a" else "team_a"
            cap_id = game[game["toss_winner_team"]]["captain"]
            cap_name = next(p["name"] for p in game[game["toss_winner_team"]]["players"] if p["id"] == cap_id)
            winner_team_name = "Team A 🔴" if game["toss_winner_team"] == "team_a" else "Team B 🔵"
            kb = [[InlineKeyboardButton("Bat 🏏", callback_data="toss_bat"), InlineKeyboardButton("Bowl 🥎", callback_data="toss_bowl")]]
            try: await query.message.delete()
            except Exception: pass
            await context.bot.send_message(chat_id, text=f"❌ You lost the toss!

🎉 <b>{winner_team_name}</b> (<a href='tg://user?id={cap_id}'>{cap_name}</a>) won the toss. What will they choose?", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    elif query.data in ["toss_bat", "toss_bowl"]:
        if game.get("state") != "TEAM_TOSS_DECISION": return
        if user_id != game[game["toss_winner_team"]]["captain"]:
            try: await query.answer("Only the toss winning captain can decide!", show_alert=True)
            except: pass
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
        host_id = game["host_id"]
        try: host_name = (await context.bot.get_chat_member(chat_id, host_id)).user.first_name
        except: host_name = "Host"
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id, text=f"✅ The captain chose to {dec_text} first!")
        kb = [[InlineKeyboardButton(str(o), callback_data=f"tovers_{o}") for o in [3, 5, 10]], [InlineKeyboardButton(str(o), callback_data=f"tovers_{o}") for o in [15, 20, 25]]]
        await context.bot.send_message(chat_id, f"<a href='tg://user?id={host_id}'>{host_name}</a> (Game Host), select the number of overs for this match:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

    elif query.data.startswith("tovers_"):
        if game.get("state") != "TEAM_OVERS": return
        if user_id != game["host_id"]:
            try: await query.answer("Only the host can select overs!", show_alert=True)
            except: pass
            return
        overs = int(query.data.split("_")[1])
        game.update({"target_overs": overs, "state": "PLAYING", "innings": 1, "waiting_for": "TEAM_OPENERS_BAT", "is_free_hit": False, "special_used_this_over": False, "innings_start_msg_pending": True})
        try: await query.edit_message_text(f"✅ Match set for <b>{overs} Overs</b> per side!", parse_mode="HTML", reply_markup=None)
        except: pass
        await context.bot.send_message(chat_id, f"Batting Captain/Host, please select your opening pair using:
<code>/batting [number]</code> (do it twice).", parse_mode="HTML")

    elif query.data.startswith("spell_"):
        if context.bot_data.get(chat_id, {}).get("state") in ["JOINING", "PLAYING"]:
            try: await query.edit_message_caption(caption="❌ A match is already active or setting up in this group!", reply_markup=None)
            except: pass
            return
        spell_len = int(query.data.split("_")[1])
        context.bot_data[chat_id] = {"state": "JOINING", "mode": "SOLO", "spell": spell_len, "players": []}
        try: await query.edit_message_caption(caption=f"🏏 <b>Queue Open!</b> (Spell: {spell_len} balls) ⚖️
👉 Type /join
👉 Type /leavesolo to exit queue
👉 Admin can type /startsolo", parse_mode="HTML", reply_markup=None)
        except: pass

    elif query.data == "cancel":
        if game.get("state") == "PLAYING":
            try: await query.edit_message_caption(caption="❌ Match is already playing! Use /endmatch to stop it.", reply_markup=None)
            except: pass
            return
        game["state"] = "NOT_PLAYING"
        for prefix in ["autostart_", "team_join_", "queueremind_"]:
            for job in context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}"): job.schedule_removal()
        try: await query.edit_message_caption(caption="Setup cancelled. 🏏❌", reply_markup=None)
        except: pass
        
    elif query.data == "vote_host":
        if "host_votes" not in game: return
        if user_id in game["host_votes"]:
            try: await query.answer("You already voted!", show_alert=True)
            except: pass
            return
        game["host_votes"].add(user_id)
        votes = len(game["host_votes"])
        if votes >= 4:
            game["host_id"] = game["host_vote_target"]
            try: await query.edit_message_text(f"✅ Vote passed! Game Host successfully changed to <b>{game['host_vote_name']}</b>! 👑", parse_mode="HTML", reply_markup=None)
            except: pass
        else:
            try: await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"Vote ✅ ({votes}/4)", callback_data="vote_host")]]))
            except: pass

    elif query.data.startswith("endmatch_"):
        parts = query.data.split("_")
        action = parts[1]; targ_chat_id = int(parts[2])
        if not await is_admin(update.effective_chat, update.effective_user.id):
            await context.bot.send_message(chat_id, "❌ Only admins can click this!")
            return
        if action == "yes":
            game_ref = context.bot_data.get(targ_chat_id)
            if game_ref: 
                try: await commit_player_stats(game_ref)
                except Exception as e: print(f"Error in stats: {e}")
                game_ref["state"] = "NOT_PLAYING"
                for prefix in ["autostart_", "team_join_", "queueremind_", "afk1_", "afk10_", "afk30_", "afk60_", "afk90_"]:
                    try:
                        for job in context.job_queue.get_jobs_by_name(f"{prefix}{targ_chat_id}"): job.schedule_removal()
                    except: pass
            try: await query.edit_message_text("🛑 <b>Match has been force-ended by an Admin.</b>", parse_mode="HTML", reply_markup=None)
            except Exception: pass
        elif action == "no":
            try: await query.edit_message_text("✅ Force-end cancelled. The match continues!", reply_markup=None)
            except Exception: pass

    elif query.data.startswith("special_"):
        group_id = int(query.data.split("_")[1])
        game = context.bot_data.get(group_id)
        if not game or game["state"] != "PLAYING" or game.get("waiting_for") != "BOWLER": return
        if game.get("mode") == "SOLO": bowler = game["players"][game["bowler_idx"]]; batter = game["players"][game["batter_idx"]]
        else: bowler = game["current_bowler"]; batter = game["striker"]
            
        if update.effective_user.id != bowler["id"] or game.get("special_used_this_over"): return
        if "active_bowlers" in context.bot_data and update.effective_user.id in context.bot_data["active_bowlers"]:
            del context.bot_data["active_bowlers"][update.effective_user.id]
            
        game["special_used_this_over"] = True
        clear_afk_timer(context, group_id)
        roll = random.randint(1, 100)
        
        if roll <= 60:
            try: await query.edit_message_text("Oops! Missed yorker and gave a <b>WIDE</b> ball! 1 extra run. You must bowl again.", parse_mode="HTML", reply_markup=None)
            except: pass
            batter["runs"] += 1; bowler["conceded"] += 1
            if game.get("mode") == "TEAM": game["batting_team_ref"]["score"] += 1
            await context.bot.send_message(group_id, "🚨 <b>WIDE BALL!</b> 1 extra run. Bowler must re-bowl! 🥎", parse_mode="HTML")
            await trigger_bowl(context, group_id)
        elif roll <= 80:
            try: await query.edit_message_text("Oops! Missed yorker and gave a <b>NO BALL!</b>
Koi na kismat ki baat hai !", parse_mode="HTML", reply_markup=None)
            except: pass
            game["current_bowl"] = "NO_BALL"
            game["waiting_for"] = "BATTER"
            hit_opts = "1-6" if game.get("mode") == "SOLO" else "0-6"
            await send_media_safely(context, group_id, MEDIA["batter_turn"], f"🚨 Ball delivered !! 🥎💨
👉 <a href='tg://user?id={batter['id']}'>{batter['name']}</a>, type {hit_opts} to hit! 🏏👇")
            set_afk_timer(context, group_id, batter["id"], "BATTER")
        else:
            msg = "🎯 <b>Yorker pel diya bhai 😶‍🌫️</b> Let's see how the batter reacts...
⚠️ If the batter chooses "
            msg += "0-3, they survive. " if game.get("mode") == "TEAM" else "1-3, they survive. "
            msg += "Otherwise, they are OUT! ☝️"
            try: await query.edit_message_text(msg, parse_mode="HTML", reply_markup=None)
            except: pass
            game["current_bowl"] = "YORKER"
            game["waiting_for"] = "BATTER"
            hit_opts = "1-6" if game.get("mode") == "SOLO" else "0-6"
            await send_media_safely(context, group_id, MEDIA["batter_turn"], f"🚨 Ball bowled! 🥎💨
👉 <a href='tg://user?id={batter['id']}'>{batter['name']}</a>, type {hit_opts} to hit! 🏏👇")
            set_afk_timer(context, group_id, batter["id"], "BATTER")

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    chat_type = update.message.chat.type
    if not user_input.isdigit(): return
    val = int(user_input)

    if chat_type == "private":
        user_id = update.effective_user.id
        group_id = context.bot_data.get("active_bowlers", {}).get(user_id)
        if not group_id: return
        game = context.bot_data.get(group_id)
        if not game or game["state"] != "PLAYING" or game.get("waiting_for") != "BOWLER": return
        if game.get("mode") == "SOLO": bowler = game["players"][game["bowler_idx"]]; batter = game["players"][game["batter_idx"]]
        else: bowler = game["current_bowler"]; batter = game["striker"]
        if user_id != bowler["id"]: return
        if val < 1 or val > 6:
            await update.message.reply_text("❌ Bowlers can only bowl numbers from 1 to 6!")
            return
        clear_afk_timer(context, group_id)
        game["current_bowl"] = val
        game["waiting_for"] = "BATTER"
        if user_id in context.bot_data.get("active_bowlers", {}): del context.bot_data["active_bowlers"][user_id] 
        
        chat = await context.bot.get_chat(group_id)
        chat_url = None
        if chat.username: chat_url = f"https://t.me/{chat.username}"
        elif chat.invite_link: chat_url = chat.invite_link
        else:
            try: chat_url = await chat.export_invite_link()
            except: pass
                
        kb = [[InlineKeyboardButton("Back to Game 🔙", url=chat_url)]] if chat_url else []
        hit_opts = "1-6" if game.get("mode") == "SOLO" else "0-6"
        await update.message.reply_text(f"Choice locked! 🔒 You bowled a <b>{val}</b>.", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb) if kb else None)
        await send_media_safely(context, group_id, MEDIA["batter_turn"], f"🚨 Ball bowled! 🥎💨
👉 <a href='tg://user?id={batter['id']}'>{batter['name']}</a>, type {hit_opts} to hit! 🏏👇")
        set_afk_timer(context, group_id, batter["id"], "BATTER")
    else:
        chat_id = update.effective_chat.id
        game = context.bot_data.get(chat_id)
        if not game or game["state"] != "PLAYING" or game.get("waiting_for") != "BATTER": return
            
        if game.get("mode") == "SOLO":
            if val < 1 or val > 6: return
            batter = game["players"][game["batter_idx"]]
            bowler = game["players"][game["bowler_idx"]]
        else:
            if val < 0 or val > 6: return
            batter = game["striker"]
            bowler = game["current_bowler"]
            
        hit_val = val
        if update.effective_user.id != batter["id"]: return
        game["waiting_for"] = "PROCESSING_BATTER"
        clear_afk_timer(context, chat_id)
            
        if hit_val == 4: batter["match_4s"] = batter.get("match_4s", 0) + 1
        elif hit_val == 6: batter["match_6s"] = batter.get("match_6s", 0) + 1
            
        bowl_val = game["current_bowl"]
        media_url = None
        milestone_media = None
        milestone_text = None
        is_free_hit = game.get("is_free_hit", False)
        is_legal_delivery = True
        
        if bowl_val == "NO_BALL":
            is_legal_delivery = False
            bowler["consecutive_wickets"] = 0
            batter["balls_faced"] += 1
            game["is_free_hit"] = True 
            old_runs = batter["runs"]
            batter["runs"] += (hit_val + 1)
            bowler["conceded"] += (hit_val + 1)
            if game.get("mode") == "TEAM": game["batting_team_ref"]["score"] += (hit_val + 1)
            
            result_text = f"🚨 <b>IT WAS A NO BALL!</b> 1 penalty run.
🚀 <b>NEXT BALL WILL BE A FREE HIT!</b> 🚀

🏏 Batter hit: <b>{hit_val}</b>

"
            if hit_val == 0: result_text += f"🛡️ <b>Solid defense! Dot ball.</b> ({batter['name']}: {batter['runs']} off {batter['balls_faced']})"
            else: result_text += f"🏃‍♂️ <b>Great shot! {hit_val} runs!</b> 🔥 ({batter['name']}: {batter['runs']} off {batter['balls_faced']})"
            media_url = MEDIA.get(hit_val, MEDIA[0])
            await send_media_safely(context, chat_id, media_url, result_text, reply_to_message_id=update.message.message_id)
            
            if old_runs < 100 and batter["runs"] >= 100:
                milestone_media = MEDIA["100"]
                milestone_text = f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥
<a href='tg://user?id={batter['id']}'>{batter['name']}</a> has smashed a glorious century! What an innings! 🏏🏟️"
            elif old_runs < 50 and batter["runs"] >= 50:
                milestone_media = MEDIA["50"]
                milestone_text = f"🏏 <b>HALF-CENTURY! BRILLIANT INNINGS!</b> 💥🙌
<a href='tg://user?id={batter['id']}'>{batter['name']}</a> reaches 50! Keep it going! 🔥"
            if milestone_media: await send_media_safely(context, chat_id, milestone_media, milestone_text)
                
            if game.get("mode") == "TEAM" and hit_val % 2 != 0:
                swap_strike(game)
                await context.bot.send_message(chat_id, f"🔄 Strike rotated! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!", parse_mode="HTML")
                
            if game.get("mode") == "TEAM" and game["innings"] == 2 and game["batting_team_ref"]["score"] >= game["target"]:
                await process_team_innings_end(context, chat_id, game)
                return
            if game["state"] == "PLAYING": game["waiting_for"] = "BOWLER"
                
        elif bowl_val == "YORKER":
            batter["balls_faced"] += 1; bowler["balls_bowled"] += 1
            if game.get("mode") == "SOLO": game["balls_bowled"] += 1
            if game.get("mode") == "TEAM": game["bowling_team_ref"]["balls_bowled"] += 1
            
            survives = hit_val in ([0, 1, 2, 3] if game.get("mode") == "TEAM" else [1, 2, 3])
                
            if not survives:
                if is_free_hit:
                    game["is_free_hit"] = False
                    bowler["consecutive_wickets"] = 0
                    result_text = f"🥎 Bowler delivery: <b>YORKER</b>
🏏 Batter hit: <b>{hit_val}</b>

💥 <b>BOWLED! BUT IT'S A FREE HIT!</b> 😅
<a href='tg://user?id={batter['id']}'>{batter['name']}</a> survives and scores 0 runs!"
                    await send_media_safely(context, chat_id, MEDIA["batter_turn"], result_text, reply_to_message_id=update.message.message_id)
                else:
                    bowler["wickets"] += 1
                    result_text = f"🥎 Bowler delivery: <b>YORKER</b>
🏏 Batter hit: <b>{hit_val}</b>

💥 <b>HOWZAT! OUT!</b> ☝️ {batter['name']} is bowled by a lethal yorker for {batter['runs']}! 😔🚶‍♂️"
                    await send_media_safely(context, chat_id, MEDIA["yorker"], result_text, reply_to_message_id=update.message.message_id)
                    if batter["runs"] == 0: await send_media_safely(context, chat_id, MEDIA["duck"], f"🦆 <a href='tg://user?id={batter['id']}'>{batter['name']}</a> got a duck 🦆")
                             
                    bowler["consecutive_wickets"] = bowler.get("consecutive_wickets", 0) + 1
                    if bowler["consecutive_wickets"] == 3:
                        bowler["consecutive_wickets"] = 0
                        if users_col is not None: await users_col.update_one({"user_id": bowler["id"]}, {"$inc": {"hat_tricks": 1}}, upsert=True)
                        ht_vid = "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777819065/VID_20260503200210_rabpvn.mp4"
                        await send_media_safely(context, chat_id, ht_vid, f"🎩 <b>HAT-TRICK!</b> <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, you are a magician!! 🪄🔥")
                    
                    dismiss_batter(game, batter)
                    if game.get("mode") == "TEAM":
                        game["batting_team_ref"]["wickets"] += 1
                        if game["batting_team_ref"]["wickets"] >= len(game["batting_team_ref"]["players"]) - 1:
                            await process_team_innings_end(context, chat_id, game)
                            return
                        else:
                            game["waiting_for"] = "TEAM_BATTER_SELECT"
                            await context.bot.send_message(chat_id, f"🏏 Captain/Host, type <code>/batting</code> to see batters list or <code>/batting [number]</code> to select the next batter.", parse_mode="HTML")
                    else:
                        game["batter_idx"] += 1
                        if game["batter_idx"] >= len(game["players"]):
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
                if is_free_hit: game["is_free_hit"] = False
                old_runs = batter["runs"]; batter["runs"] += hit_val; bowler["conceded"] += hit_val
                if game.get("mode") == "TEAM": game["batting_team_ref"]["score"] += hit_val
                
                result_text = f"🥎 Bowler delivery: <b>YORKER</b>
🏏 Batter hit: <b>{hit_val}</b>

🏃‍♂️ <b>Great shot! Dug out the yorker for {hit_val} runs!</b> 🔥 ({batter['name']}: {batter['runs']} off {batter['balls_faced']})"
                await send_media_safely(context, chat_id, MEDIA.get(hit_val, MEDIA[0]), result_text, reply_to_message_id=update.message.message_id)
                
                if old_runs < 100 and batter["runs"] >= 100: await send_media_safely(context, chat_id, MEDIA["100"], f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥
<a href='tg://user?id={batter['id']}'>{batter['name']}</a> has smashed a glorious century! What an innings! 🏏🏟️")
                elif old_runs < 50 and batter["runs"] >= 50: await send_media_safely(context, chat_id, MEDIA["50"], f"🏏 <b>HALF-CENTURY! BRILLIANT INNINGS!</b> 💥🙌
<a href='tg://user?id={batter['id']}'>{batter['name']}</a> reaches 50! Keep it going! 🔥")

                if game.get("mode") == "TEAM":
                    if game["innings"] == 2 and game["batting_team_ref"]["score"] >= game["target"]:
                        await process_team_innings_end(context, chat_id, game)
                        return
                    if hit_val % 2 != 0:
                        swap_strike(game)
                        await context.bot.send_message(chat_id, f"🔄 Strike rotated! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!", parse_mode="HTML")
                        
        elif str(hit_val) == str(bowl_val):
            batter["balls_faced"] += 1; bowler["balls_bowled"] += 1
            if game.get("mode") == "SOLO": game["balls_bowled"] += 1
            if game.get("mode") == "TEAM": game["bowling_team_ref"]["balls_bowled"] += 1
            
            if is_free_hit:
                game["is_free_hit"] = False
                bowler["consecutive_wickets"] = 0
                result_text = f"🥎 Bowler delivery: <b>{bowl_val}</b>
🏏 Batter hit: <b>{hit_val}</b>

💥 <b>BOWLED! BUT IT'S A FREE HIT!</b> 😅
<a href='tg://user?id={batter['id']}'>{batter['name']}</a> survives and scores 0 runs!"
                await send_media_safely(context, chat_id, MEDIA["batter_turn"], result_text, reply_to_message_id=update.message.message_id)
            else:
                bowler["wickets"] += 1 
                result_text = f"🥎 Bowler delivery: <b>{bowl_val}</b>
🏏 Batter hit: <b>{hit_val}</b>

💥 <b>HOWZAT! OUT!</b> ☝️ {batter['name']} is dismissed for {batter['runs']}! 😔🤸🏻
{batter['name']} KOI NA HOTA HAI !! "
                await send_media_safely(context, chat_id, MEDIA["out"], result_text, reply_to_message_id=update.message.message_id)
                if batter["runs"] == 0: await send_media_safely(context, chat_id, MEDIA["duck"], f"🦆 <a href='tg://user?id={batter['id']}'>{batter['name']}</a> got a duck 🦆")
                
                bowler["consecutive_wickets"] = bowler.get("consecutive_wickets", 0) + 1
                if bowler["consecutive_wickets"] == 3:
                    bowler["consecutive_wickets"] = 0
                    if users_col is not None: await users_col.update_one({"user_id": bowler["id"]}, {"$inc": {"hat_tricks": 1}}, upsert=True)
                    ht_vid = "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777819065/VID_20260503200210_rabpvn.mp4"
                    await send_media_safely(context, chat_id, ht_vid, f"🎩 <b>HAT-TRICK!</b> <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, you are a magician!! 🪄🔥")
                        
                dismiss_batter(game, batter)
                if game.get("mode") == "TEAM":
                    game["batting_team_ref"]["wickets"] += 1
                    if game["batting_team_ref"]["wickets"] >= len(game["batting_team_ref"]["players"]) - 1:
                        await process_team_innings_end(context, chat_id, game)
                        return
                    else:
                        game["waiting_for"] = "TEAM_BATTER_SELECT"
                        await context.bot.send_message(chat_id, f"🏏 Captain/Host, type <code>/batting</code> to see batters list or <code>/batting [number]</code> to select the next batter.", parse_mode="HTML")
                else:
                    game["batter_idx"] += 1
                    if game["batter_idx"] >= len(game["players"]):
                        await commit_player_stats(game)
                        game["state"] = "NOT_PLAYING"
                        await trigger_full_scorecard_message(context, chat_id, game)
                        return
                    if game["batter_idx"] == game["bowler_idx"]:
                        game["bowler_idx"] = (game["bowler_idx"] + 1) % len(game["players"])
                        game["balls_bowled"] = 0 
                        game["special_used_this_over"] = False
        else:
            bowler["consecutive_wickets"] = 0; batter["balls_faced"] += 1; bowler["balls_bowled"] += 1
            if game.get("mode") == "SOLO": game["balls_bowled"] += 1
            if game.get("mode") == "TEAM": game["bowling_team_ref"]["balls_bowled"] += 1
            if is_free_hit: game["is_free_hit"] = False
                
            old_runs = batter["runs"]; batter["runs"] += hit_val; bowler["conceded"] += hit_val
            if game.get("mode") == "TEAM": game["batting_team_ref"]["score"] += hit_val
            
            result_text = f"🏏 Batter hit: <b>{hit_val}</b>

"
            if hit_val == 0: result_text += f"🛡️ <b>Solid defense! Dot ball.</b> ({batter['name']}: {batter['runs']} off {batter['balls_faced']})"
            else: result_text += f"🏃‍♂️ <b>Great shot! {hit_val} runs!</b> 🔥 ({batter['name']}: {batter['runs']} off {batter['balls_faced']})"
            
            await send_media_safely(context, chat_id, MEDIA.get(hit_val, MEDIA[0]), result_text, reply_to_message_id=update.message.message_id)
            
            if old_runs < 100 and batter["runs"] >= 100: await send_media_safely(context, chat_id, MEDIA["100"], f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥
<a href='tg://user?id={batter['id']}'>{batter['name']}</a> has smashed a glorious century! What an innings! 🏏🏟️")
            elif old_runs < 50 and batter["runs"] >= 50: await send_media_safely(context, chat_id, MEDIA["50"], f"🏏 <b>HALF-CENTURY! BRILLIANT INNINGS!</b> 💥🙌
<a href='tg://user?id={batter['id']}'>{batter['name']}</a> reaches 50! Keep it going! 🔥")

            if game.get("mode") == "TEAM":
                if game["innings"] == 2 and game["batting_team_ref"]["score"] >= game["target"]:
                    await process_team_innings_end(context, chat_id, game)
                    return
                if hit_val % 2 != 0:
                    swap_strike(game)
                    await context.bot.send_message(chat_id, f"🔄 Strike rotated! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!", parse_mode="HTML")

        is_over_complete = False
        if is_legal_delivery:
            if game.get("mode") == "SOLO" and game["balls_bowled"] >= game["spell"]: is_over_complete = True
            elif game.get("mode") == "TEAM" and game["bowling_team_ref"]["balls_bowled"] % 6 == 0 and game["bowling_team_ref"]["balls_bowled"] > 0: is_over_complete = True

        if is_over_complete:
            spell_text = f"🔁 <b>Over Completed!</b> 🛑 {bowler['name']} finished.
"
            if game.get("mode") == "TEAM":
                swap_strike(game)
                game["last_bowler_id"] = bowler["id"]; game["special_used_this_over"] = False
                if game["bowling_team_ref"]["balls_bowled"] >= game["target_overs"] * 6:
                    await process_team_innings_end(context, chat_id, game)
                    return
                await trigger_full_scorecard_message(context, chat_id, game)
                team = game["batting_team_ref"]
                spell_text += f"
📊 Score: {team['score']}/{team['wickets']}
"
                
                if game.get("striker"):
                    spell_text += f"🔄 Strike rotated for new over! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!
"
                    
                spell_text += f"Bowling Captain/Host, select next bowler using <code>/bowling</code> to see list or <code>/bowling [num]</code>."
                await context.bot.send_message(chat_id, spell_text, parse_mode="HTML")
                if game.get("waiting_for") == "TEAM_BATTER_SELECT": game["need_new_bowler"] = True
                else: game["waiting_for"] = "TEAM_BOWLER_SELECT"
            else:
                await trigger_full_scorecard_message(context, chat_id, game)
                await context.bot.send_message(chat_id, spell_text, parse_mode="HTML")
                game["balls_bowled"] = 0; game["special_used_this_over"] = False
                game["bowler_idx"] = (game["bowler_idx"] + 1) % len(game["players"])
                if game["bowler_idx"] == game["batter_idx"]: game["bowler_idx"] = (game["bowler_idx"] + 1) % len(game["players"])
                if game["state"] == "PLAYING": game["waiting_for"] = "BOWLER"
        else:
            if game["state"] == "PLAYING" and game.get("waiting_for") == "PROCESSING_BATTER": game["waiting_for"] = "BOWLER"
                
        if game["state"] == "PLAYING" and game.get("waiting_for") == "BOWLER":
            await asyncio.sleep(0.3) 
            await trigger_bowl(context, chat_id)

if __name__ == '__main__':
    print("Starting ELITE CRICKET BOT Server...")
    app = Application.builder().token(TOKEN).concurrent_updates(True).build()
    app.add_handler(TypeHandler(Update, global_tracker), group=-1)
    app.add_handler(ChatMemberHandler(track_bot_kicks, ChatMemberHandler.MY_CHAT_MEMBER))
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("join", join_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("remove", remove_command))
    app.add_handler(CommandHandler("changehost", changehost_command))
    app.add_handler(CommandHandler("changecap", changecap_command))
    app.add_handler(CommandHandler("changeover", changeover_command))
    app.add_handler(CommandHandler("create_team", create_team_command))
    app.add_handler(CommandHandler("rejoin", rejoin_command))
    app.add_handler(CommandHandler("leavesolo", leavesolo_command))
    app.add_handler(CommandHandler("startsolo", startsolo_command))
    app.add_handler(CommandHandler("endmatch", endmatch_command))
    app.add_handler(CommandHandler("soloscore", soloscore_command))
    app.add_handler(CommandHandler("score", teamscore_command))
    app.add_handler(CommandHandler("teams", teams_command))
    app.add_handler(CommandHandler("batting", batting_command))
    app.add_handler(CommandHandler("bowling", bowling_command))
    app.add_handler(CommandHandler("userstats", userstats_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("botstats", botstats_command))
    app.add_handler(CommandHandler("botgroups", botgroups_command))
    
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    
    if WEBHOOK_URL:
        clean_url = WEBHOOK_URL.rstrip('/')
        print(f"Starting Webhook on Port {PORT}...")
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=f"{clean_url}/{TOKEN}")
    else:
        print("WEBHOOK_URL not found. Falling back to Polling...")
        app.run_polling(poll_interval=0.1, timeout=10, drop_pending_updates=True)
