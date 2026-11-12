#!/usr/bin/env python3
"""SwingPilot: quota-aware, rotating-stock end-of-day PAPER trader.

No broker credentials, no live orders, no real money. Uses validated daily
market data; incomplete/unavailable data means no simulated trade.
"""
import datetime as dt
import json
import math
import os
import pathlib
import time
import urllib.parse
import urllib.request

from evolution import EVOLUTION_FILE, update_evolution

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH = ROOT / 'docs' / 'data' / 'state.json'
CONFIG = ROOT / 'config.json'
TODAY = dt.datetime.now(dt.timezone.utc).date()
LAST_REQUEST_AT = None


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.replace(path)


def api_call(params, spacing_seconds=9.0):
    """Respect Twelve Data Basic's 8-credit/minute quota.

    Each call here requests ONE symbol (one time_series credit). Calls are
    spaced at least 9 seconds, so rolling 60 seconds holds <=7 requests.
    Other users/processes sharing the same API key can still exhaust quota.
    """
    global LAST_REQUEST_AT
    key = os.getenv('TWELVEDATA_API_KEY')
    if not key:
        raise RuntimeError('TWELVEDATA_API_KEY fehlt. Keine Kursdaten, keine Trades.')
    if LAST_REQUEST_AT is not None:
        remaining = spacing_seconds - (time.monotonic() - LAST_REQUEST_AT)
        if remaining > 0:
            time.sleep(remaining)
    LAST_REQUEST_AT = time.monotonic()
    args = {**params, 'apikey': key}
    endpoint = args.pop('_endpoint')
    url = 'https://api.twelvedata.com/' + endpoint + '?' + urllib.parse.urlencode(args)
    req = urllib.request.Request(url, headers={'User-Agent': 'SwingPilotPaper/0.3'})
    with urllib.request.urlopen(req, timeout=25) as response:
        result = json.load(response)
    if not isinstance(result, dict) or result.get('status') == 'error' or result.get('code'):
        raise RuntimeError(str(result.get('message', result)) if isinstance(result, dict) else 'Ungültige API-Antwort')
    return result


def candles(symbol, spacing_seconds=9.0):
    data = api_call({'_endpoint': 'time_series', 'symbol': symbol, 'interval': '1day',
                     'outputsize': 95, 'format': 'JSON'}, spacing_seconds)
    arr = []
    for row in data.get('values', []):
        try:
            date = dt.date.fromisoformat(row['datetime'][:10])
            close = float(row['close'])
            high = float(row['high'])
            low = float(row['low'])
            if close > 0 and all(math.isfinite(x) for x in (close, high, low)):
                arr.append({'date': date.isoformat(), 'close': close, 'high': high, 'low': low})
        except (ValueError, KeyError, TypeError):
            pass
    return sorted(arr, key=lambda x: x['date'])


def sma(values, n):
    return sum(values[-n:]) / n if len(values) >= n else None


def rsi(values, n=14):
    if len(values) < n + 1:
        return None
    diffs = [values[i] - values[i - 1] for i in range(len(values) - n, len(values))]
    gain = sum(max(x, 0) for x in diffs) / n
    loss = sum(max(-x, 0) for x in diffs) / n
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100 - 100 / (1 + gain / loss)


def score(bars):
    """Generate an indicator signal from the PREVIOUS completed session."""
    prior = bars[:-1]
    if len(prior) < 51:
        return None
    closes = [x['close'] for x in prior]
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    r = rsi(closes)
    ret5 = closes[-1] / closes[-6] - 1
    buy = closes[-1] > ma20 > ma50 and 43 <= r <= 72 and ret5 > 0
    sell = closes[-1] < ma20 or r >= 79
    strength = (closes[-1] / ma20 - 1) * 100 + ret5 * 100 + (ma20 / ma50 - 1) * 35
    return {'buy': buy, 'sell': sell, 'score': round(strength, 3),
            'rsi': round(r, 1), 'sma20': round(ma20, 3),
            'sma50': round(ma50, 3), 'prior_date': prior[-1]['date']}


def fee(gross, market):
    """Illustrative fees, NOT a complete or verified Swissquote tariff."""
    return 5.0 if market == 'SIX' else 4.8


