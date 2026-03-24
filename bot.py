import os
import logging
import asyncio
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# 启用日志
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ========== 环境变量 ==========
TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ========== AI 对话状态 ==========
ai_mode = {}  # {user_id: True}

# ========== 辅助函数 ==========
def get_user_id(update: Update) -> int:
    if update.effective_user:
        return update.effective_user.id
    elif update.callback_query and update.callback_query.from_user:
        return update.callback_query.from_user.id
    return None

# ========== AI 对话 ==========
async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    if not OPENAI_API_KEY:
        await update.message.reply_text("⚠️ 未配置 OpenAI API Key，暂时无法使用 AI 功能。")
        return
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": query}],
                "max_tokens": 500
            }
            async with session.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers) as resp:
                data = await resp.json()
                reply = data["choices"][0]["message"]["content"]
                await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"AI 出错了：{str(e)}")

# ========== 主菜单（广告按钮） ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        # 新闻频道
        [InlineKeyboardButton("📰 天游国际", url="t.me/tianyouguoji")],
        # 娱乐城广告（可根据图片替换链接）
        [InlineKeyboardButton("天游国际", url="https://t.me/example1"),
         InlineKeyboardButton("天游国际", url="https://t.me/example2")],
        [InlineKeyboardButton("天游国际", url="https://t.me/example3"),
         InlineKeyboardButton("天游国际", url="https://t.me/example4")],
        [InlineKeyboardButton("天游国际", url="https://t.me/example5"),
         InlineKeyboardButton("天游国际", url="https://t.me/example6")],
        [InlineKeyboardButton("天游国际", url="https://t.me/example7"),
         InlineKeyboardButton("天游国际", url="https://t.me/example8")],
        [InlineKeyboardButton("天游国际", url="https://t.me/example9"),
         InlineKeyboardButton("天游国际", url="https://t.me/example10")],
        [InlineKeyboardButton("天游国际", url="https://t.me/example11"),
         InlineKeyboardButton("天游国际", url="https://t.me/example12")],
        [InlineKeyboardButton("天游国际", url="https://t.me/example13"),
         InlineKeyboardButton("天游国际", url="https://t.me/example14")],
        [InlineKeyboardButton("天游国际", url="https://t.me/example15"),
         InlineKeyboardButton("天游国际", url="https://t.me/example16")],
        [InlineKeyboardButton("天游国际", url="https://t.me/example17"),
         InlineKeyboardButton("5天游国际", url="https://t.me/example18")],
        [InlineKeyboardButton("N9国际N9.COM", url="https://t.me/example19"),
         InlineKeyboardButton("天游国际", url="https://t.me/example20")],
        [InlineKeyboardButton("2028大额出款无忧", url="https://t.me/example21"),
         InlineKeyboardButton("7T.com全球公认最稳", url="https://t.me/example22")],
        [InlineKeyboardButton("乐天USDT", url="t.me/ltusdt888")],
        # 功能按钮（AI + 客服）
        [InlineKeyboardButton("🤖 AI 对话", callback_data="ai_mode"),
         InlineKeyboardButton("📞 联系客服", url="https://t.me/letianUSDT")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
   await update.message.reply_text(
        """乐天USDT —— 您的全能支付管家
我们以全行业USDT充值为基石，
以自动化代付为效率引擎，为您构建安全、稳定、
极速的一站式金融体验。
行业先锋，为效率而生。
诚招商户，代理加盟，
与我们共同“助跑”世界杯，共赢全球机遇！
点击下方商户跳转对应频道/群组

💬 私聊我并点击「AI 对话」后，即可随意聊天，我会调用 AI 回答你。
👥 在群组中请使用 /ai 问题 来提问。""",
        reply_markup=reply_markup
    )

# ========== 回调处理（仅处理 AI 模式） ==========
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "ai_mode":
        user_id = get_user_id(update)
        if user_id:
            ai_mode[user_id] = True
            await query.edit_message_text(
                "🤖 AI 对话模式已开启！\n"
                "现在你可以直接发送任何消息，我会调用 AI 回复你。\n"
                "输入 /cancel 可退出对话模式。"
            )
    else:
        await query.edit_message_text("功能开发中...")

# ========== 普通消息处理（私聊 AI 模式 + 群组命令） ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = get_user_id(update)
    chat_type = update.effective_chat.type
    text = update.message.text.strip()

    # 处理 /cancel 命令（私聊）
    if text == "/cancel" and user_id in ai_mode:
        del ai_mode[user_id]
        await update.message.reply_text("已退出 AI 对话模式。")
        return

    # 私聊模式：如果用户处于 AI 模式，则调用 AI
    if chat_type == "private" and user_id in ai_mode:
        await ai_chat(update, context, text)
        return

    # 群组模式：仅处理 /ai 命令
    if chat_type in ["group", "supergroup"] and text.startswith("/ai"):
        query = text[4:].strip()
        if not query:
            await update.message.reply_text("请提供问题，例如 /ai 你好")
            return
        # 引用原消息回复
        await ai_chat(update, context, query)
        return

    # 其他情况：提示使用 /start
    await update.message.reply_text("请使用 /start 查看菜单。")

# ========== 错误处理 ==========
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"发生错误: {context.error}")

# ========== 主函数 ==========
def main():
    if not TOKEN:
        raise ValueError("没有设置 TELEGRAM_TOKEN 环境变量！")
    app = Application.builder().token(TOKEN).build()

    # 命令
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))

    # 普通消息
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 回调
    app.add_handler(CallbackQueryHandler(button_callback))

    app.add_error_handler(error_handler)

    print("🤖 机器人启动中...")
    app.run_polling()

if __name__ == "__main__":
    main()
