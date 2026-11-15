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
assert m.known_category("couriers@mail.wolt.com", "רוצים לטוס למונדיאל 2026?!", []) is None  # שולח קבלות, אבל לא קבלה
assert m.known_category("noreply@dominos.co.il", "החשבונית שלך מדומינו'ס", []) is None  # לא מוכר → AI
assert m.known_category("noreply@bookaflight.co.il", "ההזמנה שלך", []) == "orders"
assert m.known_category("news@shop.com", "מבצע", ["CATEGORY_PROMOTIONS"]) == "junk"  # Gmail כבר מיין
assert m.known_category("info@max-finance.co.il", "פירוט חיובים חודשי", ["CATEGORY_PROMOTIONS"]) == "bill"  # מוכר גובר
assert m.known_category("info@max-finance.co.il", "x", ["CATEGORY_PROMOTIONS"]) is None  # בלי מילות קבלה, ומוגן → AI
assert m.known_category("news@bank.co.il", "חשבונית", ["CATEGORY_PROMOTIONS"]) is None  # מוגן — שואלים AI
assert m.known_category("someone@shop.com", "hello", ["CATEGORY_UPDATES"]) is None
assert m.known_category("aryehlayani426@gmail.com", "(ללא נושא)", []) == "important"  # אנשים פרטיים
assert m.decide("donotreply@digital.gov.il", "מכשיר חדש נקשר לחשבונך", "important") == "security"

# 📥 איפה כל סוג נשאר: (תווית, נשאר בתיבה?)
assert m.placement("important") == ("📬 חשוב", True)
assert m.placement("bill", paid=False) == ("🧾 חשבונות", True)
assert m.placement("bill", paid=True) == ("🧾 חשבונות", False)
assert m.placement("studies") == ("🎓 לימודים", True)
assert m.placement("waiting") == ("⏳ ממתין לתשובה", True)
assert m.placement("security") == ("🔐 אבטחה", True)
assert m.placement("dev") == ("💻 פיתוח", False)
assert m.placement("orders") == ("✈️ הזמנות ונסיעות", False)
assert m.placement("coupon") == ("🎟️ קופונים", False)
assert m.placement("other") == ("📁 כללי", False)

# ⌛ פג תוקף → לפח: כל מה שבאבטחה ובפיתוח אחרי יום; דיוור מערכת של אפקה אחרי יומיים
assert m.EXPIRY_DAYS == {"security": 1, "dev": 1, "studies": 2}
assert m.is_expired("security", "Your Vercel security code: 448014", "system@vercel.com")
assert m.is_expired("security", "Security alert", "no-reply@accounts.google.com")
assert m.is_expired("dev", "Preview deployment failed for amiret-prep", "notifications@vercel.com")
assert m.is_expired("studies", "יום הבחירות 27.10", "sms@afeka.ac.il")
assert m.is_expired("studies", "x", "afekais.do.not.reply@afeka.ac.il")
assert not m.is_expired("studies", "דוח ניסוי 5", "aryeh.layani@s.afeka.ac.il")  # סטודנט — אדם פרטי
assert not m.is_expired("studies", "'[EXTERNAL] - '", "ramie@afeka.ac.il")      # מרצה שכותב אישית
assert not m.is_expired("studies", "היי מאור", "help@limudnaim.co.il")          # לא אפקה
assert not m.is_expired("important", "x", "sms@afeka.ac.il")

# דיוור מערכת של אפקה → ישר לארכיון; אנשים מאפקה נשארים בתיבה
assert m.is_afeka_system("sms@afeka.ac.il") and m.is_afeka_system("targilim@afeka.ac.il")
assert m.is_afeka_system("helpdesk@afeka.ac.il") and not m.is_afeka_system("batia@afeka.ac.il")
assert m.is_afeka_system("teachingbox@afeka.ac.il") and m.is_afeka_system("learning@afeka.ac.il")  # TeachingBox — לא צריך
assert m.placement("studies", address="sms@afeka.ac.il") == ("🎓 לימודים", False)
assert m.placement("studies", address="ramie@afeka.ac.il") == ("🎓 לימודים", True)

