
import os
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient

# Replace with your actual bot token
TOKEN = os.getenv("BOT_TOKEN")
# Replace with your MongoDB URI
MONGO_URI = os.getenv("MONGO_URI")

# MongoDB Setup
try:
    client = MongoClient(MONGO_URI)
    db = client['cricket_bot_db']
    users_col = db['users']
except Exception as e:
    print(f"MongoDB Connection Error: {e}")
    users_col = None

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

SCOREBOARD_IMG = 'https://res.cloudinary.com/dxgfxfoog/image/upload/v1777784494/1777783840734-01_buclxw.jpg'
TEAMS_ROSTER_IMG = 'https://res.cloudinary.com/dxgfxfoog/image/upload/v1777706897/file_00000000c1947207ae83551202e6e003_f4o3y9.png'

# --- HELPER FUNCTIONS ---
async def send_media_safely(context, chat_id, media_url, caption, reply_markup=None, reply_to_message_id=None):
    """Helper to send media reliably, falling back to an embedded link if the direct upload fails."""
    try:
        # FIX: Rely strictly on file extensions or definitive GIF host to avoid Telegram API crashes with mixed-format MP4s
        if media_url.endswith('.gif') or "giphy.com" in media_url:
            await context.bot.send_animation(chat_id=chat_id, animation=media_url, caption=caption, parse_mode='HTML', reply_markup=reply_markup, reply_to_message_id=reply_to_message_id)
        else:
            await context.bot.send_video(chat_id=chat_id, video=media_url, caption=caption, parse_mode='HTML', reply_markup=reply_markup, reply_to_message_id=reply_to_message_id)
    except Exception as e:
        print(f"Failed to send media {media_url}: {e}. Using fallback.")
        fallback_caption = f"<a href='{media_url}'>&#8205;</a>{caption}"
        await context.bot.send_message(chat_id=chat_id, text=fallback_caption, parse_mode='HTML', reply_markup=reply_markup, reply_to_message_id=reply_to_message_id)

def init_user_db(user_id, first_name, username):
    if users_col is None: return
    user = users_col.find_one({"user_id": user_id})
    if not user:
        users_col.insert_one({
            "user_id": user_id,
            "first_name": first_name,
            "username": username,
            "highest_score": {"runs": 0, "balls": 0},
            "total_runs": 0,
            "balls_faced": 0,
            "solo_matches": 0,
            "team_matches": 0,
            "total_6s": 0,
            "total_4s": 0,
            "centuries": 0,
            "half_centuries": 0,
            "ducks": 0,
            "balls_bowled": 0,
            "runs_conceded": 0,
            "wickets": 0,
            "motm": 0,
            "hat_tricks": 0
        })

def update_user_db(user_id, updates):
    if users_col is None: return
    users_col.update_one({"user_id": user_id}, {"$inc": updates}, upsert=True)

def update_highest_score(user_id, runs, balls):
    if users_col is None: return
    user = users_col.find_one({"user_id": user_id})
    if user and runs > user.get('highest_score', {}).get('runs', 0):
        users_col.update_one({"user_id": user_id}, {"$set": {"highest_score": {"runs": runs, "balls": balls}}})

def update_match_played(players, mode):
    if users_col is None: return
    field = "solo_matches" if mode == "SOLO" else "team_matches"
    for p in players:
        update_user_db(p['id'], {field: 1})

def commit_player_stats(game):
    if users_col is None: return
    players = game['players'] if game.get('mode') != 'TEAM' else game['team_a']['players'] + game['team_b']['players']
    
    for p in players:
        update_highest_score(p['id'], p['runs'], p['balls_faced'])
        updates = {
            "total_runs": p['runs'],
            "balls_faced": p['balls_faced'],
            "balls_bowled": p['balls_bowled'],
            "runs_conceded": p['conceded'],
            "wickets": p['wickets'],
            "total_4s": p.get('match_4s', 0),
            "total_6s": p.get('match_6s', 0),
        }
        if p['runs'] == 0 and p.get('is_out', False):
            updates['ducks'] = 1
        if p['runs'] >= 100:
            updates['centuries'] = 1
        elif p['runs'] >= 50:
            updates['half_centuries'] = 1
            
        update_user_db(p['id'], updates)
        
    update_match_played(players, game.get('mode', 'SOLO'))
    potm = get_potm_data(game)
    if potm:
         update_user_db(potm['id'], {"motm": 1})

def get_potm_data(game):
    best_player = None
    best_score = -999
    players = game['players'] if game.get('mode') != 'TEAM' else game['team_a']['players'] + game['team_b']['players']
    
    for p in players:
        score = p['runs'] + (p['wickets'] * 15) - (p['conceded'] * 0.5)
        if score > best_score:
            best_score = score
            best_player = p
    return best_player

async def is_admin(chat, user_id):
    # FIX: Robust admin check that doesn't fail if the bot lacks broad admin retrieval privileges
    try:
        member = await chat.get_member(user_id)
        return member.status in ['administrator', 'creator']
    except Exception as e:
        print(f"Admin Check Error: {e}")
        return False

def get_next_num(players):
    nums = [p['num'] for p in players if 'num' in p]
    i = 1
    while i in nums:
        i += 1
    return i

def is_user_playing_anywhere(context, user_id):
    for cid, data in context.bot_data.items():
        if isinstance(data, dict) and data.get('state') not in ['NOT_PLAYING', None, 'TEAM_FINISHED']:
            if any(p.get('id') == user_id for p in data.get('players', [])): return True
            if 'team_a' in data and any(p.get('id') == user_id for p in data.get('team_a', {}).get('players', [])): return True
            if 'team_b' in data and any(p.get('id') == user_id for p in data.get('team_b', {}).get('players', [])): return True
    return False

def generate_scorecard(game):
    if game.get('mode') == 'TEAM':
        return generate_team_scorecard(game)
        
    text = "\n📊 <b>SOLO MATCH SCORECARD</b> 📊\n"
    text += "═══════════════════════════\n"
    for p in game['players']:
        overs = p['balls_bowled'] // 6
        balls = p['balls_bowled'] % 6
        overs_str = f"{overs}.{balls}"
        eco = (p['conceded'] / p['balls_bowled']) * 6 if p['balls_bowled'] > 0 else 0.00
        text += f"👤 <b>{p['name']}</b>\n"
        text += f"   🏏 Batting ➜ <b>{p['runs']}</b> Runs ({p['balls_faced']} Balls)\n"
        text += f"   🥎 Bowling ➜ <b>{p['wickets']}</b> W | {p['conceded']} R | {overs_str} Ov | Eco: {eco:.1f}\n"
        text += "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
    return text

def generate_team_scorecard(game):
    text = "\n🏆 <b>TEAM MATCH SCORECARD</b> 🏆\n"
    text += "═══════════════════════════\n"
    
    for team_key, team_name in [('team_a', 'Team A 🔴'), ('team_b', 'Team B 🔵')]:
        team = game.get(team_key)
        if not team: continue
        
        opp_team_key = 'team_b' if team_key == 'team_a' else 'team_a'
        opp_team = game.get(opp_team_key)
        
        if opp_team:
            played_overs = opp_team['balls_bowled'] // 6
            played_balls = opp_team['balls_bowled'] % 6
        else:
            played_overs, played_balls = 0, 0
            
        text += f"🎖️ <b>{team_name}</b> ➜ <b>{team['score']}/{team['wickets']}</b> ({played_overs}.{played_balls} Ov Played)\n"
        
        text += "<i>🏏 Batters:</i>\n"
        for p in team['players']:
            if p['balls_faced'] > 0 or p.get('is_striker') or p.get('is_non_striker'):
                status = "🏏" if not p['is_out'] else "❌"
                text += f"  {status} {p['name']} ➜ {p['runs']} ({p['balls_faced']})\n"
                
        text += "<i>🥎 Bowlers:</i>\n"
        for p in team['players']:
            if p['balls_bowled'] > 0:
                p_ov = p['balls_bowled'] // 6
                p_bl = p['balls_bowled'] % 6
                eco = (p['conceded'] / p['balls_bowled']) * 6
                text += f"  🥎 {p['name']} ➜ {p_ov}.{p_bl} Ov | {p['conceded']} R | {p['wickets']} W | Eco {eco:.1f}\n"
        text += "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        
    if game['state'] == 'TEAM_FINISHED':
        all_players = game['team_a']['players'] + game['team_b']['players']
        top_scorer = max(all_players, key=lambda x: x['runs'])
        top_wicket_taker = max(all_players, key=lambda x: x['wickets'])

        chasing_team = game['batting_team_ref']
        defending_team = game['bowling_team_ref']

        chasing_name = 'Team A 🔴' if chasing_team == game['team_a'] else 'Team B 🔵'
        defending_name = 'Team A 🔴' if defending_team == game['team_a'] else 'Team B 🔵'

        if chasing_team['score'] > defending_team['score']:
            wickets_left = (len(chasing_team['players']) - 1) - chasing_team['wickets']
            balls_left = (game['target_overs'] * 6) - defending_team['balls_bowled']
            overs_left = f"{balls_left // 6}.{balls_left % 6}"
            result_str = f"🎉 <b>{chasing_name} WINS by {wickets_left} wickets!</b> (with {overs_left} overs left)\n"
        elif defending_team['score'] > chasing_team['score']:
            run_diff = defending_team['score'] - chasing_team['score']
            result_str = f"🎉 <b>{defending_name} WINS by {run_diff} runs!</b>\n"
        else:
            result_str = "🤝 <b>IT\'S A TIE!</b> 🤝\n"

        text += result_str
        text += "═══════════════════════════\n"
        text += "📈 <b>MATCH HIGHLIGHTS:</b>\n"
        text += f"🏏 Most Runs: <b>{top_scorer['name']}</b> ({top_scorer['runs']})\n"
        text += f"🥎 Most Wickets: <b>{top_wicket_taker['name']}</b> ({top_wicket_taker['wickets']})\n"
        text += "═══════════════════════════\n"
            
    return text

def get_potm(game):
    best_player = get_potm_data(game)
    if best_player:
        return f"\n🏅 <b>PLAYER OF THE MATCH: <a href='tg://user?id={best_player['id']}'>{best_player['name']}</a></b> 🏅\nHere is your reward, take this 💋\n"
    return ""

def generate_teams_message(game):
    text = "🏟️ <b>TEAMS ROSTER</b> 🏟️\n\n"
    is_playing = game.get('state') == 'PLAYING'
    bat_team = game.get('batting_team_ref', {}) if is_playing else {}
    bowl_team = game.get('bowling_team_ref', {}) if is_playing else {}
    
    for team_key, team_dict in [('team_a', game.get('team_a', {})), ('team_b', game.get('team_b', {}))]:
        team_name = "🔴 <b>TEAM A</b>" if team_key == 'team_a' else "🔵 <b>TEAM B</b>"
        text += f"{team_name}\n"
        
        for i, p in enumerate(team_dict.get('players', []), 1):
            cap = " (C) 👑" if team_dict.get('captain') == p['id'] else ""
            status = ""
            if is_playing:
                if team_dict == bat_team:
                    if p.get('is_out'): status = " - (Out)"
                    elif p.get('is_striker'): status = " - (On Strike)"
                    elif p.get('is_non_striker'): status = " - (On Non Strike)"
                    else: status = " - (Available)"
                elif team_dict == bowl_team:
                    cb = game.get('current_bowler', {})
                    if cb and cb.get('id') == p['id']: status = " - (Bowling)"
            
            text += f" {p.get('num', i)}. <a href='tg://user?id={p['id']}'>{p['name']}</a>{cap}<i>{status}</i>\n"
        text += "\n"
    return text

