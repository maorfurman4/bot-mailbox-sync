"""AURA HQ reporter for the Python bots. No dependencies. Copy this one file next to the bot's code.

It writes one row per station event to Supabase (public.bot_events), which the office reads.
Needs SUPABASE_URL and SUPABASE_SERVICE_KEY in the environment (or AURA_SUPABASE_URL and AURA_SUPABASE_KEY, which
win when both exist); without them it does nothing.
It never raises and never waits more than 2.5 seconds: the office must not be able to break a bot.

    from aura_report import working

    with working('news', 'market', 'מושך מדדים ומניות') as w:      # -> status "working"
        data = fetch_market()
        w.done(f'{len(data)} סימולים', symbols=len(data))          # -> status "done" with real numbers
    # an exception inside the block reports status "error" and is raised again, unchanged

Station ids must match office/public/js/aura.config.js.
"""
import json
import os
import re
import ssl
import time
import urllib.request
from datetime import datetime, timezone

try:  # a Python without system certificates (a Mac install) still verifies, with certifi's list when it is there
    import certifi
    _TLS = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _TLS = None

STATUSES = ('idle', 'working', 'done', 'error')

# Serverless bots (a webhook that must answer fast): set BUFFERED = True once, and call flush() once before the HTTP
# response goes out. Every report of the request then travels in ONE request instead of one each, and none is lost
# when the platform freezes the function after the response.
BUFFERED = False
_pending = []


_announced = False
_quiet_until = 0.0  # after a failed report the office is left alone for a minute, so a bot never pays the timeout twice in a row


def _config():
    """AURA_SUPABASE_URL / AURA_SUPABASE_KEY win, for a bot whose own SUPABASE_* variables point at another project."""
    return (os.environ.get('AURA_SUPABASE_URL') or os.environ.get('SUPABASE_URL'),
            os.environ.get('AURA_SUPABASE_KEY') or os.environ.get('SUPABASE_SERVICE_KEY'))


def _announce(url, key):
    """One line in the run's log, at the first report: is telemetry on, and if not, why."""
    global _announced
    if _announced:
        return
    _announced = True
    why = ('AURA_REPORT=off' if os.environ.get('AURA_REPORT') == 'off' else 'missing SUPABASE_URL' if not url
           else 'missing SUPABASE_SERVICE_KEY' if not key else '')
    print(f'[AURA] Telemetry disabled: {why}' if why else '[AURA] Telemetry enabled', flush=True)


def _send(payload, url, key):
    """One POST to the office: a row, or a list of rows (a bulk insert). Never raises."""
    global _quiet_until
    try:
        req = urllib.request.Request(
            url.rstrip('/') + '/rest/v1/bot_events', data=json.dumps(payload).encode(), method='POST',
            headers={'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'Prefer': 'return=minimal'})
        urllib.request.urlopen(req, timeout=2.5, context=_TLS).close()
        return True
    except Exception:
        _quiet_until = time.time() + 60
        return False


def station(bot, station_id, status, headline=None, metrics=None, handoff_to=None, worker_type=None, buffered=None):
    """Report one event. Returns True if the office got it (or, when buffered, that it waits for flush())."""
    url, key = _config()
    _announce(url, key)  # at the first report, not at import: a bot may set its defaults after importing this file
    if not url or not key or status not in STATUSES or os.environ.get('AURA_REPORT') == 'off' or time.time() < _quiet_until:
        return False
    row = {
        'bot': bot, 'kind': 'station', 'station_id': station_id, 'status': status,
        'text': (headline or '')[:300] or None, 'metrics': metrics or None, 'handoff_to': handoff_to,
        'worker_type': worker_type, 'run_id': os.environ.get('GITHUB_RUN_ID'),
    }
    if BUFFERED if buffered is None else buffered:
        _pending.append({**row, 'ts': datetime.now(timezone.utc).isoformat()})  # the real moment, not the moment of the flush
        return True
    return _send(row, url, key)


def buffer(bot, station_id, status, headline=None, metrics=None, handoff_to=None, worker_type=None):
    """Like station(), but always waits for flush()."""
    return station(bot, station_id, status, headline, metrics, handoff_to, worker_type, buffered=True)


def flush():
    """Send everything buffered, in one request. Call it once, right before the webhook answers. Never raises."""
    if not _pending:
        return True
    rows = _pending[:]
    del _pending[:]
    url, key = _config()
    if not url or not key or os.environ.get('AURA_REPORT') == 'off' or time.time() < _quiet_until:
        return False
    return _send(rows, url, key)


def _safe(exc_type, exc):
    """An error's summary without what an exception text can carry: URLs (a Telegram URL holds the bot token) and long tokens."""
    text = re.sub(r'https?://\S+', '[url]', str(exc))
    text = re.sub(r'\S{24,}', '[...]', text)
    return f'{exc_type.__name__}: {text}'[:160]


class working:
    """with working(bot, station_id, headline) as w: ...; w.done(headline, **metrics)"""

    def __init__(self, bot, station_id, headline=None, **kw):
        self.bot, self.station_id, self.headline, self.kw, self.closed = bot, station_id, headline, kw, False

    def __enter__(self):
        station(self.bot, self.station_id, 'working', self.headline, **self.kw)
        return self

    def update(self, headline, **metrics):
        station(self.bot, self.station_id, 'working', headline, metrics, **self.kw)

    def done(self, headline=None, handoff_to=None, **metrics):
        self.closed = True
        station(self.bot, self.station_id, 'done', headline or self.headline, metrics, handoff_to, **self.kw)

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            station(self.bot, self.station_id, 'error', _safe(exc_type, exc), **self.kw)
        elif not self.closed:
            self.done()
        return False


if __name__ == '__main__':   # python aura_report.py : self-check, no network
    os.environ.pop('SUPABASE_URL', None)
    assert station('news', 'market', 'working') is False, 'without keys it must do nothing'
    os.environ.update(SUPABASE_URL='http://127.0.0.1:9', SUPABASE_SERVICE_KEY='x')
    assert station('news', 'market', 'nonsense') is False
    assert station('news', 'market', 'working', 'x') is False, 'an unreachable office must not raise'
    assert _quiet_until > time.time(), 'after a failure the office is left alone for a while'
    try:
        with working('news', 'market', 'x'):
            raise ValueError('boom')
    except ValueError:
        pass
    else:
        raise AssertionError('the bot error must pass through')
    assert 'SECRET' not in _safe(ValueError, ValueError('failed https://api.telegram.org/bot123:SECRETSECRET/send key=SECRETSECRETSECRETSECRETSECRET'))
    _quiet_until = 0.0
    assert buffer('yahli', 'parse', 'working', 'x') is True and buffer('yahli', 'parse', 'done', 'y') is True
    assert len(_pending) == 2 and _pending[0]['ts'] <= _pending[1]['ts'], 'buffered rows keep their own time and order'
    assert flush() is False and not _pending, 'a flush to an unreachable office fails quietly and leaves nothing behind'
    assert flush() is True, 'nothing to send is fine'
    print('ok: aura_report')
