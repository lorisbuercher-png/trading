"""Deterministic tests for long-option paper portfolio execution and expiry guards."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"bot"))

from options_engine import new_state, step, choose_option, valid_quote
from options_runner import rows_from_columnar, next_dates

NY=ZoneInfo("America/New_York")
SYM="AAPL261218C00200000"

def quote(asof, bid=3.50, ask=3.80, expiry="2026-12-18", sym=SYM, side="call"):
    updated=int(dt.datetime.fromisoformat(asof+"T16:00:00").replace(tzinfo=NY).timestamp())
    expiry_epoch=int(dt.datetime.fromisoformat(expiry+"T16:00:00").replace(tzinfo=NY).timestamp())
    return {"optionSymbol":sym,"underlying":"AAPL","side":side,"strike":200,
            "expiration":expiry_epoch,"updated":updated,"dte":35,
            "bid":bid,"ask":ask,"volume":100,"openInterest":300,
            "underlyingPrice":201}

def bars(asof):
    a=dt.date.fromisoformat(asof)
    return [{"date":(a-dt.timedelta(days=80-i)).isoformat(),
             "close":150+i*.6} for i in range(81)]

class OptionsTests(unittest.TestCase):
    def setUp(self):
        self.a="2026-11-12"
        self.b="2026-11-13"
        self.bots=new_state("2026-11-11")

    def run_day(self,date,price=None):
        return step(self.bots,date,{"AAPL":[price or quote(date)]},{},
                    {"AAPL":bars(date)},.8)

    def test_five_bots_start_without_stock_positions(self):
        self.assertEqual(sum(b["cash_chf"] for b in self.bots["bots"]),10000)
        self.assertEqual(len(self.bots["bots"]),5)
        self.assertEqual(self.bots["instrument"],"US_LISTED_OPTIONS")
        self.assertTrue(all(b["positions"]=={} for b in self.bots["bots"]))

    def test_quote_must_be_same_day_and_standard(self):
        self.assertTrue(valid_quote(quote(self.a),self.a))
        self.assertFalse(valid_quote(quote(self.a),self.b))
        self.assertFalse(valid_quote(quote(self.a,ask=0),self.a))
        self.assertFalse(valid_quote(quote(self.a,bid=0.10,ask=4.0),self.a))
        self.assertFalse(valid_quote(quote(self.a,sym="BAD"),self.a))

    def test_signal_never_trades_on_same_day(self):
        with patch("options_engine.signal",return_value={"buy":True,"sell":False,"score":10}):
            self.run_day(self.a)
        bot=self.bots["bots"][0]
        self.assertEqual(bot["cash_chf"],2000)
        self.assertEqual(bot["positions"],{})
        self.assertEqual(bot["pending"]["action"],"BUY")
        self.assertEqual(self.bots["total_nav_chf"],10000)
        with patch("options_engine.signal",return_value=None):
            self.run_day(self.b)
        self.assertEqual(len(bot["positions"]),1)
        self.assertEqual(bot["cash_chf"],round(2000-(3.8*100*.8+3),2))
        self.assertEqual(bot["trades"][0]["side"],"BUY_TO_OPEN")
        self.assertTrue(bot["nav_chf"]<=2000)
        self.assertLessEqual(2000-bot["cash_chf"],600)

    def test_repeat_day_is_idempotent(self):
        self.run_day(self.a)
        before=copy.deepcopy(self.bots)
        self.run_day(self.a)
        self.assertEqual(before,self.bots)

    def test_bearish_signal_prepares_put_not_stock(self):
        p=quote(self.a,sym="AAPL261218P00200000",side="put")
        with patch("options_engine.signal",return_value={"buy":False,"sell":True,"score":-6}):
            self.run_day(self.a,p)
        self.assertEqual(self.bots["bots"][0]["pending"]["symbol"],"AAPL261218P00200000")

    def test_missing_quote_blocks_trade_and_no_fake_expiry(self):
        bot=self.bots["bots"][0]
        p=quote(self.a)
        with patch("options_engine.signal",return_value={"buy":True,"sell":False,"score":10}):
            self.run_day(self.a,p)
        # Next day: provider has only a PUT, the requested Call cannot be priced.
        with patch("options_engine.signal",return_value=None):
            self.run_day(self.b,quote(self.b,sym="AAPL261218P00200000",side="put"))
        self.assertIsNone(bot["pending"])
        self.assertEqual(bot["positions"],{})
        self.assertEqual(bot["cash_chf"],2000)

    def test_generation_preserves_lost_capital(self):
        bot=self.bots["bots"][0]
        bot["days_alive"]=25
        bot["closed_trades"]=3
        bot["cash_chf"]=1600
        bot["nav_chf"]=1600
        bot["peak_chf"]=2000
        with patch("options_engine.signal",return_value=None):
            self.run_day(self.a)
        self.assertEqual(bot["generation"],2)
        self.assertEqual(bot["cash_chf"],1600)
        self.assertEqual(self.bots["graveyard"][0]["end_chf"],1600)
        self.assertEqual(self.bots["total_nav_chf"],9600)

    def test_no_exit_with_unpriced_expired_contract(self):
        bot=self.bots["bots"][0]
        bot["positions"][SYM]={"symbol":SYM,"underlying":"AAPL","side":"call",
           "strike":200,"expiry":"2026-11-11","qty":1,"multiplier":100,
           "entry_ask_usd":3.8,"entry_cost_chf":307,"mark_bid_usd":1.8,"mark_chf":144}
        bot["cash_chf"]=1693
        with patch("options_engine.signal",return_value=None):
            self.run_day(self.a,quote(self.a,sym="AAPL261218P00200000",side="put"))
        self.assertIn(SYM,bot["positions"])
        self.assertTrue(any("Settlement" in w for w in bot["warnings"]))
        self.assertEqual(self.bots["status"],"attention")

    def test_columnar_parser_and_business_day_catchup(self):
        q=rows_from_columnar({"s":"ok","optionSymbol":[SYM],"bid":[1.5],"ask":[2.0]})
        self.assertEqual(q[0]["optionSymbol"],SYM)
        self.assertEqual(q[0]["bid"],1.5)
        self.assertEqual(next_dates("2026-11-13","2026-11-17"),["2026-11-16","2026-11-17"])

if __name__=="__main__":
    unittest.main()
