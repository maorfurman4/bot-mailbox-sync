"""בדיקות קצרות: python test_mail.py (בלי רשת, בלי Gmail)"""
import os

os.environ.setdefault("DRY_RUN", "1")
import sync_script as m  # noqa: E402

# כתובת השולח מתוך כותרת From
assert m.sender_of('"AliExpress" <ae-msg-notify01@deals.aliexpress.com>') == "ae-msg-notify01@deals.aliexpress.com"
assert m.sender_of("Info@Wolt.com") == "info@wolt.com"

# חסימה: דומיין תופס תת-דומיינים, אבל לא דומיין שרק מכיל את השם
assert m.is_blocked("messages-noreply@linkedin.com")
assert m.is_blocked("noreply@buynotice.alibaba.com")
assert m.is_blocked("aeug-member-benefits29@deals.aliexpress.com")
assert not m.is_blocked("account@notice.aliexpress.com")  # קודי אימות ושינוי סיסמה
assert not m.is_blocked("me@notlinkedin.com")

# הגנה: לפי שולח או לפי נושא
assert m.is_protected("inbal_shahar@mod.gov.il", "אגף השיקום")
assert m.is_protected("aryehlayani426@gmail.com", "דוח ניסוי")
assert m.is_protected("no-reply@accounts.example.com", "Security alert")
assert m.is_protected("account@notice.aliexpress.com", "Your AliExpress Account Password Has Been Changed")
assert m.is_protected("x@shop.com", "חשבונית עבור הזמנתך")
assert not m.is_protected("news@shop.com", "מבצע סוף עונה")

# פרסומת לפי חוק: "פרסומת" בתחילת או בסוף הנושא (חשבונית ש"מכילה דבר פרסומת" באמצע — לא)
assert m.is_ad("פרסומת | אזור מכירת חיסול") and m.is_ad("הבחירה עליכם – הקאשבק עלינו. פרסומת")
assert not m.is_ad("חשבונית מחברת אמישראגז - מכיל דבר פרסומת 26641800 מספר צרכן")

# ההחלטה הסופית: אבטחה > חסימה > פרסומת > הגנה > AI
assert m.decide("messages-noreply@linkedin.com", "LinkedIn digest", "other") == "block"
assert m.decide("security@mail.instagram.com", "New login to Instagram", "junk") == "security"  # אבטחה עוברת חסימה
assert m.decide("security@mail.instagram.com", "Username changed on Instagram", "junk") == "security"  # לפי השולח
assert m.decide("no-reply@mail.instagram.com", "see more in your feed", "other") == "block"
assert m.decide("info@max-finance.co.il", "הבחירה עליכם – הקאשבק עלינו. פרסומת", "junk") == "junk"  # מוגן, אבל פרסומת
assert m.decide("noreply@openai.com", "Your API credit balance has $3.00 remaining", "junk") == "other"
assert m.decide("inbal_shahar@mod.gov.il", "אגף השיקום", "other") == "important"
assert m.decide("sms@afeka.ac.il", "x", "junk") == "other"  # מוגן
assert m.decide("news@shop.com", "מבצע", "junk") == "junk"
assert m.decide("noreply@meiavivim.co.il", "חשבון מים תקופתי", "bill") == "bill"
assert m.decide("store@carrefour.co.il", "שובר מתנה", "coupon") == "coupon"
assert m.decide("x@shop.com", "y", "nonsense") == "other"  # קטגוריה לא מוכרת — לא נוגעים

# קישור תשלום: רק לאתר של השולח או לסולק מוכר, ורק אם באמת מופיע במייל
body = "לתשלום: https://pay.meiavivim.co.il/bill?id=1 או https://evil.example/pay"
assert m.safe_pay_link("https://pay.meiavivim.co.il/bill?id=1", "noreply@meiavivim.co.il", body)
assert not m.safe_pay_link("https://evil.example/pay", "noreply@meiavivim.co.il", body)
assert not m.safe_pay_link("https://pay.meiavivim.co.il/other", "noreply@meiavivim.co.il", body)  # לא במייל
assert m.safe_pay_link("https://secure.tranzila.com/x", "invoice@amisragas.co.il", "https://secure.tranzila.com/x")
assert not m.safe_pay_link("לא נמצא", "a@b.co.il", body)

# תאריך יעד לתשלום
assert m.parse_due("05/11/2026") == "2026-11-05"
assert m.parse_due("לא צוין") is None and m.parse_due(None) is None


# ביטול הרשמה: רק One-Click רשמי (RFC 8058)
h = {"List-Unsubscribe": "<mailto:u@x.com>, <https://x.com/u?id=1>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
assert m.one_click_url(h) == "https://x.com/u?id=1"
assert m.one_click_url({"List-Unsubscribe": "<https://x.com/u>"}) is None  # בלי One-Click — לא נוגעים
assert m.one_click_url({}) is None

# 🏷️ חוקים לפני AI — שולח מוכר או מיון של Gmail, בלי לשלם על טוקנים
assert m.known_category("notifications@github.com", "PR #51", []) == "dev"
assert m.known_category("sms@afeka.ac.il", "יום הבחירות", []) == "studies"
assert m.known_category("googleplay-noreply@google.com", "Order Receipt", []) == "bill"
assert m.known_category("no-reply@accounts.google.com", "Security alert", []) is None  # google.com כללי — לא bill
assert m.known_category("info@wolt.com", "קבלת רכישה", []) == "bill"
assert m.known_category("noreply@bookaflight.co.il", "ההזמנה שלך", []) == "orders"
assert m.known_category("news@shop.com", "מבצע", ["CATEGORY_PROMOTIONS"]) == "junk"  # Gmail כבר מיין
assert m.known_category("info@max-finance.co.il", "x", ["CATEGORY_PROMOTIONS"]) == "bill"  # מוכר גובר
assert m.known_category("news@bank.co.il", "חשבונית", ["CATEGORY_PROMOTIONS"]) is None  # מוגן — שואלים AI
assert m.known_category("someone@shop.com", "hello", ["CATEGORY_UPDATES"]) is None

# 📥 איפה כל סוג נשאר: (תווית, נשאר בתיבה?)
assert m.placement("important") == ("📬 חשוב", True)
assert m.placement("bill", paid=False) == ("🧾 חשבונות", True)
assert m.placement("bill", paid=True) == ("🧾 חשבונות", False)
assert m.placement("studies") == ("🎓 לימודים", True)
assert m.placement("security") == ("🔐 אבטחה", True)
assert m.placement("dev") == ("💻 פיתוח", False)
assert m.placement("orders") == ("✈️ הזמנות ונסיעות", False)
assert m.placement("coupon") == ("🎟️ קופונים", False)
assert m.placement("other") == ("📁 כללי", False)

# קריאת AI אחת לכמה מיילים — תשובה חלקית או שגויה לא מפילה כלום
assert m.parse_batch({"results": [{"i": 0, "category": "dev"}, {"i": 2, "category": "junk"}, {"i": 9, "category": "x"}]}, 3) == {
    0: "dev", 2: "junk"}
assert m.parse_batch({}, 2) == {}

# שחזור מהפח: מוגן, לא פרסומת
assert m.should_rescue("noreply@openai.com", "Your OpenAI API credit balance has $3.00 remaining")
assert not m.should_rescue("info@max-finance.co.il", "הבחירה עליכם – הקאשבק עלינו. פרסומת")
assert not m.should_rescue("news@shop.com", "מבצע")

print("ok")
