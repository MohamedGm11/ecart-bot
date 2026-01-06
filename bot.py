
import telebot
import requests
import re
from bs4 import BeautifulSoup
from io import BytesIO
from datetime import datetime
import time
from flask import Flask
from threading import Thread

# --- إعدادات السيرفر الوهمي للبقاء اونلاين ---
server = Flask(__name__)

@server.route('/')
def home():
    return "Bot is running..."

def run():
    # المنفذ 8080 هو القياسي في سيرفرات ريندر
    server.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
# ---------------------------------------------
# ================= إعدادات البوت =================
BOT_TOKEN = "7954594632:AAE4K0Fw9ALWWP5ivwFErvIo5oURG4ssucc"   # ضع التوكن الخاص بك هنا
API_KEY = "gi40KrD0alg1GKMuwMGA7Lvsv0JRO8VA2eqFlE1R1e1bce28"   # ضع مفتاح API الموقع الجديد هنا

BASE_URL = "https://private.mybrocard.com/api/v2"

if ":" not in BOT_TOKEN or "ضع_توكن" in BOT_TOKEN:
    print("❌ خطأ: تأكد من وضع التوكن ومفتاح API بشكل صحيح.")
    exit()

bot = telebot.TeleBot(BOT_TOKEN)
user_sessions = {}

# ================= دوال مساعدة =================

def call_api(method, endpoint, params=None, json_data=None):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    url = f"{BASE_URL}/{endpoint}"
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, params=params)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=json_data)
        
        if response.status_code in [200, 201]:
            return response.json()
    except Exception as e:
        print(f"API Error: {e}")
    return None

def format_date(date_str):
    if not date_str: return "N/A"
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        return str(date_str)

def get_full_card_details(card_id):
    embed_data = call_api("POST", f"cards/{card_id}/embed")
    if embed_data and 'link' in embed_data:
        try:
            page_response = requests.get(embed_data['link'])
            if page_response.status_code == 200:
                soup = BeautifulSoup(page_response.text, 'html.parser')
                
                real_pan = ""
                pan_div = soup.find("div", {"id": "pan"})
                if pan_div:
                    for span in pan_div.find_all("span"):
                        if span.get_text().strip().isdigit():
                            real_pan += span.get_text().strip()
                
                real_date = ""
                date_div = soup.find("div", {"id": "date"})
                if date_div:
                    match = re.search(r'\d{2}/\d{2}', date_div.get_text().strip())
                    if match: real_date = match.group(0)

                real_cvv = ""
                cvv_wrapper = soup.find("div", {"id": "cvv-wrapper"})
                if cvv_wrapper:
                    match_cvv = re.search(r'\d{3}', cvv_wrapper.get_text())
                    if match_cvv: real_cvv = match_cvv.group(0)
                
                return {"pan": real_pan, "date": real_date, "cvv": real_cvv}
        except: pass
    return None

