"""SwingPilot Evolution: five isolated CHF 2,000 PAPER agents.

Pure deterministic, risk-limited evolution; no LLM, no broker connection.
Market data are passed in from the existing scanner, avoiding extra API calls.
Orders are simulated at daily close using signals from the PRIOR session.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
from pathlib import Path

EVOLUTION_FILE = Path(__file__).resolve().parents[1] / "docs" / "data" / "evolution.json"
START_PER_BOT = 2000.0

PERSONAS = [
    ("alpha", "Alpha", "Momentum"),
    ("hunter", "Hunter", "Breakout"),
    ("shield", "Shield", "Defensiv"),
    ("scout", "Scout", "Trendfolge"),
    ("nova", "Nova", "Adaptiv"),
]

BASE_PARAMS = {
    "alpha": {"rsi_min": 45, "rsi_max": 71, "momentum_min": 0.0, "stop_pct": 0.07},
    "hunter": {"rsi_min": 48, "rsi_max": 77, "momentum_min": 0.005, "stop_pct": 0.09},
    "shield": {"rsi_min": 40, "rsi_max": 66, "momentum_min": 0.0, "stop_pct": 0.045},
    "scout": {"rsi_min": 44, "rsi_max": 73, "momentum_min": 0.01, "stop_pct": 0.07},
    "nova": {"rsi_min": 43, "rsi_max": 70, "momentum_min": 0.005, "stop_pct": 0.06},
}


def seed(asof: str) -> dict:
    bots = []
    for slug, name, style in PERSONAS:
        bots.append({
            "slot": slug, "name": name, "style": style, "generation": 1,
            "bot_id": slug + "-g1", "status": "active",
            "initial_capital_chf": START_PER_BOT, "generation_start_chf": START_PER_BOT,
            "cash_chf": START_PER_BOT, "nav_chf": START_PER_BOT,
            "peak_chf": START_PER_BOT, "drawdown_pct": 0.0,
            "positions": {}, "entry_prices_chf": {}, "marks_chf": {},
            "params": copy.deepcopy(BASE_PARAMS[slug]),
            "days_alive": 0, "closed_trades": 0, "winning_trades": 0,
            "trades": [], "history": [{"date": asof, "nav_chf": START_PER_BOT}],
            "stale_holdings": [],
        })
    return {
        "schema_version": 1, "mode": "paper_only", "engine": "rule_based_evolution",
        "start_date": asof, "last_date": asof,
        "total_start_chf": 10000.0, "total_nav_chf": 10000.0,
        "bots": bots, "graveyard": [], "evolution_events": [],
        "market_coverage": {}, "warnings": [],
        "description": "5 separate paper portfolios; modeled EOD fills and fees; no real broker orders.",
    }


def sma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def rsi(vals, n=14):
    if len(vals) < n + 1:
        return None
    changes = [vals[i] - vals[i - 1] for i in range(len(vals) - n, len(vals))]
    gains = sum(max(x, 0.0) for x in changes) / n
    losses = sum(max(-x, 0.0) for x in changes) / n
    return 100.0 if losses == 0 and gains > 0 else (50.0 if losses == 0 else 100 - 100 / (1 + gains / losses))


def signal(bars, style, params):
    """Only bars up to the preceding day determine an entry/exit signal."""
    prior = bars[:-1]
    if len(prior) < 52:
        return None
    vals = [b["close"] for b in prior]
    c = vals[-1]
    ma10, ma20, ma50 = sma(vals, 10), sma(vals, 20), sma(vals, 50)
    momentum = c / vals[-6] - 1
    relative_strength = rsi(vals)
    changes = [vals[i] / vals[i - 1] - 1 for i in range(len(vals) - 19, len(vals))]
    mean = sum(changes) / len(changes)
    vol = math.sqrt(sum((x - mean) ** 2 for x in changes) / len(changes))
    threshold = params["momentum_min"]
    eligible = params["rsi_min"] <= relative_strength <= params["rsi_max"]
    if style == "Momentum":
        buy = eligible and c > ma20 > ma50 and momentum > threshold
    elif style == "Breakout":
        buy = eligible and c > max(vals[-21:-1]) * 1.002 and momentum > threshold
    elif style == "Defensiv":
        buy = eligible and c > ma50 and ma20 > ma50 and vol < 0.028 and momentum > threshold
    elif style == "Trendfolge":
        buy = eligible and ma10 > ma20 > ma50 and c > ma10 and momentum > threshold
    else:
        buy = eligible and c > ma20 > ma50 and momentum > threshold
    sell = c < ma20 or relative_strength > min(84, params["rsi_max"] + 10)
    score = (c / ma20 - 1) * 100 + momentum * 100 - vol * (180 if style == "Defensiv" else 30)
    return {"buy": bool(buy), "sell": bool(sell), "score": score}


def trading_fee(gross, currency):
    """Illustrative, NOT a broker quote."""
    return (4.8 if currency == "USD" else 5.0) + (gross * 0.005 if currency == "USD" else 0.0)


def nav_of(bot):
    return round(bot["cash_chf"] + sum(q * bot["marks_chf"].get(k, 0) for k, q in bot["positions"].items()), 2)


def close_trade(bot, ticker, price_chf, market_date, currency, reason):
    q = bot["positions"].pop(ticker)
    gross = q * price_chf
    charge = trading_fee(gross, currency)
    bot["cash_chf"] = round(bot["cash_chf"] + gross - charge, 2)
    entry = bot["entry_prices_chf"].pop(ticker)
    pnl = (price_chf - entry) * q - charge
    bot["closed_trades"] += 1
    if pnl > 0:
        bot["winning_trades"] += 1
    bot["trades"].append({
        "date": market_date, "side": "SELL", "ticker": ticker, "qty": q,
        "price_chf": round(price_chf, 4), "fees_chf": round(charge, 2),
        "pnl_excluding_entry_fees_chf": round(pnl, 2), "reason": reason,
        "generation": bot["generation"],
    })


def open_trade(bot, ticker, price_chf, market_date, currency):
    equity = nav_of(bot)
    budget = min(equity * 0.35, bot["cash_chf"] - equity * 0.10)
    if budget < 150 or price_chf <= 0:
        return False
    q = max(0, int((budget - (4.8 if currency == "USD" else 5.0)) / (price_chf * (1.005 if currency == "USD" else 1.0))))
    gross = q * price_chf
    charge = trading_fee(gross, currency)
    if q <= 0 or gross < 150 or gross + charge > min(budget, bot["cash_chf"] - equity * 0.10):
        return False
    bot["cash_chf"] = round(bot["cash_chf"] - gross - charge, 2)
    bot["positions"][ticker] = q
    bot["entry_prices_chf"][ticker] = price_chf
    bot["trades"].append({
        "date": market_date, "side": "BUY", "ticker": ticker, "qty": q,
        "price_chf": round(price_chf, 4), "fees_chf": round(charge, 2),
        "reason": "Signal vom abgeschlossenen Vortag", "generation": bot["generation"],
    })
    return True


def mutate(base, generation, slot_index):
    """Deterministic, bounded parameter mutation, not guaranteed learning."""
    p = dict(base)
    delta = ((generation * 7 + slot_index * 3) % 5) - 2
    p["rsi_min"] = max(35, min(53, p["rsi_min"] + delta))
    p["rsi_max"] = max(62, min(79, p["rsi_max"] - delta))
    p["momentum_min"] = round(max(-0.01, min(0.03, p["momentum_min"] + delta * 0.002)), 4)
    p["stop_pct"] = round(max(0.04, min(0.10, p["stop_pct"] + delta * 0.005)), 4)
    return p


def step(state, market_date, series, usdchf, assets, scan=None, warnings=None):
    """Process at most one NEW, fully closed market day. State is mutable."""
    if market_date <= state["last_date"]:
        return state
    if not (0.5 < usdchf < 1.5):
        raise ValueError("Ungültiger USD/CHF-Kurs")
    valid = {
        t: bars for t, bars in series.items()
        if t in assets and bars and bars[-1]["date"] == market_date
        and len(bars) >= 53 and bars[-1]["close"] > 0
    }
    prices = {
        t: round(bars[-1]["close"] * (usdchf if assets[t]["currency"] == "USD" else 1), 5)
        for t, bars in valid.items()
    }
    if not prices:
        raise ValueError("Keine aktuellen Schlusskurse")
    state["market_coverage"] = scan or {}
    state["warnings"] = list(warnings or [])
    for slot_index, bot in enumerate(state["bots"]):
        bot["days_alive"] += 1
        bot["marks_chf"].update(prices)
        bot["stale_holdings"] = sorted(t for t in bot["positions"] if t not in prices)
        indicators = {
            t: signal(bars, bot["style"], bot["params"]) for t, bars in valid.items()
        }
        indicators = {t: v for t, v in indicators.items() if v}
        sold = False
        for t in list(bot["positions"]):
            if t not in prices:
                continue
            sig = indicators.get(t)
            stop = prices[t] <= bot["entry_prices_chf"].get(t, prices[t]) * (1 - bot["params"]["stop_pct"])
            if stop or (sig and sig["sell"]):
                close_trade(bot, t, prices[t], market_date, assets[t]["currency"],
                            "Schlusskurs-Stop" if stop else "Trend-Exit")
                sold = True
                break
        if not sold and len(bot["positions"]) < 2:
            candidates = sorted(
                ((v["score"], t) for t, v in indicators.items() if v["buy"] and t not in bot["positions"]),
                reverse=True,
            )
            for _, t in candidates:
                if open_trade(bot, t, prices[t], market_date, assets[t]["currency"]):
                    break
        bot["nav_chf"] = nav_of(bot)
        bot["peak_chf"] = max(bot["peak_chf"], bot["nav_chf"])
        bot["drawdown_pct"] = round(100 * (bot["peak_chf"] - bot["nav_chf"]) / bot["peak_chf"], 2) if bot["peak_chf"] else 0.0
        bot["history"].append({"date": market_date, "nav_chf": bot["nav_chf"]})
        # Avoid killing bots on one losing trade. Need experience AND loss/drawdown.
        life_return = (bot["nav_chf"] / bot["generation_start_chf"] - 1)
        retire = bot["days_alive"] >= 15 and (
            (bot["closed_trades"] >= 2 and life_return <= -0.07 and bot["drawdown_pct"] >= 8)
            or (bot["days_alive"] >= 20 and life_return <= -0.12)
        )
        if not retire or bot["stale_holdings"]:
            continue
        # Liquidate fully before a replacement, retaining losses and modeled fees.
        for t in list(bot["positions"]):
            close_trade(bot, t, prices[t], market_date, assets[t]["currency"], "Generation beendet")
        closing_nav = nav_of(bot)
        state["graveyard"].append({
            "bot_id": bot["bot_id"], "name": bot["name"],
            "generation": bot["generation"], "start_chf": bot["generation_start_chf"],
            "end_chf": closing_nav, "lifetime_days": bot["days_alive"],
            "roi_pct": round(100 * (closing_nav / bot["generation_start_chf"] - 1), 2),
            "date": market_date, "reason": "Verlust- und Drawdown-Grenze",
        })
        # Select current best surviving agent as parent; do not clone its capital.
        survivors = [b for b in state["bots"] if b is not bot]
        parent = max(survivors, key=lambda b: b["nav_chf"] / b["generation_start_chf"] - 1 - b["drawdown_pct"] / 200)
        previous_id = bot["bot_id"]
        old_gen = bot["generation"]
        child_parameters = mutate(bot["params"], old_gen + 1, slot_index)
        # Share one parameter from a higher-performing peer; retain the slot's style.
        if parent["nav_chf"] > parent["generation_start_chf"]:
            child_parameters["rsi_max"] = parent["params"]["rsi_max"]
        bot.update({
            "generation": old_gen + 1, "bot_id": bot["slot"] + "-g" + str(old_gen + 1),
            "cash_chf": closing_nav, "nav_chf": closing_nav,
            "generation_start_chf": closing_nav, "peak_chf": closing_nav,
            "positions": {}, "entry_prices_chf": {}, "marks_chf": {},
            "params": child_parameters, "days_alive": 0, "closed_trades": 0,
            "winning_trades": 0, "history": [{"date": market_date, "nav_chf": closing_nav}],
            "trades": [], "drawdown_pct": 0.0, "stale_holdings": [],
        })
        state["evolution_events"].append({
            "date": market_date, "retired": previous_id, "born": bot["bot_id"],
            "parent": parent["bot_id"], "inherited_capital_chf": closing_nav,
            "reason": "Verlust und Drawdown nach Mindestlaufzeit",
        })
    state["last_date"] = market_date
    state["total_nav_chf"] = round(sum(b["nav_chf"] for b in state["bots"]), 2)
    return state


def update_evolution(market_date, series, usdchf, assets, scan=None, warnings=None):
    """Called once by the legacy trader after validation; independent state file."""
    if not EVOLUTION_FILE.exists():
        state = seed(market_date)  # new challenge begins at the latest confirmed session
        state["market_coverage"] = scan or {}
        state["warnings"] = list(warnings or [])
    else:
        state = json.loads(EVOLUTION_FILE.read_text(encoding="utf-8"))
        step(state, market_date, series, usdchf, assets, scan, warnings)
    EVOLUTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = EVOLUTION_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(EVOLUTION_FILE)
    return state
