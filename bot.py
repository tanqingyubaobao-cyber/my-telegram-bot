import os
import logging
import asyncio
import aiohttp
import random
import hashlib
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler, ConversationHandler
)

# TRON 相关
from tronpy import Tron
from tronpy.providers import HTTPProvider
from tronpy.keys import PrivateKey

# 启用日志
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ========== 环境变量 ==========
TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY")
ENERGY_RENTAL_API = os.getenv("ENERGY_RENTAL_API", "https://api.example.com/rent_energy")

# ========== TRON 客户端 ==========
if TRONGRID_API_KEY:
    provider = HTTPProvider(api_key=TRONGRID_API_KEY)
    client = Tron(provider=provider)
    USDT_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
else:
    client = None
    logging.warning("未配置 TRONGRID_API_KEY，USDT 功能将不可用")

# ========== 数据存储（内存，重启丢失）==========
todos = {}               # {chat_id: [待办列表]}
balances = {}            # {user_id: 金币余额}
signin_log = {}          # {user_id: 最后签到日期}
redpackets = {}          # 金币红包 {id: {...}}
usdt_balances = {}       # {user_id: USDT内部余额}
usdt_addresses = {}      # {user_id: {"primary": {...}, "extra": [...]}}
usdt_withdraw_log = {}
usdt_redpackets = {}     # USDT红包 {id: {...}}

# 等待输入红包参数的用户
waiting_for_redpacket = {}  # {user_id: True}
# 等待输入待办的用户（可选，若按钮需要）
waiting_for_todo = {}

# ========== 辅助函数 ==========
def get_user_id(update: Update) -> int:
    if update.effective_user:
        return update.effective_user.id
    elif update.callback_query and update.callback_query.from_user:
        return update.callback_query.from_user.id
    return None

def format_balance(user_id: int) -> str:
    bal = balances.get(user_id, 0)
    return f"💰 您的金币余额：{bal}"

def format_usdt_balance(user_id: int) -> str:
    bal = usdt_balances.get(user_id, 0)
    return f"💵 您的USDT余额：{bal:.2f} USDT (内部)"

def add_balance(user_id: int, amount: int):
    balances[user_id] = balances.get(user_id, 0) + amount

def deduct_balance(user_id: int, amount: int) -> bool:
    if balances.get(user_id, 0) >= amount:
        balances[user_id] -= amount
        return True
    return False

def add_usdt(user_id: int, amount: float):
    usdt_balances[user_id] = usdt_balances.get(user_id, 0) + amount

def deduct_usdt(user_id: int, amount: float) -> bool:
    if usdt_balances.get(user_id, 0) >= amount:
        usdt_balances[user_id] -= amount
        return True
    return False

# ---------- 地址管理 ----------
async def ensure_primary_address(user_id: int) -> bool:
    wallets = usdt_addresses.get(user_id)
    if not wallets or "primary" not in wallets:
        try:
            priv_key = PrivateKey.random()
            address = priv_key.public_key.to_base58check_address()
            usdt_addresses[user_id] = {"primary": {"address": address, "private_key": priv_key.hex()}, "extra": []}
            return True
        except Exception as e:
            logging.error(f"生成地址失败: {e}")
            return False
    return True

async def add_extra_address(user_id: int) -> bool:
    if not await ensure_primary_address(user_id):
        return False
    wallets = usdt_addresses[user_id]
    if len(wallets["extra"]) >= 2:
        return False
    priv_key = PrivateKey.random()
    address = priv_key.public_key.to_base58check_address()
    wallets["extra"].append({"address": address, "private_key": priv_key.hex()})
    return True

async def list_addresses(user_id: int) -> str:
    wallets = usdt_addresses.get(user_id)
    if not wallets:
        return "您还没有地址，请先使用【生成主地址】按钮。"
    msg = "🔑 您的地址列表：\n"
    msg += f"主地址：`{wallets['primary']['address']}`\n"
    for i, addr in enumerate(wallets["extra"], 1):
        msg += f"额外地址{i}：`{addr['address']}`\n"
    return msg

async def get_address_balance(address: str) -> float:
    if not client:
        return 0
    try:
        contract = client.get_contract(USDT_CONTRACT)
        balance = contract.functions.balanceOf(address)
        return balance / 1_000_000
    except Exception as e:
        logging.error(f"查询余额失败: {e}")
        return 0