# שיחה שענית בה — לא נמחקת ולא "ממתינה לתשובה"
assert m.i_replied([["INBOX"], ["SENT"]]) and not m.i_replied([["INBOX"], ["INBOX", "UNREAD"]])

# ⏳ ממתין לתשובה — רק אדם אמיתי, לא מערכת
assert m.is_person("gash69@gmail.com", "Re:") and m.is_person("inbal_shahar@mod.gov.il", "בוצר לידור")
assert not m.is_person("do_not_reply@maccabi4u.org.il", "x") and not m.is_person("noreply@electiontraining.co.il", "x")
assert not m.is_person("harelinsurance@harel-group.co.il", "הדוח התקופתי שלך בפנסיה")  # שולח עסקי
assert not m.is_person("info@payme.io", "רכישה בוצעה בהצלחה")
assert not m.is_person("inbal_shahar@mod.gov.il", "מענה אוטומטי: אגף השיקום")  # תשובה אוטומטית

# קריאת AI אחת לכמה מיילים — תשובה חלקית או שגויה לא מפילה כלום
assert m.parse_batch({"results": [{"i": 0, "category": "dev"}, {"i": 2, "category": "junk"}, {"i": 9, "category": "x"}]}, 3) == {
    0: "dev", 2: "junk"}
assert m.parse_batch({}, 2) == {}

# 🔀 מיזוג התוויות שלך: מה שה-AI חשב לזבל לא נמחק (רק פרסומת מסומנת או שולח חסום)
assert m.merge_action("junk", "סיכום חודש מאי") == "other"
assert m.merge_action("junk", "פרסומת | מבצע") == "junk"
assert m.merge_action("block", "x") == "block" and m.merge_action("bill", "x") == "bill"
assert m.MERGE_LABELS == ["חיובים[", "split", "הזמנות", "קופוננים קארפור", "רודוס", "הנדסת חשמל", "עוסק פטור", "חשוב", "קופונים"]

# שולחים מוכרים שה-AI פספס
assert m.known_category("service@10bis.co.il", "הזמנת משלוח משופרסל - כלל ארצי", []) is None  # הזמנה, לא חשבון → AI
assert m.known_category("service@10bis.co.il", "חשבונית עבור הזמנתך", []) == "bill"
assert m.known_category("hello@splitwise.com", "'ועד בית 3 חודשים' (₪750.00) added by Maxim a.", []) == "bill"
assert m.known_category("hello@splitwise.com", "Amit Hooberman paid you ₪133.33", []) == "bill"
assert m.known_category("info@payme.io", "רכישה 107059544 בוצעה בהצלחה", []) == "bill"
assert m.known_category("donotreply@pango.co.il", "פרטי עסקת פנגו בחניון", []) == "bill"
assert m.known_category("carmelton@printernet.co.il", "החשבונית החודשית שלך ממנהרות הכרמל", []) == "bill"

# מיקום: מייל חדש שעקף את התיבה בפילטר ישן — חשבון פתוח חוזר לתיבה; במיזוג/סידור ישן לא נוגעים במיקום
assert m.inbox_change(True, ["Label_x"], move=True) == ("INBOX", None)
assert m.inbox_change(False, ["INBOX"], move=True) == (None, "INBOX")
assert m.inbox_change(True, ["INBOX"], move=True) == (None, None)
assert m.inbox_change(False, ["INBOX"], move=False) == (None, None)

# 🏠 Splitwise → "לשלם למקסים — <מה> <החלק שלי> ₪" (לא הסכום הכולל; המיילים האמיתיים מ-30/10/2026)
internet = ("'אינטרנט ' (₪135.00) added by Maxim a.",
            "Hey Maor! Maxim just added “אינטרנט ” to the group “Bulbulim”. October 30, 2026 General אינטרנט "
            "Total: ₪135.00 You owe ₪45.00 View on Splitwise")
