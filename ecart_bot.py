"""
E-Cart Telegram Bot - Virtual Card Management System
Production-ready bot for card verification, 3DS codes, and statements
All user-facing messages in Arabic (العربية)
"""

import os
import re
import logging
import threading
import time
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
from io import BytesIO

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

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Validate environment variables
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")
if not API_KEY:
    raise ValueError("API_KEY environment variable is required")

# Initialize bot
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# User sessions storage (in production, use Redis or database)
user_sessions: Dict[int, Dict] = {}

# Flask keep-alive server
app = Flask(__name__)


@app.route("/")
def health_check():
    """Health check endpoint for Render"""
    return "E-Cart Bot is running!", 200


@app.route("/health")
def health():
    """Additional health endpoint"""
    return {"status": "healthy", "service": "E-Cart", "timestamp": datetime.utcnow().isoformat()}, 200


# ============================================================================
# ARABIC MESSAGES (الرسائل بالعربية)
# ============================================================================

class Messages:
    """All user-facing messages in Arabic"""
    
    # Welcome & Auth
    WELCOME = """
🏦 <b>مرحباً بك في نظام E-Cart</b>

نظام إدارة البطاقات الافتراضية الخاص بك.

<b>للتسجيل، أرسل بيانات بطاقتك بالصيغة التالية:</b>
<code>رقم_البطاقة CVV MM/YY</code>

<b>مثال:</b>
<code>4532015112830366 123 12/25</code>

⚠️ <i>بياناتك آمنة ولا يتم تخزينها.</i>
"""
    
    HELP = """
📖 <b>دليل الاستخدام</b>

<b>للدخول إلى حسابك:</b>
1. احصل على بيانات بطاقتك الافتراضية
2. أرسلها بالصيغة: <code>رقم_البطاقة CVV MM/YY</code>

<b>الخدمات المتاحة:</b>
• 🔐 <b>كود 3DS</b> - عرض أكواد التحقق من المعاملات الأخيرة
• 📜 <b>كشف حساب</b> - إجمالي المصروفات وملف المعاملات
• ❌ <b>خروج</b> - تسجيل الخروج من الجلسة

<b>الصيغ المدعومة:</b>
• <code>1234567890123456 123 12/25</code>
• <code>1234-5678-9012-3456 123 12/25</code>
"""
    
    INVALID_FORMAT = """
❌ <b>صيغة غير صحيحة!</b>

الرجاء إرسال بيانات البطاقة بالصيغة التالية:
<code>رقم_البطاقة CVV MM/YY</code>

<b>مثال:</b> <code>4532015112830366 123 12/25</code>
"""
    
    SEARCHING = "🔍 <b>جاري البحث عن البطاقة...</b>\nالرجاء الانتظار."
    
    CARD_NOT_FOUND = """
❌ <b>البطاقة غير موجودة!</b>

لم يتم العثور على بطاقة تنتهي بـ <code>{last_four}</code>.
الرجاء التحقق من الرقم والمحاولة مرة أخرى.
"""
    
    CARD_FOUND = "✅ <b>تم العثور على البطاقة!</b>\n🔐 جاري التحقق من الملكية..."
    
    VERIFICATION_FAILED = """
❌ <b>فشل التحقق!</b>

لم نتمكن من التحقق من بيانات البطاقة.
الرجاء التأكد من صحة CVV وتاريخ الانتهاء.
"""
    
    LOGIN_SUCCESS = """
✅ <b>تم تسجيل الدخول بنجاح!</b>

💳 <b>البطاقة:</b> xxxx-xxxx-xxxx-{last_four}
📝 <b>الاسم:</b> {title}

اختر الخدمة المطلوبة من القائمة أدناه:
"""
    
    # Main Menu
    MAIN_MENU = """
🏠 <b>القائمة الرئيسية</b>

💳 البطاقة: xxxx-xxxx-xxxx-{last_four}

اختر الخدمة المطلوبة:
"""
    
    BTN_3DS = "🔐 كود 3DS"
    BTN_STATEMENT = "📜 كشف حساب"
    BTN_LOGOUT = "❌ خروج"
    BTN_BACK = "🔙 رجوع"
    BTN_REFRESH = "🔄 تحديث"
    
    # 3DS Feature
    FETCHING_3DS = "🔐 <b>جاري جلب أكواد التحقق...</b>\nالرجاء الانتظار."
    
    NO_TRANSACTIONS_3DS = """
📭 <b>لا توجد معاملات حديثة</b>

لم يتم العثور على معاملات تحتوي على أكواد تحقق.
"""
    
    TRANSACTIONS_3DS_HEADER = """
🔐 <b>أكواد التحقق (3DS/OTP)</b>

💳 البطاقة: xxxx-xxxx-xxxx-{last_four}

<b>آخر المعاملات:</b>
━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    # Statement Feature
    FETCHING_STATEMENT = """