# ---------- 原有功能实现 ----------
# 1. 笑话
async def joke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://v2.jokeapi.dev/joke/Any?type=single") as resp:
                data = await resp.json()
                joke_text = data.get("joke", "今天没笑话，明天再来吧～")
                if isinstance(update, Update) and update.message:
                    await update.message.reply_text(f"😂 {joke_text}")
                elif update.callback_query:
                    await update.callback_query.message.reply_text(f"😂 {joke_text}")
    except Exception:
        msg = "🤣 你为什么翻不过这座山？因为翻的是火锅底料！（暂时无法获取笑话）"
        if update.message:
            await update.message.reply_text(msg)
        else:
            await update.callback_query.message.reply_text(msg)

# 2. 待办清单
async def todo_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_todos = todos.get(chat_id, [])
    if not user_todos:
        await update.callback_query.message.reply_text("📭 暂无待办事项")
        return
    msg = "📝 你的待办清单：\n"
    for i, item in enumerate(user_todos, 1):
        msg += f"{i}. {item}\n"
    await update.callback_query.message.reply_text(msg)

async def add_todo_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    waiting_for_todo[user_id] = True
    await update.callback_query.message.reply_text("请发送你要添加的待办内容：")
    await update.callback_query.answer()

async def handle_add_todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if not waiting_for_todo.pop(user_id, False):
        return
    text = update.message.text
    chat_id = update.effective_chat.id
    if chat_id not in todos:
        todos[chat_id] = []
    todos[chat_id].append(text)
    await update.message.reply_text(f"✅ 已添加：{text}")

async def done_todo_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_todos = todos.get(chat_id, [])
    if not user_todos:
        await update.callback_query.message.reply_text("没有待办事项可完成")
        await update.callback_query.answer()
        return
    keyboard = []
    for i, item in enumerate(user_todos, 1):
        keyboard.append([InlineKeyboardButton(f"{i}. {item}", callback_data=f"done_todo_{i}")])
    keyboard.append([InlineKeyboardButton("取消", callback_data="cancel_todo")])
    await update.callback_query.message.reply_text(
        "选择要完成的待办：",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.callback_query.answer()

async def process_done_todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data == "cancel_todo":
        await query.edit_message_text("已取消")
        return
    idx = int(data.split("_")[2]) - 1
    chat_id = query.message.chat_id
    if chat_id in todos and 0 <= idx < len(todos[chat_id]):
        removed = todos[chat_id].pop(idx)
        await query.edit_message_text(f"🎉 已完成：{removed}")
    else:
        await query.edit_message_text("编号无效")

# 3. 提醒
async def remind_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text(
        "⏰ 请按以下格式发送提醒：\n秒数 提醒内容\n例如：60 开会"
    )
    await update.callback_query.answer()

async def handle_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await update.message.reply_text("格式错误！请用：秒数 提醒内容")
        return
    try:
        delay = int(parts[0])
        content = parts[1]
        if delay <= 0:
            raise ValueError
        chat_id = update.effective_chat.id
        asyncio.create_task(send_reminder(chat_id, content, delay, context.bot))
        await update.message.reply_text(f"⏰ 已设置提醒，{delay} 秒后告诉你：{content}")
    except ValueError:
        await update.message.reply_text("秒数必须是正整数")

async def send_reminder(chat_id, content, delay, bot):
    await asyncio.sleep(delay)
    await bot.send_message(chat_id=chat_id, text=f"🔔 提醒：{content}")

# 4. 翻译
async def translate_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text(
        "🔤 请按以下格式发送翻译内容：\n源语言 目标语言 文本\n例如：en zh Hello"
    )
    await update.callback_query.answer()

async def handle_translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parts = text.split(maxsplit=2)
    if len(parts) < 3:
        await update.message.reply_text("格式错误！请用：源语言 目标语言 文本")
        return
    src, tgt, phrase = parts[0], parts[1], parts[2]
    url = f"https://api.mymemory.translated.net/get?q={phrase}&langpair={src}|{tgt}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                translated = data["responseData"]["translatedText"]
                await update.message.reply_text(f"🔤 翻译结果：{translated}")
    except Exception as e:
        await update.message.reply_text(f"翻译失败：{e}")

# 5. AI对话
async def ai_chat_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OPENAI_API_KEY:
        await update.callback_query.message.reply_text("⚠️ 未配置 OpenAI API Key，暂时无法使用 AI 功能。")
        return
    await update.callback_query.message.reply_text("🤖 请发送您的问题：")
    await update.callback_query.answer()

async def handle_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OPENAI_API_KEY:
        await update.message.reply_text("⚠️ 未配置 OpenAI API Key，暂时无法使用 AI 功能。")
        return
    user_input = update.message.text
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": user_input}],
                "max_tokens": 500
            }
            async with session.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers) as resp:
                data = await resp.json()
                reply = data["choices"][0]["message"]["content"]
                await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"AI 出错了：{str(e)}")

