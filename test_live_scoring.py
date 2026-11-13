import unittest

from guillotine_odds import extract_live_scores, extract_live_rosters, extract_teams


class LiveScoringTests(unittest.TestCase):
    def test_home_away_scores(self):
        data = {"schedule": [{"matchupPeriodId": 9, "home": {"teamId": 1, "totalPoints": 42.5}, "away": {"teamId": 2, "totalPoints": 11.0}}]}
        scores = extract_live_scores(data, 9)
        self.assertEqual(scores[1]["actual_points"], 42.5)
        self.assertEqual(scores[2]["actual_points"], 11.0)

    def test_scoring_period_preferred(self):
        data = {"schedule": [
            {"matchupPeriodId": 8, "scoringPeriodId": 8, "home": {"teamId": 1, "totalPoints": 1}},
            {"matchupPeriodId": 8, "scoringPeriodId": 9, "home": {"teamId": 1, "totalPoints": 20}},
        ]}
        self.assertEqual(extract_live_scores(data, 9)[1]["actual_points"], 20)

    def test_player_ids_not_roster_positions(self):
        def entry(pid, score):
            return {"lineupSlotId": 2, "playerPoolEntry": {"player": {"id": pid, "stats": [
                {"scoringPeriodId": 9, "statSourceId": 0, "appliedTotal": score}]}}}
        data = {"schedule": [{"matchupPeriodId": 9, "home": {"teamId": 1,
            "rosterForCurrentScoringPeriod": {"entries": [entry(22, 13), entry(11, 7)]}}}]}
        live = extract_live_rosters(data, 9)
        self.assertEqual(live[1][11]["actual_points"], 7)
        league = {"teams": [{"id": 1, "name": "Example", "roster": {"entries": [
            {"lineupSlotId": 2, "playerPoolEntry": {"player": {"id": 11, "fullName": "A"}}},
            {"lineupSlotId": 2, "playerPoolEntry": {"player": {"id": 22, "fullName": "B"}}},
        ]}}]}
        teams, _ = extract_teams(league, 9, live)
        self.assertEqual([p.actual_points for p in teams[0].starters], [7, 13])


if __name__ == "__main__":
    unittest.main()