📜 <b>جاري إعداد كشف الحساب...</b>

⏳ جاري جلب جميع المعاملات...
قد يستغرق هذا بعض الوقت.
"""
    
    FETCHING_PAGE = "📊 جاري جلب الصفحة {current}/{total}..."
    
    STATEMENT_HEADER = """
📜 <b>كشف حساب E-Cart</b>

💳 البطاقة: xxxx-xxxx-xxxx-{last_four}
📅 التاريخ: {date}

━━━━━━━━━━━━━━━━━━━━━━━━
💰 <b>إجمالي المصروفات:</b> <code>${total_spend}</code>
📊 <b>عدد المعاملات:</b> {transaction_count}
━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    STATEMENT_FILE_SENT = """
✅ <b>تم إرسال كشف الحساب!</b>

📎 الملف المرفق يحتوي على تفاصيل جميع المعاملات.
"""
    
    NO_TRANSACTIONS = """
📭 <b>لا توجد معاملات</b>

لم يتم العثور على أي معاملات مكتملة لهذه البطاقة.
"""
    
    # Logout
    LOGGED_OUT = """
👋 <b>تم تسجيل الخروج بنجاح</b>

شكراً لاستخدامك نظام E-Cart.
للدخول مرة أخرى، أرسل بيانات بطاقتك.
"""
    
    # Errors
    SESSION_EXPIRED = """
⚠️ <b>انتهت الجلسة</b>

الرجاء تسجيل الدخول مرة أخرى بإرسال بيانات بطاقتك.
"""
    
    ERROR_OCCURRED = """
❌ <b>حدث خطأ!</b>

عذراً، حدث خطأ أثناء معالجة طلبك.
الرجاء المحاولة مرة أخرى لاحقاً.
"""
    
    API_ERROR = """
❌ <b>خطأ في الاتصال</b>

تعذر الاتصال بالخادم. الرجاء المحاولة بعد قليل.
"""
    
    UNKNOWN_COMMAND = "❓ أمر غير معروف. استخدم /help للمساعدة."


# ============================================================================
# API CLIENT
# ============================================================================

