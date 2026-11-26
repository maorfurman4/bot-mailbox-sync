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
AFEKA_SYSTEM = ["sms", "afekais.do.not.reply", "targilim", "helpdesk", "teachingbox", "learning"]

# 🧾 שולח קבלות מוכר נחשב "חשבון" רק אם הנושא באמת נראה כמו קבלה; אחרת ה-AI מחליט (Wolt שולחים גם פרסומות)
# "הזמנה/order" בכוונה לא כאן — אישור הזמנה שייך ל"הזמנות", לא ל"חשבונות"
RECEIPT_SUBJECT = r"קבל|חשבונ|חשבון|תשלום|חיוב|רכישה|עסק|₪|receipt|invoice|payment|refund|statement|paid|balance"

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

# 💸 הוצאות עסק → monday ("💼 עסקים ופרויקטים" → "💰 הכנסות והוצאות"). דומיין → (ספק, מה, פרויקט או None)
BUSINESS_VENDORS = {
    "openai.com": ("OpenAI", "טעינת קרדיט API", "🤖 בוטים בטלגרם (יוסי, חדשות)"),
    "anthropic.com": ("Anthropic", "מנוי Claude", None),
    "vercel.com": ("Vercel", "חיוב חודשי", "🎯 AMIRNET"),
    "supabase.com": ("Supabase", "חיוב חודשי", "🎯 AMIRNET"),
    "supabase.io": ("Supabase", "חיוב חודשי", "🎯 AMIRNET"),
    "render.com": ("Render", "חיוב חודשי", "🛒 בוט עלי אקספרס"),
    "namecheap.com": ("Namecheap", "דומיין", None),
    "godaddy.com": ("GoDaddy", "דומיין", None),
    "porkbun.com": ("Porkbun", "דומיין", None),
    "cloudflare.com": ("Cloudflare", "דומיין", None),
}
# קבלה אמיתית — לא "נשארו לך $3", לא "החיוב נכשל", לא "יחויב בעוד שבוע"
EXPENSE_SUBJECT = r"receipt|invoice|funded|payment|paid|קבלה|חשבונית"
NOT_EXPENSE_SUBJECT = r"remaining|failed|declined|upcoming|will be charged|trial|reminder|past due"
USD_TO_ILS = 3.4  # ברירת מחדל בלבד: כל ריצה מחליפה בשער היציג של בנק ישראל (sync_script.usd_rate); הסכום בדולרים נשמר בהערות

# 🏠 Splitwise (קבוצת הדירה): מי הוסיף את ההוצאה → למי משלמים
SPLITWISE_PAYEES = {"Maxim": "מקסים"}

# 🛒 אישור הזמנה בחנות אונליין (15.11: אמזון "Ordered 3 items: ..." נכנס ל-✈️ ולא הגיע לבוט הכספים).
# רק לפי הנושא: בגוף של אמזון יש תמיד "Shipped / Out for delivery / Delivered" (פס ההתקדמות)
ORDER_SUBJECT = (r"\bordered\b|order confirm|order received|your order|thanks for your order|thank you for your order|"
                 r"אישור הזמנה|הזמנתך|ההזמנה שלך|הזמנה מס|הזמנה התקבלה|הזמנה חדשה")
# משלוח/ביטול/החזר — אותה הזמנה, לא רכישה נוספת; טיסות והזמנות מקום — נשארות ב-✈️ בלי הצעה
NOT_ORDER_SUBJECT = (r"ship|deliver|arriv|dispatch|on the way|out for|cancel|refund|return|review|rate |feedback|"
                     r"flight|booking|hotel|reservation|נשלח|נמסר|בדרך|משלוח|בוטל|ביטול|החזר|דרג|חוות דעת|טיסה|מלון|כרטיס")
ORDER_NUMBER = r"(?:order\s*(?:#|number|no\.?)|הזמנה\s*(?:מס['׳]?|#|מספר))\s*:?\s*([A-Z0-9][A-Z0-9-]{4,})"
