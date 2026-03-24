python
import os
import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# 启用日志，方便查看运行状态
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ========== 配置区域 ==========
# 从环境变量读取敏感信息（Railway 里设置）
TOKEN = os.getenv("TELEGRAM_TOKEN")          # 你第1步拿到的 Token，必须设置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # 可选，如果想用 AI 对话就去 OpenAI 官网申请
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")# 可选，用 OpenWeatherMap 申请
# ==============================

# 临时存储待办和提醒（简单版，重启会丢失，适合个人使用）
todos = {}      # {chat_id: [待办列表]}
reminders = {}  # {chat_id: [(时间, 内容)]}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 你好！我是你的全能助手\n"
        "支持以下功能：\n"
        "/ai <问题> - AI 智能问答（需配置 OpenAI）\n"
        "/weather <城市> - 查询天气\n"
        "/translate <源语言> <目标语言> <文本> - 翻译\n"
        "/todo - 查看待办\n"
        "/addtodo <内容> - 添加待办\n"
        "/donetodo <编号> - 完成待办\n"
        "/remind <秒数> <内容> - 设置提醒\n"
        "/joke - 随机笑话\n"
        "直接发送文字我也会陪你聊天（基础回复）"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ---------- AI 对话 ----------
async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OPENAI_API_KEY:
        await update.message.reply_text("⚠️ 未配置 OpenAI API Key，暂时无法使用 AI 功能。")
        return
    user_input = ' '.join(context.args) if context.args else None
    if not user_input:
        await update.message.reply_text("请用 /ai 加问题，例如：/ai 你好")
        return
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            }
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

# ---------- 天气查询 ----------
async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WEATHER_API_KEY:
        await update.message.reply_text("⚠️ 未配置天气 API Key，暂时无法查询天气。")
        return
    city = ' '.join(context.args)
    if not city:
        await update.message.reply_text("请用 /weather 城市名，例如：/weather 北京")
        return
    try:
        # 使用 OpenWeatherMap 免费 API
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

# ---------- 翻译（调用免费库，无密钥要求）----------
async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("格式：/translate 源语言 目标语言 文本，如：/translate en zh Hello")
        return
    src = args[0]
    tgt = args[1]
    text = ' '.join(args[2:])
    # 使用免费的 MyMemory 翻译 API
    url = f"https://api.mymemory.translated.net/get?q={text}&langpair={src}|{tgt}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                translated = data["responseData"]["translatedText"]
                await update.message.reply_text(f"🔤 翻译结果：{translated}")
    except Exception as e:
        await update.message.reply_text(f"翻译失败：{e}")

# ---------- 待办清单 ----------
async def todo_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_todos = todos.get(chat_id, [])
    if not user_todos:
        await update.message.reply_text("📭 暂无待办事项")
        return
    msg = "📝 你的待办清单：\n"
    for i, item in enumerate(user_todos, 1):
        msg += f"{i}. {item}\n"
    await update.message.reply_text(msg)

async def add_todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = ' '.join(context.args)
    if not text:
        await update.message.reply_text("请提供待办内容，如 /addtodo 买牛奶")
        return
    if chat_id not in todos:
        todos[chat_id] = []
    todos[chat_id].append(text)
    await update.message.reply_text(f"✅ 已添加：{text}")

async def done_todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("请提供编号，如 /donetodo 2")
        return
    try:
        idx = int(context.args[0]) - 1
        if chat_id not in todos or idx < 0 or idx >= len(todos[chat_id]):
            await update.message.reply_text("编号无效")
            return
        removed = todos[chat_id].pop(idx)
        await update.message.reply_text(f"🎉 已完成：{removed}")
    except ValueError:
        await update.message.reply_text("编号必须是数字")

# ---------- 定时提醒（后台任务）----------
async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("格式：/remind 秒数 提醒内容，如 /remind 60 开会")
        return
    try:
        delay = int(context.args[0])
        content = ' '.join(context.args[1:])
        chat_id = update.effective_chat.id
        # 创建异步任务
        asyncio.create_task(send_reminder(chat_id, content, delay, context.bot))
        await update.message.reply_text(f"⏰ 已设置提醒，{delay} 秒后告诉你：{content}")
    except ValueError:
        await update.message.reply_text("秒数必须是整数")

async def send_reminder(chat_id, content, delay, bot):
    await asyncio.sleep(delay)
    await bot.send_message(chat_id=chat_id, text=f"🔔 提醒：{content}")

# ---------- 随机笑话 ----------
async def joke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 使用免费的 jokeapi
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://v2.jokeapi.dev/joke/Any?type=single") as resp:
                data = await resp.json()
                joke_text = data.get("joke", "今天没笑话，明天再来吧～")
                await update.message.reply_text(f"😂 {joke_text}")
    except Exception:
        await update.message.reply_text("🤣 你为什么翻不过这座山？因为翻的是火锅底料！（暂时无法获取笑话，给你现编一个）")

# ---------- 普通文字回复（基础聊天）----------
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # 简单回应，可以扩展
    await update.message.reply_text(f"你说：{text}\n试试 /help 看我能做什么～")

# ---------- 错误处理 ----------
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"发生错误: {context.error}")

# ---------- 主函数 ----------
def main():
    if not TOKEN:
        raise ValueError("没有设置 TELEGRAM_TOKEN 环境变量！")
    app = Application.builder().token(TOKEN).build()
    
    # 命令
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ai", ai_chat))
    app.add_handler(CommandHandler("weather", weather))
    app.add_handler(CommandHandler("translate", translate))
    app.add_handler(CommandHandler("todo", todo_list))
    app.add_handler(CommandHandler("addtodo", add_todo))
    app.add_handler(CommandHandler("donetodo", done_todo))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(CommandHandler("joke", joke))
    # 普通消息
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
    app.add_error_handler(error_handler)
    
    print("🤖 机器人启动中...")
    app.run_polling()

if __name__ == "__main__":
    main()