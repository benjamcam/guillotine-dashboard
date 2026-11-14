#!/usr/bin/env python3
"""Regression checks for actual team totals derived from lineup scores."""

import unittest

from guillotine_odds import Starter, Team, actual_team_total, simulate


class ActualTeamTotalTests(unittest.TestCase):
    def setUp(self):
        self.team = Team(1, "Fixture team", [
            Starter("Scored player A", "RB", 12.0, 18.4, True),
            Starter("Scored player B", "WR", 10.0, 7.2, True),
            Starter("Not played", "QB", 20.0, None, False),
        ])

    def test_sums_actual_starter_scores_when_team_total_is_missing(self):
        self.assertAlmostEqual(actual_team_total(self.team, None), 25.6)

    def test_zero_team_total_uses_nonzero_lineup_sum(self):
        self.assertAlmostEqual(actual_team_total(self.team, 0), 25.6)

    def test_zero_team_total_stays_zero_when_lineup_sum_is_zero(self):
        zero_team = Team(2, "Zero team", [Starter("No points yet", "RB", 10.0, 0.0, True)])
        self.assertEqual(actual_team_total(zero_team, 0), 0)

    def test_explicit_nonzero_espn_team_total_takes_precedence(self):
        self.assertEqual(actual_team_total(self.team, 26.1), 26.1)

    def test_simulation_output_contains_lineup_sum_despite_stale_zero(self):
        result = simulate([self.team], {1: {"actual_points": 0}}, simulations=5, seed=1)
        self.assertAlmostEqual(result[0]["actual_points"], 25.6)
        self.assertAlmostEqual(
            sum(p["actual_points"] or 0 for p in result[0]["lineup"]), 25.6
        )


if __name__ == "__main__":
    unittest.main()
