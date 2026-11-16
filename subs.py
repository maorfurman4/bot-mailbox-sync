"""💳 מנויים (16.11, C3): מנוי חדש → הצעה לקבועה בבוט הכספים (✅/✖️); ⏳ תקופת ניסיון שנגמרת; 📈 עליית מחיר.
בלי סקירה חודשית. קודם הנושא (בלי AI), ורק אז gpt-4o-mini מחלץ — וסכום שלא כתוב במייל נזרק."""

import re

# נושא שנראה כמו מנוי — רק אז שואלים AI
NEW_SUB = re.compile(r"welcome to|subscription (?:is )?(?:confirmed|started|activated)|you(?:'re| are) (?:now )?subscribed|"
                     r"thanks for subscribing|your (?:\w+ )?(?:plan|membership|subscription) (?:is active|has started|starts)|"
                     r"המנוי (?:שלך )?(?:הופעל|אושר|החל)|ברוכים הבאים ל|נרשמת למנוי|הצטרפת ל", re.I)
TRIAL_END = re.compile(r"trial (?:ends|is ending|will end|expires|ending)|free trial.{0,20}(?:end|expir)|"
                       r"תקופת (?:ה)?ניסיון.{0,20}(?:מסתיימת|נגמרת|תסתיים)", re.I)
PRICE_UP = re.compile(r"price (?:change|increase|update)|(?:changes?|update) to your (?:plan|price|subscription)|"
                      r"new price|העלאת מחיר|שינוי (?:ב)?מחיר|עדכון מחיר|המחיר (?:יעלה|עולה|משתנה)", re.I)

def kind_of(subject: str) -> str | None:
    s = subject or ""
    if TRIAL_END.search(s):
        return "trial_end"
    if PRICE_UP.search(s):
        return "price_up"
    if NEW_SUB.search(s):
        return "subscription"
    return None

PROMPT = """מייל על מנוי של מאור. סוג לפי הנושא: {kind}.
נושא: {subject}
תוכן: {body}

חלץ JSON בלבד (מה שלא כתוב במייל — null, אל תנחש):
{{"service": "<שם השירות, קצר, כמו 'Netflix'>", "amount": <המחיר החודשי / החדש — מספר> או null,
"currency": "₪" או "$" או null, "old_amount": <המחיר הקודם — רק בעליית מחיר> או null,
"date": "YYYY-MM-DD — מתי נגמר הניסיון / מתי המחיר החדש נכנס / מתי החיוב הראשון" או null,
"monthly": true אם זה חיוב חודשי, false אם שנתי/חד-פעמי}}"""

def _num(x):
    try:
        return round(float(str(x).replace(",", "")), 2)
    except (TypeError, ValueError):
        return None

def in_text(amount: float, text: str) -> bool:
    """הסכום באמת כתוב במייל (לא ממציאים)."""
    plain = (text or "").replace(",", "")
    whole = f"{amount:.2f}".rstrip("0").rstrip(".")
    tail = r"0*" if "." in whole else r"(?:\.0+)?"  # "49.9" = "49.90"; "20" = "20.00" אבל לא "200"
    return bool(re.search(rf"(?<![\d.]){re.escape(whole)}{tail}(?![\d])", plain))

def extract(ask_ai, kind: str, subject: str, body: str, usd_to_ils: float) -> dict | None:
    """{"kind", "service", "amount" (₪), "old_amount" (₪), "date", "day"} או None (לא ברור / לא חודשי / סכום מומצא)."""
    got = ask_ai(PROMPT.format(kind=kind, subject=subject[:200], body=" ".join((body or "").split())[:2000]))
    if not isinstance(got, dict) or not str(got.get("service") or "").strip():
        return None
    text = f"{subject}\n{body}"
    rate = usd_to_ils if got.get("currency") == "$" else 1.0
    amount, old = _num(got.get("amount")), _num(got.get("old_amount"))
    if amount is not None and not in_text(amount, text):
        amount = None
    if old is not None and not in_text(old, text):
        old = None
    day = str(got.get("date") or "")
    date_ok = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day))
    out = {"kind": kind, "service": str(got["service"]).strip()[:40], "date": day if date_ok else None,
           "amount": round(amount * rate, 2) if amount else None, "old_amount": round(old * rate, 2) if old else None}
    if kind == "subscription":
        if not out["amount"] or got.get("monthly") is False:
            return None  # בלי מחיר חודשי — אין מה להציע כקבועה
        out["day"] = int(day[8:10]) if date_ok else None
    if kind == "price_up" and not out["amount"]:
        return None
    return out
