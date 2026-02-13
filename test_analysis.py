
import unittest
from analyzer import KalshiAnalyzer

class TestKalshiAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analyzer = KalshiAnalyzer()

    def test_brier_score(self):
        # (0.7 - 1)^2 = 0.09
        self.assertEqual(round(self.analyzer.brier_score(0.7, 1), 2), 0.09)
        # (0.3 - 0)^2 = 0.09
        self.assertEqual(round(self.analyzer.brier_score(0.3, 0), 2), 0.09)

    def test_calibration(self):
        markets = [
            {'price': 0.1, 'outcome': 0},
            {'price': 0.1, 'outcome': 1},
            {'price': 0.9, 'outcome': 1}
        ]
        cal = self.analyzer.calculate_calibration(markets)
        self.assertTrue(len(cal) > 0)
        # Bin 0-10% (idx 0) has 0.1, 1 outcome freq 50%
        # Actually 0.1 might fall into bin 10-20% depending on min(int(p*10), 9)
        # 0.1 * 10 = 1.0 -> bin_idx 1 (10-20%)
        # 0.9 * 10 = 9.0 -> bin_idx 9 (90-100%)
        
        found_90 = False
        for entry in cal:
            if entry['bin'] == '90-100%':
                self.assertEqual(entry['actual'], 1.0)
                found_90 = True
        self.assertTrue(found_90)

    def test_longshot_bias(self):
        class MockTrade:
            def __init__(self, price, side, count=1):
                self.yes_price = price
                self.taker_side = side
                self.count = count

        # Many YES takers at low price
        trades = [MockTrade(0.1, 'yes') for _ in range(10)]
        bias = self.analyzer.detect_longshot_bias(trades)
        self.assertTrue(bias['bias_detected'])

        # No bias
        trades = [MockTrade(0.1, 'no') for _ in range(10)]
        bias = self.analyzer.detect_longshot_bias(trades)
        self.assertFalse(bias['bias_detected'])

if __name__ == "__main__":
    unittest.main()
