# -*- coding: utf-8 -*-
"""
================================================
   Telegram 全能机器人 - 乐天USDT
   功能：广告按钮 + 帮助信息
   部署说明：
     1. 确保 Railway 环境变量中设置：
        - TELEGRAM_TOKEN（必填）
     2. 确保 requirements.txt 包含：
        python-telegram-bot>=21.10
        aiohttp>=3.10.5
     3. 在 Railway 的 Settings 中设置 Start Command 为：
        python bot.py
     4. 部署后，向机器人发送 /start 即可使用。
================================================
"""
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# 启用日志
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ========== 环境变量 ==========
TOKEN = os.getenv("TELEGRAM_TOKEN")

# ========== 辅助函数 ==========
def get_user_id(update: Update) -> int:
    if update.effective_user:
        return update.effective_user.id
    elif update.callback_query and update.callback_query.from_user:
        return update.callback_query.from_user.id
    return None

# ========== 主菜单（广告按钮） ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 使用 Markdown 格式化欢迎文字
    welcome_text = (
        "*乐天USDT —— 您的全能支付管家*\n\n"
        "我们以全行业USDT充值为基石，\n"
        "以自动化代付为效率引擎，为您构建*安全、稳定、*\n"
        "*极速的一站式金融体验*。\n\n"
        "🌟 *行业先锋，为效率而生。*\n\n"
        "🔥 诚招商户，代理加盟，\n"
        "与我们共同“助跑”世界杯，共赢全球机遇！\n\n"
        "👇 *点击下方商户跳转对应频道/群组* 👇"
    )
    
    keyboard = [
        # 第一行：新闻频道（单个按钮，居中）
        [InlineKeyboardButton("📰 天游国际", url="https://t.me/tianyouguoji")],
        # 两列广告按钮
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
         InlineKeyboardButton("天游国际", url="https://t.me/example18")],
        [InlineKeyboardButton("乐天USDT", url="https://t.me/ltusdt888"),
         InlineKeyboardButton("乐天USDT", url="https://t.me/ltusdt888")],
        [InlineKeyboardButton("乐天USDT", url="https://t.me/ltusdt888"),
         InlineKeyboardButton("乐天USDT", url="https://t.me/ltusdt888")],
        [InlineKeyboardButton("乐天USDT", url="https://t.me/ltusdt888")],
        # 功能按钮（帮助 + 客服）
        [InlineKeyboardButton("📖 帮助", callback_data="help"),
         InlineKeyboardButton("📞 联系客服", url="https://t.me/letianUSDT")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)

# ========== 回调处理 ==========
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "help":
        help_text = (
            "📖 *帮助信息*\n\n"
            "• 点击上方广告按钮可直接跳转对应频道/群组。\n"
            "• 如需联系客服，请点击「📞 联系客服」。\n"
            "• 有任何问题，欢迎随时反馈。"
        )
        await query.edit_message_text(help_text, parse_mode="Markdown")
    else:
        await query.edit_message_text("功能开发中...")

# ========== 普通消息处理 ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 除命令外，其他消息统一提示使用 /start
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