power = ("'חשמל ' (₪903.00) added by Maxim a.", "Total: ₪903.00 You owe ₪301.00")
assert m.parse_splitwise(*internet) == ("אינטרנט", "מקסים", 45.0)
assert m.parse_splitwise(*power) == ("חשמל", "מקסים", 301.0)
assert m.parse_splitwise("'ועד בית 3 חודשים' (₪750.00) added by Maxim a.", "You owe ₪1,250.50")[2] == 1250.5
assert m.parse_splitwise("'פיצה' (₪120.00) added by Maxim a.", "Total: ₪120.00 You are owed ₪80.00") is None
assert m.parse_splitwise("Amit Hooberman paid you ₪133.33 on Splitwise", "") is None
assert m.parse_splitwise("Your balance for October", "You owe ₪346.00") is None
assert m.parse_splitwise("'אוכל שישי' (₪649.00) updated by Maxim a.", "You owe ₪200.00") is None
assert m.parse_splitwise("'גז' (₪90.00) added by Amit H.", "no share line")[1:] == ("Amit", None)  # → AI כגיבוי
assert m.fmt(45.0) == "45" and m.fmt(45.5) == "45.5"

# 💸 הוצאות עסק: ספק לפי דומיין + נושא של קבלה; סכום לפי כללים
assert m.business_vendor("noreply@tm.openai.com", "Your OpenAI API account has been funded")[0] == "OpenAI"
assert m.business_vendor("noreply@tm.openai.com", "Your OpenAI API credit balance has $3.00 remaining") is None
assert m.business_vendor("invoice+statements@mail.anthropic.com", "Your receipt from Anthropic, PBC #2195-1239-9910")[:2] == \
    ("Anthropic", "מנוי Claude")
assert m.business_vendor("billing@vercel.com", "Your Vercel invoice")[2] == "🎯 AMIRNET"
assert m.business_vendor("billing@vercel.com", "Payment failed") is None
assert m.business_vendor("shop@wolt.com", "Your receipt") is None  # לא ספק עסקי
assert m.parse_amount("We charged $10.00 to your credit card ending in 3814") == (10.0, "$")
assert m.parse_amount("Receipt from Anthropic, PBC $85.88 Paid on October 24 ... Max plan $100.00 ... Amount paid $85.88") == (85.88, "$")
assert m.parse_amount("סה\"כ לתשלום ₪ 1,200.00") == (1200.0, "₪")
assert m.parse_amount("no money here") is None

# 🧾 חשבונית ב-PDF: ה-PDF עובר להתחלה (אחרת נחתך ב-3000 תווים — מנהרות הכרמל 11/2026); סכום שלא בטקסט — "לא צוין"
mail_part = "החשבונית החודשית שלך מצורפת " + "(Link: https://nmall.printernet.co.il/x) " * 80
body = mail_part + "\n--- PDF (a.pdf) --- סה\"כ כולל מע\"מ 24.16 לא לתשלום"
src = m.bill_text(body)
assert src.startswith("--- PDF") and "24.16" in src and len(src) <= 3000
assert m.bill_text("רק מייל, בלי PDF") == "רק מייל, בלי PDF"
assert m.amount_in_text("24.16", src)
assert m.amount_in_text("24.16", "סהכ 61.42")  # עברית מ-PDF מתהפכת — גם המספר
assert not m.amount_in_text("96", src) and not m.amount_in_text("לא צוין", src)
assert m.amount_in_text("96", "סכום 96.00 ₪")


from datetime import date  # noqa: E402

