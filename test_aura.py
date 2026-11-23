"""AURA HQ station reports: python test_aura.py (no network, no Gmail)"""
import os

os.environ.setdefault("DRY_RUN", "1")
import aura_report  # noqa: E402
import sync_script as M  # noqa: E402

assert os.environ.get("AURA_REPORT") == "off"  # a dry run stays silent

events = []
real = aura_report.station, M.station, M.known_category, dict(M.SENT)
aura_report.station = M.station = lambda bot, sid, status, headline=None, metrics=None, handoff_to=None, **kw: \
    events.append((bot, sid, status, headline, metrics, handoff_to))
try:
    # rules only: working -> done with the real count; the AI station does not run, so it reports nothing
    M.known_category = lambda *a: "other"
    assert M.classify([{"id": "1", "sender": "a@b.c", "subject": "s", "labels": []}]) == {"1": "other"}
    assert [(e[1], e[2]) for e in events] == [("rules", "working"), ("rules", "done")] and events[1][4] == {"classified": 1}

    # the accountant passes the result through and counts
    events.clear()
    assert M.accountant(lambda x: x + 1, 1) == 2
    assert [(e[1], e[2], e[4]) for e in events] == [("accountant", "working", None), ("accountant", "done", {"bills": 1})]

    # an error is reported without its text (it can hold a token or a subject) and still propagates unchanged
    events.clear()
    boom = RuntimeError("https://api.telegram.org/botSECRET/sendMessage נושא סודי")
    try:
        M.accountant(lambda: (_ for _ in ()).throw(boom))
    except RuntimeError as ex:
        assert ex is boom
    else:
        raise AssertionError("the error must propagate")
    assert [(e[1], e[2]) for e in events] == [("accountant", "working"), ("accountant", "error")]
    assert "SECRET" not in events[1][3] and "סודי" not in events[1][3] and events[1][3].startswith("RuntimeError")

    # the error report says where in the bot's own code it happened (file, line, function only)
    w = events[1][4]["where"]
    assert w["file"].endswith("test_aura.py") and w["func"] == "<genexpr>" and isinstance(w["line"], int), w
    assert any(t.startswith("sync_script.py:") and t.endswith(" accountant") for t in w["trace"]), w
finally:
    aura_report.station, M.station, M.known_category = real[:3]
    M.SENT.update(real[3])
print("ok: aura stations")

# AURA control: Maor's overrides; none set -> today's values; wrong type -> ignored; paused -> main() stops before Gmail or any report
import time  # noqa: E402
import important  # noqa: E402
real_cfg = (M.AI_MODEL, important.DAILY_LIMIT, M.WAITING_AFTER_DAYS)
def aura(settings, paused=False):
    M.AI_MODEL, important.DAILY_LIMIT, M.WAITING_AFTER_DAYS = real_cfg  # each case starts from the code's values
    aura_report._cfg["mail"] = (time.time(), {"paused": paused, "settings": settings})
    M.apply_aura_settings()
    return M.AI_MODEL, important.DAILY_LIMIT, M.WAITING_AFTER_DAYS
assert aura({}) == real_cfg == ((os.environ.get("AI_MODEL", "").strip() or "gpt-6.1-terra"), 3, 3)
assert aura({"AI_MODEL": ["gpt-6-luna"], "DAILY_LIMIT": 5, "WAITING_AFTER_DAYS": 7}) == ("gpt-6-luna", 5, 7)
assert important.split_daily(list(range(6)), 0) == ([0, 1, 2, 3, 4], [5])
assert aura({"AI_MODEL": "gpt-6-luna", "DAILY_LIMIT": "abc", "WAITING_AFTER_DAYS": 2.5}) == real_cfg
aura({}, paused=True)
events.clear()
real_services, aura_report.station, M.station = M.get_google_services, (lambda *a, **k: events.append(a)), (lambda *a, **k: events.append(a))
M.get_google_services = lambda: (_ for _ in ()).throw(AssertionError("ran while paused"))
try:
    M.main()
    assert events == [], events
finally:
    M.get_google_services, aura_report.station, M.station = real_services, real[0], real[1]
aura({})
print("ok: aura control")

# AURA's central scheduler: when AURA starts this bot (AURA_SCHEDULES on), GitHub's own cron run is a duplicate and skips;
# a dispatch (AURA or by hand) always runs; AURA unreachable -> no settings -> the cron is the backup and runs
def cron_case(event, settings):
    os.environ["GITHUB_EVENT_NAME"] = event
    aura_report._cfg["mail"] = (time.time(), {"paused": False, "settings": settings})
    return M.cron_superseded()
try:
    assert cron_case("schedule", {"AURA_SCHEDULES": True}) is True
    assert cron_case("workflow_dispatch", {"AURA_SCHEDULES": True}) is False
    assert cron_case("schedule", {}) is False
    assert cron_case("schedule", {"AURA_SCHEDULES": False}) is False
    os.environ["GITHUB_EVENT_NAME"] = "schedule"; aura_report._cfg["mail"] = (time.time(), {"paused": False, "settings": {"AURA_SCHEDULES": True}})
    events.clear(); M.get_google_services = lambda: (_ for _ in ()).throw(AssertionError("ran a superseded cron run"))
    aura_report.station = M.station = lambda *a, **k: events.append(a)
    M.main(); assert events == [], events
finally:
    os.environ.pop("GITHUB_EVENT_NAME", None); M.get_google_services, aura_report.station, M.station = real_services, real[0], real[1]
aura({})
print("ok: aura scheduler guard")

# public run logs (the repo is public since 2026-11-23): on GitHub no sender, subject or name reaches the log
os.environ["GITHUB_ACTIONS"] = "true"
try:
    assert M.public("trash: a@b.c | נושא אישי") == "trash: …"
    assert M.public("unsubscribe news@shop.com") == "unsubscribe …"
    assert M.public("monday → לוח / קבוצה: רותי") == "monday → לוח / קבוצה: …"
    assert M.public("failures → telegram") == "failures → telegram"
    import contextlib as _c, io as _io
    buf = _io.StringIO()
    with _c.redirect_stdout(buf):
        M.act("trash: secret@x.com | שם", lambda: None)
    assert "secret@x.com" not in buf.getvalue() and "trash" in buf.getvalue(), buf.getvalue()
finally:
    os.environ.pop("GITHUB_ACTIONS", None)
assert M.public("trash: a@b.c | s") == "trash: a@b.c | s"   # locally (Maor's own runs) the full line stays
print("ok: public logs")
