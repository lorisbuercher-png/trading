import importlib.util
import pathlib
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock
import json

MODULE = pathlib.Path(__file__).resolve().parents[1] / 'bot' / 'trader.py'
spec = importlib.util.spec_from_file_location('swingpilot_trader', MODULE)
trader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trader)


class ScannerTests(unittest.TestCase):
    def test_holdings_priority_and_rotation(self):
        universe = [{'ticker': f'S{i}', 'provider_symbol': f'S{i}', 'currency':'USD', 'market':'NASDAQ'} for i in range(50)]
        state = {'positions': {'S49': 3}, 'scan_cursor': 0}
        first, cursor = trader.choose_scan(universe, state, 32)
        self.assertEqual(first[0]['ticker'], 'S49')
        self.assertEqual(len(first), 32)
        state['scan_cursor'] = cursor
        second, _ = trader.choose_scan(universe, state, 32)
        self.assertEqual(second[0]['ticker'], 'S49')
        self.assertEqual(len(set(x['ticker'] for x in first + second)), 50)

    def test_signal_is_prior_bar_only(self):
        from datetime import date
        prices = [100 + i * 0.25 for i in range(70)]
        bars = [{'date': (date(2026, 1, 1) + timedelta(days=i)).isoformat(), 'close': p} for i, p in enumerate(prices)]
        first_signal = trader.score(bars)
        bars[-1]['close'] = 100000
        self.assertEqual(first_signal, trader.score(bars))

    def test_no_real_order_or_double_trade_and_existing_positions_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            tmp = pathlib.Path(temp)
            config = {'start_date': '2026-11-03', 'end_date': '2026-12-03',
                      'scan_limit_per_run': 2, 'universe': [
                          {'ticker': 'CB', 'provider_symbol': 'CB', 'currency': 'USD', 'market': 'NYSE'},
                          {'ticker': 'AAPL', 'provider_symbol': 'AAPL', 'currency': 'USD', 'market': 'NASDAQ'}]}
            state = {'status': 'active', 'start_date': '2026-11-03', 'end_date': '2026-12-03',
                     'start_capital_chf': 10000, 'cash_chf': 6646.97, 'positions': {'CB': 11},
                     'marks_chf': {'CB': 298.4}, 'trades': [{'date': '2026-11-02', 'ticker': 'CB', 'side': 'BUY'}],
                     'history': [{'date': '2026-11-03', 'nav_chf': 9929.57}], 'signals': {}}
            (tmp / 'config.json').write_text(json.dumps(config))
            (tmp / 'docs/data').mkdir(parents=True)
            (tmp / 'docs/data/state.json').write_text(json.dumps(state))
            def fake_candles(symbol, spacing):
                prices = ([0.82 for i in range(70)] if symbol == 'USD/CHF' else [100 + i * 0.2 for i in range(70)])
                return [{'date': (date(2026, 8, 27) + timedelta(days=i)).isoformat(),
                         'close': x, 'high': x+1, 'low': x-1} for i, x in enumerate(prices)]
            # Latest fabricated series date is 2026-11-04, and TODAY 2026-11-05.
            with mock.patch.object(trader, 'PATH', tmp / 'docs/data/state.json'), \
                 mock.patch.object(trader, 'CONFIG', tmp / 'config.json'), \
                 mock.patch.object(trader, 'TODAY', date(2026, 11, 5)), \
                 mock.patch.object(trader, 'candles', side_effect=fake_candles), \
                 mock.patch.dict('os.environ', {'TWELVEDATA_API_KEY': 'fake'}):
                trader.main()
                saved = json.loads((tmp / 'docs/data/state.json').read_text())
                self.assertGreaterEqual(saved['positions'].get('CB', 0), 0)
                self.assertEqual(len(saved['trades']), 2)
                self.assertEqual(saved['trades'][-1]['side'], 'SELL')
                self.assertEqual(saved['history'][-1]['date'], '2026-11-04')
                self.assertEqual(saved['status'], 'active')
                self.assertEqual(saved['scan']['watchlist_size'], 2)
                trader.main()
                again = json.loads((tmp / 'docs/data/state.json').read_text())
                self.assertEqual(len(again['trades']), len(saved['trades']))


if __name__ == '__main__':
    unittest.main()
