from flask import Flask
from threading import Thread
import os

# =========================
# KEEP-ALIVE WEB SERVER
# =========================

app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Bot is running!"

def run_web():
    app_web.run(
        host='0.0.0.0',
        port=int(os.environ.get("PORT", 10000))
    )

# Start Flask in background thread
Thread(target=run_web).start()
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Replace with your actual bot token
TOKEN = '8614255689:AAEhfHsuDwQdMrOHHhIeY7ud9mXomq2XmSI'

MEDIA = {
    'batter_turn': 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777688554/VID_20260502075045_eab7uu.mp4',
    'bowler_turn': 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777694389/VID_20260502092829_np7h5d.mp4',
    'out': 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777641612/1777641553346_zexrt4.mp4',
    'duck': 'https://media.giphy.com/media/krewXUB6LBja/giphy.gif', 
    '50': 'https://media.giphy.com/media/07oir8PhvSReDNpNi7/giphy.gif',
    '100': 'https://media.giphy.com/media/pR0jymbIr7HrrpISUW/giphy.gif',
    'yorker': 'https://media.giphy.com/media/2CUJFvoRXDrUeG1mOS/giphy.gif',
    1: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642218/animation.gif_1_u1ksyt.mp4',
    2: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642586/VID_20260501_190546_668_tdnzth.mp4',
    3: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642484/VID_20260501_190413_260_cylqql.mp4',
    4: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777644250/VID_20260501_193031_696_quwh5m.mp4',
    5: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777642378/VID_20260501_190216_576_yonoc2.mp4',
    6: 'https://res.cloudinary.com/dxgfxfoog/video/upload/v1777641118/VideoToGifConverterBot_1_zxgkql.mp4'
}

# --- HELPER FUNCTIONS ---
async def is_admin(chat, user_id):
    try:
        member = await chat.get_member(user_id)
        return member.status in ['administrator', 'creator']
    except Exception:
        return False

def generate_scorecard(game):
    text = "\n📊 <b>MATCH SCORECARD</b> 📊\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    for p in game['players']:
        overs = p['balls_bowled'] // 6
        balls = p['balls_bowled'] % 6
        overs_str = f"{overs}.{balls}"
        eco = (p['conceded'] / p['balls_bowled']) * 6 if p['balls_bowled'] > 0 else 0.00
        text += f"👤 <b>{p['name']}</b>\n"
        text += f"   🏏 Batting: {p['runs']} Runs ({p['balls_faced']} Balls)\n"
        text += f"   🥎 Bowling: {p['wickets']} W | {p['conceded']} R | {overs_str} Ov | Eco: {eco:.1f}\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n"
    return text

def get_potm(game):
    best_player = None
    best_score = -999
    for p in game['players']:
        score = p['runs'] + (p['wickets'] * 15) - (p['conceded'] * 0.5)
        if score > best_score:
            best_score = score
            best_player = p
    if best_player:
        return f"\n🏅 <b>PLAYER OF THE MATCH: {best_player['name']}</b> 🏅\n"
    return ""

# --- TIMERS ---
def set_afk_timer(context, chat_id, user_id, role):
    clear_afk_timer(context, chat_id)
    context.job_queue.run_once(afk_warning_10, 10, data={'chat_id': chat_id, 'user_id': user_id, 'role': role}, name=f"afk10_{chat_id}")
    context.job_queue.run_once(afk_warning_60, 60, data={'chat_id': chat_id, 'user_id': user_id, 'role': role}, name=f"afk60_{chat_id}")
    context.job_queue.run_once(afk_timeout, 90, data={'chat_id': chat_id, 'user_id': user_id, 'role': role}, name=f"afk90_{chat_id}")

def clear_afk_timer(context, chat_id):
    for prefix in ['afk10_', 'afk60_', 'afk90_']:
        jobs = context.job_queue.get_jobs_by_name(f"{prefix}{chat_id}")
        for job in jobs: job.schedule_removal()

