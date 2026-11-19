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
finally:
    aura_report.station, M.station, M.known_category = real[:3]
    M.SENT.update(real[3])
print("ok: aura stations")