# --- TIMERS ---
def set_afk_timer(context, chat_id, user_id, role):
    clear_afk_timer(context, chat_id)
    game = context.bot_data.get(chat_id)
    if not game: return
    
    if game.get('mode') == 'TEAM':
        context.job_queue.run_once(team_afk_warning_10, 10, data={'chat_id': chat_id, 'user_id': user_id, 'role': role}, name=f"afk10_{chat_id}")
        context.job_queue.run_once(team_afk_warning_30, 30, data={'chat_id': chat_id, 'user_id': user_id, 'role': role}, name=f"afk60_{chat_id}")
        context.job_queue.run_once(team_afk_timeout, 60, data={'chat_id': chat_id, 'user_id': user_id, 'role': role}, name=f"afk90_{chat_id}")
    else:
        context.job_queue.run_once(afk_warning_start, 10, data={'chat_id': chat_id, 'user_id': user_id, 'role': role}, name=f"afk10_{chat_id}")
        context.job_queue.run_once(afk_warning_30, 30, data={'chat_id': chat_id, 'user_id': user_id, 'role': role}, name=f"afk30_{chat_id}")
        context.job_queue.run_once(afk_timeout, 60, data={'chat_id': chat_id, 'user_id': user_id, 'role': role}, name=f"afk60_{chat_id}")

def clear_afk_timer(context, chat_id):
    for prefix in ['afk1_', 'afk10_', 'afk30_', 'afk60_', 'afk90_']:
        jobs = context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}")
        for job in jobs: job.schedule_removal()