# ── הסכום הכולל לפי כללים (8.11: 10bis — ה-AI לקח "11" מ"קומה 11"); שורות אמיתיות מ-PyPDF2, בלי פרטים אישיים ──
tenbis = "\n".join(["ןיגב םחנמ ךרד  146 המוק ןואט ילאירזע ,ביבא לת  11 .  דוקימ  6492103",  # הכתובת — לא הסכום
                    'רואית תומכ ריחמ הס "כ', "יצרא ללכ - לסרפוש הדעסממ הנמזה רובע םולשת 1 2.0",
                    'כ"הס 1.69', 'מ"עמ 0.31', 'םולשתל כ"הס 2.0', ":הגופת ךיראת  05/30"])
assert m.total_amount(tenbis) == (2.0, "₪")  # 'סה"כ לתשלום' הפוך — לא 1.69 (לפני מע"מ), לא 11
wolt = "\n".join(["Apple Pay  75.60", "דמי תפעול 18% 1  3.60  3.60", '(סה"כ בש"ח )כולל מע״מ  75.60',
                   'סך נטומע"מ סה"כ', '18% מע"מ  64.07  11.53  75.60', 'ש"ח  16.00  :Wolt+ סך החסכון'])
assert m.total_amount(wolt) == (75.6, "₪")
pappi = '(סה"כ בש"ח )כולל מע״מ  65.10\n18% מע"מ  55.17  9.93  65.102 / 2ש"ח  16.00  :Wolt+ סך החסכון'
assert m.total_amount(pappi) == (65.1, "₪")
assert m.total_amount('סה"כ ILS 75.60 75.60 מסמכי ההזמנה') == (75.6, "₪")  # תקציר המייל של Wolt
assert m.total_amount("Amount paid $85.88 ... Subtotal $100.00") == (85.88, "$")
assert m.total_amount("Subtotal 50.00") is None and m.total_amount("") is None
assert m.issue_date("תאריך הפקה 20:56  06.11.2026") == date(2026, 11, 6)
assert m.issue_date(":ךיראת  07/11/2026 :העש  07:53:04\n:הגופת ךיראת  05/30") == date(2026, 11, 7)
assert m.issue_date("05/30 only") is None
# → בוט הכספים: "וולט · פאפי פסטה"; סוד נגזר מהטוקן; בלי טוקן — כלום
assert m.vendor_label("info@wolt.com", "פאפי פסטה") == "וולט · פאפי פסטה"
assert m.vendor_label("service@10bis.co.il", "תן ביס") == "תן ביס" and m.vendor_label("a@b.com", "X") == "X"
posts = []
_req, _act, _tok = m.requests.post, m.act, m.FINANCE_BOT_TOKEN
m.act = lambda desc, fn, *a, **k: fn(*a, **k)
m.requests.post = lambda url, **k: posts.append((url, k)) or type("R", (), {"ok": True, "status_code": 200})()
m.FINANCE_BOT_TOKEN = ""
m.to_finance("X", 10, date(2026, 11, 6), False, "id1")
assert not posts
m.FINANCE_BOT_TOKEN = "tok"
m.to_finance("וולט · פאפי פסטה", 65.1, date(2026, 11, 6), False, "id1")
url, k = posts[-1]
import hashlib  # noqa: E402
assert url.endswith("?ingest") and k["headers"]["X-Ingest-Secret"] == hashlib.sha256(b"ingest:tok").hexdigest()[:32]
assert k["json"] == {"vendor": "וולט · פאפי פסטה", "amount": 65.1, "date": "2026-11-06", "business": False,
                     "link": m.gmail_link("id1")}
m.requests.post, m.act, m.FINANCE_BOT_TOKEN = _req, _act, _tok

# 🛒 אישור הזמנה באמזון (12.11) — אותו מבנה כמו המייל, בלי פרטים אישיים (מספר הזמנה, סכום וכתובת בדויים)
amazon = "\n".join(["Your Orders", "", "    thanks for your order!", "Ordered", "", "Shipped", "", "Out for delivery", "",
                     "Delivered", "", "Arriving November 24", "", "Order #", "111-0000000-0000001", "",
                     "View or edit order", "https://www.amazon.com/your-orders/order-details?orderID=111-0000000-0000001",
                     "", "Grand Total:", "123.45 ILS", "", "(866) 216-1075 410 Terry Avenue N., Seattle, WA 98109"])
