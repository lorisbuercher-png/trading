"""Automated options-only PAPER trading runner using verified historical EOD data.

Needs GitHub Action secrets MARKETDATA_TOKEN and TWELVEDATA_API_KEY.
If any required data or credential is unavailable, it writes a clear status and
does NOT invent trades. Never connects to a broker or sends real orders.
"""
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from options_engine import new_state, step

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH = ROOT / "docs" / "data" / "options.json"
NY = ZoneInfo("America/New_York")
UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
USER_AGENT = {"User-Agent": "SwingPilot-Options-Paper/1.0", "Accept": "application/json"}


def read_state():
    return json.loads(PATH.read_text(encoding="utf-8"))


def save_state(state):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    p = PATH.with_suffix(".tmp")
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    p.replace(PATH)


def request_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status not in (200,203):
            raise RuntimeError(f"Data provider HTTP {response.status}")
        data = json.load(response)
    if not isinstance(data, dict) or data.get("s") == "error" or data.get("status") == "error":
        raise RuntimeError("Ungültige oder fehlgeschlagene Kursantwort")
    return data


def option_api(path, params, token):
    if not token:
        raise RuntimeError("MARKETDATA_TOKEN fehlt")
    url = "https://api.marketdata.app/v1/options/" + path + "/?" + urllib.parse.urlencode(params)
    return request_json(url, {**USER_AGENT, "Authorization":"Bearer "+token})


def rows_from_columnar(raw):
    """MarketData.app option payloads: columnar arrays, one row per index."""
    symbols = raw.get("optionSymbol") or []
    if not isinstance(symbols, list):
        symbols = [symbols]
    rows = []
    for i, symbol in enumerate(symbols):
        row = {}
        for key,value in raw.items():
            if key in ("s", "errmsg", "nextTime", "prevTime"):
                continue
            if isinstance(value,list):
                row[key] = value[i] if i < len(value) else None
            else:
                row[key] = value
        row["optionSymbol"] = symbol
        rows.append(row)
    return rows


def get_chain(symbol, asof, token):
    # A small, standard-only, ~35-DTE historical EOD chain limits API usage.
    raw = option_api("chain/"+symbol, dict(date=asof, dte=35,
                            strikeLimit=12, nonstandard="false"), token)
    rows = rows_from_columnar(raw)
    for row in rows:
        if row.get("underlying") is None:
            row["underlying"] = symbol
    return rows


def get_option_quote(occ, asof, token):
    raw = option_api("quotes/"+occ, {"date":asof}, token)
    rows = rows_from_columnar(raw)
    return rows[0] if rows else None


def twelvedata(symbol, key):
    url = "https://api.twelvedata.com/time_series?" + urllib.parse.urlencode({
        "symbol":symbol,"interval":"1day","outputsize":"90","format":"JSON"})
    # Twelve Data requires apikey; include it only in request URL, never logs.
    url += "&apikey=" + urllib.parse.quote(key)
    with urllib.request.urlopen(urllib.request.Request(url, headers=USER_AGENT),timeout=30) as response:
        data = json.load(response)
    if not isinstance(data,dict) or data.get("status")=="error" or not isinstance(data.get("values"),list):
        raise RuntimeError("Twelve Data hat keine gültigen Schlusskurse für " + symbol)
    bars=[]
    for value in data["values"]:
        try:
            date = dt.date.fromisoformat(value["datetime"][:10]).isoformat()
            close = float(value["close"])
            if close > 0:
                bars.append({"date":date, "close":close})
        except (TypeError, ValueError, KeyError):
            continue
    return sorted(bars,key=lambda r:r["date"])


def next_dates(after, until, max_days=3):
    day = dt.date.fromisoformat(after) + dt.timedelta(days=1)
    end = dt.date.fromisoformat(until)
    result=[]
    while day <= end and len(result) < max_days:
        if day.weekday() < 5:
            result.append(day.isoformat())
        day += dt.timedelta(days=1)
    return result