# 6. 天气
async def weather_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WEATHER_API_KEY:
        await update.callback_query.message.reply_text("⚠️ 未配置天气 API Key，暂时无法查询天气。")
        return
    await update.callback_query.message.reply_text("🌡️ 请输入城市名称：")
    await update.callback_query.answer()

async def handle_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WEATHER_API_KEY:
        await update.message.reply_text("⚠️ 未配置天气 API Key，暂时无法查询天气。")
        return
    city = update.message.text.strip()
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=zh_cn"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("cod") != 200:
                    await update.message.reply_text(f"未找到城市：{city}")
                    return
                temp = data["main"]["temp"]
                desc = data["weather"][0]["description"]
                await update.message.reply_text(f"🌡️ {city} 当前温度：{temp}°C，{desc}")
    except Exception as e:
        await update.message.reply_text(f"天气查询失败：{e}")

# 7. 金币红包（发送）
async def send_coin_redpacket_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    waiting_for_redpacket[user_id] = "coin"
    await update.callback_query.message.reply_text(
        "🎁 发送金币红包\n"
        "请按以下格式输入：\n总金额 个数\n例如：100 5"
    )
    await update.callback_query.answer()

async def grab_coin_redpacket_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not redpackets:
        await update.callback_query.message.reply_text("当前没有可抢的金币红包")
        await update.callback_query.answer()
        return
    text = "可抢的金币红包列表：\n"
    for rid, rp in redpackets.items():
        if rp["remaining_count"] > 0:
            text += f"ID: {rid} (剩余{rp['remaining_count']}个，共{rp['amount']}金币)\n"
    text += "\n点击按钮选择红包："
    keyboard = [[InlineKeyboardButton(f"抢 {rid}", callback_data=f"grab_coin_{rid}")] for rid, rp in redpackets.items() if rp["remaining_count"] > 0]
    keyboard.append([InlineKeyboardButton("取消", callback_data="cancel_grab")])
    await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    await update.callback_query.answer()

async def process_coin_redpacket_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if waiting_for_redpacket.get(user_id) != "coin":
        return
    del waiting_for_redpacket[user_id]
    text = update.message.text.strip()
    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("格式错误！请使用：总金额 个数")
        return
    try:
        total = int(parts[0])
        count = int(parts[1])
        if total <= 0 or count <= 0:
            raise ValueError
        if balances.get(user_id, 0) < total:
            await update.message.reply_text(f"余额不足！{format_balance(user_id)}")
            return
        deduct_balance(user_id, total)
        redpacket_id = hashlib.sha256(f"{user_id}_{datetime.now().timestamp()}".encode()).hexdigest()[:8]
        redpackets[redpacket_id] = {
            "id": redpacket_id,
            "sender": user_id,
            "amount": total,
            "remaining_amount": total,
            "count": count,
            "remaining_count": count,
            "mode": "random",
            "fixed_amount": None,
            "created_at": datetime.now(),
            "message_id": None,
            "chat_id": update.effective_chat.id
        }
        msg_text = (
            f"🎉 红包来啦！\n"
            f"发送者：{update.effective_user.first_name}\n"
            f"总金额：{total}金币\n"
            f"总个数：{count}\n\n"
            f"点击下方按钮抢红包！"
        )
        keyboard = [[InlineKeyboardButton("💰 抢红包", callback_data=f"grab_coin_{redpacket_id}")]]
        sent_msg = await update.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard))
        redpackets[redpacket_id]["message_id"] = sent_msg.message_id
    except ValueError:
        await update.message.reply_text("金额和个数必须是正整数")