async def afk_warning_start(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data['chat_id'], job.data['user_id'], job.data['role']
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'PLAYING' or game.get('waiting_for') != role: return
    player = next((p for p in game['players'] if p['id'] == user_id), None)
    if not player: return
    await context.bot.send_message(chat_id, f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, it is your turn! You have <b>50 seconds</b> to play. ⏳", parse_mode='HTML')

async def afk_warning_30(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data['chat_id'], job.data['user_id'], job.data['role']
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'PLAYING' or game.get('waiting_for') != role: return
    player = next((p for p in game['players'] if p['id'] == user_id), None)
    if not player: return
    await context.bot.send_message(chat_id, f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, HURRY UP! You only have <b>30 seconds</b> left to play! ⏰", parse_mode='HTML')

async def afk_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data['chat_id'], job.data['user_id'], job.data['role']
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'PLAYING' or game.get('waiting_for') != role: return
    
    player = next((p for p in game['players'] if p['id'] == user_id), None)
    if not player: return
        
    await context.bot.send_message(chat_id, f"⏳ <b>TIME'S UP!</b> {player['name']} was AFK for 60 seconds and has been ELIMINATED! ❌", parse_mode='HTML')
    
    elim_idx = next((i for i, p in enumerate(game['players']) if p['id'] == user_id), -1)
    if elim_idx == -1: return
    game['players'] = [p for p in game['players'] if p['id'] != user_id]
        
    if len(game['players']) < 2:
        commit_player_stats(game)
        game['state'] = 'NOT_PLAYING'
        await context.bot.send_message(chat_id, "Not enough players left! Match abandoned. 🛑", parse_mode='HTML')
        return
        
    if elim_idx < game['batter_idx']:
        game['batter_idx'] -= 1
    
    if game['batter_idx'] >= len(game['players']):
        commit_player_stats(game)
        game['state'] = 'NOT_PLAYING'
        await context.bot.send_message(chat_id, "🏁 <b>MATCH FINISHED!</b> 🏁", parse_mode='HTML')
        await trigger_full_scorecard_message(context, chat_id, game)
        return
        
    available_bowlers = [i for i in range(len(game['players'])) if i != game['batter_idx']]
    if available_bowlers:
         game['bowler_idx'] = random.choice(available_bowlers)
    else:
         commit_player_stats(game)
         game['state'] = 'NOT_PLAYING'
         await context.bot.send_message(chat_id, "Not enough players left! Match abandoned. 🛑", parse_mode='HTML')
         return
         
    game['waiting_for'] = 'BOWLER'
    game['balls_bowled'] = 0
    game['special_used_this_over'] = False
    await trigger_bowl(context, chat_id)

async def team_afk_warning_10(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data['chat_id'], job.data['user_id'], job.data['role']
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'PLAYING' or game.get('waiting_for') != role: return
    player = next((p for p in game['team_a']['players'] + game['team_b']['players'] if p['id'] == user_id), None)
    if not player: return
    await context.bot.send_message(chat_id, f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, you have been AFK! You have <b>50 more seconds</b> left to play. ⏳", parse_mode='HTML')

async def team_afk_warning_30(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data['chat_id'], job.data['user_id'], job.data['role']
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'PLAYING' or game.get('waiting_for') != role: return
    player = next((p for p in game['team_a']['players'] + game['team_b']['players'] if p['id'] == user_id), None)
    if not player: return
    await context.bot.send_message(chat_id, f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, HURRY UP! You only have <b>30 seconds</b> left to play! ⏰", parse_mode='HTML')

async def team_afk_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data['chat_id'], job.data['user_id'], job.data['role']
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'PLAYING' or game.get('waiting_for') != role: return
    
    player = next((p for p in game['team_a']['players'] + game['team_b']['players'] if p['id'] == user_id), None)
    if not player: return
    
    if role == 'BATTER':
        player['is_out'] = True
        game['batting_team_ref']['score'] -= 5
        player['runs'] -= 5
        game['batting_team_ref']['wickets'] += 1
        await context.bot.send_message(chat_id, f"⏳ <b>TIME'S UP!</b> {player['name']} was AFK for 60 seconds! ❌\n📉 <b>PENALTY:</b> -5 Runs to the team and batter! They are OUT!", parse_mode='HTML')
        if game['batting_team_ref']['wickets'] >= len(game['batting_team_ref']['players']) - 1:
            await process_team_innings_end(context, chat_id, game)
            return
        game['waiting_for'] = 'TEAM_BATTER_SELECT'
        await context.bot.send_message(chat_id, f"🏏 Captain/Host, please select the next batter using <code>/batting [number]</code>.", parse_mode='HTML')
    elif role == 'BOWLER':
        game['batting_team_ref']['score'] += 5
        player['conceded'] += 5
        game['waiting_for'] = 'TEAM_BOWLER_SELECT'
        game['last_bowler_id'] = player['id']
        await context.bot.send_message(chat_id, f"⏳ <b>TIME'S UP!</b> {player['name']} timed out! ❌\n📈 <b>PENALTY:</b> +5 Runs to Batting Team!\nCaptain/Host, please select a NEW bowler to continue the over using <code>/bowling [number]</code>.", parse_mode='HTML')

async def queue_reminder(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data['chat_id']
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'JOINING' or game.get('mode') != 'SOLO':
        context.job.schedule_removal()
        return
    await context.bot.send_message(chat_id, f"⏳ <b>Queue is open!</b> Type /join to enter the match! There are 35 seconds left to join. (Total: {len(game['players'])}) 🏏", parse_mode='HTML')

async def auto_start_match(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data['chat_id']
    
    jobs = context.job_queue.get_jobs_by_name(f"queueremind_{chat_id}")
    for j in jobs: j.schedule_removal()
    
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'JOINING': return
    
    if len(game['players']) >= 2:
        game.update({'state': 'PLAYING', 'waiting_for': 'BOWLER', 'batter_idx': 0, 'bowler_idx': 1, 'balls_bowled': 0, 'special_used_this_over': False, 'is_free_hit': False})
        await context.bot.send_message(chat_id, "⏳ <b>70 seconds are up! THE MATCH AUTO-STARTS NOW!</b> 🚨\nLet's head to the pitch! 🏟️", parse_mode='HTML')
        await trigger_bowl(context, chat_id)
    else:
        game['state'] = 'NOT_PLAYING'
        await context.bot.send_message(chat_id, "⏳ <b>70 seconds are up, but there are not enough players!</b> Match setup abandoned. 🛑", parse_mode='HTML')

async def trigger_team_captains(context, chat_id, game):
    game['state'] = 'TEAM_CAPTAINS'
    for team_key in ['team_a', 'team_b']:
        random.shuffle(game[team_key]['players'])
        for idx, p in enumerate(game[team_key]['players'], 1):
            p['num'] = idx
            
    roster = generate_teams_message(game)
    await context.bot.send_photo(chat_id, photo=TEAMS_ROSTER_IMG, caption=roster, parse_mode='HTML')
    
    kb = [
        [InlineKeyboardButton("Team A Captain 👑", callback_data="team_cap_a"), 
         InlineKeyboardButton("Team B Captain 👑", callback_data="team_cap_b")]
    ]
    await context.bot.send_message(chat_id, "Who will lead the teams? Members click your team's button to become the Captain! ⚡", reply_markup=InlineKeyboardMarkup(kb))

async def team_join_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data['chat_id']
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'TEAM_JOINING': return
    if len(game['team_a']['players']) < 2 or len(game['team_b']['players']) < 2:
        game['is_paused_waiting_players'] = True
        await context.bot.send_message(chat_id, "⏳ Time's up! But we need at least 2 players in each team! The queue is paused. ⏸️\nOnce both teams have 2 players, the setup will automatically proceed!", parse_mode='HTML')
        return
    await trigger_team_captains(context, chat_id, game)

# --- COMMAND LOGIC ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_type = update.message.chat.type
    chat_id = update.effective_chat.id
    
    if chat_type == 'private':
        if context.args:
            try:
                group_id = int(context.args[0])
                
                if 'active_bowlers' not in context.bot_data:
                    context.bot_data['active_bowlers'] = {}
                context.bot_data['active_bowlers'][update.effective_user.id] = group_id
                
                game = context.bot_data.get(group_id)
                if game and game['state'] == 'PLAYING' and game.get('waiting_for') == 'BOWLER':
                    if game.get('mode') == 'SOLO':
                        bowler = game['players'][game['bowler_idx']]
                        allowed_vals = "1-6"
                    else:
                        bowler = game['current_bowler']
                        allowed_vals = "1-6"
                        
                    if bowler and update.effective_user.id == bowler['id']:
                        keyboard = []
                        if not game.get('special_used_this_over'):
                            keyboard.append([InlineKeyboardButton("🎯 Try for yorker 🎯", callback_data=f"special_{group_id}")])
                            
                        await update.message.reply_text(
                            f"🥎 <b>Your Turn to Bowl!</b>\nType {allowed_vals} or Try for yorker! 🤔👇", 
                            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                            parse_mode='HTML'
                        )
                        return
                    else:
                        await update.message.reply_text("It is not your turn to bowl right now! 🚫🏏")
                        return
            except ValueError:
                pass
                
        welcome_private = (
            "<b>Welcome to ELITE CRICKET BOT! 🏏</b>\n\n"
            "Step into the ultimate Telegram Cricket experience! Whether you want to practice your skills in Solo Mode or clash with rivals in a full-fledged Team T20 match, this bot brings the stadium to your screen."
        )
        kb_private = [
            [InlineKeyboardButton("Contact Developer 👨‍💻", url="https://t.me/xrztz")],
            [InlineKeyboardButton("Support Group 💬", url="https://t.me/eclplays")],
            [InlineKeyboardButton("Play Cricket 🏏", url="https://t.me/eclplays")]
        ]
        await update.message.reply_photo(
            photo='https://res.cloudinary.com/dxgfxfoog/image/upload/v1777818831/file_00000000677c71fa8d7d9caa8a1b3cc9_k7l0au.png',
            caption=welcome_private,
            reply_markup=InlineKeyboardMarkup(kb_private),
            parse_mode='HTML'
        )
        return

    game = context.bot_data.get(chat_id)
    if game is None:
        game = {'state': 'NOT_PLAYING'}
        context.bot_data[chat_id] = game

    if game.get('state') not in ['NOT_PLAYING', None, 'TEAM_FINISHED']:
        await update.message.reply_text("❌ A match is already active in this group! Finish it or ask an admin to /endmatch first.")
        return
        
    welcome_text = (
        "Welcome to the <b>ELITE CRICKET BOT</b> Arena! 🏆\n"
        "Join our official community at @eclplays. 🏏\n\n"
        "🔥 <b>A tournament is currently going on! Register via @eclregisbot</b> 🔥\n\n"
        "Choose your mode: 👇"
    )
    
    keyboard = [
        [InlineKeyboardButton("Solo Game 🏏", callback_data='solo_game')],
        [InlineKeyboardButton("Team Game 👥", callback_data='team_game')],
        [InlineKeyboardButton("Cancel ❌", callback_data='cancel')]
    ]
    
    await update.message.reply_photo(
        photo='https://res.cloudinary.com/dxgfxfoog/image/upload/v1777690770/IMG_20260502_082816_001_t0wejv.jpg',
        caption=welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def create_team_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'TEAM_SETUP_HOST': return
    
    if update.effective_user.id != game.get('host_id'):
        await update.message.reply_text("❌ Only the Game Host can create the teams!")
        return
        
    game['state'] = 'TEAM_JOINING'
    game['is_paused_waiting_players'] = False
    game['team_a'] = {'players': [], 'captain': None, 'score': 0, 'wickets': 0, 'balls_bowled': 0}
    game['team_b'] = {'players': [], 'captain': None, 'score': 0, 'wickets': 0, 'balls_bowled': 0}
    
    kb = [
        [InlineKeyboardButton("Join Team A 🔴", callback_data='join_team_a'),
         InlineKeyboardButton("Join Team B 🔵", callback_data='join_team_b')]
    ]
    
    context.job_queue.run_once(team_join_timeout, 10, data={'chat_id': chat_id}, name=f"team_join_{chat_id}")
    await update.message.reply_text("⚔️ <b>TEAM REGISTRATION OPEN!</b> ⚔️\n\nPlayers, choose your sides! You have 10 seconds to join. ⏳\n<b>(Host can type /rejoin to extend 30s or use /add or /remove)</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def rejoin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'TEAM_JOINING': return
    if update.effective_user.id != game.get('host_id'): return
    
    jobs = context.job_queue.get_jobs_by_name(f"team_join_{chat_id}")
    for job in jobs: job.schedule_removal()
    
    context.job_queue.run_once(team_join_timeout, 30, data={'chat_id': chat_id}, name=f"team_join_{chat_id}")
    await update.message.reply_text("⏳ <b>Registration Extended!</b> 30 more seconds to join the teams! 👥", parse_mode='HTML')

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    
    game = context.bot_data.get(chat_id)
    if not game or game.get('mode') != 'TEAM': 
        await update.message.reply_text("❌ No active team match setup found!")
        return
        
    if update.effective_user.id != game.get('host_id'):
        await update.message.reply_text("❌ Only the Game Host can add players manually!")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: /add a OR /add b (while replying to a user's message or tagging @username)")
        return
        
    team_choice = context.args[0].lower()
    if team_choice not in ['a', 'b']:
        await update.message.reply_text("❌ Please specify team 'a' or 'b'. Example: /add a")
        return
        
    team_key = f"team_{team_choice}"
    target_user = None
    
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    elif len(context.args) > 1:
        for entity in update.message.entities:
            if entity.type == 'text_mention':
                target_user = entity.user
                break
                
    if not target_user:
        await update.message.reply_text("❌ Please reply to a user's message or tag their @username properly!")
        return
        
    if target_user.is_bot:
        await update.message.reply_text("❌ You cannot add a bot to the team!")
        return
        
    if is_user_playing_anywhere(context, target_user.id):
        await update.message.reply_text("❌ you are already in a game or in a queue in either this or other group")
        return
        
    in_a = any(p['id'] == target_user.id for p in game['team_a']['players'])
    in_b = any(p['id'] == target_user.id for p in game['team_b']['players'])
    if in_a:
        await update.message.reply_text(f"❌ {target_user.first_name} is already in Team A 🔴!")
        return
    if in_b:
        await update.message.reply_text(f"❌ {target_user.first_name} is already in Team B 🔵!")
        return
        
    username = target_user.username.lower() if target_user.username else None
    
    init_user_db(target_user.id, target_user.first_name, username)
    new_player = {'id': target_user.id, 'name': target_user.first_name, 'username': username, 'runs': 0, 'balls_faced': 0, 'wickets': 0, 'conceded': 0, 'balls_bowled': 0, 'is_out': False, 'match_4s': 0, 'match_6s': 0}
    
    if game.get('state') != 'TEAM_JOINING':
        new_player['num'] = get_next_num(game[team_key]['players'])
        
    game[team_key]['players'].append(new_player)
    team_name = 'TEAM A 🔴' if team_choice == 'a' else 'TEAM B 🔵'
    await update.message.reply_text(f"✅ <b>{target_user.first_name}</b> has been manually added to {team_name} by the Host! 👥", parse_mode='HTML')
    
    if game.get('is_paused_waiting_players'):
        if len(game['team_a']['players']) >= 2 and len(game['team_b']['players']) >= 2:
            game['is_paused_waiting_players'] = False
            await context.bot.send_message(chat_id, "✅ Minimum player requirement met! Resuming setup... ▶️")
            await trigger_team_captains(context, chat_id, game)

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    
    game = context.bot_data.get(chat_id)
    if not game or game.get('mode') != 'TEAM': 
        await update.message.reply_text("❌ No active team match setup found!")
        return
        
    if update.effective_user.id != game.get('host_id'):
        await update.message.reply_text("❌ Only the Game Host can remove players manually!")
        return
        
    target_user = None
    target_username = None
    
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    elif len(context.args) > 0:
        for entity in update.message.entities:
            if entity.type == 'text_mention':
                target_user = entity.user
                break
            elif entity.type == 'mention':
                target_username = update.message.text[entity.offset:entity.offset+entity.length].lstrip('@').lower()
                break
                
    if not target_user and not target_username:
        await update.message.reply_text("❌ Please reply to a user's message or tag their @username properly!")
        return
        
    removed = False
    target_name = ""
    for team_key in ['team_a', 'team_b']:
        for p in list(game[team_key]['players']):
            if (target_user and p['id'] == target_user.id) or (target_username and p.get('username') == target_username):
                target_name = p['name']
                game[team_key]['players'].remove(p)
                removed = True
                for i, p_rem in enumerate(game[team_key]['players'], 1):
                    p_rem['num'] = i
                break
                
    if removed:
        await update.message.reply_text(f"✅ <b>{target_name}</b> has been successfully removed from their team! Numbers updated. 🚪", parse_mode='HTML')
    else:
        name = target_user.first_name if target_user else target_username
        await update.message.reply_text(f"❌ {name} is not in any team!")

async def changehost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    
    game = context.bot_data.get(chat_id)
    if not game or game.get('mode') != 'TEAM' or game.get('state') in ['NOT_PLAYING', None, 'TEAM_FINISHED']: 
        await update.message.reply_text("❌ No active team match to change host!")
        return
        
    target_user = None
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    elif len(context.args) > 0:
        for entity in update.message.entities:
            if entity.type == 'text_mention':
                target_user = entity.user
                break
                
    if not target_user:
        await update.message.reply_text("❌ Please reply to a user's message or tag their @username!")
        return
        
    if target_user.is_bot:
        await update.message.reply_text("❌ A bot cannot be the Game Host!")
        return
        
    if update.effective_user.id == game.get('host_id'):
        game['host_id'] = target_user.id
        await update.message.reply_text(f"✅ Host privileges successfully transferred to <b>{target_user.first_name}</b>! 👑", parse_mode='HTML')
    else:
        game['host_vote_target'] = target_user.id
        game['host_vote_name'] = target_user.first_name
        game['host_votes'] = set()
        
        kb = [[InlineKeyboardButton("Vote ✅ (0/4)", callback_data="vote_host")]]
        await update.message.reply_text(f"🗳️ Vote initiated to change host to <b>{target_user.first_name}</b>!\n4 votes required.", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == 'private': return
    chat_id = update.effective_chat.id
    game = context.bot_data.get(chat_id)

    if not game or game.get('state') != 'JOINING':
        await update.message.reply_text("No match is open for joining! Type /start ❌🏏")
        return

    user = update.effective_user

    if is_user_playing_anywhere(context, user.id):
        await update.message.reply_text("❌ you are already in a game or in a queue in either this or other group")
        return

    if any(p['id'] == user.id for p in game['players']):
        await update.message.reply_text(f"⚠️ <b>{user.first_name}</b>, you are ALREADY in the queue! Please wait for the match to start. ⏳🧍‍♂️", parse_mode='HTML')
        return

    username = user.username.lower() if user.username else None
    
    init_user_db(user.id, user.first_name, username)
    game['players'].append({'id': user.id, 'name': user.first_name, 'username': username, 'runs': 0, 'conceded': 0, 'wickets': 0, 'balls_bowled': 0, 'balls_faced': 0, 'match_4s': 0, 'match_6s': 0})
    
    timer_msg = ""
    if len(game['players']) == 1:
        context.job_queue.run_once(auto_start_match, 70, data={'chat_id': chat_id}, name=f"autostart_{chat_id}")
        context.job_queue.run_repeating(queue_reminder, interval=35, first=35, data={'chat_id': chat_id}, name=f"queueremind_{chat_id}")
        timer_msg = "\n⏳ <i>Auto-start timer initiated: Match begins in 70 seconds!</i>"
        
    await update.message.reply_text(f"✅ <b>{user.first_name}</b> joined! (Total: {len(game['players'])}) 👥{timer_msg}", parse_mode='HTML')

async def leavesolo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    
    game = context.bot_data.get(chat_id)
    if not game: return
        
    if game.get('state') == 'PLAYING':
        await update.message.reply_text("❌ The match has already started! You can't leave now.")
        return
        
    if game.get('state') == 'JOINING':
        user_id = update.effective_user.id
        player = next((p for p in game['players'] if p['id'] == user_id), None)
        if player:
            game['players'] = [p for p in game['players'] if p['id'] != user_id]
            await update.message.reply_text(f"👋 <b>{update.effective_user.first_name}</b> has left the queue. (Total: {len(game['players'])}) 👥", parse_mode='HTML')
            
            if len(game['players']) == 0:
                for prefix in ['autostart_', 'queueremind_']:
                    jobs = context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}")
                    for job in jobs: job.schedule_removal()
                await update.message.reply_text("Queue is empty! 🏏 Timer stopped.")
        else:
            await update.message.reply_text("You are not in the queue! ❌")

async def startsolo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.message.chat.type == 'private': return
    
    if not await is_admin(update.effective_chat, update.effective_user.id):
        await update.message.reply_text("❌ Only group admins can start the match manually!")
        return

    game = context.bot_data.get(chat_id)
    if not game or game['state'] != 'JOINING': return
    if len(game['players']) < 2:
        await update.message.reply_text("We need at least 2 players! 👥🏏")
        return
        
    for prefix in ['autostart_', 'queueremind_']:
        jobs = context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}")
        for job in jobs: job.schedule_removal()
        
    game.update({'state': 'PLAYING', 'waiting_for': 'BOWLER', 'batter_idx': 0, 'bowler_idx': 1, 'balls_bowled': 0, 'special_used_this_over': False, 'is_free_hit': False})
    
    await update.message.reply_text("🚨 <b>THE MATCH HAS BEGUN!</b> 🚨", parse_mode='HTML')
    await trigger_bowl(context, chat_id)

async def endmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    
    if not await is_admin(update.effective_chat, update.effective_user.id):
        await update.message.reply_text("❌ Only group admins can end the match!")
        return
        
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') in ['NOT_PLAYING', None, 'TEAM_FINISHED']:
        await update.message.reply_text("❌ There is no active match to end!")
        return
        
    keyboard = [
        [InlineKeyboardButton("Yes, End Match ✅", callback_data=f"endmatch_yes_{chat_id}")],
        [InlineKeyboardButton("Cancel ❌", callback_data=f"endmatch_no_{chat_id}")]
    ]
    await update.message.reply_text("⚠️ <b>Admin Action:</b> Are you sure you want to force-end the current match?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def soloscore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    game = context.bot_data.get(chat_id)
    if not game or game.get('mode') != 'SOLO' or game.get('state') in ['NOT_PLAYING', None]:
        await update.message.reply_text("❌ No active solo match is currently being played!")
        return
    await trigger_full_scorecard_message(context, chat_id, game)

async def teamscore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    game = context.bot_data.get(chat_id)
    if not game or game.get('mode') != 'TEAM' or game.get('state') in ['NOT_PLAYING', None]:
        await update.message.reply_text("❌ No active team match is currently being played!")
        return
    await trigger_full_scorecard_message(context, chat_id, game)

async def teams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    game = context.bot_data.get(chat_id)
    if not game or game.get('mode') != 'TEAM' or game.get('state') in ['NOT_PLAYING', 'TEAM_SETUP_HOST', 'TEAM_JOINING']:
        await update.message.reply_text("❌ No active team match right now!")
        return
    roster = generate_teams_message(game)
    await update.message.reply_photo(photo=TEAMS_ROSTER_IMG, caption=roster, parse_mode='HTML')

async def batting_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    game = context.bot_data.get(chat_id)
    if not game or game.get('mode') != 'TEAM': 
        await update.message.reply_text("❌ There is no active team match currently! This command is only for team matches.")
        return
    if game.get('state') != 'PLAYING': 
        await update.message.reply_text("❌ The match hasn't started yet!")
        return
    batting_team = game['batting_team_ref']
    if not context.args or not context.args[0].isdigit():
        text = "🏏 <b>AVAILABLE BATTERS:</b>\n"
        for p in batting_team['players']:
            status = "❌ (Out)" if p.get('is_out') else ("🏏 (On Pitch)" if p.get('is_striker') or p.get('is_non_striker') else "✅ (Available)")
            text += f"[{p.get('num', '?')}] {p['name']} - {status}\n"
        text += "\n👉 <i>Usage: /batting [number] to select.</i>"
        await update.message.reply_text(text, parse_mode='HTML')
        return

    if update.effective_user.id not in [batting_team['captain'], game['host_id']]: 
        await update.message.reply_text("❌ Only the Host or Batting Team Captain can select the batter!")
        return
        
    if game.get('waiting_for') not in ['TEAM_OPENERS_BAT', 'TEAM_BATTER_SELECT']: return
        
    p_num = int(context.args[0])
    selected = next((p for p in batting_team['players'] if p.get('num') == p_num), None)
    
    if not selected:
        await update.message.reply_text(f"❌ Player {p_num} not found in your team!")
        return
    if selected.get('is_out'):
        await update.message.reply_text(f"❌ {selected['name']} is already out!")
        return
    
    st = game.get('striker') or {}
    ns = game.get('non_striker') or {}
    if st.get('id') == selected['id'] or ns.get('id') == selected['id']:
        await update.message.reply_text(f"❌ {selected['name']} is already on the pitch!")
        return
        
    if game['waiting_for'] == 'TEAM_OPENERS_BAT':
        if not game.get('striker'):
            game['striker'] = selected
            selected['is_striker'] = True
            await update.message.reply_text(f"🏏 <b>{selected['name']}</b> selected as Striker!", parse_mode='HTML')
        elif not game.get('non_striker'):
            game['non_striker'] = selected
            selected['is_non_striker'] = True
            openers_gif = "https://media.giphy.com/media/hGJTJqTNaj0XXkLXZr/giphy.gif"
            caption_txt = f"🏏 <b>{selected['name']}</b> selected as Non-Striker!\n\nBowling Team Captain/Host, type /bowling to see bowlers or /bowling [num] to select opening bowler."
            await send_media_safely(context, chat_id, openers_gif, caption_txt)
            game['waiting_for'] = 'TEAM_BOWLER_SELECT'
    else:
        game['striker'] = selected
        selected['is_striker'] = True
        await update.message.reply_text(f"🏏 <b>{selected['name']}</b> walks out to the pitch!", parse_mode='HTML')
        
        if game.get('need_new_bowler'):
            game['need_new_bowler'] = False
            game['waiting_for'] = 'TEAM_BOWLER_SELECT'
            await update.message.reply_text("Bowling Captain/Host, please select the next bowler using <code>/bowling [num]</code>.", parse_mode='HTML')
        else:
            game['waiting_for'] = 'BOWLER'
            await trigger_bowl(context, chat_id)

async def bowling_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    game = context.bot_data.get(chat_id)
    if not game or game.get('mode') != 'TEAM':
        await update.message.reply_text("❌ There is no active team match currently! This command is only for team matches.")
        return
    if game.get('state') != 'PLAYING': 
        await update.message.reply_text("❌ The match hasn't started yet!")
        return
    
    bowling_team = game['bowling_team_ref']
    if not context.args or not context.args[0].isdigit():
        text = "🥎 <b>AVAILABLE BOWLERS:</b>\n"
        for p in bowling_team['players']:
            status = "✅ (Available)"
            if game.get('last_bowler_id') == p['id']:
                status = "⏳ (Bowled Last Over)"
            cb = game.get('current_bowler') or {}
            if cb.get('id') == p['id']:
                status = "🥎 (Bowling Now)"
            text += f"[{p.get('num', '?')}] {p['name']} - {p['balls_bowled']//6}.{p['balls_bowled']%6} Ov - {status}\n"
        text += "\n👉 <i>Usage: /bowling [number] to select.</i>"
        await update.message.reply_text(text, parse_mode='HTML')
        return

    if update.effective_user.id not in [bowling_team['captain'], game['host_id']]: 
        await update.message.reply_text("❌ Only the Host or Bowling Team Captain can select the bowler!")
        return
        
    if game.get('waiting_for') != 'TEAM_BOWLER_SELECT': return
        
    p_num = int(context.args[0])
    selected = next((p for p in bowling_team['players'] if p.get('num') == p_num), None)
    
    if not selected:
        await update.message.reply_text(f"❌ Player {p_num} not found in your team!")
        return
    if game.get('last_bowler_id') == selected['id']:
        await update.message.reply_text("❌ A bowler cannot bowl two consecutive overs!")
        return
        
    game['current_bowler'] = selected
    game['waiting_for'] = 'BOWLER'
    
    await update.message.reply_text(f"🥎 <b>{selected['name']}</b> is handed the ball!", parse_mode='HTML')
    if game.get('innings_start_msg_pending'):
        game['innings_start_msg_pending'] = False
        await update.message.reply_text("🚨 <b>THE INNINGS HAS BEGUN!</b> 🚨", parse_mode='HTML')
    await trigger_bowl(context, chat_id)

async def trigger_full_scorecard_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, game_data):
    scorecard = generate_scorecard(game_data)
    potm = get_potm(game_data) if game_data.get('state') in ['NOT_PLAYING', 'TEAM_FINISHED'] else ""
    final_caption = f"{scorecard}{potm}"
    await context.bot.send_photo(
        chat_id=chat_id,
        photo=SCOREBOARD_IMG,
        caption=final_caption,
        parse_mode='HTML'
    )

async def trigger_bowl(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    game = context.bot_data[chat_id]
    if game.get('mode') == 'TEAM':
        bowler = game['current_bowler']
        batter = game['striker']
        over_info = f"{game['bowling_team_ref']['balls_bowled'] // 6}.{game['bowling_team_ref']['balls_bowled'] % 6} / {game['target_overs']}"
    else:
        bowler = game['players'][game['bowler_idx']]
        batter = game['players'][game['batter_idx']]
        over_info = f"{game['balls_bowled']}/{game['spell']} balls"
    
    if 'active_bowlers' not in context.bot_data:
        context.bot_data['active_bowlers'] = {}
    context.bot_data['active_bowlers'][bowler['id']] = chat_id
    
    bot_info = await context.bot.get_me()
    url = f"https://t.me/{bot_info.username}"
    
    free_hit_tag = "🚀 <b>FREE HIT ACTIVE!</b>\n" if game.get('is_free_hit') else ""
    
    dm_text = f"🏏 <b>Match in Progress!</b>\n\n"
    dm_text += f"🏏 Batter: <b>{batter['name']}</b> ({batter['runs']} runs)\n"
    dm_text += f"🥎 Over Status: {over_info}.\n\n"
    dm_text += "👉 <b>Your Turn to Bowl!</b> Type a number from 1 to 6."
    
    keyboard = []
    if not game.get('special_used_this_over'):
        keyboard.append([InlineKeyboardButton("🎯 Try for yorker 🎯", callback_data=f"special_{chat_id}")])
        
    dm_sent = False
    try:
        await context.bot.send_message(
            chat_id=bowler['id'],
            text=dm_text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            parse_mode='HTML'
        )
        dm_sent = True
    except Exception:
        pass
        
    if dm_sent:
        group_text = f"{free_hit_tag}📊 <b>Status:</b>\n🏏 <b>Batter:</b> {batter['name']} ({batter['runs']})\n🥎 <b>Bowler:</b> {bowler['name']} (Over: {over_info})\n\n👉 <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, check your DM to bowl! 🤫🥎"
        group_kb = [[InlineKeyboardButton("Bowl Delivery 🥎", url=url)]]
    else:
        fallback_url = f"https://t.me/{bot_info.username}?start={chat_id}"
        group_text = f"{free_hit_tag}📊 <b>Status:</b>\n🏏 <b>Batter:</b> {batter['name']} ({batter['runs']})\n🥎 <b>Bowler:</b> {bowler['name']} (Over: {over_info})\n\n⚠️ <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, I couldn't DM you! Click below to start me, then bowl! 🤫🥎"
        group_kb = [[InlineKeyboardButton("Start Bot & Bowl 🤖", url=fallback_url)]]
        
    await send_media_safely(context, chat_id, MEDIA['bowler_turn'], group_text, InlineKeyboardMarkup(group_kb))
    set_afk_timer(context, chat_id, bowler['id'], 'BOWLER')

def swap_strike(game):
    if game.get('striker') and game.get('non_striker'):
        temp = game['striker']
        game['striker'] = game['non_striker']
        game['non_striker'] = temp
        game['striker']['is_striker'] = True
        game['striker']['is_non_striker'] = False
        game['non_striker']['is_striker'] = False
        game['non_striker']['is_non_striker'] = True

async def process_team_innings_end(context, chat_id, game):
    if game['innings'] == 1:
        game['innings'] = 2
        game['target'] = game['batting_team_ref']['score'] + 1
        
        temp = game['batting_team_ref']
        game['batting_team_ref'] = game['bowling_team_ref']
        game['bowling_team_ref'] = temp
        
        game['striker'] = None
        game['non_striker'] = None
        game['current_bowler'] = None
        game['last_bowler_id'] = None
        game['is_free_hit'] = False
        game['special_used_this_over'] = False
        
        text = f"🛑 <b>INNINGS BREAK!</b> 🛑\n\n🎯 Target for the Bowling team: <b>{game['target']} runs</b> in {game['target_overs']} overs.\n\n"
        text += "Batting Captain/Host, please select your opening pair using:\n<code>/batting [number]</code> (do it twice)."
        game['waiting_for'] = 'TEAM_OPENERS_BAT'
        game['innings_start_msg_pending'] = True
        
        await context.bot.send_message(chat_id, text, parse_mode='HTML')
    else:
        commit_player_stats(game)
        game['state'] = 'TEAM_FINISHED'
        await context.bot.send_message(chat_id, "🏁 <b>MATCH FINISHED!</b> 🏁", parse_mode='HTML')
        await trigger_full_scorecard_message(context, chat_id, game)
        game['state'] = 'NOT_PLAYING'

# --- USER STATS COMMAND ---
async def userstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    target_user = None
    target_username = None

    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
    elif len(context.args) > 0:
        for entity in update.message.entities:
            if entity.type == 'text_mention':
                target_user = entity.user
                break
            elif entity.type == 'mention':
                target_username = update.message.text[entity.offset:entity.offset+entity.length].lstrip('@').lower()
                break
    
    if not target_user and not target_username:
        target_user = update.effective_user

    if users_col is None:
        await update.message.reply_text("❌ Database connection error.")
        return

    thunder_msg = await context.bot.send_message(chat_id, "⚡")
    await asyncio.sleep(2)
    try: await thunder_msg.delete()
    except Exception: pass

    try:
        user_data = None
        if target_user:
             user_data = users_col.find_one({"user_id": target_user.id})
        elif target_username:
             user_data = users_col.find_one({"username": target_username})

        if not user_data:
             name = target_user.first_name if target_user else target_username
             await update.message.reply_text(f"❌ No stats found for {name}.")
             return

        hs_runs = user_data.get('highest_score', {}).get('runs', 0)
        hs_balls = user_data.get('highest_score', {}).get('balls', 0)
        total_runs = user_data.get('total_runs', 0)
        balls_faced = user_data.get('balls_faced', 0)
        sr = (total_runs / balls_faced * 100) if balls_faced > 0 else 0

        balls_bowled = user_data.get('balls_bowled', 0)
        runs_conceded = user_data.get('runs_conceded', 0)
        overs = balls_bowled // 6
        rem_balls = balls_bowled % 6
        eco = (runs_conceded / balls_bowled * 6) if balls_bowled > 0 else 0

        stats_text = f"📊 <b>PLAYER STATISTICS</b> 📊\n"
        stats_text += f"═══════════════════════════\n"
        stats_text += f"👤 <b>Name:</b> {user_data.get('first_name', 'Unknown')}\n"
        stats_text += f"🆔 <b>ID:</b> <code>{user_data.get('user_id', 'Unknown')}</code>\n"
        stats_text += f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        stats_text += f"🏏 <b>BATTING STATS</b>\n"
        stats_text += f"🔸 <b>Highest Score:</b> {hs_runs} ({hs_balls})\n"
        stats_text += f"🔸 <b>Total Runs:</b> {total_runs}\n"
        stats_text += f"🔸 <b>Strike Rate:</b> {sr:.2f}\n"
        stats_text += f"🔸 <b>6s:</b> {user_data.get('total_6s', 0)} | <b>4s:</b> {user_data.get('total_4s', 0)}\n"
        stats_text += f"🔸 <b>100s:</b> {user_data.get('centuries', 0)} | <b>50s:</b> {user_data.get('half_centuries', 0)}\n"
        stats_text += f"🔸 <b>Ducks 🦆:</b> {user_data.get('ducks', 0)}\n"
        stats_text += f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        stats_text += f"🥎 <b>BOWLING STATS</b>\n"
        stats_text += f"🔹 <b>Wickets:</b> {user_data.get('wickets', 0)}\n"
        stats_text += f"🔹 <b>Hat-Tricks:</b> {user_data.get('hat_tricks', 0)}\n"
        stats_text += f"🔹 <b>Overs Bowled:</b> {overs}.{rem_balls}\n"
        stats_text += f"🔹 <b>Economy:</b> {eco:.2f}\n"
        stats_text += f"┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        stats_text += f"🏆 <b>MATCH & AWARDS</b>\n"
        stats_text += f"🔸 <b>Solo Matches:</b> {user_data.get('solo_matches', 0)}\n"
        stats_text += f"🔸 <b>Team Matches:</b> {user_data.get('team_matches', 0)}\n"
        stats_text += f"🔸 <b>MOTM Awards:</b> {user_data.get('motm', 0)}\n"
        stats_text += f"═══════════════════════════"

        stats_img = 'https://res.cloudinary.com/dxgfxfoog/image/upload/v1777818873/file_00000000fa6871fa8d9b30faff9899ae_hbyn9j.png'
        await update.message.reply_photo(photo=stats_img, caption=stats_text, parse_mode='HTML')

    except Exception as e:
         print(f"Error fetching stats: {e}")
         await update.message.reply_text("❌ An error occurred while fetching stats.")

# --- CALLBACKS & GAMEPLAY ---
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    game = context.bot_data.get(chat_id)
    if game is None:
        game = {'state': 'NOT_PLAYING'}
        context.bot_data[chat_id] = game

    if query.data == 'solo_game':
        if game.get('state') not in ['NOT_PLAYING', None, 'TEAM_FINISHED']:
            try: await query.edit_message_caption(caption="❌ A match is already active or setting up in this group!", reply_markup=None)
            except: pass
            return
            
        keyboard = [[InlineKeyboardButton("3 Balls 🥎", callback_data='spell_3')], [InlineKeyboardButton("6 Balls 🥎", callback_data='spell_6')]]
        try: await query.message.delete()
        except: pass
        await context.bot.send_photo(
            chat_id=chat_id,
            photo='https://res.cloudinary.com/dxgfxfoog/image/upload/v1777720022/file_00000000483072079f73014e1bba1fde_l4thrv.png',
            caption="Select Spell Limit: ⚖️🏏",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == 'team_game':
        if game.get('state') not in ['NOT_PLAYING', None, 'TEAM_FINISHED']:
            try: await query.edit_message_caption(caption="❌ A match is already active or setting up in this group!", reply_markup=None)
            except: pass
            return
            
        text = "👥 <b>TEAM GAME MODE</b> 👥\n\nForm two teams, appoint captains, toss the coin, and clash in an epic T20-style showdown! 🏆🏏\n\nWho will take charge?"
        kb = [[InlineKeyboardButton("HOST BANUNGA 👿", callback_data='host_banunga')], [InlineKeyboardButton("CANCEL ❌", callback_data='cancel')]]
        try: await query.message.delete()
        except: pass
        await context.bot.send_photo(
            chat_id=chat_id,
            photo='https://res.cloudinary.com/dxgfxfoog/image/upload/v1777720311/file_00000000332072078d00837e7d719f5e_ybg18b.png',
            caption=text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif query.data == 'host_banunga':
        if is_user_playing_anywhere(context, user_id):
            await query.answer("❌ you are already in a game or in a queue in either this or other group", show_alert=True)
            return
        context.bot_data[chat_id] = {'state': 'TEAM_SETUP_HOST', 'host_id': user_id, 'mode': 'TEAM'}
        try: 
            await query.edit_message_caption(
                caption=f"👑 <a href='tg://user?id={user_id}'>{update.effective_user.first_name}</a> is the Game Host!\n\nHost, please send /create_team to open the team registration.", 
                parse_mode='HTML', 
                reply_markup=None
            )
        except Exception as e:
            print(f"host_banunga exception: {e}")

    elif query.data == 'join_team_a':
        if game.get('state') != 'TEAM_JOINING': return
        if is_user_playing_anywhere(context, user_id):
            await context.bot.send_message(chat_id, "❌ you are already in a game or in a queue in either this or other group")
            return
        
        in_a = any(p['id'] == user_id for p in game['team_a']['players'])
        in_b = any(p['id'] == user_id for p in game['team_b']['players'])
        if in_a or in_b:
            team_name = "Team A 🔴" if in_a else "Team B 🔵"
            await query.answer(f"⚠️ You are already in {team_name}! Wait for the host to start.", show_alert=True)
            return

        username = update.effective_user.username.lower() if update.effective_user.username else None
        init_user_db(user_id, update.effective_user.first_name, username)
        game['team_a']['players'].append({'id': user_id, 'name': update.effective_user.first_name, 'username': username, 'runs': 0, 'balls_faced': 0, 'wickets': 0, 'conceded': 0, 'balls_bowled': 0, 'is_out': False, 'match_4s': 0, 'match_6s': 0})
        await context.bot.send_message(chat_id, f"🔴 <b>{update.effective_user.first_name}</b> joined Team A!", parse_mode='HTML')
        
        if game.get('is_paused_waiting_players'):
            if len(game['team_a']['players']) >= 2 and len(game['team_b']['players']) >= 2:
                game['is_paused_waiting_players'] = False
                await context.bot.send_message(chat_id, "✅ Minimum player requirement met! Resuming setup... ▶️")
                await trigger_team_captains(context, chat_id, game)

    elif query.data == 'join_team_b':
        if game.get('state') != 'TEAM_JOINING': return
        if is_user_playing_anywhere(context, user_id):
            await context.bot.send_message(chat_id, "❌ you are already in a game or in a queue in either this or other group")
            return
            
        in_a = any(p['id'] == user_id for p in game['team_a']['players'])
        in_b = any(p['id'] == user_id for p in game['team_b']['players'])
        if in_a or in_b:
            team_name = "Team A 🔴" if in_a else "Team B 🔵"
            await query.answer(f"⚠️ You are already in {team_name}! Wait for the host to start.", show_alert=True)
            return

        username = update.effective_user.username.lower() if update.effective_user.username else None
        init_user_db(user_id, update.effective_user.first_name, username)
        game['team_b']['players'].append({'id': user_id, 'name': update.effective_user.first_name, 'username': username, 'runs': 0, 'balls_faced': 0, 'wickets': 0, 'conceded': 0, 'balls_bowled': 0, 'is_out': False, 'match_4s': 0, 'match_6s': 0})
        await context.bot.send_message(chat_id, f"🔵 <b>{update.effective_user.first_name}</b> joined Team B!", parse_mode='HTML')
        
        if game.get('is_paused_waiting_players'):
            if len(game['team_a']['players']) >= 2 and len(game['team_b']['players']) >= 2:
                game['is_paused_waiting_players'] = False
                await context.bot.send_message(chat_id, "✅ Minimum player requirement met! Resuming setup... ▶️")
                await trigger_team_captains(context, chat_id, game)

    elif query.data in ['team_cap_a', 'team_cap_b']:
        if game.get('state') != 'TEAM_CAPTAINS': return
        team_key = 'team_a' if query.data == 'team_cap_a' else 'team_b'
        
        if not any(p['id'] == user_id for p in game[team_key]['players']):
            await query.answer("You are not in this team!", show_alert=True)
            return
            
        if game[team_key]['captain']:
            await query.answer("Captain already selected!", show_alert=True)
            return
            
        game[team_key]['captain'] = user_id
        await context.bot.send_message(chat_id, f"👑 <b>{update.effective_user.first_name}</b> is now Captain of {'Team A 🔴' if team_key == 'team_a' else 'Team B 🔵'}!", parse_mode='HTML')
        
        if game['team_a']['captain'] and game['team_b']['captain']:
            game['state'] = 'TEAM_TOSS'
            toss_winner_team = random.choice(['team_a', 'team_b'])
            game['toss_winner_team'] = toss_winner_team
            cap_id = game[toss_winner_team]['captain']
            cap_name = next(p['name'] for p in game[toss_winner_team]['players'] if p['id'] == cap_id)
            
            kb = [[InlineKeyboardButton("Heads 🪙", callback_data="toss_heads"), InlineKeyboardButton("Tails 🪙", callback_data="toss_tails")]]
            toss_vid = "https://res.cloudinary.com/dxgfxfoog/video/upload/v1777819028/VID_20260503195638_lhif0h.mp4"
            caption_msg = f"🪙 <b>TOSS TIME!</b>\n<a href='tg://user?id={cap_id}'>{cap_name}</a>, call the toss!"
            await send_media_safely(context, chat_id, toss_vid, caption_msg, InlineKeyboardMarkup(kb))

    elif query.data in ['toss_heads', 'toss_tails']:
        if game.get('state') != 'TEAM_TOSS': return
        if user_id != game[game['toss_winner_team']]['captain']:
            await query.answer("Only the designated captain can call the toss!", show_alert=True)
            return
            
        won_toss = random.choice([True, False])
        if won_toss:
            game['state'] = 'TEAM_TOSS_DECISION'
            winner_team_name = 'Team A 🔴' if game['toss_winner_team'] == 'team_a' else 'Team B 🔵'
            kb = [[InlineKeyboardButton("Bat 🏏", callback_data="toss_bat"), InlineKeyboardButton("Bowl 🥎", callback_data="toss_bowl")]]
            text_cap = f"🎉 <b>{winner_team_name}</b> won the toss! What will you do?"
            try: await query.message.delete()
            except Exception: pass
            await context.bot.send_message(chat_id, text=text_cap, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
        else:
            game['state'] = 'TEAM_TOSS_DECISION'
            game['toss_winner_team'] = 'team_b' if game['toss_winner_team'] == 'team_a' else 'team_a'
            cap_id = game[game['toss_winner_team']]['captain']
            cap_name = next(p['name'] for p in game[game['toss_winner_team']]['players'] if p['id'] == cap_id)
            winner_team_name = 'Team A 🔴' if game['toss_winner_team'] == 'team_a' else 'Team B 🔵'
            
            kb = [[InlineKeyboardButton("Bat 🏏", callback_data="toss_bat"), InlineKeyboardButton("Bowl 🥎", callback_data="toss_bowl")]]
            text_cap = f"❌ You lost the toss!\n\n🎉 <b>{winner_team_name}</b> (<a href='tg://user?id={cap_id}'>{cap_name}</a>) won the toss. What will they choose?"
            try: await query.message.delete()
            except Exception: pass
            await context.bot.send_message(chat_id, text=text_cap, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

    elif query.data in ['toss_bat', 'toss_bowl']:
        if game.get('state') != 'TEAM_TOSS_DECISION': return
        if user_id != game[game['toss_winner_team']]['captain']:
            await query.answer("Only the toss winning captain can decide!", show_alert=True)
            return
            
        if query.data == 'toss_bat':
            game['batting_team_ref'] = game[game['toss_winner_team']]
            game['bowling_team_ref'] = game['team_b' if game['toss_winner_team'] == 'team_a' else 'team_a']
            dec_text = "bat 🏏"
        else:
            game['bowling_team_ref'] = game[game['toss_winner_team']]
            game['batting_team_ref'] = game['team_b' if game['toss_winner_team'] == 'team_a' else 'team_a']
            dec_text = "bowl 🥎"
            
        game['state'] = 'TEAM_OVERS'
        host_id = game['host_id']
        try:
            host_user = await context.bot.get_chat_member(chat_id, host_id)
            host_name = host_user.user.first_name
        except:
            host_name = "Host"
            
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id, text=f"✅ The captain chose to {dec_text} first!")
            
        kb = [[InlineKeyboardButton(str(o), callback_data=f"tovers_{o}") for o in [3, 5, 10]], 
              [InlineKeyboardButton(str(o), callback_data=f"tovers_{o}") for o in [15, 20, 25]]]
        await context.bot.send_message(chat_id, f"<a href='tg://user?id={host_id}'>{host_name}</a> (Game Host), select the number of overs for this match:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

    elif query.data.startswith('tovers_'):
        if game.get('state') != 'TEAM_OVERS': return
        if user_id != game['host_id']:
            await query.answer("Only the host can select overs!", show_alert=True)
            return
            
        overs = int(query.data.split('_')[1])
        game['target_overs'] = overs
        game['state'] = 'PLAYING'
        game['innings'] = 1
        game['waiting_for'] = 'TEAM_OPENERS_BAT'
        game['is_free_hit'] = False
        game['special_used_this_over'] = False
        game['innings_start_msg_pending'] = True
        
        try: await query.edit_message_text(f"✅ Match set for <b>{overs} Overs</b> per side!", parse_mode='HTML', reply_markup=None)
        except: pass
        await context.bot.send_message(chat_id, f"Batting Captain/Host, please select your opening pair using:\n<code>/batting [number]</code> (do it twice).", parse_mode='HTML')

    elif query.data.startswith('spell_'):
        if context.bot_data.get(chat_id, {}).get('state') in ['JOINING', 'PLAYING']:
            try: await query.edit_message_caption(caption="❌ A match is already active or setting up in this group!", reply_markup=None)
            except: pass
            return
            
        spell_len = int(query.data.split('_')[1])
        context.bot_data[chat_id] = {'state': 'JOINING', 'mode': 'SOLO', 'spell': spell_len, 'players': []}
        try: await query.edit_message_caption(caption=f"🏏 <b>Queue Open!</b> (Spell: {spell_len} balls) ⚖️\n👉 Type /join\n👉 Type /leavesolo to exit queue\n👉 Admin can type /startsolo", parse_mode='HTML', reply_markup=None)
        except: pass

    elif query.data == 'cancel':
        if game.get('state') == 'PLAYING':
            try: await query.edit_message_caption(caption="❌ Match is already playing! Use /endmatch to stop it.", reply_markup=None)
            except: pass
            return
        game['state'] = 'NOT_PLAYING'
        for prefix in ['autostart_', 'team_join_', 'queueremind_']:
            jobs = context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}")
            for job in jobs: job.schedule_removal()
        try: await query.edit_message_caption(caption="Setup cancelled. 🏏❌", reply_markup=None)
        except: pass
        
    elif query.data == 'vote_host':
        if 'host_votes' not in game: return
        if user_id in game['host_votes']:
            await query.answer("You already voted!", show_alert=True)
            return
            
        game['host_votes'].add(user_id)
        votes = len(game['host_votes'])
        
        if votes >= 4:
            game['host_id'] = game['host_vote_target']
            try: await query.edit_message_text(f"✅ Vote passed! Game Host successfully changed to <b>{game['host_vote_name']}</b>! 👑", parse_mode='HTML', reply_markup=None)
            except: pass
        else:
            kb = [[InlineKeyboardButton(f"Vote ✅ ({votes}/4)", callback_data="vote_host")]]
            try: await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(kb))
            except: pass

    elif query.data.startswith('endmatch_'):
        parts = query.data.split('_')
        action = parts[1]
        targ_chat_id = int(parts[2])
        
        if not await is_admin(update.effective_chat, update.effective_user.id):
            await query.answer("❌ Only admins can click this!", show_alert=True)
            return
            
        if action == 'yes':
            game_ref = context.bot_data.get(targ_chat_id)
            if game_ref: 
                commit_player_stats(game_ref)
                game_ref['state'] = 'NOT_PLAYING'
                for prefix in ['autostart_', 'team_join_', 'queueremind_', 'afk1_', 'afk10_', 'afk30_', 'afk60_', 'afk90_']:
                    jobs = context.job_queue.get_jobs_by_name(f"{prefix}{targ_chat_id}")
                    for job in jobs: job.schedule_removal()
            # FIX: Ensure we safely edit and handle the exception if it triggers twice
            try: await query.edit_message_text("🛑 <b>Match has been force-ended by an Admin.</b>", parse_mode='HTML', reply_markup=None)
            except Exception as e: print(f"endmatch_yes edit fail: {e}")
        elif action == 'no':
            try: await query.edit_message_text("✅ Force-end cancelled. The match continues!", reply_markup=None)
            except Exception as e: print(f"endmatch_no edit fail: {e}")

    elif query.data.startswith('special_'):
        group_id = int(query.data.split('_')[1])
        game = context.bot_data.get(group_id)
        
        if not game or game['state'] != 'PLAYING' or game.get('waiting_for') != 'BOWLER': return
        
        if game.get('mode') == 'SOLO':
            bowler = game['players'][game['bowler_idx']]
            batter = game['players'][game['batter_idx']]
        else:
            bowler = game['current_bowler']
            batter = game['striker']
            
        if update.effective_user.id != bowler['id']: return
        if game.get('special_used_this_over'): return
        
        if 'active_bowlers' in context.bot_data and update.effective_user.id in context.bot_data['active_bowlers']:
            del context.bot_data['active_bowlers'][update.effective_user.id]
            
        game['special_used_this_over'] = True
        clear_afk_timer(context, group_id)
        
        roll = random.randint(1, 100)
        
        if roll <= 60:
            try: await query.edit_message_text("Oops! Missed yorker and gave a <b>WIDE</b> ball! 1 extra run. You must bowl again.", parse_mode='HTML', reply_markup=None)
            except: pass
            batter['runs'] += 1
            bowler['conceded'] += 1
            if game.get('mode') == 'TEAM':
                game['batting_team_ref']['score'] += 1
            await context.bot.send_message(group_id, "🚨 <b>WIDE BALL!</b> 1 extra run. Bowler must re-bowl! 🥎", parse_mode='HTML')
            await trigger_bowl(context, group_id)
            
        elif roll <= 80:
            try: await query.edit_message_text("Oops! Missed yorker and gave a <b>NO BALL!</b>", parse_mode='HTML', reply_markup=None)
            except: pass
            game['current_bowl'] = 'NO_BALL'
            game['waiting_for'] = 'BATTER'
            
            hit_opts = "1-6" if game.get('mode') == 'SOLO' else "0-6"
            await send_media_safely(context, group_id, MEDIA['batter_turn'], f"🚨 Ball bowled! 🥎💨\n👉 <a href='tg://user?id={batter['id']}'>{batter['name']}</a>, type {hit_opts} to hit! 🏏👇")
            set_afk_timer(context, group_id, batter['id'], 'BATTER')
            
        else:
            msg = "🎯 <b>You landed a perfect YORKER!</b> Let's see how the batter reacts...\n⚠️ If the batter chooses "
            if game.get('mode') == 'TEAM':
                msg += "0-3, they survive. "
            else:
                msg += "1-3, they survive. "
            msg += "Otherwise, they are OUT! ☝️"
            try: await query.edit_message_text(msg, parse_mode='HTML', reply_markup=None)
            except: pass
            
            game['current_bowl'] = 'YORKER'
            game['waiting_for'] = 'BATTER'
            
            hit_opts = "1-6" if game.get('mode') == 'SOLO' else "0-6"
            await send_media_safely(context, group_id, MEDIA['batter_turn'], f"🚨 Ball bowled! 🥎💨\n👉 <a href='tg://user?id={batter['id']}'>{batter['name']}</a>, type {hit_opts} to hit! 🏏👇")
            set_afk_timer(context, group_id, batter['id'], 'BATTER')

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    chat_type = update.message.chat.type
    
    if not user_input.isdigit(): return
    val = int(user_input)

    # DM INPUT (BOWLER)
    if chat_type == 'private':
        user_id = update.effective_user.id
        group_id = context.bot_data.get('active_bowlers', {}).get(user_id)
        if not group_id: return
        
        game = context.bot_data.get(group_id)
        if not game or game['state'] != 'PLAYING' or game.get('waiting_for') != 'BOWLER': return
        
        if game.get('mode') == 'SOLO':
            bowler = game['players'][game['bowler_idx']]
            batter = game['players'][game['batter_idx']]
        else:
            bowler = game['current_bowler']
            batter = game['striker']
            
        if user_id != bowler['id']: return

        if val < 1 or val > 6:
            await update.message.reply_text("❌ Bowlers can only bowl numbers from 1 to 6!")
            return

        clear_afk_timer(context, group_id)
        game['current_bowl'] = val
        game['waiting_for'] = 'BATTER'
        del context.bot_data['active_bowlers'][user_id] 
        
        chat = await context.bot.get_chat(group_id)
        chat_url = None
        if chat.username:
            chat_url = f"https://t.me/{chat.username}"
        elif chat.invite_link:
            chat_url = chat.invite_link
        else:
            try: chat_url = await chat.export_invite_link()
            except: pass
                
        kb = []
        if chat_url:
            kb.append([InlineKeyboardButton("Back to Game 🔙", url=chat_url)])

        hit_opts = "1-6" if game.get('mode') == 'SOLO' else "0-6"
        await update.message.reply_text(f"Choice locked! 🔒 You bowled a <b>{val}</b>.", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(kb) if kb else None)
        await send_media_safely(context, group_id, MEDIA['batter_turn'], f"🚨 Ball bowled! 🥎💨\n👉 <a href='tg://user?id={batter['id']}'>{batter['name']}</a>, type {hit_opts} to hit! 🏏👇")
        set_afk_timer(context, group_id, batter['id'], 'BATTER')

    # GROUP INPUT (BATTER)
    else:
        chat_id = update.effective_chat.id
        game = context.bot_data.get(chat_id)
        
        if not game or game['state'] != 'PLAYING' or game.get('waiting_for') != 'BATTER': return
            
        if game.get('mode') == 'SOLO':
            if val < 1 or val > 6: return
            batter = game['players'][game['batter_idx']]
            bowler = game['players'][game['bowler_idx']]
        else:
            if val < 0 or val > 6: return
            batter = game['striker']
            bowler = game['current_bowler']
            
        hit_val = val
        if update.effective_user.id != batter['id']: return
            
        clear_afk_timer(context, chat_id)
        
        lock_msg = await context.bot.send_message(chat_id, "<b>BATTR CHOICE LOCKED</b> 🔒", parse_mode='HTML')
        await asyncio.sleep(0.2)
        try: await lock_msg.delete()
        except Exception: pass
            
        if hit_val == 4:
            batter['match_4s'] = batter.get('match_4s', 0) + 1
        elif hit_val == 6:
            batter['match_6s'] = batter.get('match_6s', 0) + 1
            
        bowl_val = game['current_bowl']
        media_url = None
        milestone_media = None
        milestone_text = None
        is_free_hit = game.get('is_free_hit', False)
        
        if bowl_val == 'NO_BALL':
            bowler['consecutive_wickets'] = 0
            batter['balls_faced'] += 1
            game['is_free_hit'] = True 
            
            old_runs = batter['runs']
            batter['runs'] += (hit_val + 1)
            bowler['conceded'] += (hit_val + 1)
            
            if game.get('mode') == 'TEAM':
                game['batting_team_ref']['score'] += (hit_val + 1)
            
            result_text = f"🚨 <b>IT WAS A NO BALL!</b> 1 penalty run.\n🚀 <b>NEXT BALL WILL BE A FREE HIT!</b> 🚀\n\n"
            result_text += f"🥎 Bowler delivery: <b>[HIDDEN]</b> 🤫\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
            if hit_val == 0:
                result_text += f"🛡️ <b>Solid defense! Dot ball.</b> ({batter['name']}: {batter['runs']})"
            else:
                result_text += f"🏃‍♂️ <b>Great shot! {hit_val} runs!</b> 🔥 ({batter['name']}: {batter['runs']})"
            media_url = MEDIA.get(hit_val, MEDIA[0])
            
            await send_media_safely(context, chat_id, media_url, result_text, reply_to_message_id=update.message.message_id)
            
            if old_runs < 100 and batter['runs'] >= 100:
                milestone_media = MEDIA['100']
                milestone_text = f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> has smashed a glorious century! What an innings! 🏏🏟️"
            elif old_runs < 50 and batter['runs'] >= 50:
                milestone_media = MEDIA['50']
                milestone_text = f"🏏 <b>HALF-CENTURY! BRILLIANT INNINGS!</b> 💥🙌\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> reaches 50! Keep it going! 🔥"
                
            if milestone_media:
                await send_media_safely(context, chat_id, milestone_media, milestone_text)
                
            if game.get('mode') == 'TEAM' and hit_val % 2 != 0:
                swap_strike(game)
                await context.bot.send_message(chat_id, f"🔄 Strike rotated! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!", parse_mode='HTML')
                
            if game.get('mode') == 'TEAM':
                if game['innings'] == 2 and game['batting_team_ref']['score'] >= game['target']:
                    await process_team_innings_end(context, chat_id, game)
                    return
                    
            if game['state'] == 'PLAYING':
                game['waiting_for'] = 'BOWLER'
                
        elif bowl_val == 'YORKER':
            batter['balls_faced'] += 1
            bowler['balls_bowled'] += 1
            if game.get('mode') == 'SOLO': game['balls_bowled'] += 1
            if game.get('mode') == 'TEAM': game['bowling_team_ref']['balls_bowled'] += 1
            
            if game.get('mode') == 'TEAM': survives = hit_val in [0, 1, 2, 3]
            else: survives = hit_val in [1, 2, 3]
                
            if not survives:
                if is_free_hit:
                    game['is_free_hit'] = False
                    bowler['consecutive_wickets'] = 0
                    result_text = f"🥎 Bowler delivery: <b>YORKER</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n💥 <b>BOWLED! BUT IT\'S A FREE HIT!</b> 😅\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> survives and scores 0 runs!"
                    await send_media_safely(context, chat_id, MEDIA['batter_turn'], result_text, reply_to_message_id=update.message.message_id)
                else:
                    bowler['wickets'] += 1
                    result_text = f"🥎 Bowler delivery: <b>YORKER</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                    result_text += f"💥 <b>HOWZAT! OUT!</b> ☝️ {batter['name']} is bowled by a lethal yorker for {batter['runs']}! 😔🚶‍♂️"
                    
                    await send_media_safely(context, chat_id, MEDIA['yorker'], result_text, reply_to_message_id=update.message.message_id)
                    
                    if batter['runs'] == 0:
                        duck_text = f"🦆 <a href='tg://user?id={batter['id']}'>{batter['name']}</a> got a duck 🦆"
                        await send_media_safely(context, chat_id, MEDIA['duck'], duck_text)
                             
                    bowler['consecutive_wickets'] = bowler.get('consecutive_wickets', 0) + 1
                    if bowler['consecutive_wickets'] == 3:
                        bowler['consecutive_wickets'] = 0
                        if users_col is not None: users_col.update_one({"user_id": bowler['id']}, {"$inc": {"hat_tricks": 1}}, upsert=True)
                        ht_vid = 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777819065/VID_20260503200210_rabpvn.mp4'
                        ht_cap = f"🎩 <b>HAT-TRICK!</b> <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, you are a magician!! 🪄🔥"
                        await send_media_safely(context, chat_id, ht_vid, ht_cap)
                    
                    batter['is_out'] = True
                    
                    if game.get('mode') == 'TEAM':
                        game['batting_team_ref']['wickets'] += 1
                        if game['batting_team_ref']['wickets'] >= len(game['batting_team_ref']['players']) - 1:
                            await process_team_innings_end(context, chat_id, game)
                            return
                        else:
                            game['waiting_for'] = 'TEAM_BATTER_SELECT'
                            await context.bot.send_message(chat_id, f"🏏 Captain/Host, type <code>/batting</code> to see batters list or <code>/batting [number]</code> to select the next batter.", parse_mode='HTML')
                    else:
                        game['batter_idx'] += 1
                        if game['batter_idx'] >= len(game['players']):
                            commit_player_stats(game)
                            game['state'] = 'NOT_PLAYING'
                            await trigger_full_scorecard_message(context, chat_id, game)
                            return
                        if game['batter_idx'] == game['bowler_idx']:
                            game['bowler_idx'] = (game['bowler_idx'] + 1) % len(game['players'])
                            game['balls_bowled'] = 0 
                            game['special_used_this_over'] = False
            else:
                bowler['consecutive_wickets'] = 0
                if is_free_hit: game['is_free_hit'] = False
                old_runs = batter['runs']
                batter['runs'] += hit_val
                bowler['conceded'] += hit_val
                if game.get('mode') == 'TEAM': game['batting_team_ref']['score'] += hit_val
                
                result_text = f"🥎 Bowler delivery: <b>YORKER</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                result_text += f"🏃‍♂️ <b>Great shot! Dug out the yorker for {hit_val} runs!</b> 🔥 ({batter['name']}: {batter['runs']})"
                media_url = MEDIA.get(hit_val, MEDIA[0])
                
                await send_media_safely(context, chat_id, media_url, result_text, reply_to_message_id=update.message.message_id)
                
                if old_runs < 100 and batter['runs'] >= 100:
                    milestone_media = MEDIA['100']
                    milestone_text = f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> has smashed a glorious century! What an innings! 🏏🏟️"
                    await send_media_safely(context, chat_id, milestone_media, milestone_text)
                elif old_runs < 50 and batter['runs'] >= 50:
                    milestone_media = MEDIA['50']
                    milestone_text = f"🏏 <b>HALF-CENTURY! BRILLIANT INNINGS!</b> 💥🙌\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> reaches 50! Keep it going! 🔥"
                    await send_media_safely(context, chat_id, milestone_media, milestone_text)

                if game.get('mode') == 'TEAM':
                    if game['innings'] == 2 and game['batting_team_ref']['score'] >= game['target']:
                        await process_team_innings_end(context, chat_id, game)
                        return
                    if hit_val % 2 != 0:
                        swap_strike(game)
                        await context.bot.send_message(chat_id, f"🔄 Strike rotated! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!", parse_mode='HTML')
                        
        elif str(hit_val) == str(bowl_val):
            batter['balls_faced'] += 1
            bowler['balls_bowled'] += 1
            if game.get('mode') == 'SOLO': game['balls_bowled'] += 1
            if game.get('mode') == 'TEAM': game['bowling_team_ref']['balls_bowled'] += 1
            
            if is_free_hit:
                game['is_free_hit'] = False
                bowler['consecutive_wickets'] = 0
                result_text = f"🥎 Bowler delivery: <b>{bowl_val}</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n💥 <b>BOWLED! BUT IT\'S A FREE HIT!</b> 😅\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> survives and scores 0 runs!"
                await send_media_safely(context, chat_id, MEDIA['batter_turn'], result_text, reply_to_message_id=update.message.message_id)
            else:
                bowler['wickets'] += 1 
                result_text = f"🥎 Bowler delivery: <b>{bowl_val}</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                result_text += f"💥 <b>HOWZAT! OUT!</b> ☝️ {batter['name']} is dismissed for {batter['runs']}! 😔🚶‍♂️"
                
                await send_media_safely(context, chat_id, MEDIA['out'], result_text, reply_to_message_id=update.message.message_id)
                
                if batter['runs'] == 0:
                    duck_text = f"🦆 <a href='tg://user?id={batter['id']}'>{batter['name']}</a> got a duck 🦆"
                    await send_media_safely(context, chat_id, MEDIA['duck'], duck_text)
                
                bowler['consecutive_wickets'] = bowler.get('consecutive_wickets', 0) + 1
                if bowler['consecutive_wickets'] == 3:
                    bowler['consecutive_wickets'] = 0
                    if users_col is not None: users_col.update_one({"user_id": bowler['id']}, {"$inc": {"hat_tricks": 1}}, upsert=True)
                    ht_vid = 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777819065/VID_20260503200210_rabpvn.mp4'
                    ht_cap = f"🎩 <b>HAT-TRICK!</b> <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, you are a magician!! 🪄🔥"
                    await send_media_safely(context, chat_id, ht_vid, ht_cap)
                        
                batter['is_out'] = True
                if game.get('mode') == 'TEAM':
                    game['batting_team_ref']['wickets'] += 1
                    if game['batting_team_ref']['wickets'] >= len(game['batting_team_ref']['players']) - 1:
                        await process_team_innings_end(context, chat_id, game)
                        return
                    else:
                        game['waiting_for'] = 'TEAM_BATTER_SELECT'
                        await context.bot.send_message(chat_id, f"🏏 Captain/Host, type <code>/batting</code> to see batters list or <code>/batting [number]</code> to select the next batter.", parse_mode='HTML')
                else:
                    game['batter_idx'] += 1
                    if game['batter_idx'] >= len(game['players']):
                        commit_player_stats(game)
                        game['state'] = 'NOT_PLAYING'
                        await trigger_full_scorecard_message(context, chat_id, game)
                        return
                    if game['batter_idx'] == game['bowler_idx']:
                        game['bowler_idx'] = (game['bowler_idx'] + 1) % len(game['players'])
                        game['balls_bowled'] = 0 
                        game['special_used_this_over'] = False
        
        # RUNS OR DEFENSE (0)
        else:
            bowler['consecutive_wickets'] = 0
            batter['balls_faced'] += 1
            bowler['balls_bowled'] += 1
            if game.get('mode') == 'SOLO': game['balls_bowled'] += 1
            if game.get('mode') == 'TEAM': game['bowling_team_ref']['balls_bowled'] += 1
            
            if is_free_hit: game['is_free_hit'] = False
                
            old_runs = batter['runs']
            batter['runs'] += hit_val
            bowler['conceded'] += hit_val
            if game.get('mode') == 'TEAM': game['batting_team_ref']['score'] += hit_val
            
            result_text = f"🥎 Bowler delivery: <b>[HIDDEN]</b> 🤫\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
            if hit_val == 0: result_text += f"🛡️ <b>Solid defense! Dot ball.</b> ({batter['name']}: {batter['runs']})"
            else: result_text += f"🏃‍♂️ <b>Great shot! {hit_val} runs!</b> 🔥 ({batter['name']}: {batter['runs']})"
            media_url = MEDIA.get(hit_val, MEDIA[0])
            
            await send_media_safely(context, chat_id, media_url, result_text, reply_to_message_id=update.message.message_id)
            
            if old_runs < 100 and batter['runs'] >= 100:
                milestone_media = MEDIA['100']
                milestone_text = f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> has smashed a glorious century! What an innings! 🏏🏟️"
            elif old_runs < 50 and batter['runs'] >= 50:
                milestone_media = MEDIA['50']
                milestone_text = f"🏏 <b>HALF-CENTURY! BRILLIANT INNINGS!</b> 💥🙌\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> reaches 50! Keep it going! 🔥"
                
            if milestone_media:
                await send_media_safely(context, chat_id, milestone_media, milestone_text)

            if game.get('mode') == 'TEAM':
                if game['innings'] == 2 and game['batting_team_ref']['score'] >= game['target']:
                    await process_team_innings_end(context, chat_id, game)
                    return
                if hit_val % 2 != 0:
                    swap_strike(game)
                    await context.bot.send_message(chat_id, f"🔄 Strike rotated! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!", parse_mode='HTML')

        # OVER COMPLETION CHECK
        is_over_complete = False
        if game.get('mode') == 'SOLO' and game['balls_bowled'] >= game['spell']:
            is_over_complete = True
        elif game.get('mode') == 'TEAM' and game['bowling_team_ref']['balls_bowled'] % 6 == 0 and game['bowling_team_ref']['balls_bowled'] > 0:
            is_over_complete = True

        if is_over_complete:
            spell_text = f"🔁 <b>Over Completed!</b> 🛑 {bowler['name']} finished.\n"
            
            if game.get('mode') == 'TEAM':
                swap_strike(game)
                game['last_bowler_id'] = bowler['id']
                
                if game['bowling_team_ref']['balls_bowled'] >= game['target_overs'] * 6:
                    await process_team_innings_end(context, chat_id, game)
                    return
                
                await trigger_full_scorecard_message(context, chat_id, game)
                team = game['batting_team_ref']
                spell_text += f"\n📊 Score: {team['score']}/{team['wickets']}\n"
                spell_text += f"🔄 Strike rotated for new over! 🏏 <a href='tg://user?id={game['striker']['id']}'>{game['striker']['name']}</a> is now on strike!\n"
                spell_text += f"Bowling Captain/Host, select next bowler using <code>/bowling</code> to see list or <code>/bowling [num]</code>."
                await context.bot.send_message(chat_id, spell_text, parse_mode='HTML')
                
                if game.get('waiting_for') == 'TEAM_BATTER_SELECT':
                    game['need_new_bowler'] = True
                else:
                    game['waiting_for'] = 'TEAM_BOWLER_SELECT'
            else:
                await trigger_full_scorecard_message(context, chat_id, game)
                await context.bot.send_message(chat_id, spell_text, parse_mode='HTML')
                game['balls_bowled'] = 0
                game['special_used_this_over'] = False
                game['bowler_idx'] = (game['bowler_idx'] + 1) % len(game['players'])
                if game['bowler_idx'] == game['batter_idx']:
                     game['bowler_idx'] = (game['bowler_idx'] + 1) % len(game['players'])
                if game['state'] == 'PLAYING':
                    game['waiting_for'] = 'BOWLER'
                     
        else:
            if game.get('waiting_for') == 'BATTER':
                game['waiting_for'] = 'BOWLER'
                
        if game['state'] == 'PLAYING' and game.get('waiting_for') == 'BOWLER':
            await asyncio.sleep(0.3)
            await trigger_bowl(context, chat_id)

if __name__ == '__main__':
    print("Starting ELITE CRICKET BOT Server...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('join', join_command))
    app.add_handler(CommandHandler('add', add_command))
    app.add_handler(CommandHandler('remove', remove_command))
    app.add_handler(CommandHandler('changehost', changehost_command))
    app.add_handler(CommandHandler('create_team', create_team_command))
    app.add_handler(CommandHandler('rejoin', rejoin_command))
    app.add_handler(CommandHandler('leavesolo', leavesolo_command))
    app.add_handler(CommandHandler('startsolo', startsolo_command))
    app.add_handler(CommandHandler('endmatch', endmatch_command))
    app.add_handler(CommandHandler('soloscore', soloscore_command))
    app.add_handler(CommandHandler('score', teamscore_command))
    app.add_handler(CommandHandler('teams', teams_command))
    app.add_handler(CommandHandler('batting', batting_command))
    app.add_handler(CommandHandler('bowling', bowling_command))
    app.add_handler(CommandHandler('userstats', userstats_command))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    
    app.run_polling(poll_interval=1.0)