async def afk_warning_10(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data['chat_id'], job.data['user_id'], job.data['role']
    game = context.bot_data.get(chat_id)
    
    if not game or game.get('state') != 'PLAYING' or game.get('waiting_for') != role: return
    
    if role == 'BATTER' and game['players'][game['batter_idx']]['id'] != user_id: return
    if role == 'BOWLER' and game['players'][game['bowler_idx']]['id'] != user_id: return
    
    player = next((p for p in game['players'] if p['id'] == user_id), None)
    if not player: return
    
    await context.bot.send_message(chat_id, f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, you have been AFK! You have <b>80 more seconds</b> left to play. ⏳", parse_mode='HTML')

async def afk_warning_60(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data['chat_id'], job.data['user_id'], job.data['role']
    game = context.bot_data.get(chat_id)
    
    if not game or game.get('state') != 'PLAYING' or game.get('waiting_for') != role: return
    
    if role == 'BATTER' and game['players'][game['batter_idx']]['id'] != user_id: return
    if role == 'BOWLER' and game['players'][game['bowler_idx']]['id'] != user_id: return
    
    player = next((p for p in game['players'] if p['id'] == user_id), None)
    if not player: return
    
    await context.bot.send_message(chat_id, f"⚠️ <a href='tg://user?id={user_id}'>{player['name']}</a>, HURRY UP! You only have <b>30 seconds</b> left to play! ⏰", parse_mode='HTML')

async def afk_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id, role = job.data['chat_id'], job.data['user_id'], job.data['role']
    game = context.bot_data.get(chat_id)
    
    if not game or game.get('state') != 'PLAYING' or game.get('waiting_for') != role: return
    
    if role == 'BATTER' and game['players'][game['batter_idx']]['id'] != user_id: return
    if role == 'BOWLER' and game['players'][game['bowler_idx']]['id'] != user_id: return
    
    player = next((p for p in game['players'] if p['id'] == user_id), None)
    if not player: return
    
    await context.bot.send_message(chat_id, f"⏳ <b>TIME'S UP!</b> {player['name']} was AFK for 90 seconds and has been ELIMINATED! ❌", parse_mode='HTML')
    
    game['players'] = [p for p in game['players'] if p['id'] != user_id]
    
    if len(game['players']) < 2:
        game['state'] = 'NOT_PLAYING'
        await context.bot.send_message(chat_id, "Not enough players left! Match abandoned. 🛑", parse_mode='HTML')
        return

    game['batter_idx'] = min(game['batter_idx'], len(game['players']) - 1)
    game['bowler_idx'] = (game['batter_idx'] + 1) % len(game['players'])
    
    game['waiting_for'] = 'BOWLER'
    game['balls_bowled'] = 0
    game['special_used_this_over'] = False
    await trigger_bowl(context, chat_id)

async def auto_start_match(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data['chat_id']
    game = context.bot_data.get(chat_id)
    
    if not game or game.get('state') != 'JOINING': return
    
    if len(game['players']) >= 2:
        game.update({'state': 'PLAYING', 'waiting_for': 'BOWLER', 'batter_idx': 0, 'bowler_idx': 1, 'balls_bowled': 0, 'special_used_this_over': False, 'is_free_hit': False})
        await context.bot.send_message(chat_id, "⏳ <b>90 seconds are up! THE MATCH AUTO-STARTS NOW!</b> 🚨\nLet's head to the pitch! 🏟️", parse_mode='HTML')
        await trigger_bowl(context, chat_id)
    else:
        game['state'] = 'NOT_PLAYING'
        await context.bot.send_message(chat_id, "⏳ <b>90 seconds are up, but there are not enough players!</b> Match setup abandoned. 🛑", parse_mode='HTML')


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
                    bowler = game['players'][game['bowler_idx']]
                    if update.effective_user.id == bowler['id']:
                        keyboard = []
                        if not game.get('special_used_this_over'):
                            keyboard.append([InlineKeyboardButton("🌟 Special Delivery 🌟", callback_data=f"special_{group_id}")])
                            
                        await update.message.reply_text(
                            "🥎 <b>Your Turn to Bowl!</b>\nType 1-6 or use your Special Delivery! 🤔👇", 
                            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                            parse_mode='HTML'
                        )
                        return
                    else:
                        await update.message.reply_text("It is not your turn to bowl right now! 🚫🏏")
                        return
            except ValueError:
                pass
        await update.message.reply_text("Please add ELITE CRICKET BOT to a group to play! 🏏🏟️👥")
        return

    if context.bot_data.get(chat_id, {}).get('state') in ['JOINING', 'PLAYING']:
        await update.message.reply_text("❌ A match is already active in this group! Finish it or ask an admin to /endsolo first.")
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


async def join_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == 'private': return
    chat_id = update.effective_chat.id
    game = context.bot_data.get(chat_id)

    if not game or game.get('state') != 'JOINING':
        await update.message.reply_text("No match is open for joining! Type /start ❌🏏")
        return

    user = update.effective_user

    for cid, data in context.bot_data.items():
        if isinstance(data, dict) and data.get('state') in ['JOINING', 'PLAYING']:
            if cid != chat_id and any(p['id'] == user.id for p in data.get('players', [])):
                await update.message.reply_text(f"❌ {user.first_name}, you are already in a match or queue in another group! Finish or leave that one first.")
                return

    if any(p['id'] == user.id for p in game['players']):
        await update.message.reply_text(f"Hold on {user.first_name}! You're already queued. ⏳🧍‍♂️")
        return

    game['players'].append({'id': user.id, 'name': user.first_name, 'runs': 0, 'conceded': 0, 'wickets': 0, 'balls_bowled': 0, 'balls_faced': 0})
    
    timer_msg = ""
    if len(game['players']) == 1:
        context.job_queue.run_once(auto_start_match, 90, data={'chat_id': chat_id}, name=f"autostart_{chat_id}")
        timer_msg = "\n⏳ <i>Auto-start timer initiated: Match begins in 90 seconds!</i>"
        
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
                jobs = context.job_queue.get_jobs_by_name(f"autostart_{chat_id}")
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
        
    jobs = context.job_queue.get_jobs_by_name(f"autostart_{chat_id}")
    for job in jobs: job.schedule_removal()
        
    game.update({'state': 'PLAYING', 'waiting_for': 'BOWLER', 'batter_idx': 0, 'bowler_idx': 1, 'balls_bowled': 0, 'special_used_this_over': False, 'is_free_hit': False})
    
    await update.message.reply_text("🚨 <b>THE MATCH HAS BEGUN!</b> 🚨", parse_mode='HTML')
    await trigger_bowl(context, chat_id)


async def endsolo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    
    if not await is_admin(update.effective_chat, update.effective_user.id):
        await update.message.reply_text("❌ Only group admins can end the match!")
        return
        
    game = context.bot_data.get(chat_id)
    if not game or game['state'] not in ['JOINING', 'PLAYING']:
        await update.message.reply_text("❌ There is no active match to end!")
        return
        
    keyboard = [
        [InlineKeyboardButton("Yes, End Match ✅", callback_data=f"endsolo_yes_{chat_id}")],
        [InlineKeyboardButton("Cancel ❌", callback_data=f"endsolo_no_{chat_id}")]
    ]
    await update.message.reply_text("⚠️ <b>Admin Action:</b> Are you sure you want to force-end the current match?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')


async def soloscore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == 'private': return
    
    game = context.bot_data.get(chat_id)
    if not game or game.get('state') != 'PLAYING':
        await update.message.reply_text("❌ No active match is currently being played!")
        return
        
    scorecard = generate_scorecard(game)
    await update.message.reply_photo(
        photo='https://res.cloudinary.com/dxgfxfoog/image/upload/v1777690370/file_000000003b007208989acb9335cd9f20_skv1se.png',
        caption=scorecard,
        parse_mode='HTML'
    )

async def trigger_full_scorecard_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, game_data):
    scorecard = generate_scorecard(game_data)
    potm = get_potm(game_data)
    final_caption = f"🏆 <b>INNINGS OVER!</b>\n{scorecard}{potm}"
    
    await context.bot.send_photo(
        chat_id=chat_id,
        photo='https://res.cloudinary.com/dxgfxfoog/image/upload/v1777690370/file_000000003b007208989acb9335cd9f20_skv1se.png',
        caption=final_caption,
        parse_mode='HTML'
    )


async def trigger_bowl(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    game = context.bot_data[chat_id]
    bowler = game['players'][game['bowler_idx']]
    batter = game['players'][game['batter_idx']]
    
    if 'active_bowlers' not in context.bot_data:
        context.bot_data['active_bowlers'] = {}
    context.bot_data['active_bowlers'][bowler['id']] = chat_id
    
    bot_info = await context.bot.get_me()
    url = f"https://t.me/{bot_info.username}"
    
    free_hit_tag = "🚀 <b>FREE HIT ACTIVE!</b>\n" if game.get('is_free_hit') else ""
    
    dm_text = f"🏏 <b>Match in Progress!</b>\n\n"
    dm_text += f"🏏 Batter: <b>{batter['name']}</b> ({batter['runs']} runs)\n"
    dm_text += f"🥎 Over Status: {game['balls_bowled']}/{game['spell']} balls bowled.\n\n"
    dm_text += "👉 <b>Your Turn to Bowl!</b> Type a number from 1 to 6."
    
    keyboard = []
    if not game.get('special_used_this_over'):
        keyboard.append([InlineKeyboardButton("🌟 Special Delivery 🌟", callback_data=f"special_{chat_id}")])
        
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
        group_text = f"{free_hit_tag}📊 <b>Status:</b>\n🏏 <b>Batter:</b> {batter['name']} ({batter['runs']})\n🥎 <b>Bowler:</b> {bowler['name']} (Over: {game['balls_bowled']}/{game['spell']})\n\n👉 <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, check your DM to bowl! 🤫🥎"
        group_kb = [[InlineKeyboardButton("Bowl Delivery 🥎", url=url)]]
    else:
        fallback_url = f"https://t.me/{bot_info.username}?start={chat_id}"
        group_text = f"{free_hit_tag}📊 <b>Status:</b>\n🏏 <b>Batter:</b> {batter['name']} ({batter['runs']})\n🥎 <b>Bowler:</b> {bowler['name']} (Over: {game['balls_bowled']}/{game['spell']})\n\n⚠️ <a href='tg://user?id={bowler['id']}'>{bowler['name']}</a>, I couldn't DM you! Click below to start me, then bowl! 🤫🥎"
        group_kb = [[InlineKeyboardButton("Start Bot & Bowl 🤖", url=fallback_url)]]
        
    await context.bot.send_animation(
        chat_id=chat_id,
        animation=MEDIA['bowler_turn'],
        caption=group_text,
        reply_markup=InlineKeyboardMarkup(group_kb),
        parse_mode='HTML'
    )
        
    set_afk_timer(context, chat_id, bowler['id'], 'BOWLER')


# --- CALLBACKS & GAMEPLAY ---
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    chat_id = update.effective_chat.id

    if query.data == 'solo_game':
        if context.bot_data.get(chat_id, {}).get('state') in ['JOINING', 'PLAYING']:
            await query.edit_message_caption(caption="❌ A match is already active or setting up in this group!")
            return
            
        keyboard = [[InlineKeyboardButton("3 Balls 🥎", callback_data='spell_3')], [InlineKeyboardButton("6 Balls 🥎", callback_data='spell_6')]]
        await query.edit_message_caption(caption="Select Spell Limit: ⚖️🏏", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == 'team_game':
        await query.edit_message_caption(
            caption="Team Game 👥 mode is currently <b>under maintenance</b> 🛠️.\n"
            "Please play a Solo Game for now, or join @eclplays for updates. 🏏",
            parse_mode='HTML'
        )

    elif query.data.startswith('spell_'):
        if context.bot_data.get(chat_id, {}).get('state') in ['JOINING', 'PLAYING']:
            await query.edit_message_caption(caption="❌ A match is already active or setting up in this group!")
            return
            
        spell_len = int(query.data.split('_')[1])
        context.bot_data[chat_id] = {'state': 'JOINING', 'spell': spell_len, 'players': []}
        await query.edit_message_caption(caption=f"🏏 <b>Queue Open!</b> (Spell: {spell_len} balls) ⚖️\n👉 Type /join\n👉 Type /leavesolo to exit queue\n👉 Admin can type /startsolo", parse_mode='HTML')

    elif query.data == 'cancel':
        game = context.bot_data.get(chat_id)
        if game and game.get('state') == 'PLAYING':
            await query.edit_message_caption(caption="❌ Match is already playing! Use /endsolo to stop it.")
            return
        if game and game.get('state') == 'JOINING':
            game['state'] = 'NOT_PLAYING'
            jobs = context.job_queue.get_jobs_by_name(f"autostart_{chat_id}")
            for job in jobs: job.schedule_removal()
        await query.edit_message_caption(caption="Setup cancelled. 🏏❌")

    elif query.data.startswith('endsolo_'):
        parts = query.data.split('_')
        action = parts[1]
        targ_chat_id = int(parts[2])
        
        if not await is_admin(update.effective_chat, update.effective_user.id):
            await query.answer("❌ Only admins can click this!", show_alert=True)
            return
            
        if action == 'yes':
            game = context.bot_data.get(targ_chat_id)
            if game: 
                game['state'] = 'NOT_PLAYING'
                jobs = context.job_queue.get_jobs_by_name(f"autostart_{targ_chat_id}") 
                for prefix in ['afk10_', 'afk60_', 'afk90_']:
                    jobs += context.job_queue.get_jobs_by_name(f"{prefix}{targ_chat_id}")
                for job in jobs: job.schedule_removal()
            await query.edit_message_text("🛑 <b>Match has been force-ended by an Admin.</b>", parse_mode='HTML')
        elif action == 'no':
            await query.edit_message_text("✅ Force-end cancelled. The match continues!")

    elif query.data.startswith('special_'):
        group_id = int(query.data.split('_')[1])
        game = context.bot_data.get(group_id)
        
        if not game or game['state'] != 'PLAYING' or game.get('waiting_for') != 'BOWLER': return
        bowler = game['players'][game['bowler_idx']]
        if update.effective_user.id != bowler['id']: return
        if game.get('special_used_this_over'): return
        
        if 'active_bowlers' in context.bot_data and update.effective_user.id in context.bot_data['active_bowlers']:
            del context.bot_data['active_bowlers'][update.effective_user.id]
            
        game['special_used_this_over'] = True
        clear_afk_timer(context, group_id)
        roll = random.randint(1, 100)
        
        if roll <= 85: # WIDE
            await query.edit_message_text("🚨 You bowled a <b>WIDE!</b> 1 extra run. You must bowl again.", parse_mode='HTML')
            game['players'][game['batter_idx']]['runs'] += 1
            game['players'][game['bowler_idx']]['conceded'] += 1
            await context.bot.send_message(group_id, "🚨 <b>WIDE BALL!</b> 1 extra run. Bowler must re-bowl! 🥎", parse_mode='HTML')
            
            # Re-trigger bowl immediately so bowler gets the prompt again
            await trigger_bowl(context, group_id)
            
        elif roll <= 90: # YORKER & BOWLED
            await query.edit_message_text("💥 <b>PERFECT YORKER!</b> You shattered the stumps!", parse_mode='HTML')
            
            batter = game['players'][game['batter_idx']]
            bowler_ref = game['players'][game['bowler_idx']]
            is_free_hit = game.get('is_free_hit', False)
            
            batter['balls_faced'] += 1
            game['balls_bowled'] += 1
            bowler_ref['balls_bowled'] += 1
            
            if is_free_hit:
                game['is_free_hit'] = False
                result_text = f"🥎 Bowler delivery: <b>YORKER</b>\n🏏 Batter hit: <b>MISSED</b>\n\n💥 <b>BOWLED! BUT IT'S A FREE HIT!</b> 😅\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> survives and scores 0 runs!"
                media_url = MEDIA['batter_turn']
            else:
                bowler_ref['wickets'] += 1
                result_text = f"🥎 Bowler delivery: <b>YORKER</b>\n🏏 Batter hit: <b>MISSED</b>\n\n"
                
                if batter['runs'] == 0:
                    media_url = MEDIA['duck']
                    result_text += f"🦆 <a href='tg://user?id={batter['id']}'>{batter['name']}</a> got a duck 🦆"
                else:
                    media_url = MEDIA['yorker'] 
                    result_text += f"💥 <b>HOWZAT! OUT!</b> ☝️ {batter['name']} is dismissed for {batter['runs']}! 😔🚶‍♂️"
                
                game['batter_idx'] += 1
                
                if game['batter_idx'] >= len(game['players']):
                    game['state'] = 'NOT_PLAYING'
                    await context.bot.send_animation(group_id, animation=media_url, caption=result_text, parse_mode='HTML')
                    await trigger_full_scorecard_message(context, group_id, game)
                    return
                    
                if game['batter_idx'] == game['bowler_idx']:
                    game['bowler_idx'] = (game['bowler_idx'] + 1) % len(game['players'])
                    game['balls_bowled'] = 0 
                    game['special_used_this_over'] = False
                
            if game['state'] == 'PLAYING' and game['balls_bowled'] >= game['spell']:
                result_text += f"\n\n🔁 <b>Spell Completed!</b> 🛑 {game['players'][game['bowler_idx']]['name']} finished."
                result_text += generate_scorecard(game) 
                game['balls_bowled'] = 0
                game['special_used_this_over'] = False
                game['bowler_idx'] = (game['bowler_idx'] + 1) % len(game['players'])
                if game['bowler_idx'] == game['batter_idx']:
                     game['bowler_idx'] = (game['bowler_idx'] + 1) % len(game['players'])
                     
            await context.bot.send_animation(group_id, animation=media_url, caption=result_text, parse_mode='HTML')
            
            if game['state'] == 'PLAYING':
                game['waiting_for'] = 'BOWLER'
                await trigger_bowl(context, group_id)

        else: # NO BALL
            await query.edit_message_text("🚨 <b>NO BALL!</b> 1 run penalty. You must bowl the Free Hit!", parse_mode='HTML')
            game['is_free_hit'] = True 
            game['players'][game['batter_idx']]['runs'] += 1
            game['players'][game['bowler_idx']]['conceded'] += 1
            
            await context.bot.send_message(
                group_id, 
                "🚨 <b>NO BALL!</b> 1 run penalty.\n🚀 <b>NEXT BALL WILL BE A FREE HIT!</b> 🚀\nBowler must re-bowl! 🥎", 
                parse_mode='HTML'
            )
            # Send prompt to bowler again
            await trigger_bowl(context, group_id)


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    chat_type = update.message.chat.type
    
    if not user_input.isdigit() or not (1 <= int(user_input) <= 6): return

    # DM INPUT
    if chat_type == 'private':
        user_id = update.effective_user.id
        group_id = context.bot_data.get('active_bowlers', {}).get(user_id)
        if not group_id: return
        
        game = context.bot_data.get(group_id)
        if not game or game['state'] != 'PLAYING' or game.get('waiting_for') != 'BOWLER': return
        
        bowler = game['players'][game['bowler_idx']]
        if user_id != bowler['id']: return

        clear_afk_timer(context, group_id)
        game['current_bowl'] = int(user_input)
        game['waiting_for'] = 'BATTER'
        
        del context.bot_data['active_bowlers'][user_id] 

        await update.message.reply_text(f"Choice locked! 🔒 You bowled a <b>{user_input}</b>.", parse_mode='HTML')
        
        batter = game['players'][game['batter_idx']]
        await context.bot.send_animation(group_id, animation=MEDIA['batter_turn'], caption=f"🚨 Ball bowled! 🥎💨\n👉 <a href='tg://user?id={batter['id']}'>{batter['name']}</a>, type 1-6 to hit! 🏏👇", parse_mode='HTML')
        set_afk_timer(context, group_id, batter['id'], 'BATTER')

    # GROUP INPUT
    else:
        chat_id = update.effective_chat.id
        game = context.bot_data.get(chat_id)
        
        if not game or game['state'] != 'PLAYING' or game.get('waiting_for') != 'BATTER': return
            
        batter = game['players'][game['batter_idx']]
        hit_val = int(user_input)
        
        if update.effective_user.id != batter['id']: return
            
        clear_afk_timer(context, chat_id)
        
        thunder_msg = await context.bot.send_message(chat_id, "⚡")
        await asyncio.sleep(0.7)
        try:
            await thunder_msg.delete()
        except Exception:
            pass
            
        bowl_val = game['current_bowl']
        bowler = game['players'][game['bowler_idx']]
        media_url = None
        milestone_media = None
        milestone_text = None
        is_free_hit = game.get('is_free_hit', False)
        
        batter['balls_faced'] += 1
        
        if bowl_val != 'NO_BALL': 
            game['balls_bowled'] += 1
            bowler['balls_bowled'] += 1
            
        if is_free_hit and bowl_val != 'NO_BALL': 
            game['is_free_hit'] = False
        
        # WICKET
        if hit_val == bowl_val and bowl_val != 'NO_BALL':
            if is_free_hit:
                media_url = MEDIA['batter_turn'] 
                result_text = f"🥎 Bowler delivery: <b>{bowl_val}</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n💥 <b>BOWLED! BUT IT'S A FREE HIT!</b> 😅\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> survives and scores 0 runs!"
            else:
                bowler['wickets'] += 1 
                result_text = f"🥎 Bowler delivery: <b>{bowl_val}</b>\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
                if batter['runs'] == 0:
                    media_url = MEDIA['duck']
                    result_text += f"🦆 <a href='tg://user?id={batter['id']}'>{batter['name']}</a> got a duck 🦆"
                else:
                    media_url = MEDIA['out']
                    result_text += f"💥 <b>HOWZAT! OUT!</b> ☝️ {batter['name']} is dismissed for {batter['runs']}! 😔🚶‍♂️"
                
                game['batter_idx'] += 1
                if game['batter_idx'] >= len(game['players']):
                    game['state'] = 'NOT_PLAYING'
                    await update.message.reply_animation(animation=media_url, caption=result_text, parse_mode='HTML')
                    await trigger_full_scorecard_message(context, chat_id, game)
                    return
                    
                if game['batter_idx'] == game['bowler_idx']:
                    game['bowler_idx'] = (game['bowler_idx'] + 1) % len(game['players'])
                    game['balls_bowled'] = 0 
                    game['special_used_this_over'] = False
        
        # RUNS
        else:
            old_runs = batter['runs']
            batter['runs'] += hit_val
            bowler['conceded'] += hit_val
            
            result_text = f"🥎 Bowler delivery: <b>[HIDDEN]</b> 🤫\n🏏 Batter hit: <b>{hit_val}</b>\n\n"
            result_text += f"🏃‍♂️ <b>Great shot! {hit_val} runs!</b> 🔥 ({batter['name']}: {batter['runs']})"
            media_url = MEDIA.get(hit_val, MEDIA['batter_turn'])
            
            if old_runs < 100 and batter['runs'] >= 100:
                milestone_media = MEDIA['100']
                milestone_text = f"👑 <b>CENTURY! TAKE A BOW!</b> 💯🔥\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> has smashed a glorious century! What an innings! 🏏🏟️"
            elif old_runs < 50 and batter['runs'] >= 50:
                milestone_media = MEDIA['50']
                milestone_text = f"🏏 <b>HALF-CENTURY! BRILLIANT INNINGS!</b> 💥🙌\n<a href='tg://user?id={batter['id']}'>{batter['name']}</a> reaches 50! Keep it going! 🔥"

        # SPELL CHECK
        if game['state'] == 'PLAYING' and game['balls_bowled'] >= game['spell']:
            result_text += f"\n\n🔁 <b>Spell Completed!</b> 🛑 {game['players'][game['bowler_idx']]['name']} finished."
            result_text += generate_scorecard(game)
            game['balls_bowled'] = 0
            game['special_used_this_over'] = False
            game['bowler_idx'] = (game['bowler_idx'] + 1) % len(game['players'])
            if game['bowler_idx'] == game['batter_idx']:
                 game['bowler_idx'] = (game['bowler_idx'] + 1) % len(game['players'])
                 
        await update.message.reply_animation(animation=media_url, caption=result_text, parse_mode='HTML')
        
        if milestone_media:
            await context.bot.send_animation(chat_id, animation=milestone_media, caption=milestone_text, parse_mode='HTML')
            
        if game['state'] == 'PLAYING':
            game['waiting_for'] = 'BOWLER'
            await trigger_bowl(context, chat_id)


if __name__ == '__main__':
    print("Starting ELITE CRICKET BOT Server...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('join', join_command))
    app.add_handler(CommandHandler('leavesolo', leavesolo_command))
    app.add_handler(CommandHandler('startsolo', startsolo_command))
    app.add_handler(CommandHandler('endsolo', endsolo_command))
    app.add_handler(CommandHandler('soloscore', soloscore_command))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    
    app.run_polling(poll_interval=1.0)