def main():
    state=read_state() if PATH.exists() else new_state("2026-11-11")
    state["last_check"]=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    marketdata_key=os.getenv("MARKETDATA_TOKEN")
    twelve_key=os.getenv("TWELVEDATA_API_KEY")
    missing=[name for name,key in [("MARKETDATA_TOKEN",marketdata_key),
                                   ("TWELVEDATA_API_KEY",twelve_key)] if not key]
    if missing:
        state["status"]="setup_required"
        state["last_error"]="Fehlende GitHub-Secrets: "+", ".join(missing)
        state["warnings"]=[state["last_error"]+"; keine simulierten Optionsorders ausgeführt."]
        save_state(state)
        print("::warning::"+state["last_error"])
        return
    # 07:40 UTC Tue–Sat is 02:40/03:40 US Eastern, after the previous US close.
    today_ny=dt.datetime.now(NY).date()
    target=(today_ny-dt.timedelta(days=1)).isoformat()
    dates=next_dates(state["last_date"],target)
    if not dates:
        print("No new completed trading day",state["last_date"])
        save_state(state)
        return
    try:
        # Cache all data once per job; each stock quote costs one Twelve Data credit.
        underlying={}
        for ticker in UNIVERSE:
            underlying[ticker]=twelvedata(ticker,twelve_key)
            time.sleep(9)
        fx_series=twelvedata("USD/CHF",twelve_key)
        for asof in dates:
            usable={}
            for ticker,bars in underlying.items():
                clipped=[b for b in bars if b["date"]<=asof]
                if clipped and clipped[-1]["date"]==asof and len(clipped)>=53:
                    usable[ticker]=clipped
            fx_history=[b for b in fx_series if b["date"]<=asof]
            if len(usable)<3 or not fx_history or fx_history[-1]["date"]!=asof:
                raise RuntimeError(asof+": keine ausreichenden aktuellen US- oder USDCHF-Tageskurse")
            fx=fx_history[-1]["close"]
            chains={}
            errors=[]
            for ticker in usable:
                try:
                    chain=get_chain(ticker,asof,marketdata_key)
                    if chain:
                        chains[ticker]=chain
                    else:
                        errors.append(ticker+": keine Optionskette")
                except Exception as e:
                    errors.append(ticker+": "+type(e).__name__)
            if not chains:
                raise RuntimeError(asof+": keine verfügbaren Optionsketten, keine Orders")
            symbols={pos for bot in state["bots"] for pos in bot["positions"]}
            symbols.update(bot["pending"]["symbol"] for bot in state["bots"] if bot.get("pending"))
            in_chains={q["optionSymbol"] for rows in chains.values() for q in rows}
            quotes={}
            for sym in sorted(symbols - in_chains):
                try:
                    q=get_option_quote(sym,asof,marketdata_key)
                    if q:
                        quotes[sym]=q
                except Exception as e:
                    errors.append("Offener Kontrakt "+sym+": "+type(e).__name__)
            coverage={"underlyings_requested":len(UNIVERSE), "with_underlying_history":len(usable),
              "option_chains_valid":len(chains), "contracts_returned":sum(len(c) for c in chains.values()),
              "provider_errors":errors, "date":asof}
            step(state,asof,chains,quotes,usable,fx,coverage)
            state["warnings"].extend(errors)
            if errors:
                state["status"]="attention"
            state["last_error"]=None
            print("Options PAPER", asof, "NAV",state["total_nav_chf"],
                  "chain sources",len(chains),"pending",sum(bool(b.get("pending")) for b in state["bots"]))
        save_state(state)
    except Exception as exc:
        state["status"]="attention"
        state["last_error"]=str(exc)[:260]
        state["warnings"]=[state["last_error"], "Keine neuen Orders ohne verifizierte Options- und FX-Kursdaten"]
        save_state(state)
        print("::warning::Options-Simulation pausiert: "+state["last_error"])
        # Fail the workflow for visibility; status file is persisted by always() step.
        sys.exit(1)


if __name__=="__main__":
    main()