amazon_subject = "Ordered 3 items: Electronics, Kitchen & Dining"
assert m.total_amount(amazon) == (123.45, "₪")  # "Grand Total:" ושורה אחריה — לא 866/410
assert m.total_amount("Grand Total:\n$45.00") == (45.0, "$")  # המטבע בשורה של המספר
assert m.order_number(amazon) == "111-0000000-0000001"
assert m.order_number("אישור הזמנה מספר: 778899") == "778899" and m.order_number("no order here") is None
assert m.is_order("auto-confirm@amazon.com", amazon_subject)
assert m.is_order("shop@ksp.co.il", "אישור הזמנה מספר 778899")
for subject in ("Shipped: Your Amazon order", "Out for delivery: 3 items", "Delivered: Your package", "Your refund",
                "Your order has been cancelled", "הזמנתך נשלחה"):
    assert not m.is_order("shipment-tracking@amazon.com", subject), subject
assert not m.is_order("noreply@elal.co.il", "Your order confirmation")  # טיסות — ✈️ בלי הצעה
assert not m.is_order("a@b.com", "Your flight booking — order confirmation")
assert not m.is_order("billing@vercel.com", "Your order receipt")  # הוצאת עסק — כבר נשלחת לחוד
assert m.shop_name("Amazon.com <auto-confirm@amazon.com>", "auto-confirm@amazon.com") == "Amazon"
assert m.shop_name("", "orders@ksp.co.il") == "ksp"

class FakeGmail:  # users().messages().get(...).execute() / list(...).execute()
    def __init__(self, full, done=()):
        self.full, self.done = full, list(done)
    def users(self): return self
    def messages(self): return self
    def get(self, userId, id, **k):
        return type("X", (), {"execute": lambda _s: self.full if id == "new" else next(d for d in self.done if d["id"] == id)})()
    def list(self, **k):
        return type("X", (), {"execute": lambda _s: {"messages": [{"id": d["id"]} for d in self.done]}})()

sent = []
_tf, _eb = m.to_finance, m.extract_body
m.to_finance = lambda *a: sent.append(a)
m.extract_body = lambda gmail, msg_id, payload, snippet="": amazon
mail = {"id": "new", "from": "Amazon.com <auto-confirm@amazon.com>", "sender": "auto-confirm@amazon.com",
        "subject": amazon_subject, "snippet": amazon_subject}
full = {"payload": {}, "internalDate": "1794493421000"}
assert m.handle_order(FakeGmail(full), mail)
assert sent[-1][:4] == ("Amazon · הזמנה אונליין", 123.45, date(2026, 11, 12), False)
assert not m.handle_order(FakeGmail(full), mail)  # אותו מספר הזמנה באותה ריצה — לא פעמיים
m.SEEN_ORDERS.clear()
older = {"id": "old", "internalDate": "1794400000000",
         "payload": {"headers": [{"name": "From", "value": "auto-confirm@amazon.com"}, {"name": "Subject", "value": amazon_subject}]}}
shipped = {**older, "payload": {"headers": [{"name": "From", "value": "shipment-tracking@amazon.com"},
                                            {"name": "Subject", "value": "Shipped: 3 items"}]}}
assert not m.handle_order(FakeGmail(full, [older]), mail)  # אישור קודם (ריצה קודמת) עם אותו מספר
assert m.handle_order(FakeGmail(full, [shipped]), mail)  # מייל משלוח עם המספר — לא נחשב הצעה קודמת
m.SEEN_ORDERS.clear()
m.extract_body = lambda *a, **k: "Order # 111-0000000-0000002 thanks"  # בלי סכום — אין הצעה
assert not m.handle_order(FakeGmail(full), mail)
m.to_finance, m.extract_body = _tf, _eb
m.SEEN_ORDERS.clear()
print("ok")