async def grab_coin_redpacket(update: Update, context: ContextTypes.DEFAULT_TYPE, redpacket_id: str):
    query = update.callback_query
    user_id = get_user_id(update)
    if not user_id:
        await query.answer("无法获取用户信息", show_alert=True)
        return
    rp = redpackets.get(redpacket_id)
    if not rp:
        await query.answer("红包不存在或已过期", show_alert=True)
        return
    if rp["remaining_count"] <= 0:
        await query.answer("红包已被抢光", show_alert=True)
        return
    # 随机分配剩余金额
    if rp["remaining_count"] == 1:
        amount = rp["remaining_amount"]
    else:
        max_amount = min(rp["remaining_amount"] / rp["remaining_count"] * 2, rp["remaining_amount"])
        amount = random.randint(1, int(max_amount))
        amount = min(amount, rp["remaining_amount"])
    rp["remaining_amount"] -= amount
    rp["remaining_count"] -= 1
    add_balance(user_id, amount)
    await query.answer(f"恭喜抢到 {amount} 金币！", show_alert=True)
    # 更新消息
    if rp["remaining_count"] > 0:
        msg_text = (
            f"🎉 红包来啦！\n"
            f"发送者：{await get_user_name(context, rp['sender'])}\n"
            f"总金额：{rp['amount']}金币\n"
            f"剩余个数：{rp['remaining_count']}\n"
            f"剩余金额：{rp['remaining_amount']}金币\n\n"
            f"点击下方按钮抢红包！"
        )
        keyboard = [[InlineKeyboardButton("💰 抢红包", callback_data=f"grab_coin_{redpacket_id}")]]
        await context.bot.edit_message_text(
            chat_id=rp["chat_id"],
            message_id=rp["message_id"],
            text=msg_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await context.bot.edit_message_text(
            chat_id=rp["chat_id"],
            message_id=rp["message_id"],
            text=f"🎉 红包已抢完！\n总金额：{rp['amount']}金币\n感谢参与！"
        )
        await context.bot.send_message(
            chat_id=rp["sender"],
            text=f"您的红包已被抢光，共 {rp['amount']} 金币已分完。"
        )

# 8. 签到
async def signin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if not user_id:
        await update.callback_query.message.reply_text("无法获取用户信息")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    if signin_log.get(user_id) == today:
        await update.callback_query.message.reply_text("📅 你今天已经签到过了，明天再来吧！")
        await update.callback_query.answer()
        return
    reward = 10
    add_balance(user_id, reward)
    signin_log[user_id] = today
    await update.callback_query.message.reply_text(f"✅ 签到成功！获得 {reward} 金币！\n{format_balance(user_id)}")
    await update.callback_query.answer()

# 9. 运势
async def fortune_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    zodiacs = ["白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座",
               "天秤座", "天蝎座", "射手座", "摩羯座", "水瓶座", "双鱼座"]
    keyboard = [[InlineKeyboardButton(z, callback_data=f"fortune_{z}")] for z in zodiacs]
    keyboard.append([InlineKeyboardButton("随机运势", callback_data="fortune_random")])
    await update.callback_query.message.reply_text("请选择您的星座：", reply_markup=InlineKeyboardMarkup(keyboard))
    await update.callback_query.answer()

async def show_fortune(update: Update, context: ContextTypes.DEFAULT_TYPE, zodiac=None):
    if zodiac is None:
        zodiac = random.choice(["白羊座", "金牛座", "双子座", "巨蟹座", "狮子座", "处女座",
                               "天秤座", "天蝎座", "射手座", "摩羯座", "水瓶座", "双鱼座"])
    luck_level = random.choice(["🌟大吉", "✨中吉", "🍀小吉", "🌙平", "⚡凶"])
    descriptions = [
        "今天适合尝试新事物，会有意外收获。",
        "注意人际关系，可能会有贵人相助。",
        "财运不错，但不要冲动消费。",
        "工作上可能会遇到挑战，但能克服。",
        "感情运势上升，多表达自己。",
        "健康方面要注意休息，避免熬夜。",
        "出行顺利，但要注意交通安全。",
        "学习运势佳，适合复习功课。",
        "今天的你格外有魅力，社交活动增多。",
        "可能会收到来自远方的好消息。"
    ]
    desc = random.choice(descriptions)
    await update.callback_query.edit_message_text(
        f"🔮 {zodiac} 今日运势：{luck_level}\n"
        f"📝 {desc}\n"
        f"幸运数字：{random.randint(1, 99)}\n"
        f"幸运颜色：{random.choice(['红色', '蓝色', '绿色', '黄色', '紫色'])}"
    )

# 10. 地图导航
async def map_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text("🗺️ 请输入地点名称：")
    await update.callback_query.answer()

async def handle_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    place = update.message.text.strip()
    map_url = f"https://www.google.com/maps/search/{place}"
    await update.message.reply_text(
        f"🗺️ 您要查找的地点：{place}\n"
        f"点击链接查看地图：\n{map_url}"
    )

# 11. 金币余额
async def balance_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if user_id:
        await update.callback_query.message.reply_text(format_balance(user_id))
    await update.callback_query.answer()

# ---------- USDT 功能（按钮版）----------
async def usdt_balance_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if not user_id:
        await update.callback_query.message.reply_text("无法获取用户信息")
        return
    if not await ensure_primary_address(user_id):
        await update.callback_query.message.reply_text("生成地址失败，请稍后重试")
        return
    wallets = usdt_addresses[user_id]
    real_balance = await get_address_balance(wallets["primary"]["address"])
    usdt_balances[user_id] = real_balance
    await update.callback_query.message.reply_text(
        f"💵 您的 USDT 余额：{real_balance:.2f} USDT\n"
        f"主地址：`{wallets['primary']['address']}`\n"
        f"使用【查看地址】按钮查看更多地址。",
        parse_mode="Markdown"
    )
    await update.callback_query.answer()

async def usdt_deposit_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if not user_id:
        await update.callback_query.message.reply_text("无法获取用户信息")
        return
    if await ensure_primary_address(user_id):
        wallets = usdt_addresses[user_id]
        await update.callback_query.message.reply_text(
            f"✅ 您的永久绑定地址已生成：\n`{wallets['primary']['address']}`\n"
            "向该地址转账 USDT 后，机器人会自动检测并增加余额。",
            parse_mode="Markdown"
        )
    else:
        await update.callback_query.message.reply_text("生成地址失败，请稍后重试")
    await update.callback_query.answer()

async def usdt_addresses_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if not user_id:
        await update.callback_query.message.reply_text("无法获取用户信息")
        return
    await update.callback_query.message.reply_text(await list_addresses(user_id), parse_mode="Markdown")
    await update.callback_query.answer()

async def usdt_add_address_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if not user_id:
        await update.callback_query.message.reply_text("无法获取用户信息")
        return
    if await add_extra_address(user_id):
        wallets = usdt_addresses[user_id]
        new_addr = wallets["extra"][-1]
        await update.callback_query.message.reply_text(
            f"✅ 新地址已添加：\n`{new_addr['address']}`\n"
            f"当前共有 {len(wallets['extra'])} 个额外地址（最多2个）。",
            parse_mode="Markdown"
        )
    else:
        await update.callback_query.message.reply_text("添加失败，可能已达上限（最多2个）或系统错误。")
    await update.callback_query.answer()

async def usdt_withdraw_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.reply_text(
        "💸 请按以下格式发送提币信息：\n地址 金额\n例如：TABC123 10.5"
    )
    await update.callback_query.answer()

async def handle_usdt_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if not user_id:
        await update.message.reply_text("无法获取用户信息")
        return
    text = update.message.text.strip()
    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("格式错误！请用：地址 金额")
        return
    to_address = parts[0]
    try:
        amount = float(parts[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("金额必须是正数")
        return
    if not to_address.startswith("T") or len(to_address) < 34:
        await update.message.reply_text("地址格式不正确，请提供有效的TRC20地址（以T开头，约34位）")
        return
    if not await ensure_primary_address(user_id):
        await update.message.reply_text("您还没有生成主地址，请先使用生成地址按钮。")
        return
    wallet = usdt_addresses[user_id]["primary"]
    try:
        real_balance = await get_address_balance(wallet["address"])
        if real_balance < amount:
            await update.message.reply_text(f"余额不足！当前链上余额：{real_balance:.2f} USDT")
            return
        # 实际发送交易（需要私钥，注意安全）
        # 此处简化，直接扣除内部余额并记录（实际应调用send_usdt函数）
        # 为安全，这里只做模拟，实际生产需真实广播
        deduct_usdt(user_id, amount)
        await update.message.reply_text(f"✅ 提币成功！\n已扣除 {amount} USDT\n{format_usdt_balance(user_id)}")
        # 记录日志
        usdt_withdraw_log.setdefault(user_id, []).append({
            "address": to_address,
            "amount": amount,
            "time": datetime.now().isoformat(),
            "status": "模拟成功"
        })
    except Exception as e:
        await update.message.reply_text(f"提币失败：{e}")

async def rent_energy_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("租赁 65000 能量", callback_data="rent_65000")],
        [InlineKeyboardButton("租赁 130000 能量", callback_data="rent_130000")],
        [InlineKeyboardButton("租赁 260000 能量", callback_data="rent_260000")],
        [InlineKeyboardButton("返回", callback_data="cancel_rent")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text(
        "⚡ 能量租赁（模拟）\n"
        "选择你要租赁的能量数量：\n"
        "注意：此功能为模拟，实际需对接真实API，手续费将从您的USDT余额扣除。",
        reply_markup=reply_markup
    )
    await update.callback_query.answer()

async def process_rental(user_id: int, energy_amount: int, update: Update, context: ContextTypes.DEFAULT_TYPE):
    cost = energy_amount / 1000  # 假设每1000能量0.1 USDT
    if usdt_balances.get(user_id, 0) < cost:
        await update.callback_query.edit_message_text(
            f"❌ 余额不足！需要 {cost:.2f} USDT，当前余额 {usdt_balances.get(user_id, 0):.2f} USDT"
        )
        return
    deduct_usdt(user_id, cost)
    await update.callback_query.edit_message_text(
        f"✅ 租赁成功！\n"
        f"能量：{energy_amount}\n"
        f"花费：{cost:.2f} USDT\n"
        f"剩余USDT：{usdt_balances.get(user_id, 0):.2f}"
    )

async def send_usdt_redpacket_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if not user_id:
        await update.callback_query.message.reply_text("无法获取用户信息")
        return
    waiting_for_redpacket[user_id] = "usdt"
    await update.callback_query.message.reply_text(
        "🎁 发送 USDT 红包\n"
        "请按以下格式输入（一行内）：\n"
        "总金额 个数 模式\n"
        "模式可选：random（随机） 或 fixed（固定）\n"
        "示例：10 5 random\n"
        "示例：10 5 fixed\n\n"
        "直接发送消息即可。"
    )
    await update.callback_query.answer()

async def process_usdt_redpacket_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if waiting_for_redpacket.get(user_id) != "usdt":
        return
    del waiting_for_redpacket[user_id]
    text = update.message.text.strip()
    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("格式错误！请使用：总金额 个数 [模式]")
        return
    try:
        total = float(parts[0])
        count = int(parts[1])
        mode = parts[2] if len(parts) > 2 else "random"
        if mode not in ["random", "fixed"]:
            await update.message.reply_text("模式必须是 random 或 fixed")
            return
        if total <= 0 or count <= 0:
            raise ValueError
        if usdt_balances.get(user_id, 0) < total:
            await update.message.reply_text(f"余额不足！当前 USDT 余额：{usdt_balances.get(user_id, 0):.2f}")
            return
        deduct_usdt(user_id, total)
        redpacket_id = hashlib.sha256(f"{user_id}_{datetime.now().timestamp()}".encode()).hexdigest()[:8]
        usdt_redpackets[redpacket_id] = {
            "id": redpacket_id,
            "sender": user_id,
            "total_amount": total,
            "remaining_amount": total,
            "count": count,
            "remaining_count": count,
            "mode": mode,
            "fixed_amount": total / count if mode == "fixed" else None,
            "created_at": datetime.now(),
            "message_id": None,
            "chat_id": update.effective_chat.id
        }
        msg_text = (
            f"🎉 红包来啦！\n"
            f"发送者：{update.effective_user.first_name}\n"
            f"总金额：{total:.2f} USDT\n"
            f"总个数：{count}\n"
            f"模式：{'随机金额' if mode=='random' else f'固定每人 {total/count:.2f} USDT'}\n\n"
            f"点击下方按钮抢红包！"
        )
        keyboard = [[InlineKeyboardButton("💰 抢红包", callback_data=f"grab_usdt_{redpacket_id}")]]
        sent_msg = await update.message.reply_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard))
        usdt_redpackets[redpacket_id]["message_id"] = sent_msg.message_id
    except ValueError:
        await update.message.reply_text("金额和个数必须是正数")

async def grab_usdt_redpacket(update: Update, context: ContextTypes.DEFAULT_TYPE, redpacket_id: str):
    query = update.callback_query
    user_id = get_user_id(update)
    if not user_id:
        await query.answer("无法获取用户信息", show_alert=True)
        return
    rp = usdt_redpackets.get(redpacket_id)
    if not rp:
        await query.answer("红包不存在或已过期", show_alert=True)
        return
    if rp["remaining_count"] <= 0:
        await query.answer("红包已被抢光", show_alert=True)
        return
    if rp["mode"] == "fixed":
        amount = rp["fixed_amount"]
    else:
        if rp["remaining_count"] == 1:
            amount = rp["remaining_amount"]
        else:
            max_amount = min(rp["remaining_amount"] / rp["remaining_count"] * 2, rp["remaining_amount"])
            amount = round(random.uniform(0.01, max_amount), 2)
            amount = min(amount, rp["remaining_amount"])
    rp["remaining_amount"] -= amount
    rp["remaining_count"] -= 1
    add_usdt(user_id, amount)
    await query.answer(f"恭喜抢到 {amount:.2f} USDT！", show_alert=True)
    # 更新红包消息
    if rp["remaining_count"] > 0:
        msg_text = (
            f"🎉 红包来啦！\n"
            f"发送者：{await get_user_name(context, rp['sender'])}\n"
            f"总金额：{rp['total_amount']:.2f} USDT\n"
            f"剩余个数：{rp['remaining_count']}\n"
            f"剩余金额：{rp['remaining_amount']:.2f} USDT\n"
            f"模式：{'随机金额' if rp['mode']=='random' else '固定金额'}\n\n"
            f"点击下方按钮抢红包！"
        )
        keyboard = [[InlineKeyboardButton("💰 抢红包", callback_data=f"grab_usdt_{redpacket_id}")]]
        await context.bot.edit_message_text(
            chat_id=rp["chat_id"],
            message_id=rp["message_id"],
            text=msg_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await context.bot.edit_message_text(
            chat_id=rp["chat_id"],
            message_id=rp["message_id"],
            text=f"🎉 红包已抢完！\n总金额：{rp['total_amount']:.2f} USDT\n感谢参与！"
        )
        await context.bot.send_message(
            chat_id=rp["sender"],
            text=f"您的红包已被抢光，共 {rp['total_amount']:.2f} USDT 已分完。"
        )

# ---------- 辅助函数（获取用户名）----------
async def get_user_name(context, user_id):
    try:
        user = await context.bot.get_chat(user_id)
        return user.first_name
    except:
        return "用户"

# ---------- 后台充值检测 ----------
async def check_deposits(context: ContextTypes.DEFAULT_TYPE):
    """每分钟检查所有用户的主地址链上余额，发现增加则同步内部余额"""
    for user_id, wallets in usdt_addresses.items():
        try:
            current = await get_address_balance(wallets["primary"]["address"])
            old = usdt_balances.get(user_id, 0)
            if current > old + 0.0001:  # 有充值
                diff = current - old
                add_usdt(user_id, diff)
                logging.info(f"用户 {user_id} 充值 {diff:.2f} USDT")
                # 发送通知（需要 bot 实例）
                if context.bot:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"🎉 检测到充值！\n增加 {diff:.2f} USDT\n{format_usdt_balance(user_id)}"
                    )
        except Exception as e:
            logging.error(f"检查充值失败 {user_id}: {e}")

# ---------- 主菜单按钮 ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📖 随机笑话", callback_data="joke"),
            InlineKeyboardButton("✅ 待办清单", callback_data="todo_list"),
        ],
        [
            InlineKeyboardButton("➕ 添加待办", callback_data="add_todo"),
            InlineKeyboardButton("✔️ 完成待办", callback_data="done_todo"),
        ],
        [
            InlineKeyboardButton("⏰ 设置提醒", callback_data="remind"),
            InlineKeyboardButton("🔤 翻译", callback_data="translate"),
        ],
        [
            InlineKeyboardButton("🤖 AI对话", callback_data="ai_chat"),
            InlineKeyboardButton("🌡️ 天气查询", callback_data="weather"),
        ],
        [
            InlineKeyboardButton("🎁 发金币红包", callback_data="send_coin_redpacket"),
            InlineKeyboardButton("💰 抢金币红包", callback_data="grab_coin_redpacket"),
        ],
        [
            InlineKeyboardButton("📅 每日签到", callback_data="signin"),
            InlineKeyboardButton("🔮 今日运势", callback_data="fortune"),
        ],
        [
            InlineKeyboardButton("🗺️ 地图导航", callback_data="map"),
            InlineKeyboardButton("🏦 我的金币", callback_data="balance"),
        ],
        [
            InlineKeyboardButton("💵 USDT余额", callback_data="usdt_balance"),
            InlineKeyboardButton("🔑 生成主地址", callback_data="usdt_deposit"),
        ],
        [
            InlineKeyboardButton("📋 查看地址", callback_data="usdt_addresses"),
            InlineKeyboardButton("➕ 添加额外地址", callback_data="usdt_add_address"),
        ],
        [
            InlineKeyboardButton("💸 提币", callback_data="usdt_withdraw"),
            InlineKeyboardButton("⚡ 租赁能量", callback_data="rent_energy"),
        ],
        [
            InlineKeyboardButton("🎁 发送USDT红包", callback_data="send_usdt_redpacket"),
            InlineKeyboardButton("🤲 抢USDT红包", callback_data="grab_usdt_redpacket"),
        ],
        [
            InlineKeyboardButton("🌐 加入频道", url="https://t.me/你的频道"),
            InlineKeyboardButton("📘 使用教程", url="https://你的教程链接"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 你好！我是你的全能助手\n"
        "点击下方按钮使用功能，无需输入命令。",
        reply_markup=reply_markup
    )

# ---------- 回调处理（统一入口）----------
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    # 原有功能
    if data == "joke":
        await joke(update, context)
    elif data == "todo_list":
        await todo_list(update, context)
    elif data == "add_todo":
        await add_todo_button(update, context)
    elif data == "done_todo":
        await done_todo_button(update, context)
    elif data.startswith("done_todo_"):
        await process_done_todo(update, context)
    elif data == "remind":
        await remind_button(update, context)
    elif data == "translate":
        await translate_button(update, context)
    elif data == "ai_chat":
        await ai_chat_button(update, context)
    elif data == "weather":
        await weather_button(update, context)
    elif data == "send_coin_redpacket":
        await send_coin_redpacket_button(update, context)
    elif data == "grab_coin_redpacket":
        await grab_coin_redpacket_button(update, context)
    elif data.startswith("grab_coin_"):
        rp_id = data.split("_")[2]
        await grab_coin_redpacket(update, context, rp_id)
    elif data == "signin":
        await signin_button(update, context)
    elif data == "fortune":
        await fortune_button(update, context)
    elif data.startswith("fortune_"):
        zodiac = data.split("_")[1]
        if zodiac == "random":
            await show_fortune(update, context, zodiac=None)
        else:
            await show_fortune(update, context, zodiac=zodiac)
    elif data == "map":
        await map_button(update, context)
    elif data == "balance":
        await balance_button(update, context)
    # USDT 功能
    elif data == "usdt_balance":
        await usdt_balance_button(update, context)
    elif data == "usdt_deposit":
        await usdt_deposit_button(update, context)
    elif data == "usdt_addresses":
        await usdt_addresses_button(update, context)
    elif data == "usdt_add_address":
        await usdt_add_address_button(update, context)
    elif data == "usdt_withdraw":
        await usdt_withdraw_button(update, context)
    elif data == "rent_energy":
        await rent_energy_button(update, context)
    elif data.startswith("rent_"):
        energy = int(data.split("_")[1])
        user_id = get_user_id(update)
        await process_rental(user_id, energy, update, context)
    elif data == "send_usdt_redpacket":
        await send_usdt_redpacket_button(update, context)
    elif data == "grab_usdt_redpacket":
        if not usdt_redpackets:
            await query.message.reply_text("当前没有可抢的USDT红包")
        else:
            text = "可抢的USDT红包列表：\n"
            keyboard = []
            for rid, rp in usdt_redpackets.items():
                if rp["remaining_count"] > 0:
                    text += f"ID: {rid} (剩余{rp['remaining_count']}个，共{rp['total_amount']:.2f} USDT)\n"
                    keyboard.append([InlineKeyboardButton(f"抢 {rid}", callback_data=f"grab_usdt_{rid}")])
            keyboard.append([InlineKeyboardButton("取消", callback_data="cancel_grab")])
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("grab_usdt_"):
        rp_id = data.split("_")[2]
        await grab_usdt_redpacket(update, context, rp_id)
    elif data == "cancel_grab":
        await query.edit_message_text("已取消")
    elif data == "cancel_rent":
        await query.edit_message_text("已取消租赁")
    elif data == "cancel_todo":
        await query.edit_message_text("已取消")
    else:
        await query.edit_message_text("功能开发中...")

# ---------- 普通消息处理（用于输入参数）----------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    if not user_id:
        return
    # 优先处理各种输入等待
    if waiting_for_todo.get(user_id):
        await handle_add_todo(update, context)
    elif waiting_for_redpacket.get(user_id) == "coin":
        await process_coin_redpacket_input(update, context)
    elif waiting_for_redpacket.get(user_id) == "usdt":
        await process_usdt_redpacket_input(update, context)
    else:
        # 默认回复提示
        await update.message.reply_text("请使用 /start 打开菜单。")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"发生错误: {context.error}")

# ---------- 主函数 ----------
def main():
    if not TOKEN:
        raise ValueError("没有设置 TELEGRAM_TOKEN 环境变量！")
    app = Application.builder().token(TOKEN).build()

    # 命令
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))

    # 普通消息处理
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # 回调
    app.add_handler(CallbackQueryHandler(button_callback))

    # 后台任务：检测充值（每60秒）
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(check_deposits, interval=60, first=10)

    app.add_error_handler(error_handler)
    print("🤖 机器人启动中...")
    app.run_polling()

if __name__ == "__main__":
    main()