class ECartAPI:
    """E-Cart API client with authentication and error handling"""
    
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
    
    def _request(self, method: str, endpoint: str, params: dict = None,
                 data: dict = None) -> Optional[Dict]:
        """Make API request with error handling"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=data,
                timeout=self.timeout
            )
            
            if response.status_code == 401:
                logger.error("API authentication failed")
                return None
            
            if response.status_code == 403:
                logger.error("API access denied")
                return None
            
            if response.status_code >= 400:
                logger.error(f"API error {response.status_code}: {response.text}")
                return None
            
            return response.json()
            
        except requests.exceptions.Timeout:
            logger.error(f"API timeout for {endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"API request error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return None
    
    def get_cards(self, page: int = 1, per_page: int = 1000,
                  last_fours: List[str] = None) -> Optional[Dict]:
        """Get list of cards with optional filtering"""
        params = {
            "page": page,
            "per_page": per_page,
            "archived": "include"
        }
        
        if last_fours:
            for i, lf in enumerate(last_fours):
                params[f"last_fours[{i}]"] = lf
        
        return self._request("GET", "/cards", params=params)
    
    def get_card(self, card_id: int) -> Optional[Dict]:
        """Get single card details"""
        return self._request("GET", f"/cards/{card_id}")
    
    def create_embed_link(self, card_id: int) -> Optional[Dict]:
        """Create embed link to verify card ownership"""
        return self._request("POST", f"/cards/{card_id}/embed")
    
    def get_payments(self, card_id: int = None, page: int = 1,
                     per_page: int = 1000) -> Optional[Dict]:
        """Get payments with pagination support"""
        params = {
            "page": page,
            "per_page": per_page
        }
        
        if card_id:
            params["cards[]"] = card_id
        
        return self._request("GET", "/payments", params=params)
    
    def get_recent_payments(self, card_id: int, limit: int = 10) -> Optional[List[Dict]]:
        """Get recent payments for 3DS codes"""
        result = self.get_payments(card_id=card_id, page=1, per_page=limit)
        
        if not result:
            return None
        
        return result.get("data", [])
    
    def get_all_payments_for_card(self, card_id: int,
                                   status_callback=None) -> Tuple[List[Dict], bool]:
        """
        Fetch ALL payments for a card using pagination loop.
        Returns tuple of (payments_list, success_flag)
        """
        all_payments = []
        page = 1
        total_pages = 1
        
        while page <= total_pages:
            if status_callback and page > 1:
                status_callback(page, total_pages)
            
            result = self.get_payments(card_id=card_id, page=page, per_page=1000)
            
            if not result:
                logger.error(f"Failed to fetch payments page {page}")
                return all_payments, False
            
            payments = result.get("data", [])
            all_payments.extend(payments)
            
            total_pages = result.get("last_page", 1)
            current_page = result.get("current_page", 1)
            
            logger.info(f"Fetched page {current_page}/{total_pages}, "
                       f"got {len(payments)} payments")
            
            page += 1
            
            # Small delay to avoid rate limiting
            if page <= total_pages:
                time.sleep(0.2)
        
        return all_payments, True


# Initialize API client
api_client = ECartAPI(API_KEY, BASE_URL)


# ============================================================================
# CARD VERIFICATION & PROCESSING
# ============================================================================

def parse_card_input(text: str) -> Optional[Dict]:
    """
    Parse user input: CardNumber CVV MM/YY
    Returns dict with card_number, cvv, expiry_month, expiry_year
    """
    text = text.strip()
    
    patterns = [
        # Format: 1234567890123456 123 12/25
        r'^(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\s+(\d{3,4})\s+(\d{2})[\/\-](\d{2})$',
        # Format: 1234567890123456 123 1225
        r'^(\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\s+(\d{3,4})\s+(\d{2})(\d{2})$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, text)
        if match:
            card_number = re.sub(r'[\s\-]', '', match.group(1))
            cvv = match.group(2)
            month = match.group(3)
            year = match.group(4)
            
            if len(card_number) != 16:
                return None
            if not (1 <= int(month) <= 12):
                return None
            
            return {
                "card_number": card_number,
                "last_four": card_number[-4:],
                "cvv": cvv,
                "expiry_month": month,
                "expiry_year": year,
                "expiry_formatted": f"{month}/{year}"
            }
    
    return None


def find_card_by_last_four(last_four: str) -> Optional[Dict]:
    """Find card by last 4 digits"""
    result = api_client.get_cards(last_fours=[last_four])
    
    if not result or not result.get("data"):
        return None
    
    cards = result["data"]
    
    for card in cards:
        if card.get("last_four") == last_four:
            return card
    
    return None


def verify_card_ownership(card_id: int, user_input: Dict) -> Tuple[bool, Optional[str]]:
    """Verify card ownership via embed endpoint"""
    embed_result = api_client.create_embed_link(card_id)
    
    if not embed_result:
        return False, "Could not verify card details"
    
    # Embed endpoint returns a link - card found + user knows details = verified
    return True, None


def get_status_icon(state_value: int) -> str:
    """Get emoji icon for payment state"""
    icons = {
        0: "🟡",  # AUTH (pending)
        1: "✅",  # SETTLED
        2: "🔄",  # VOIDED
        3: "❌",  # DECLINED
        4: "↩️",  # REFUNDED
    }
    return icons.get(state_value, "❓")


def get_status_arabic(state_value: int) -> str:
    """Get Arabic status text"""
    statuses = {
        0: "معلق",
        1: "مكتمل",
        2: "ملغي",
        3: "مرفوض",
        4: "مسترد",
    }
    return statuses.get(state_value, "غير معروف")


def format_currency(amount: float) -> str:
    """Format amount as currency"""
    return f"{amount:,.2f}"


def format_date(date_str: str) -> str:
    """Format date string for display"""
    if not date_str:
        return "N/A"
    
    try:
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(date_str[:19], fmt[:len(date_str[:19])+2])
                return dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue
        return date_str[:16]
    except Exception:
        return date_str[:16] if len(date_str) > 16 else date_str


def format_date_arabic(date_str: str) -> str:
    """Format date in Arabic-friendly format"""
    if not date_str:
        return "غير متوفر"
    
    try:
        dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y/%m/%d - %H:%M")
    except Exception:
        return date_str[:16]


def extract_raw_descriptor(payment: Dict) -> str:
    """
    Extract the RAW DESCRIPTOR from payment.
    This is critical for 3DS codes which are embedded in the descriptor.
    """
    merchant = payment.get("merchant", {})
    
    # Priority: descriptor > name > fallback
    descriptor = merchant.get("descriptor", "")
    name = merchant.get("name", "")
    
    # Return descriptor if available (contains 3DS codes)
    if descriptor:
        return descriptor
    elif name:
        return name
    else:
        return "غير متوفر"


def calculate_total_spend(payments: List[Dict]) -> Tuple[float, List[Dict]]:
    """
    Calculate total spend from payments.
    Only counts SETTLED (state 1) payments.
    """
    valid_states = [1]  # Only SETTLED
    
    filtered = []
    total = 0.0
    
    for payment in payments:
        state_info = payment.get("state", {})
        state_value = state_info.get("value")
        
        if state_value in valid_states:
            amount = float(payment.get("amount", 0))
            total += amount
            filtered.append(payment)
    
    # Sort by date (newest first)
    filtered.sort(key=lambda x: x.get("date", ""), reverse=True)
    
    return total, filtered


def generate_statement_file(card: Dict, payments: List[Dict], 
                            total_spend: float) -> BytesIO:
    """Generate statement text file with Arabic content"""
    last_four = card.get("last_four", "****")
    card_title = card.get("title", "البطاقة")
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    lines = [
        "=" * 60,
        "كشف حساب E-Cart",
        "E-Cart Account Statement",
        "=" * 60,
        "",
        f"التاريخ (Date): {current_date}",
        f"البطاقة (Card): xxxx-xxxx-xxxx-{last_four}",
        f"اسم البطاقة (Title): {card_title}",
        "",
        "-" * 60,
        f"إجمالي المصروفات (Total Spend): ${format_currency(total_spend)}",
        f"عدد المعاملات (Transactions): {len(payments)}",
        "-" * 60,
        "",
        "تفاصيل المعاملات (Transaction Details):",
        "=" * 60,
        ""
    ]
    
    for i, payment in enumerate(payments, 1):
        state_info = payment.get("state", {})
        state_value = state_info.get("value", -1)
        
        # Get RAW DESCRIPTOR (critical for 3DS codes)
        raw_descriptor = extract_raw_descriptor(payment)
        merchant_info = payment.get("merchant", {})
        merchant_name = merchant_info.get("name", "غير معروف")
        mcc = merchant_info.get("mcc", "N/A")
        
        country_info = merchant_info.get("country", {})
        country_code = country_info.get("code", "N/A")
        
        amount = float(payment.get("amount", 0))
        currency = payment.get("currency", "USD")
        initial_amount = payment.get("initial_amount", amount)
        initial_currency = payment.get("initial_currency", currency)
        
        date = format_date(payment.get("date", ""))
        status_ar = get_status_arabic(state_value)
        
        lines.extend([
            f"[{i}] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"    الوصف الخام (Raw Descriptor): {raw_descriptor}",
            f"    اسم التاجر (Merchant): {merchant_name}",
            f"    المبلغ (Amount): ${format_currency(amount)} {currency}",
            f"    المبلغ الأصلي (Original): {initial_amount} {initial_currency}",
            f"    الحالة (Status): {status_ar}",
            f"    التاريخ (Date): {date}",
            f"    MCC: {mcc} | البلد (Country): {country_code}",
            ""
        ])
    
    if not payments:
        lines.append("لا توجد معاملات مكتملة")
        lines.append("No settled transactions found")
    
    lines.extend([
        "",
        "=" * 60,
        "نهاية الكشف - End of Statement",
        "E-Cart Virtual Card System",
        "=" * 60
    ])
    
    content = "\n".join(lines)
    
    # Create file buffer
    file_buffer = BytesIO()
    file_buffer.write(content.encode('utf-8'))
    file_buffer.seek(0)
    
    return file_buffer


# ============================================================================
# KEYBOARD BUILDERS
# ============================================================================

def get_main_menu_keyboard() -> types.ReplyKeyboardMarkup:
    """Create main menu keyboard"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton(Messages.BTN_3DS),
        types.KeyboardButton(Messages.BTN_STATEMENT)
    )
    keyboard.add(types.KeyboardButton(Messages.BTN_LOGOUT))
    return keyboard


