"""
E-Cart Telegram Bot - Virtual Card Management System
Simplified version - displays transactions directly in chat
All user-facing messages in Arabic (العربية)
"""

import os
import re
import logging
import threading
import time
import sys
from datetime import datetime
from typing import Optional, Dict, List, Tuple

import telebot
from telebot import types
import requests
from flask import Flask

# ============================================================================
# CONFIGURATION
# ============================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_KEY = os.environ.get("API_KEY")
PORT = int(os.environ.get("PORT", 8080))

BASE_URL = "https://private.mybrocard.com/api/v2"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is required")
    sys.exit(1)
if not API_KEY:
    logger.error("API_KEY environment variable is required")
    sys.exit(1)

# Initialize bot (threaded=False to avoid conflicts)
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=False)

# User sessions
user_sessions: Dict[int, Dict] = {}

# Flask keep-alive
app = Flask(__name__)


@app.route("/")
def health_check():
    return "E-Cart Bot is running!", 200


@app.route("/health")
def health():
    return {"status": "healthy", "service": "E-Cart"}, 200


# ============================================================================
# CLEAR WEBHOOK (FIX 409 ERROR)
# ============================================================================

def clear_webhook_and_updates():
    """Clear webhook and pending updates to fix 409 conflict error"""
    try:
        logger.info("Clearing webhook and pending updates...")
        bot.delete_webhook(drop_pending_updates=True)
        time.sleep(1)
        
        try:
            updates = bot.get_updates(offset=-1, timeout=1)
            if updates:
                last_update_id = updates[-1].update_id
                bot.get_updates(offset=last_update_id + 1, timeout=1)
        except:
            pass
        
        logger.info("Webhook cleared successfully")
        return True
    except Exception as e:
        logger.error(f"Error clearing webhook: {e}")
        return False


# ============================================================================
# ARABIC MESSAGES
# ============================================================================

class Messages:
    WELCOME = """
🏦 <b>مرحباً بك في نظام E-Cart</b>

<b>للتسجيل، أرسل بيانات بطاقتك:</b>
<code>رقم_البطاقة CVV MM/YY</code>

<b>مثال:</b>
<code>4532015112830366 123 12/25</code>
"""
    
    HELP = """
📖 <b>دليل الاستخدام</b>

أرسل بيانات بطاقتك بالصيغة:
<code>رقم_البطاقة CVV MM/YY</code>

<b>الخدمات:</b>
• 🔐 كود 3DS - أكواد التحقق
• 📜 كشف حساب - المعاملات والإجمالي
"""
    
    INVALID_FORMAT = """
❌ <b>صيغة غير صحيحة!</b>

أرسل البيانات بالصيغة:
<code>رقم_البطاقة CVV MM/YY</code>

مثال: <code>4532015112830366 123 12/25</code>
"""
    
    SEARCHING = "🔍 جاري البحث..."
    
    CARD_NOT_FOUND = "❌ البطاقة غير موجودة! تأكد من الرقم."
    
    VERIFICATION_FAILED = "❌ فشل التحقق من البطاقة."
    
    LOGIN_SUCCESS = """
✅ <b>تم تسجيل الدخول!</b>

💳 البطاقة: xxxx-xxxx-xxxx-{last_four}
"""
    
    MAIN_MENU = "🏠 اختر الخدمة:"
    
    BTN_3DS = "🔐 كود 3DS"
    BTN_STATEMENT = "📜 كشف حساب"
    BTN_LOGOUT = "❌ خروج"
    BTN_BACK = "🔙 رجوع"
    BTN_REFRESH = "🔄 تحديث"
    
    FETCHING = "⏳ جاري التحميل..."
    
    NO_TRANSACTIONS = "📭 لا توجد معاملات."
    
    LOGGED_OUT = "👋 تم تسجيل الخروج. أرسل بيانات البطاقة للدخول مجدداً."
    
    SESSION_EXPIRED = "⚠️ انتهت الجلسة. أرسل بيانات البطاقة."
    
    ERROR = "❌ حدث خطأ. حاول مرة أخرى."


# ============================================================================
# API CLIENT
# ============================================================================

