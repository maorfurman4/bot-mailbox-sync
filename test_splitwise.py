"""🏠 Splitwise (16.11): החלק של מאור → בוט הכספים כהצעה (✅/✖️), בלי ➗. בלי רשת. MAIL_DIR=<תיקייה> — על קוד אחר."""
import hashlib
import io
import os
import re
import sys
from contextlib import redirect_stdout
from datetime import date

sys.path.insert(0, os.environ.get("MAIL_DIR") or os.path.dirname(os.path.abspath(__file__)))
import sync_script as M  # noqa: E402

FAILED = []
def check(name, fn):
    try:
        fn()
        print(f"✅ {name}")
    except Exception as ex:  # noqa: BLE001
        FAILED.append(name)
        print(f"❌ {name} — {type(ex).__name__}: {ex}")

POWER = ("'חשמל' (₪903.00) added by Maxim a.", "Total: ₪903.00 You owe ₪301.00 View on Splitwise")
DAY = date(2026, 11, 16)

def run(subject, text, created=True):
    posts, tele = [], []
    saved = (M.monday_add, M.telegram, M.requests.post, M.FINANCE_BOT_TOKEN, M.DRY_RUN)
    M.monday_add = lambda *a, **k: created
    M.telegram = lambda *a, **k: tele.append(a)
    M.requests.post = lambda url, **k: posts.append((url, k)) or type("R", (), {"ok": True, "status_code": 200})()
    M.FINANCE_BOT_TOKEN, M.DRY_RUN = "fintok", False
    out = io.StringIO()
    try:
        with redirect_stdout(out):
            M.handle_splitwise({"id": "m1", "subject": subject, "snippet": text}, "", DAY)
    finally:
        (M.monday_add, M.telegram, M.requests.post, M.FINANCE_BOT_TOKEN, M.DRY_RUN) = saved
    return posts, tele, out.getvalue()

def share_to_finance():
    posts, tele, log = run(*POWER)
    url, k = posts[0]
    assert url.endswith("?ingest") and k["headers"]["X-Ingest-Secret"] == hashlib.sha256(b"ingest:fintok").hexdigest()[:32]
    assert k["json"] == {"vendor": "מקסים · חשמל (החלק שלי)", "amount": 301.0, "date": "2026-11-16", "business": False,
                         "link": M.gmail_link("m1")}, k["json"]
    assert len(tele) == 1  # ההודעה בבוט הקבלות נשארת
check("«חשמל 903, you owe 301» → בוט הכספים: «מקסים · חשמל (החלק שלי)» 301 ₪ (לא 903, בלי ➗)", share_to_finance)

def not_twice():
    posts, _, _ = run(*POWER, created=False)
    assert posts == []  # כבר ב-monday (ריצה קודמת) — כבר הוצע
check("אותו מייל שוב (כבר ב-monday) → לא מציע שוב", not_twice)

def owed_to_me():
    posts, _, _ = run("'פיצה' (₪120.00) added by Maxim a.", "Total: ₪120.00 You are owed ₪80.00")
    assert posts == []
    posts, _, _ = run("Amit Hooberman paid you ₪133.33 on Splitwise", "")
    assert posts == []
check("חייבים לי / שילמו לי → לא נרשמת הוצאה", owed_to_me)

def finance_can_read_it():
    # התבנית של בוט הכספים (MAIL_RE ב-api/webhook.py) — ההצעה שלו נבנית מ-vendor + סכום + תאריך
    mail_re = re.compile(r"📧 מהמייל: (.+) · ([\d,.]+) ₪ · (\d{1,2})\.(\d{1,2})")
    m = mail_re.search("📧 מהמייל: מקסים · חשמל (החלק שלי) · 301 ₪ · 16.11")
    assert m and m.group(1) == "מקסים · חשמל (החלק שלי)" and m.group(2) == "301"
check("בוט הכספים קורא את ההצעה (שם עם « · » באמצע) — ✅ רושם 301", finance_can_read_it)

def no_token_no_post():
    saved = M.FINANCE_BOT_TOKEN
    try:
        posts = []
        M.FINANCE_BOT_TOKEN = ""
        old = M.requests.post
        M.requests.post = lambda *a, **k: posts.append(a)
        M.monday_add, M.telegram = (lambda *a, **k: True), (lambda *a, **k: None)
        with redirect_stdout(io.StringIO()):
            M.handle_splitwise({"id": "m1", "subject": POWER[0], "snippet": POWER[1]}, "", DAY)
        M.requests.post = old
        assert posts == []
    finally:
        M.FINANCE_BOT_TOKEN = saved
check("בלי FINANCE_BOT_TOKEN → לא שולח (ולא נופל)", no_token_no_post)

print("\nok" if not FAILED else f"\n{len(FAILED)} נכשלו")
sys.exit(1 if FAILED else 0)