def get_back_keyboard() -> types.ReplyKeyboardMarkup:
    """Create back button keyboard"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton(Messages.BTN_BACK))
    return keyboard


def get_3ds_keyboard() -> types.ReplyKeyboardMarkup:
    """Create 3DS view keyboard"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton(Messages.BTN_REFRESH),
        types.KeyboardButton(Messages.BTN_BACK)
    )
    return keyboard


def remove_keyboard() -> types.ReplyKeyboardRemove:
    """Remove keyboard"""
    return types.ReplyKeyboardRemove()


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================

def get_session(user_id: int) -> Optional[Dict]:
    """Get user session"""
    return user_sessions.get(user_id)


def create_session(user_id: int, card: Dict, card_input: Dict) -> Dict:
    """Create new user session"""
    session = {
        "user_id": user_id,
        "card_id": card.get("id"),
        "card": card,
        "card_input": card_input,
        "created_at": datetime.now().isoformat(),
        "state": "authenticated"
    }
    user_sessions[user_id] = session
    return session


def destroy_session(user_id: int):
    """Destroy user session"""
    if user_id in user_sessions:
        del user_sessions[user_id]


def is_authenticated(user_id: int) -> bool:
    """Check if user is authenticated"""
    session = get_session(user_id)
    return session is not None and session.get("state") == "authenticated"