class ECartAPI:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        self.timeout = 30
    
    def _request(self, method: str, endpoint: str, params: dict = None) -> Optional[Dict]:
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method=method, url=url, params=params, timeout=self.timeout)
            if response.status_code >= 400:
                logger.error(f"API error {response.status_code}")
                return None
            return response.json()
        except Exception as e:
            logger.error(f"API error: {e}")
            return None
    
    def get_cards(self, last_fours: List[str] = None) -> Optional[Dict]:
        params = {"page": 1, "per_page": 100, "archived": "include"}
        if last_fours:
            for i, lf in enumerate(last_fours):
                params[f"last_fours[{i}]"] = lf
        return self._request("GET", "/cards", params=params)
    
    def create_embed_link(self, card_id: int) -> Optional[Dict]:
        return self._request("POST", f"/cards/{card_id}/embed")
    
    def get_payments(self, card_id: int, page: int = 1, per_page: int = 100) -> Optional[Dict]:
        params = {"page": page, "per_page": per_page, "cards[]": card_id}
        return self._request("GET", "/payments", params=params)
    
    def get_all_payments(self, card_id: int, callback=None) -> Tuple[List[Dict], bool]:
        """Fetch ALL payments with pagination"""
        all_payments = []
        page = 1
        total_pages = 1
        
        while page <= total_pages:
            if callback and page > 1:
                callback(page, total_pages)
            
            result = self.get_payments(card_id=card_id, page=page, per_page=1000)
            if not result:
                return all_payments, False
            
            payments = result.get("data", [])
            all_payments.extend(payments)
            total_pages = result.get("last_page", 1)
            page += 1
            
            if page <= total_pages:
                time.sleep(0.2)
        
        return all_payments, True


api_client = ECartAPI(API_KEY, BASE_URL)


# ============================================================================
# HELPERS
# ============================================================================

