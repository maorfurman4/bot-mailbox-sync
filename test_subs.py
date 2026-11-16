"""💳 C3 (16.11): מנוי חדש / ⏳ ניסיון / 📈 מחיר → בוט הכספים. בלי רשת, נתונים מומצאים. MAIL_DIR=<תיקייה> — על קוד אחר."""
import io
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.environ.get("MAIL_DIR") or os.path.dirname(os.path.abspath(__file__)))
FAILED = []
def check(name, fn):
    try:
        fn()
        print(f"✅ {name}")
    except Exception as ex:  # noqa: BLE001
        FAILED.append(name)
        print(f"❌ {name} — {type(ex).__name__}: {ex}")

def S():
    import subs
    return subs

SUBJECTS = [("Welcome to Netflix", "subscription"), ("Your subscription is confirmed", "subscription"),
            ("המנוי שלך הופעל", "subscription"), ("Your free trial ends in 3 days", "trial_end"),
            ("תקופת הניסיון שלך מסתיימת מחר", "trial_end"), ("Price change for your Spotify plan", "price_up"),
            ("עדכון מחיר המנוי", "price_up"), ("Your receipt from Netflix", None), ("שיעורי בית 3", None),
            ("Welcome to the course forum", "subscription")]
for subj, expect in SUBJECTS:
    check(f"נושא «{subj}» → {expect}", lambda subj=subj, expect=expect: None if S().kind_of(subj) == expect else (_ for _ in ()).throw(AssertionError(S().kind_of(subj))))

def ex(answer, kind="subscription", body="Your plan: 49.90 ₪ per month. First charge on 2026-11-20."):
    return S().extract(lambda p: answer, kind, "Welcome to Netflix", body, 3.7)

def new_sub():
    got = ex({"service": "Netflix", "amount": 49.9, "currency": "₪", "date": "2026-11-20", "monthly": True})
    assert got == {"kind": "subscription", "service": "Netflix", "date": "2026-11-20", "amount": 49.9, "old_amount": None, "day": 20}, got
check("מנוי חדש: שירות, מחיר חודשי ויום החיוב", new_sub)

def invented_amount_dropped():
    assert ex({"service": "Netflix", "amount": 59.9, "currency": "₪", "monthly": True}) is None  # 59.9 לא כתוב במייל
check("סכום שלא כתוב במייל → לא מציעים (לא ממציאים קבועה)", invented_amount_dropped)

def not_monthly():
    assert ex({"service": "X", "amount": 49.9, "currency": "₪", "monthly": False}) is None
    assert ex({"service": "", "amount": 49.9}) is None
check("שנתי / בלי שם שירות → לא מציעים", not_monthly)

def dollars():
    got = S().extract(lambda p: {"service": "ChatGPT", "amount": 20, "currency": "$", "monthly": True}, "subscription",
                      "Welcome to ChatGPT Plus", "You will be billed $20.00 monthly", 3.7)
    assert got["amount"] == 74.0
check("$20 → 74 ₪ (שער קבוע של הבוט)", dollars)

def trial():
    got = ex({"service": "Canva Pro", "amount": None, "date": "2026-11-19"}, kind="trial_end", body="Your trial ends on Nov 19")
    assert got["kind"] == "trial_end" and got["date"] == "2026-11-19" and got["service"] == "Canva Pro"
check("⏳ ניסיון נגמר: שירות + תאריך (גם בלי מחיר)", trial)

def price():
    got = ex({"service": "Spotify", "amount": 26.9, "old_amount": 21.9, "date": "2026-12-01"}, kind="price_up",
             body="Your price changes from 21.90 to 26.90 starting December 1")
    assert (got["amount"], got["old_amount"]) == (26.9, 21.9)
    assert ex({"service": "Spotify", "amount": None}, kind="price_up", body="prices change") is None
check("📈 מחיר: חדש וקודם (רק אם כתובים במייל)", price)

class Exec:
    def __init__(self, v): self.v = v
    def execute(self): return self.v
class FakeGmail:
    def users(self): return self
    def messages(self): return self
    def get(self, userId, id, format): return Exec({"payload": {}, "internalDate": "0"})

def flow():
    import sync_script as M
    saved = (M.ask_ai, M.requests.post, M.extract_body, M.OPENAI_API_KEY, M.FINANCE_BOT_TOKEN, M.DRY_RUN)
    posts = []
    M.ask_ai = lambda p: {"service": "Netflix", "amount": 49.9, "currency": "₪", "date": "2026-11-20", "monthly": True}
    M.requests.post = lambda url, **k: posts.append((url, k)) or type("R", (), {"ok": True, "status_code": 200})()
    M.extract_body = lambda *a, **k: "Your plan: 49.90 ₪ per month"
    M.OPENAI_API_KEY, M.FINANCE_BOT_TOKEN, M.DRY_RUN = "k", "fintok", False
    out = io.StringIO()
    try:
        with redirect_stdout(out):
            ok = M.handle_subscription(FakeGmail(), {"id": "m1", "subject": "Welcome to Netflix", "snippet": ""}, "subscription")
    finally:
        (M.ask_ai, M.requests.post, M.extract_body, M.OPENAI_API_KEY, M.FINANCE_BOT_TOKEN, M.DRY_RUN) = saved
    import hashlib
    url, k = posts[0]
    assert ok and url.endswith("?ingest") and k["headers"]["X-Ingest-Secret"] == hashlib.sha256(b"ingest:fintok").hexdigest()[:32]
    assert k["json"]["kind"] == "subscription" and k["json"]["amount"] == 49.9 and k["json"]["link"].startswith("https://mail.google.com/")
    assert "Netflix" not in out.getvalue() and "49" not in out.getvalue()  # בלוג — בלי שירות וסכום
check("זרימה: מנוי → בוט הכספים (אותו ingest וסוד), בלוג בלי שירות/סכום", flow)

def hooked():
    src = open(os.path.join(os.environ.get("MAIL_DIR") or os.path.dirname(os.path.abspath(__file__)), "sync_script.py"), encoding="utf-8").read()
    assert "subs.kind_of(mail[\"subject\"])" in src and "\"bill\")" in src  # לא על קבלות (הן כבר הולכות כחיוב)
check("מחובר למיון: על כל מייל חדש שאינו זבל/חסום/קבלה", hooked)

print("\nok" if not FAILED else f"\n{len(FAILED)} נכשלו")
sys.exit(1 if FAILED else 0)