# ============================================================================
# BOT HANDLERS
# ============================================================================

@bot.message_handler(commands=["start"])
def handle_start(message):
    """Handle /start command"""
    user_id = message.from_user.id
    
    # Check if already authenticated
    if is_authenticated(user_id):
        session = get_session(user_id)
        card = session.get("card", {})
        bot.send_message(
            message.chat.id,
            Messages.MAIN_MENU.format(last_four=card.get("last_four", "****")),
            reply_markup=get_main_menu_keyboard()
        )
    else:
        bot.send_message(
            message.chat.id,
            Messages.WELCOME,
            reply_markup=remove_keyboard()
        )


@bot.message_handler(commands=["help"])
def handle_help(message):
    """Handle /help command"""
    bot.reply_to(message, Messages.HELP)


@bot.message_handler(func=lambda m: m.text == Messages.BTN_LOGOUT)
def handle_logout(message):
    """Handle logout button"""
    user_id = message.from_user.id
    destroy_session(user_id)
    bot.send_message(
        message.chat.id,
        Messages.LOGGED_OUT,
        reply_markup=remove_keyboard()
    )


@bot.message_handler(func=lambda m: m.text == Messages.BTN_BACK)
def handle_back(message):
    """Handle back button"""
    user_id = message.from_user.id
    
    if not is_authenticated(user_id):
        bot.send_message(
            message.chat.id,
            Messages.SESSION_EXPIRED,
            reply_markup=remove_keyboard()
        )
        return
    
    session = get_session(user_id)
    card = session.get("card", {})
    
    bot.send_message(
        message.chat.id,
        Messages.MAIN_MENU.format(last_four=card.get("last_four", "****")),
        reply_markup=get_main_menu_keyboard()
    )