def parse_card_input(text: str) -> Optional[Dict]:
    text = text.strip()
    patterns = [
        r'^(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\s+(\d{3,4})\s+(\d{2})[\/\-](\d{2})$',
        r'^(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\s+(\d{3,4})\s+(\d{2})(\d{2})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, text)
        if match:
            card_number = re.sub(r'[\s\-]', '', match.group(1))
            if len(card_number) != 16:
                return None
            month = match.group(3)
            if not (1 <= int(month) <= 12):
                return None
            return {
                "card_number": card_number,
                "last_four": card_number[-4:],
                "cvv": match.group(2),
                "expiry": f"{month}/{match.group(4)}"
            }
    return None


def find_card(last_four: str) -> Optional[Dict]:
    result = api_client.get_cards(last_fours=[last_four])
    if not result or not result.get("data"):
        return None
    for card in result["data"]:
        if card.get("last_four") == last_four:
            return card
    return None


def format_date(date_str: str) -> str:
    if not date_str:
        return "N/A"
    try:
        dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y/%m/%d - %H:%M")
    except:
        return date_str[:16]


def get_raw_descriptor(payment: Dict) -> str:
    """Get RAW DESCRIPTOR - contains 3DS codes"""
    merchant = payment.get("merchant", {})
    return merchant.get("descriptor") or merchant.get("name") or "N/A"


def get_status_icon(state: int) -> str:
    return {0: "🟡", 1: "✅", 2: "🔄", 3: "❌", 4: "↩️"}.get(state, "❓")


# ============================================================================
# KEYBOARDS
# ============================================================================

def main_menu_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(types.KeyboardButton(Messages.BTN_3DS), types.KeyboardButton(Messages.BTN_STATEMENT))
    kb.add(types.KeyboardButton(Messages.BTN_LOGOUT))
    return kb


def back_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(types.KeyboardButton(Messages.BTN_REFRESH), types.KeyboardButton(Messages.BTN_BACK))
    return kb


def remove_kb():
    return types.ReplyKeyboardRemove()


# ============================================================================
# SESSION
# ============================================================================

def get_session(user_id: int) -> Optional[Dict]:
    return user_sessions.get(user_id)


def create_session(user_id: int, card: Dict):
    user_sessions[user_id] = {"card_id": card.get("id"), "card": card}


def destroy_session(user_id: int):
    user_sessions.pop(user_id, None)


def is_logged_in(user_id: int) -> bool:
    return user_id in user_sessions


# ============================================================================
# HANDLERS
# ============================================================================

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    if is_logged_in(msg.from_user.id):
        bot.send_message(msg.chat.id, Messages.MAIN_MENU, reply_markup=main_menu_kb())
    else:
        bot.send_message(msg.chat.id, Messages.WELCOME, reply_markup=remove_kb())


@bot.message_handler(commands=["help"])
def cmd_help(msg):
    bot.reply_to(msg, Messages.HELP)


@bot.message_handler(func=lambda m: m.text == Messages.BTN_LOGOUT)
def btn_logout(msg):
    destroy_session(msg.from_user.id)
    bot.send_message(msg.chat.id, Messages.LOGGED_OUT, reply_markup=remove_kb())


@bot.message_handler(func=lambda m: m.text == Messages.BTN_BACK)
def btn_back(msg):
    if not is_logged_in(msg.from_user.id):
        bot.send_message(msg.chat.id, Messages.SESSION_EXPIRED, reply_markup=remove_kb())
        return
    bot.send_message(msg.chat.id, Messages.MAIN_MENU, reply_markup=main_menu_kb())


@bot.message_handler(func=lambda m: m.text in [Messages.BTN_3DS, Messages.BTN_REFRESH])
def btn_3ds(msg):
    """Show recent transactions with RAW DESCRIPTOR for 3DS codes"""
    user_id = msg.from_user.id
    
    if not is_logged_in(user_id):
        bot.send_message(msg.chat.id, Messages.SESSION_EXPIRED, reply_markup=remove_kb())
        return
    
    session = get_session(user_id)
    card_id = session["card_id"]
    last_four = session["card"].get("last_four", "****")
    
    loading = bot.send_message(msg.chat.id, Messages.FETCHING, reply_markup=back_kb())
    
    try:
        result = api_client.get_payments(card_id, page=1, per_page=10)
        
        if not result or not result.get("data"):
            bot.edit_message_text(Messages.NO_TRANSACTIONS, msg.chat.id, loading.message_id)
            return
        
        payments = result["data"]
        
        # Build simple response
        lines = [
            f"🔐 <b>آخر المعاملات</b>",
            f"💳 xxxx-xxxx-xxxx-{last_four}",
            "━━━━━━━━━━━━━━━━━━━━━━",
            ""
        ]
        
        for p in payments:
            state = p.get("state", {}).get("value", -1)
            icon = get_status_icon(state)
            descriptor = get_raw_descriptor(p)
            amount = p.get("amount", "0")
            currency = p.get("currency", "USD")
            date = format_date(p.get("date", ""))
            
            lines.append(f"{icon} <code>{descriptor}</code>")
            lines.append(f"   💰 ${amount} {currency}")
            lines.append(f"   📅 {date}")
            lines.append("")
        
        lines.append("💡 <i>كود التحقق في نهاية الوصف مثل: *12345</i>")
        
        bot.edit_message_text("\n".join(lines), msg.chat.id, loading.message_id)
        
    except Exception as e:
        logger.error(f"3DS error: {e}")
        bot.edit_message_text(Messages.ERROR, msg.chat.id, loading.message_id)


@bot.message_handler(func=lambda m: m.text == Messages.BTN_STATEMENT)
def btn_statement(msg):
    """Show all transactions with total spend - directly in chat"""
    user_id = msg.from_user.id
    
    if not is_logged_in(user_id):
        bot.send_message(msg.chat.id, Messages.SESSION_EXPIRED, reply_markup=remove_kb())
        return
    
    session = get_session(user_id)
    card_id = session["card_id"]
    last_four = session["card"].get("last_four", "****")
    
    loading = bot.send_message(msg.chat.id, "📜 جاري جلب جميع المعاملات...", reply_markup=back_kb())
    
    try:
        def update_progress(current, total):
            try:
                bot.edit_message_text(f"📜 جاري جلب الصفحة {current}/{total}...", msg.chat.id, loading.message_id)
            except:
                pass
        
        all_payments, success = api_client.get_all_payments(card_id, callback=update_progress)
        
        if not all_payments:
            bot.edit_message_text(Messages.NO_TRANSACTIONS, msg.chat.id, loading.message_id)
            return
        
        # Calculate total (only settled - state 1)
        total_spend = 0.0
        settled = []
        
        for p in all_payments:
            if p.get("state", {}).get("value") == 1:
                total_spend += float(p.get("amount", 0))
                settled.append(p)
        
        # Sort by date (newest first)
        settled.sort(key=lambda x: x.get("date", ""), reverse=True)
        
        # Delete loading message
        try:
            bot.delete_message(msg.chat.id, loading.message_id)
        except:
            pass
        
        # Send summary
        summary = f"""📜 <b>كشف الحساب</b>

💳 xxxx-xxxx-xxxx-{last_four}
📅 {datetime.now().strftime("%Y/%m/%d")}

━━━━━━━━━━━━━━━━━━━━━━
💰 <b>إجمالي المصروفات:</b> <code>${total_spend:,.2f}</code>
📊 <b>عدد المعاملات:</b> {len(settled)}
━━━━━━━━━━━━━━━━━━━━━━"""
        
        bot.send_message(msg.chat.id, summary, reply_markup=main_menu_kb())
        
        # Send transactions in chunks (to avoid message too long)
        chunk_size = 15
        for i in range(0, len(settled), chunk_size):
            chunk = settled[i:i + chunk_size]
            
            lines = []
            for p in chunk:
                icon = get_status_icon(p.get("state", {}).get("value", -1))
                descriptor = get_raw_descriptor(p)
                amount = p.get("amount", "0")
                currency = p.get("currency", "USD")
                date = format_date(p.get("date", ""))
                
                lines.append(f"{icon} <code>{descriptor}</code>")
                lines.append(f"   💰 ${amount} {currency} | 📅 {date}")
                lines.append("")
            
            if lines:
                bot.send_message(msg.chat.id, "\n".join(lines))
                time.sleep(0.3)  # Avoid flood
        
        logger.info(f"Statement for user {user_id}: ${total_spend:.2f}, {len(settled)} transactions")
        
    except Exception as e:
        logger.error(f"Statement error: {e}")
        bot.send_message(msg.chat.id, Messages.ERROR, reply_markup=main_menu_kb())


@bot.message_handler(func=lambda m: True)
def handle_text(msg):
    """Handle card input or unknown text"""
    user_id = msg.from_user.id
    text = msg.text.strip()
    
    if text.startswith("/"):
        return
    
    # If logged in, show menu
    if is_logged_in(user_id):
        bot.send_message(msg.chat.id, Messages.MAIN_MENU, reply_markup=main_menu_kb())
        return
    
    # Try parse as card
    card_input = parse_card_input(text)
    if not card_input:
        bot.reply_to(msg, Messages.INVALID_FORMAT)
        return
    
    loading = bot.reply_to(msg, Messages.SEARCHING)
    
    try:
        card = find_card(card_input["last_four"])
        
        if not card:
            bot.edit_message_text(Messages.CARD_NOT_FOUND, msg.chat.id, loading.message_id)
            return
        
        # Verify ownership
        embed = api_client.create_embed_link(card["id"])
        if not embed:
            bot.edit_message_text(Messages.VERIFICATION_FAILED, msg.chat.id, loading.message_id)
            return
        
        # Create session
        create_session(user_id, card)
        
        bot.edit_message_text(
            Messages.LOGIN_SUCCESS.format(last_four=card.get("last_four", "****")),
            msg.chat.id, loading.message_id
        )
        
        bot.send_message(msg.chat.id, Messages.MAIN_MENU, reply_markup=main_menu_kb())
        
        logger.info(f"User {user_id} logged in with card {card['id']}")
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        bot.edit_message_text(Messages.ERROR, msg.chat.id, loading.message_id)


# ============================================================================
# MAIN
# ============================================================================

def run_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


def main():
    logger.info("=" * 50)
    logger.info("Starting E-Cart Bot...")
    logger.info("=" * 50)
    
    # Fix 409 error
    clear_webhook_and_updates()
    
    # Start Flask
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask started on port {PORT}")
    
    # Start polling
    logger.info("Starting bot polling...")
    
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(10)
            clear_webhook_and_updates()
            logger.info("Restarting...")


if __name__ == "__main__":
    main()
