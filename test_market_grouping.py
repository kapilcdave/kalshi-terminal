import unittest

from market_grouping import (
    build_grouped_markets,
    canonicalize_group_label,
    derive_group_label,
    infer_theme,
    summarize_groups,
)


class MarketGroupingTests(unittest.TestCase):
    def test_sports_markets_share_matchup_group(self) -> None:
        self.assertEqual(
            derive_group_label("Will Stephen Curry score 40+ points in Warriors vs Rockets?"),
            "Warriors vs Rockets",
        )

    def test_finance_markets_group_by_underlying_and_time_bucket(self) -> None:
        self.assertEqual(
            derive_group_label("S&P 500 above 4900 end of year?"),
            "S&P 500 EOY",
        )

    def test_politics_markets_group_by_office(self) -> None:
        self.assertEqual(
            derive_group_label("Will a Democrat win the presidential election in Nov 2028?"),
            "Presidential Election Nov 2028",
        )

    def test_grouped_markets_are_sorted_by_group_then_volume(self) -> None:
        grouped = build_grouped_markets(
            [
                ("a", {"question": "Will Curry score 40+ in Warriors vs Rockets?", "volume": 10}),
                ("b", {"question": "Warriors vs Rockets winner?", "volume": 100}),
                ("c", {"question": "S&P 500 above 4900 end of year?", "volume": 50}),
            ],
            "question",
        )

        self.assertEqual(grouped[0].group, "S&P 500 EOY")
        self.assertEqual(grouped[1].group, "Warriors vs Rockets")
        self.assertEqual(grouped[1].market_id, "b")

    def test_theme_inference_catches_sports(self) -> None:
        self.assertEqual(infer_theme("Warriors vs Rockets winner?"), "sports")

    def test_group_label_canonicalization_unifies_eoy_labels(self) -> None:
        self.assertEqual(
            canonicalize_group_label("S&P 500 EOY"),
            canonicalize_group_label("S&P 500 end of year"),
        )

    def test_group_summary_matches_equivalent_labels(self) -> None:
        k_groups = summarize_groups(
            [("k1", {"title": "Will the S&P 500 close above 4900 on Dec 31?", "volume": 10})],
            "title",
        )
        p_groups = summarize_groups(
            [("p1", {"question": "S&P 500 above 4900 end of year?", "volume": 20})],
            "question",
        )
        self.assertEqual(set(k_groups), set(p_groups))


if __name__ == "__main__":
    unittest.main()
