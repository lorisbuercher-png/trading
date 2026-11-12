"""Long-options-only evolution paper engine. No share orders, margin or broker API.

All option fills use verified daily bid/ask on the NEXT market session, never
the day the signal and contract were chosen. Positions use BID for NAV.
Option delivery/exercise is intentionally unsupported: unresolved expiry halts
the affected bot instead of inventing a cash settlement.
"""
from __future__ import annotations
import copy
import datetime as dt
import math
import re
from zoneinfo import ZoneInfo

from evolution import PERSONAS, BASE_PARAMS, mutate, signal

OCC = re.compile(r"^[A-Z]{1,6}[0-9]{6}[CP][0-9]{8}$")
NY = ZoneInfo("America/New_York")
START = 2000.0
MULTIPLIER = 100
BUY_LIMIT = 0.30
MIN_CASH = 0.50
COST_CHF = 3.0

def new_state(asof):
    bots = []
    for slot, name, style in PERSONAS:
        bots.append(dict(slot=slot, name=name, style=style, generation=1,
                         bot_id=f"{slot}-g1", status="active",
                         original_capital_chf=START, generation_start_chf=START,
                         nav_chf=START, cash_chf=START, peak_chf=START,
                         drawdown_pct=0.0, params=copy.deepcopy(BASE_PARAMS[slot]),
                         positions={}, pending=None, trades=[], closed_trades=0,
                         winning_trades=0, days_alive=0, history=[{"date":asof, "nav_chf":START}],
                         warnings=[]))
    return dict(schema_version=2, instrument="US_LISTED_OPTIONS", mode="paper_only",
                quote_source="MarketData.app EOD options bid/ask",
                engine="rule_based_options_evolution", status="waiting_for_data",
                start_date=asof, last_date=asof, last_check=None, total_start_chf=10000.0,
                total_nav_chf=10000.0, bots=bots, graveyard=[], evolution_events=[],
                market_coverage={}, warnings=[], last_error=None,
                note="Nur Long Calls/Puts; keine Aktienorders, Margin oder Ausübung. Keine echten Orders.")


def asof_date(timestamp):
    if isinstance(timestamp, str):
        return dt.date.fromisoformat(timestamp[:10]).isoformat()
    if not isinstance(timestamp, (int,float)) or not math.isfinite(timestamp):
        return ""
    return dt.datetime.fromtimestamp(timestamp, NY).date().isoformat()


def valid_quote(q, asof, require_liquid=True):
    try:
        sym = q["optionSymbol"]
        bid, ask = float(q["bid"]), float(q["ask"])
        expiry = q["expiration"]
        expiry = asof_date(expiry)
        if not OCC.fullmatch(sym) or q.get("side") not in ("call", "put"):
            return False
        if asof_date(q.get("updated")) != asof:
            return False
        if dt.date.fromisoformat(expiry) <= dt.date.fromisoformat(asof):
            return False
        if not (math.isfinite(bid) and math.isfinite(ask) and 0 <= bid <= ask and ask > 0):
            return False
        if require_liquid:
            if bid < 0.05 or (ask - bid)/ask > 0.22:
                return False
            if float(q.get("openInterest") or 0) < 50 or float(q.get("volume") or 0) < 1:
                return False
        return True
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def value_chf(price_usd, fx):
    return round(float(price_usd) * MULTIPLIER * fx, 2)


def pnl_pct(bot):
    return 100.0 * (bot["nav_chf"] / bot["original_capital_chf"] - 1)


def choose_option(chain, direction, asof, bot, fx):
    eligible = []
    for q in chain:
        if q.get("side") != direction or not valid_quote(q, asof):
            continue
        dte = (dt.date.fromisoformat(asof_date(q["expiration"])) - dt.date.fromisoformat(asof)).days
        if not 20 <= dte <= 65:
            continue
        try:
            underlying = float(q["underlyingPrice"])
            strike = float(q["strike"])
            if underlying <= 0 or abs(strike / underlying - 1) > .10:
                continue
            total_cost = value_chf(q["ask"], fx) + COST_CHF
            if total_cost > min(bot["nav_chf"] * BUY_LIMIT,
                                bot["cash_chf"] - bot["nav_chf"] * MIN_CASH):
                continue
            if total_cost < 30:
                continue
            # Prefer close-to-money contracts, with about 35 DTE and small spreads.
            rank = (abs(strike / underlying - 1) * 8
                    + abs(dte - 35)/100
                    + (float(q["ask"]) - float(q["bid"])) / float(q["ask"]))
            eligible.append((rank, q["optionSymbol"], q))
        except (ValueError, TypeError, KeyError, ZeroDivisionError):
            continue
    return min(eligible, key=lambda x:(x[0], x[1]))[2] if eligible else None


