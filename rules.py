"""
חוקי השולחים של מנהל המייל. כתובת או דומיין; דומיין תופס גם תת-דומיינים
("linkedin.com" תופס messages-noreply@linkedin.com, "gov.il" תופס mod.gov.il).
"""

# 🚫 נחסמים תמיד: לפח + ביטול הרשמה (רק בכפתור Unsubscribe הרשמי של השולח)
BLOCK = [
    "deals.aliexpress.com",      # פרסומות עלי אקספרס (לא account@notice — שם קודי אימות)
    "alibaba.com",
    "linkedin.com",
    "facebookmail.com",
    "mail.instagram.com",
    "info.trenitalia.it",
]

# 🔐 התראות אבטחה עוברות גם שולח חסום (למשל security@mail.instagram.com)
SECURITY_SUBJECT = r"security|sign.?in|password|verif|login|new device|אבטח|סיסמ|אימות|התחברות|מכשיר חדש"
# 🎓 דיוור מערכת של אפקה — לארכיון מיד, לפח אחרי 48 שעות. אנשים (מרצים, סטודנטים ב-s.afeka.ac.il) — לא
AFEKA_SYSTEM = ["sms", "afekais.do.not.reply", "targilim", "helpdesk"]

# 🧾 שולח קבלות מוכר נחשב "חשבון" רק אם הנושא באמת נראה כמו קבלה; אחרת ה-AI מחליט (Wolt שולחים גם פרסומות)
RECEIPT_SUBJECT = r"קבל|חשבונ|חשבון|תשלום|חיוב|רכישה|עסק|הזמנ|₪|receipt|invoice|payment|refund|order|statement|paid|balance"

# ⏳ "אדם": כתובת של ספק מייל פרטי, או כתובת אישית בסגנון first.last / first_last — ולא מערכת או תשובה אוטומטית
PERSONAL_DOMAINS = ["gmail.com", "walla.co.il", "walla.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com"]
NOT_PERSON = r"reply|notif|news|service|support|system|mailer|alert|security|billing|invoice|marketing|bounce"
AUTO_REPLY_SUBJECT = r"מענה אוטומטי|auto.?reply|automatic reply|out of office"

# 🛡️ לא נמחקים לעולם, גם אם ה-AI חושב שזה זבל
PROTECT = [
    "afeka.ac.il", "gov.il", "maccabi4u.org.il", "che.org.il",
    "max-finance.co.il", "isracard.co.il", "cal-online.co.il", "leumi.co.il", "bankhapoalim.co.il",
    "discountbank.co.il", "mizrahi-tefahot.co.il",
    "meiavivim.co.il", "milgam.co.il", "amisragas.co.il", "10bis.co.il", "wolt.com",
    "github.com", "vercel.com", "openai.com", "anthropic.com", "google.com",
    "gmail.com",                 # אנשים פרטיים
]
PROTECT_SUBJECT = (
    r"security|sign.?in|password|verif|login|new device|"
    r"אבטח|סיסמ|אימות|התחברות|כניסה|חשבונית|קבלה|חשבון|תשלום|invoice|receipt"
)

# 🏷️ שולחים מוכרים — הקטגוריה נקבעת בלי AI (חוסך טוקנים). כתובת מדויקת גוברת על דומיין.
KNOWN = {
    "important": ["gov.il", "maccabi4u.org.il", "che.org.il", "gmail.com"],  # gmail.com = אנשים פרטיים
    "studies": ["afeka.ac.il"],
    "bill": ["meiavivim.co.il", "milgam.co.il", "amisragas.co.il", "max-finance.co.il", "10bis.co.il",
             "wolt.com", "googleplay-noreply@google.com", "invoice@mail.anthropic.com",
             "payme.io", "splitwise.com", "pango.co.il", "printernet.co.il"],
    "dev": ["github.com", "vercel.com", "replit.com", "supabase.com", "supabase.io", "render.com"],
    "orders": ["bookaflight.co.il", "israir.co.il", "elal-airlines.com", "elal.co.il", "gett.com",
               "autotel.co.il", "planetcinema.co.il"],
}

# 💳 קישור תשלום מוצג רק אם הוא באתר של השולח עצמו או של סולק מוכר
PAYMENT_PROCESSORS = ["tranzila.com", "cardcom.solutions", "meshulam.co.il", "payplus.co.il",
                      "icredit.co.il", "pelecard.biz", "gov.il"]
