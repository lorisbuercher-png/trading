"""Deterministic safety checks for the SwingPilot Evolution paper engine."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
from evolution import seed, signal, step, mutate

def fixture(date="2026-11-12", last_close=130.0):
    from datetime import date as Date, timedelta
    first = Date(2026, 8, 1)
    bars = [{"date": (first + timedelta(days=i)).isoformat(), "close": 90 + 0.5 * i} for i in range(74)]
    bars[-1] = {"date": date, "close": last_close}
    return bars

class EvolutionTests(unittest.TestCase):
    def setUp(self):
        self.market = {"AAA": fixture()}
        self.assets = {"AAA": {"currency": "CHF", "market": "SIX"}}

    def test_five_independent_allocations(self):
        s = seed("2026-11-11")
        self.assertEqual(len(s["bots"]), 5)
        self.assertEqual(sum(b["cash_chf"] for b in s["bots"]), 10000)
        self.assertEqual(len({b["bot_id"] for b in s["bots"]}), 5)
        self.assertEqual(s["last_date"], "2026-11-11")

    def test_previous_day_signal_does_not_see_current_close(self):
        a = fixture(last_close=50.0)
        b = fixture(last_close=500.0)
        p = seed("2026-11-11")["bots"][0]["params"]
        self.assertEqual(signal(a, "Momentum", p), signal(b, "Momentum", p))

    def test_no_duplicate_day_or_unlisted_orders(self):
        state = seed("2026-11-11")
        step(state, "2026-11-12", self.market, 1.0, self.assets)
        before = copy.deepcopy(state)
        step(state, "2026-11-12", self.market, 1.0, self.assets)
        self.assertEqual(before, state)
        self.assertEqual(len(state["bots"]), 5)
        for b in state["bots"]:
            self.assertGreaterEqual(b["cash_chf"], b["nav_chf"] * 0.10 - 0.01)
            self.assertLessEqual(len(b["positions"]), 2)
            self.assertTrue(set(b["positions"]) <= {"AAA"})

    def test_missing_prices_never_trigger_sell_and_block_retirement(self):
        state = seed("2026-11-11")
        b = state["bots"][0]
        b["positions"] = {"MISSING": 1}
        b["marks_chf"] = {"MISSING": 100.0}
        b["entry_prices_chf"] = {"MISSING": 100.0}
        b["cash_chf"] = 1600.0
        b["days_alive"] = 20
        b["closed_trades"] = 3
        step(state, "2026-11-12", self.market, 1.0, self.assets)
        self.assertEqual(b["generation"], 1)
        self.assertIn("MISSING", b["stale_holdings"])
        self.assertIn("MISSING", b["positions"])

    def test_retirement_preserves_remaining_capital(self):
        state = seed("2026-11-11")
        b = state["bots"][0]
        b["cash_chf"] = 1700.0
        b["days_alive"] = 20
        b["closed_trades"] = 3
        step(state, "2026-11-12", self.market, 1.0, self.assets)
        self.assertEqual(b["generation"], 2)
        self.assertEqual(b["bot_id"], "alpha-g2")
        self.assertLess(b["cash_chf"], 2000.0)
        self.assertAlmostEqual(b["cash_chf"], state["graveyard"][0]["end_chf"])
        self.assertEqual(len(state["evolution_events"]), 1)

    def test_mutations_bounded(self):
        base = seed("2026-11-11")["bots"][0]["params"]
        for generation in range(2, 100):
            p = mutate(base, generation, 0)
            self.assertTrue(35 <= p["rsi_min"] <= 53)
            self.assertTrue(62 <= p["rsi_max"] <= 79)
            self.assertTrue(0.04 <= p["stop_pct"] <= 0.10)

if __name__ == "__main__":
    unittest.main()
