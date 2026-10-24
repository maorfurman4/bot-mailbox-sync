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
assert m.decide("messages-noreply@linkedin.com", "LinkedIn digest", "keep") == "block"
assert m.decide("security@mail.instagram.com", "New login to Instagram", "junk") == "security"  # אבטחה עוברת חסימה
assert m.decide("security@mail.instagram.com", "Username changed on Instagram", "junk") == "security"  # לפי השולח
assert m.decide("no-reply@mail.instagram.com", "see more in your feed", "keep") == "block"
assert m.decide("info@max-finance.co.il", "הבחירה עליכם – הקאשבק עלינו. פרסומת", "junk") == "junk"  # מוגן, אבל פרסומת
assert m.decide("noreply@openai.com", "Your API credit balance has $3.00 remaining", "junk") == "keep"
assert m.decide("inbal_shahar@mod.gov.il", "אגף השיקום", "keep") == "important"
assert m.decide("sms@afeka.ac.il", "הודעה לגבי עדכון ציון", "important") == "keep"  # אפקה: מוגן, בלי התראה
assert m.decide("sms@afeka.ac.il", "x", "junk") == "keep"
assert m.decide("news@shop.com", "מבצע", "junk") == "junk"
assert m.decide("noreply@meiavivim.co.il", "חשבון מים תקופתי", "bill") == "bill"
assert m.decide("store@carrefour.co.il", "שובר מתנה", "coupon") == "coupon"
assert m.decide("x@shop.com", "y", "nonsense") == "keep"  # קטגוריה לא מוכרת — לא נוגעים

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

# שעון ישראל אמיתי (חורף +02:00)
assert m.local_iso("2026-11-02", "10:00").endswith("+02:00")
assert m.local_iso("2026-10-20", "10:00").endswith("+03:00")

# ביטול הרשמה: רק One-Click רשמי (RFC 8058)
h = {"List-Unsubscribe": "<mailto:u@x.com>, <https://x.com/u?id=1>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
assert m.one_click_url(h) == "https://x.com/u?id=1"
assert m.one_click_url({"List-Unsubscribe": "<https://x.com/u>"}) is None  # בלי One-Click — לא נוגעים
assert m.one_click_url({}) is None

# שחזור מהפח: מוגן, לא פרסומת
assert m.should_rescue("noreply@openai.com", "Your OpenAI API credit balance has $3.00 remaining")
assert not m.should_rescue("info@max-finance.co.il", "הבחירה עליכם – הקאשבק עלינו. פרסומת")
assert not m.should_rescue("news@shop.com", "מבצע")

print("ok")