def trade(bot, side, q, asof, fx, reason):
    sym = q["optionSymbol"]
    if side == "BUY":
        if sym in bot["positions"]:
            return False
        total = value_chf(q["ask"], fx) + COST_CHF
        if total > min(bot["nav_chf"] * BUY_LIMIT,
                       bot["cash_chf"] - bot["nav_chf"] * MIN_CASH):
            return False
        bot["cash_chf"] = round(bot["cash_chf"] - total, 2)
        bot["positions"][sym] = dict(symbol=sym, underlying=q["underlying"],
             side=q["side"], strike=float(q["strike"]), expiry=asof_date(q["expiration"]),
             qty=1, multiplier=MULTIPLIER, entry_ask_usd=float(q["ask"]),
             entry_cost_chf=total, mark_bid_usd=float(q["bid"]),
             mark_chf=value_chf(q["bid"], fx))
        bot["trades"].append(dict(date=asof, side="BUY_TO_OPEN", symbol=sym,
              qty=1, premium_usd=float(q["ask"]), total_chf=total,
              reason=reason, generation=bot["generation"]))
        return True
    if side == "SELL":
        pos = bot["positions"].get(sym)
        if not pos:
            return False
        proceeds = max(0, value_chf(q["bid"], fx)-COST_CHF)
        bot["cash_chf"] = round(bot["cash_chf"] + proceeds, 2)
        pnl = round(proceeds - pos["entry_cost_chf"], 2)
        bot["closed_trades"] += 1
        bot["winning_trades"] += int(pnl > 0)
        bot["trades"].append(dict(date=asof, side="SELL_TO_CLOSE", symbol=sym,
              qty=1, premium_usd=float(q["bid"]), total_chf=proceeds,
              realized_pnl_chf=pnl, reason=reason, generation=bot["generation"]))
        del bot["positions"][sym]
        return True
    return False


def maybe_retire(state, bot, asof, index):
    # Never retire with an open option or a pending order.
    if bot["positions"] or bot["pending"]:
        return
    drawdown = bot["drawdown_pct"]
    since_generation = (bot["nav_chf"] / bot["generation_start_chf"] - 1) if bot["generation_start_chf"] else 0
    poor = (bot["days_alive"] >= 15 and bot["closed_trades"] >= 2
            and since_generation <= -0.08 and drawdown >= 10)
    severe = bot["days_alive"] >= 25 and since_generation <= -0.15
    if not (poor or severe):
        return
    original = bot["bot_id"]
    closing = bot["nav_chf"]
    parent = max((other for other in state["bots"] if other is not bot),
                 key=lambda b:b["nav_chf"] / b["original_capital_chf"] - b["drawdown_pct"]/100)
    new_gen = bot["generation"] + 1
    params = mutate(bot["params"], new_gen, index)
    if parent["nav_chf"] > parent["original_capital_chf"]:
        params["rsi_max"] = parent["params"]["rsi_max"]
    state["graveyard"].append(dict(date=asof, bot_id=original, name=bot["name"],
      generation=bot["generation"], start_chf=bot["generation_start_chf"],
      end_chf=closing, reason="Verlustgrenze nach Mindestlaufzeit"))
    bot.update(generation=new_gen, bot_id=f"{bot['slot']}-g{new_gen}", status="active",
      generation_start_chf=closing, cash_chf=closing, nav_chf=closing,
      peak_chf=closing, drawdown_pct=0, params=params, positions={},
      pending=None, days_alive=0, closed_trades=0, winning_trades=0,
      trades=[], warnings=[], history=[{"date":asof, "nav_chf":closing}])
    state["evolution_events"].append(dict(date=asof, retired=original,
      born=bot["bot_id"], parent=parent["bot_id"],
      inherited_capital_chf=closing))