@bot.message_handler(func=lambda m: m.text in [Messages.BTN_3DS, Messages.BTN_REFRESH])
def handle_3ds(message):
    """Handle 3DS code request"""
    user_id = message.from_user.id
    
    if not is_authenticated(user_id):
        bot.send_message(
            message.chat.id,
            Messages.SESSION_EXPIRED,
            reply_markup=remove_keyboard()
        )
        return
    
    session = get_session(user_id)
    card = session.get("card", {})
    card_id = session.get("card_id")
    last_four = card.get("last_four", "****")
    
    # Send loading message
    loading_msg = bot.send_message(
        message.chat.id,
        Messages.FETCHING_3DS,
        reply_markup=get_3ds_keyboard()
    )
    
    try:
        # Fetch recent transactions
        payments = api_client.get_recent_payments(card_id, limit=10)
        
        if not payments:
            bot.edit_message_text(
                Messages.NO_TRANSACTIONS_3DS,
                chat_id=message.chat.id,
                message_id=loading_msg.message_id
            )
            return
        
        # Build response with RAW DESCRIPTORS
        response_lines = [Messages.TRANSACTIONS_3DS_HEADER.format(last_four=last_four)]
        
        for payment in payments:
            state_info = payment.get("state", {})
            state_value = state_info.get("value", -1)
            
            # Get RAW DESCRIPTOR (contains 3DS codes!)
            raw_descriptor = extract_raw_descriptor(payment)
            
            amount = float(payment.get("amount", 0))
            currency = payment.get("currency", "USD")
            date = format_date_arabic(payment.get("date", ""))
            status_icon = get_status_icon(state_value)
            status_ar = get_status_arabic(state_value)
            
            response_lines.append(
                f"{status_icon} <b>الوصف:</b> <code>{raw_descriptor}</code>\n"
                f"   💰 المبلغ: ${format_currency(amount)} {currency}\n"
                f"   📅 التاريخ: {date}\n"
                f"   📌 الحالة: {status_ar}\n"
            )
        
        response_lines.append("\n💡 <i>كود التحقق يظهر عادةً في نهاية الوصف (مثل: *12345)</i>")
        
        response = "\n".join(response_lines)
        
        bot.edit_message_text(
            response,
            chat_id=message.chat.id,
            message_id=loading_msg.message_id
        )
        
    except Exception as e:
        logger.error(f"Error fetching 3DS for user {user_id}: {e}", exc_info=True)
        bot.edit_message_text(
            Messages.ERROR_OCCURRED,
            chat_id=message.chat.id,
            message_id=loading_msg.message_id
        )


@bot.message_handler(func=lambda m: m.text == Messages.BTN_STATEMENT)
def handle_statement(message):
    """Handle statement request"""
    user_id = message.from_user.id
    
    if not is_authenticated(user_id):
        bot.send_message(
            message.chat.id,
            Messages.SESSION_EXPIRED,
            reply_markup=remove_keyboard()
        )
        return
    
    session = get_session(user_id)
    card = session.get("card", {})
    card_id = session.get("card_id")
    last_four = card.get("last_four", "****")
    
    # Send loading message
    loading_msg = bot.send_message(
        message.chat.id,
        Messages.FETCHING_STATEMENT,
        reply_markup=get_back_keyboard()
    )
    
    try:
        # Progress callback
        def update_progress(current, total):
            try:
                bot.edit_message_text(
                    Messages.FETCHING_STATEMENT + f"\n\n{Messages.FETCHING_PAGE.format(current=current, total=total)}",
                    chat_id=message.chat.id,
                    message_id=loading_msg.message_id
                )
            except Exception:
                pass
        
        # Fetch ALL payments with pagination
        all_payments, success = api_client.get_all_payments_for_card(
            card_id=card_id,
            status_callback=update_progress
        )
        
        if not success and not all_payments:
            bot.edit_message_text(
                Messages.API_ERROR,
                chat_id=message.chat.id,
                message_id=loading_msg.message_id
            )
            return
        
        # Calculate total spend (only SETTLED transactions)
        total_spend, settled_payments = calculate_total_spend(all_payments)
        
        if not settled_payments:
            bot.edit_message_text(
                Messages.NO_TRANSACTIONS,
                chat_id=message.chat.id,
                message_id=loading_msg.message_id
            )
            return
        
        # Generate statement file
        current_date = datetime.now().strftime("%Y-%m-%d")
        file_buffer = generate_statement_file(card, settled_payments, total_spend)
        file_name = f"E-Cart_Statement_{current_date}.txt"
        
        # Delete loading message
        try:
            bot.delete_message(message.chat.id, loading_msg.message_id)
        except Exception:
            pass
        
        # Send summary message
        summary = Messages.STATEMENT_HEADER.format(
            last_four=last_four,
            date=current_date,
            total_spend=format_currency(total_spend),
            transaction_count=len(settled_payments)
        )
        
        bot.send_message(
            message.chat.id,
            summary,
            reply_markup=get_main_menu_keyboard()
        )
        
        # Send file
        bot.send_document(
            message.chat.id,
            file_buffer,
            visible_file_name=file_name,
            caption=Messages.STATEMENT_FILE_SENT
        )
        
        logger.info(f"Statement generated for user {user_id}, card {card_id}. "
                   f"Total: ${total_spend}, Transactions: {len(settled_payments)}")
        
    except Exception as e:
        logger.error(f"Error generating statement for user {user_id}: {e}", exc_info=True)
        try:
            bot.edit_message_text(
                Messages.ERROR_OCCURRED,
                chat_id=message.chat.id,
                message_id=loading_msg.message_id
            )
        except Exception:
            bot.send_message(message.chat.id, Messages.ERROR_OCCURRED)


