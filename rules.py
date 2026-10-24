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

# 📬 תמיד מקבלים התראה בטלגרם
IMPORTANT = ["gov.il", "maccabi4u.org.il", "che.org.il", "afeka.ac.il"]

# 💳 קישור תשלום מוצג רק אם הוא באתר של השולח עצמו או של סולק מוכר
PAYMENT_PROCESSORS = ["tranzila.com", "cardcom.solutions", "meshulam.co.il", "payplus.co.il",
                      "icredit.co.il", "pelecard.biz", "gov.il"]