# ================= معالجة الرسائل =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    msg = (
        "🔐 **نظام البطاقات**\n\n"
        "للدخول، أرسل البيانات:\n`رقم_البطاقة` مسافة `CVV` مسافة `MM/YY`"
    )
    bot.reply_to(message, msg, parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def main_handler(message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    # 1. المستخدم المسجل
    if user_id in user_sessions:
        card_id = user_sessions[user_id]
        
        if text == '🔐 كود 3DS':
            bot.reply_to(message, "🔄 جاري البحث...")
            data = call_api("GET", f"cards/{card_id}/transactions", params={"limit": 20})
            found = False
            if data and 'data' in data:
                for tx in data['data']:
                    desc = str(tx.get('description', '')).lower()
                    if any(x in desc for x in ['code', 'otp', '3ds']):
                        d_str = tx.get('created_at')
                        bot.reply_to(message, f"✅ **الكود:**\n`{tx['description']}`\n🕒 {format_date(d_str)}", parse_mode="Markdown")
                        found = True
                        break
            if not found: bot.reply_to(message, "⚠️ لم يصل الكود بعد.")

        elif text == '📜 كشف حساب':
            bot.reply_to(message, "🔄 جاري البحث في السجلات (قد يستغرق لحظات)...")
            
            all_transactions = []
            
            # === نظام البحث العميق (Pagination Loop) ===
            # نبحث في أول 5 صفحات (500 عملية) لضمان العثور على عمليات البطاقة
            for page_num in range(1, 6): 
                params = {
                    "per_page": 100,
                    "page": page_num,
                    "card[]": card_id, # محاولة الفلترة بالسيرفر أولاً (كما في المتصفح)
                    "dates[begin]": "2024-01-01"
                }
                
                response = call_api("GET", "payments", params=params)
                
                if response and 'data' in response and len(response['data']) > 0:
                    for tx in response['data']:
                        # فلترة يدوية إضافية للتأكد 100%
                        tx_card_id = tx.get('card', {}).get('id')
                        if str(tx_card_id) == str(card_id):
                            all_transactions.append(tx)
                else:
                    # إذا الصفحة فاضية، نوقف البحث
                    break
                
                # إذا جمعنا عدد كافي من العمليات (مثلا 50)، نوقف البحث لتوفير الوقت
                if len(all_transactions) >= 50:
                    break
                
                # استراحة قصيرة جداً لتخفيف الحمل
                time.sleep(0.1)

            # === العرض والترتيب ===
            if len(all_transactions) > 0:
                # إزالة التكرار (في حال تكررت العمليات)
                unique_txs = {tx['id']: tx for tx in all_transactions}.values()
                
                # الترتيب: الأحدث أولاً
                sorted_txs = sorted(unique_txs, key=lambda x: x.get('date') or "", reverse=True)
                
                report_text = f"📄 سجل المدفوعات ({len(sorted_txs)} عملية)\n"
                report_text += "="*30 + "\n"
                
                for tx in sorted_txs:
                    amt = tx.get('amount', '0')
                    curr = tx.get('currency', 'USD')
                    status = tx.get('state', {}).get('label', 'Unknown')
                    date_val = tx.get('date') 
                    date_display = format_date(date_val)
                    
                    merchant = tx.get('merchant', {})
                    merchant_name = merchant.get('name', 'Unknown')
                    descriptor = merchant.get('descriptor', '')
                    display_desc = descriptor if descriptor else merchant_name
                    
                    status_icon = "✅" if status == "Settled" else "⏳" if status == "Pending" else "❌"
                    
                    report_text += f"{status_icon} {display_desc}\n"
                    report_text += f"💰 {amt} {curr} | 📅 {date_display}\n"
                    report_text += "-"*30 + "\n"
                
                if len(report_text) > 4000:
                    file_obj = BytesIO(report_text.encode('utf-8'))
                    today_str = datetime.now().strftime("%Y-%m-%d")
                    file_obj.name = f"E-Cart_Statement_{card_id}_{today_str}.txt"
                    bot.send_document(message.chat.id, file_obj, caption="✅ E-Cart: السجل كامل في الملف.")
                else:
                    bot.reply_to(message, report_text)
            else:
                bot.reply_to(message, "📭 لا توجد عمليات لهذه البطاقة (تم البحث في آخر 500 عملية).")

        elif text == '❌ خروج':
            del user_sessions[user_id]
            bot.reply_to(message, "تم تسجيل الخروج.", reply_markup=telebot.types.ReplyKeyboardRemove())
        return

    # 2. تسجيل الدخول
    match = re.search(r'(\d{15,16})\s+(\d{3,4})\s+(\d{2}/\d{2})', text)
    if match:
        input_pan, input_cvv, input_date = match.groups()
        wait_msg = bot.reply_to(message, "⏳ جاري التحقق...")
        
        cards = call_api("GET", "cards", params={"limit": 100})
        verified_id = None
        
        if cards and 'data' in cards:
            for card in cards['data']:
                if (card.get('last_four') or card.get('last_digits')) == input_pan[-4:]:
                    real = get_full_card_details(card['id'])
                    if real and real['pan'] == input_pan and real['cvv'] == input_cvv and real['date'] == input_date:
                        verified_id = card['id']
                        break
        
        bot.delete_message(message.chat.id, wait_msg.message_id)
        
        if verified_id:
            user_sessions[user_id] = verified_id
            markup = telebot.types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
            markup.add('🔐 كود 3DS', '📜 كشف حساب', '❌ خروج')
            bot.reply_to(message, "✅ تم الدخول بنجاح!", reply_markup=markup)
        else:
            bot.reply_to(message, "⛔ البيانات غير صحيحة.")
    else:
        bot.reply_to(message, "⚠️ الصيغة: `رقم` `CVV` `MM/YY`", parse_mode="Markdown")

print("Bot is running...")
keep_alive()  # تشغيل السيرفر الوهمي
print("Bot is running...")
bot.infinity_polling()