def choose_scan(universe, state, limit, extra_held=None):
    """Prioritize ALL held symbols, then rotate fairly through the watchlist."""
    seen = set()
    unique = []
    for asset in universe:
        ticker = asset['ticker']
        if ticker not in seen:
            unique.append(asset)
            seen.add(ticker)
    holdings = [x for x in unique if state.get('positions', {}).get(x['ticker'], 0) > 0 or x['ticker'] in set(extra_held or [])]
    others = [x for x in unique if state.get('positions', {}).get(x['ticker'], 0) <= 0]
    if not others:
        return holdings, 0
    cursor = int(state.get('scan_cursor', 0)) % len(others)
    rotated = others[cursor:] + others[:cursor]
    n = max(0, limit - len(holdings))
    selected_others = rotated[:n]
    return holdings + selected_others, (cursor + len(selected_others)) % len(others)


def main():
    cfg = load_json(CONFIG)
    state = load_json(PATH)
    today = TODAY.isoformat()
    if today > cfg['end_date']:
        state['status'] = 'finished'
        save_json(PATH, state)
        return
    if today < cfg['start_date']:
        print('Not started yet')
        return
    if not os.getenv('TWELVEDATA_API_KEY'):
        state['last_error'] = 'TWELVEDATA_API_KEY fehlt. Keine Kurse und keine neuen Trades.'
        save_json(PATH, state)
        return

    universe = cfg['universe']
    assets = {x['ticker']: x for x in universe}
    state.setdefault('positions', {})
    state.setdefault('marks_chf', {})
    for asset in universe:
        state['positions'].setdefault(asset['ticker'], 0)
    limit = min(60, max(1, int(cfg.get('scan_limit_per_run', 32))))
    spacing = max(9.0, float(cfg.get('api_request_spacing_seconds', 9)))
    evolution_held = []
    if EVOLUTION_FILE.exists():
        try:
            old_evolution = load_json(EVOLUTION_FILE)
            evolution_held = [t for b in old_evolution.get('bots', [])
                              for t, q in b.get('positions', {}).items() if q > 0]
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError('Evolution-Zustand nicht lesbar, Handel gestoppt') from exc
    selection, next_cursor = choose_scan(universe, state, limit, evolution_held)
    series, problems = {}, []
    for item in selection:
        try:
            bars = candles(item['provider_symbol'], spacing)
            closed = [bar for bar in bars if bar['date'] < today]
            if len(closed) < 52:
                raise RuntimeError('weniger als 52 abgeschlossene Tageskurse')
            series[item['ticker']] = closed
        except Exception as e:
            problems.append(f"{item['ticker']}: {e}")

    # Scan status explicitly distinguishes watchlist size from covered symbols.
    state['scan_cursor'] = next_cursor
    state['scan'] = {'watchlist_size': len(universe), 'attempted': len(selection),
                     'valid': len(series), 'unavailable': len(problems),
                     'tickers_checked': [x['ticker'] for x in selection],
                     'note': 'Rotierende Stichprobe, KEIN Scan des gesamten Aktienmarkts.'}
    if not series:
        state['last_error'] = 'Keine gültigen Aktienkurse. ' + '; '.join(problems[:5])
        save_json(PATH, state)
        print('No eligible stock data')
        return

    latest = max(bars[-1]['date'] for bars in series.values())
    if latest < (TODAY - dt.timedelta(days=5)).isoformat():
        state['last_error'] = 'Alle Aktienkurse sind veraltet; kein Handel.'
        save_json(PATH, state)
        return
    if any(h['date'] == latest for h in state.get('history', [])):
        state['last_error'] = '; '.join(problems[:5]) if problems else None
        save_json(PATH, state)
        print('Already processed', latest)
        return

    valid = {k: bars for k, bars in series.items() if bars[-1]['date'] == latest}
    try:
        fx_bars = candles('USD/CHF', spacing)
        asof_fx = [x for x in fx_bars if x['date'] <= latest]
        usdchf = asof_fx[-1]['close'] if asof_fx and asof_fx[-1]['date'] >= (dt.date.fromisoformat(latest) - dt.timedelta(days=5)).isoformat() else None
    except Exception as e:
        usdchf = None
        problems.append('USD/CHF: ' + str(e))
    if not usdchf or not 0.5 < usdchf < 1.5:
        state['last_error'] = 'Kein gültiger USD/CHF-Kurs; kein Handel. ' + '; '.join(problems[:5])
        save_json(PATH, state)
        return

    prices = {k: round(bars[-1]['close'] * (usdchf if assets[k]['currency'] == 'USD' else 1), 5)
              for k, bars in valid.items()}
    signals = {k: score(bars) for k, bars in valid.items()}
    signals = {k: s for k, s in signals.items() if s is not None}
    if not signals:
        state['last_error'] = 'Keine auswertbaren Signale.'
        save_json(PATH, state)
        return

    # Paper trading only. Max 1 trade/session, max 35% new exposure,
    # at least 10% cash reserve, no leverage, no shorts.
    nav = state['cash_chf'] + sum(q * prices.get(k, state['marks_chf'].get(k, 0))
                                  for k, q in state['positions'].items())
    trade = None
    for k, qty in list(state['positions'].items()):
        if qty and k in signals and signals[k]['sell'] and k in assets:
            gross = qty * prices[k]
            cost = fee(gross, assets[k]['market']) + gross * (0.005 if assets[k]['currency'] == 'USD' else 0)
            state['cash_chf'] = round(state['cash_chf'] + gross - cost, 2)
            state['positions'][k] = 0
            trade = {'date': latest, 'ticker': k, 'side': 'SELL', 'qty': qty,
                     'unit_chf': round(prices[k], 4), 'gross_chf': round(gross, 2),
                     'cost_chf': round(cost, 2),
                     'reason': 'Signal vom Vortag: unter SMA20 oder RSI >=79'}
            break

    if trade is None:
        ranked = sorted(((s['score'], k) for k, s in signals.items()
                         if s['buy'] and state['positions'].get(k, 0) == 0), reverse=True)
        for _, k in ranked:
            budget = min(state['cash_chf'] - max(nav * 0.10, 60), nav * 0.35)
            qty = int((budget - fee(budget, assets[k]['market'])) / prices[k] /
                      (1.005 if assets[k]['currency'] == 'USD' else 1))
            if qty <= 0 or qty * prices[k] < 150:
                continue
            gross = qty * prices[k]
            cost = fee(gross, assets[k]['market']) + gross * (0.005 if assets[k]['currency'] == 'USD' else 0)
            if gross + cost > state['cash_chf'] - max(nav * 0.10, 60):
                continue
            state['cash_chf'] = round(state['cash_chf'] - gross - cost, 2)
            state['positions'][k] = qty
            trade = {'date': latest, 'ticker': k, 'side': 'BUY', 'qty': qty,
                     'unit_chf': round(prices[k], 4), 'gross_chf': round(gross, 2),
                     'cost_chf': round(cost, 2),
                     'reason': 'Vortag: Kurs > SMA20 > SMA50, RSI 43–72, Momentum positiv'}
            break
    if trade:
        state.setdefault('trades', []).append(trade)
    state['marks_chf'].update(prices)
    nav = state['cash_chf'] + sum(q * state['marks_chf'].get(k, 0)
                                  for k, q in state['positions'].items())
    state.setdefault('history', []).append({'date': latest, 'nav_chf': round(nav, 2),
                                              'cash_chf': state['cash_chf'],
                                              'usdchf': round(usdchf, 5)})
    state['last_update'] = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    state['status'] = 'active'
    state['last_error'] = '; '.join(problems[:5]) + (f'; +{len(problems)-5} weitere' if len(problems) > 5 else '') if problems else None
    state['signals'] = {k: {**s, 'price_chf': round(prices[k], 2)} for k, s in signals.items()}
    state['data_source'] = 'Twelve Data (nicht Swissquote): Tageskurse, ungefähre Ausführungen, modellierte Gebühren; rotierender Scanner'
    update_evolution(latest, valid, usdchf, assets, state['scan'], problems)
    save_json(PATH, state)
    print('Processed', latest, 'checked', len(selection), 'valid', len(valid), 'trade', trade, 'NAV', round(nav, 2))


if __name__ == '__main__':
    main()
