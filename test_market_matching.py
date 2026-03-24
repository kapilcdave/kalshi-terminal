import unittest

from market_matching import (
    build_kalshi_signature,
    build_poly_signature,
    find_cross_platform_matches,
    score_match,
)


class MarketMatchingTests(unittest.TestCase):
    def test_equivalent_sp500_market_matches(self) -> None:
        kalshi = build_kalshi_signature(
            "INXD-23DEC31-B4900",
            {"title": "Will the S&P 500 close above 4900 on Dec 31?"},
        )
        poly = build_poly_signature(
            "poly-1",
            {"question": "S&P 500 above 4900 end of year?"},
        )

        score, reasons = score_match(kalshi, poly)

        self.assertGreaterEqual(score, 0.65)
        self.assertIn("instrument=sp500", reasons)
        self.assertIn("threshold=4900", reasons)

    def test_threshold_mismatch_is_rejected(self) -> None:
        kalshi = build_kalshi_signature(
            "INXD-23DEC31-B4900",
            {"title": "Will the S&P 500 close above 4900 on Dec 31?"},
        )
        poly = build_poly_signature(
            "poly-2",
            {"question": "S&P 500 above 5000 end of year?"},
        )

        score, _ = score_match(kalshi, poly)

        self.assertEqual(score, 0.0)

    def test_cross_platform_matcher_picks_best_candidate(self) -> None:
        matches = find_cross_platform_matches(
            {
                "INXD-23DEC31-B4900": {
                    "title": "Will the S&P 500 close above 4900 on Dec 31?",
                    "price": 0.42,
                }
            },
            {
                "poly-good": {
                    "question": "S&P 500 above 4900 end of year?",
                    "price": 0.55,
                },
                "poly-bad": {
                    "question": "NASDAQ 100 above 4900 end of year?",
                    "price": 0.13,
                },
            },
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].poly_id, "poly-good")


if __name__ == "__main__":
    unittest.main()
