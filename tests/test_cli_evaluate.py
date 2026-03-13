from __future__ import annotations

import unittest

from trader.cli import parse_horizons


class CliEvaluateTests(unittest.TestCase):
    def test_parse_horizons_sorts_and_dedupes(self) -> None:
        self.assertEqual(parse_horizons("10,5,10"), [5, 10])

    def test_parse_horizons_rejects_non_positive(self) -> None:
        with self.assertRaises(ValueError):
            parse_horizons("0,5")

    def test_parse_horizons_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            parse_horizons("  ,  ")


if __name__ == "__main__":
    unittest.main()