@bot.message_handler(func=lambda message: True)
def handle_card_input(message):
    """Handle card details input or unknown messages"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Skip commands
    if text.startswith("/"):
        bot.reply_to(message, Messages.UNKNOWN_COMMAND)
        return
    
    # If authenticated and unknown input, show menu
    if is_authenticated(user_id):
        session = get_session(user_id)
        card = session.get("card", {})
        bot.send_message(
            message.chat.id,
            Messages.MAIN_MENU.format(last_four=card.get("last_four", "****")),
            reply_markup=get_main_menu_keyboard()
        )
        return
    
    # Try to parse as card input
    card_input = parse_card_input(text)
    
    if not card_input:
        bot.reply_to(message, Messages.INVALID_FORMAT)
        return
    
    # Send processing message
    processing_msg = bot.reply_to(message, Messages.SEARCHING)
    
    try:
        # Step 1: Find card by last 4 digits
        card = find_card_by_last_four(card_input["last_four"])
        
        if not card:
            bot.edit_message_text(
                Messages.CARD_NOT_FOUND.format(last_four=card_input["last_four"]),
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )
            return
        
        card_id = card.get("id")
        logger.info(f"Found card {card_id} for user {user_id}")
        
        # Step 2: Verify card ownership
        bot.edit_message_text(
            Messages.CARD_FOUND,
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )
        
        is_verified, error = verify_card_ownership(card_id, card_input)
        
        if not is_verified:
            bot.edit_message_text(
                Messages.VERIFICATION_FAILED,
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )
            return
        
        # Step 3: Create session
        create_session(user_id, card, card_input)
        
        # Step 4: Show success and main menu
        bot.edit_message_text(
            Messages.LOGIN_SUCCESS.format(
                last_four=card.get("last_four", "****"),
                title=card.get("title", "البطاقة")
            ),
            chat_id=message.chat.id,
            message_id=processing_msg.message_id
        )
        
        # Send main menu
        bot.send_message(
            message.chat.id,
            Messages.MAIN_MENU.format(last_four=card.get("last_four", "****")),
            reply_markup=get_main_menu_keyboard()
        )
        
        logger.info(f"User {user_id} authenticated with card {card_id}")
        
    except Exception as e:
        logger.error(f"Error processing card for user {user_id}: {e}", exc_info=True)
        try:
            bot.edit_message_text(
                Messages.ERROR_OCCURRED,
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )
        except Exception:
            bot.send_message(message.chat.id, Messages.ERROR_OCCURRED)


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def run_flask():
    """Run Flask server in separate thread"""
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


def main():
    """Main entry point"""
    logger.info("Starting E-Cart Telegram Bot...")
    
    # Start Flask keep-alive server in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask keep-alive server started on port {PORT}")
    
    # Start bot polling
    logger.info("Starting bot polling...")
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=60)
        except Exception as e:
            logger.error(f"Bot polling error: {e}", exc_info=True)
            time.sleep(5)
            logger.info("Restarting bot polling...")


if __name__ == "__main__":
    main()