def step(state, asof, chains, quotes, underlying_bars, fx, coverage=None):
    """All prices/underlying bars must be point-in-time verified as-of asof."""
    if asof <= state["last_date"]:
        return state
    if not .5 < fx < 1.5:
        raise ValueError("Ungültiger USDCHF-Umrechnungskurs")
    if not chains:
        raise ValueError("Keine verifizierten Optionsketten")
    symbol_to_quote = {}
    for rows in chains.values():
        for q in rows:
            if valid_quote(q, asof, require_liquid=False):
                symbol_to_quote[q["optionSymbol"]] = q
    for sym,q in quotes.items():
        if valid_quote(q, asof, require_liquid=False):
            symbol_to_quote[sym] = q
    if not symbol_to_quote:
        raise ValueError("Kein verifizierter Optionskurs für diesen Handelstag")
    blocked = []
    for i,bot in enumerate(state["bots"]):
        bot["days_alive"] += 1
        bot["warnings"] = []
        executed = False
        # Finish orders generated on a previous completed trading day.
        pending = bot.get("pending")
        if pending:
            symbol = pending["symbol"]
            q = symbol_to_quote.get(symbol)
            if not q or not valid_quote(q, asof, require_liquid=(pending["action"]=="BUY")):
                if pending["action"] == "BUY":
                    bot["warnings"].append(f"Kauf {symbol} mangels gültigem Folgetagskurs verworfen")
                    bot["pending"] = None
                else:
                    bot["warnings"].append(f"Verkauf {symbol} mangels Kurs ausgesetzt")
            elif pending["action"] == "BUY":
                if (dt.date.fromisoformat(asof_date(q["expiration"]))-dt.date.fromisoformat(asof)).days < 10:
                    bot["warnings"].append("Optionskauf verworfen: Verfall zu nah")
                else:
                    executed = trade(bot, "BUY", q, asof, fx, "Folgetagsausführung, Geld/Brief")
                bot["pending"] = None
            else:
                executed = trade(bot, "SELL", q, asof, fx, pending["reason"])
                if executed:
                    bot["pending"] = None
        # For a missing or expired quote, freeze the BOT, do not simulate exercise.
        for sym,pos in bot["positions"].items():
            q = symbol_to_quote.get(sym)
            if not q:
                bot["warnings"].append(f"{sym}: kein gültiger Schlusskurs, Bewertung eingefroren")
                if pos["expiry"] <= asof:
                    bot["warnings"].append(f"{sym}: Verfall/Settlement offen – Eingriff erforderlich")
                continue
            pos["mark_bid_usd"] = float(q["bid"])
            pos["mark_chf"] = value_chf(q["bid"], fx)
        bot["nav_chf"] = round(bot["cash_chf"] + sum(p["mark_chf"] for p in bot["positions"].values()), 2)
        bot["peak_chf"] = max(bot["peak_chf"], bot["nav_chf"])
        bot["drawdown_pct"] = round(100 * (bot["peak_chf"]-bot["nav_chf"])/bot["peak_chf"], 2) if bot["peak_chf"] else 0
        stale = bool(bot["warnings"])
        if stale:
            blocked.append(bot["bot_id"])
        # At most one order execution or scheduling decision per bot and day.
        if not bot["pending"] and not executed and not stale:
            if bot["positions"]:
                sym,pos = next(iter(bot["positions"].items()))
                q = symbol_to_quote[sym]
                dte = (dt.date.fromisoformat(pos["expiry"])-dt.date.fromisoformat(asof)).days
                downside = q["bid"] / max(.01,pos["entry_ask_usd"]) - 1
                # Close well before expiry, or on loss/benefit thresholds.
                if dte <= 10 or downside <= -bot["params"]["stop_pct"]*3 or downside >= 0.4:
                    bot["pending"] = dict(action="SELL",symbol=sym,created=asof,
                              reason="Verfall/Risiko/Gewinn – Signal vom Vortag")
            else:
                # Underlying signal uses previous completed candle, never the fill day.
                ranked = []
                for ticker,rows in chains.items():
                    bars = underlying_bars.get(ticker)
                    if not bars or len(bars) < 53 or bars[-1]["date"] != asof:
                        continue
                    s = signal(bars, bot["style"], bot["params"])
                    if not s:
                        continue
                    direction = "call" if s["buy"] else ("put" if s["sell"] else None)
                    if direction is None:
                        continue
                    candidate = choose_option(rows, direction, asof, bot, fx)
                    if candidate:
                        ranked.append((abs(s["score"]), ticker, candidate))
                if ranked:
                    _,ticker,candidate = max(ranked, key=lambda r:(r[0],r[1]))
                    bot["pending"] = dict(action="BUY", symbol=candidate["optionSymbol"],
                                   created=asof, underlying=ticker)
        bot["history"].append(dict(date=asof,nav_chf=bot["nav_chf"]))
        maybe_retire(state, bot, asof, i)
    state["last_date"] = asof
    state["total_nav_chf"] = round(sum(b["nav_chf"] for b in state["bots"]), 2)
    state["market_coverage"] = coverage or {}
    state["status"] = "attention" if blocked else "active"
    state["warnings"] = [f"Bot {x}: Kursdaten/Verfall prüfen" for x in blocked]
    state["last_error"] = None
    return state
