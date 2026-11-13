#!/usr/bin/env python3
"""Estimate ESPN guillotine-league last-place odds from weekly projections."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

LEAGUE_ID = "2031595556"
SEASON = 2026
BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league}"

# Starter provisional standard deviations, in fantasy points. These are fallbacks
# until we have pregame projection/actual history to calibrate from this league.
POSITION_SD = {"QB": 8.0, "RB": 7.0, "WR": 7.0, "TE": 5.0, "K": 4.0, "D/ST": 6.0}
BENCH_SLOT_IDS = {20, 21}  # ESPN football: bench and injured reserve
POSITION_NAMES = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}


@dataclass
class Starter:
    name: str
    position: str
    projection: float
    actual_points: float | None = None
    has_played: bool = False


@dataclass
class Team:
    team_id: int
    name: str
    starters: list[Starter]


def load_dotenv() -> None:
    """Read simple KEY=value lines from .env without an external dependency."""
    path = Path(__file__).with_name(".env")
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def fetch_json(url: str) -> dict:
    headers = {"User-Agent": "GuillotineOdds/0.1 (personal read-only tool)", "Accept": "application/json"}
    s2, swid = (os.getenv("ESPN_S2") or "").strip(), (os.getenv("ESPN_SWID") or "").strip()
    if s2 and swid:
        headers["Cookie"] = f"espn_s2={s2}; SWID={swid}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError("ESPN denied access. If this league is private, add ESPN_S2 and ESPN_SWID to the local .env file.") from exc
        raise RuntimeError(f"ESPN returned HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach ESPN: {exc.reason}") from exc


def league_url(season: int, league: str, views: list[str], extra: dict[str, str] | None = None) -> str:
    query: list[tuple[str, str]] = [("view", view) for view in views]
    if extra:
        query.extend(extra.items())
    return BASE.format(season=season, league=league) + "?" + urllib.parse.urlencode(query)


def get_projection(entry: dict, week: int) -> float | None:
    pool = entry.get("playerPoolEntry") or {}
    player = pool.get("player") or {}
    candidates = []
    stat_rows = pool.get("stats") or player.get("stats") or []
    if isinstance(stat_rows, dict):
        stat_rows = list(stat_rows.values())
    for stat in stat_rows:
        if stat.get("scoringPeriodId") != week:
            continue
        # ESPN response variants have used both 1 and 2 for projections.
        if stat.get("statTypeId") not in (1, 2) and stat.get("statSourceId") not in (1, 2):
            continue
        total = stat.get("appliedTotal")
        if total is None:
            continue
        candidates.append((stat.get("statTypeId", -1), float(total)))
    if not candidates:
        return None
    # Prefer a week-level projection over a season/remainder projection.
    candidates.sort(key=lambda pair: pair[0] == 2, reverse=True)
    return candidates[0][1]


def position_for(entry: dict) -> str:
    player = ((entry.get("playerPoolEntry") or {}).get("player") or {})
    position = player.get("defaultPositionId")
    return POSITION_NAMES.get(position, "FLEX")


def extract_teams(data: dict, week: int, live_rosters: dict[int, list[dict]] | None = None) -> tuple[list[Team], list[str]]:
    teams = []
    warnings = []
    for team in data.get("teams", []) or []:
        team_name = team.get("name") or f"Team {team.get('id', '?')}"
        starters = []
        roster = team.get("roster") or {}
        live_entries = (live_rosters or {}).get(int(team.get("id", 0)), [])
        entries = roster.get("entries", []) or []
        for entry_index, entry in enumerate(entries):
            slot = entry.get("lineupSlotId")
            if slot in BENCH_SLOT_IDS:
                continue
            pool = entry.get("playerPoolEntry") or {}
            player = pool.get("player") or {}
            projection = get_projection(entry, week)
            if projection is None:
                warnings.append(f"No week {week} projection found for {player.get('fullName', 'unknown player')} on {team_name}.")
                projection = 0.0
            live_entry = live_entries[entry_index] if entry_index < len(live_entries) else {}
            if live_entry.get("lineup_slot_id") != slot:
                live_entry = {}
            actual_points = live_entry.get("actual_points")
            starters.append(Starter(
                player.get("fullName", f"Player {player.get('id', '?')}"),
                position_for(entry),
                projection,
                actual_points,
                bool(live_entry.get("has_played")),
            ))
        if starters:
            teams.append(Team(int(team.get("id", 0)), team_name, starters))
    return teams, warnings


def extract_live_scores(data: dict, week: int) -> dict[int, dict[str, float | None]]:
    """Read current and live-projected team totals from ESPN's matchup score view."""
    scores: dict[int, dict[str, float | None]] = {}
    for matchup in data.get("schedule", []) or []:
        try:
            if int(matchup.get("matchupPeriodId", -1)) != week:
                continue
        except (TypeError, ValueError):
            continue

        sides = matchup.get("teams") or []
        if not sides:
            sides = [side for side in (matchup.get("home"), matchup.get("away")) if side]
        for side in sides:
            team_id = side.get("teamId")
            if team_id is None:
                continue
            actual = side.get("totalPoints")
            live_projection = side.get("totalProjectedPointsLive")
            scores[int(team_id)] = {
                "actual_points": float(actual) if actual is not None else None,
                "live_projected_points": float(live_projection) if live_projection is not None else None,
            }
    return scores


def extract_live_rosters(data: dict, week: int) -> dict[int, list[dict]]:
    """Read actual individual scores from ESPN's current matchup rosters."""
    rosters: dict[int, list[dict]] = {}
    for matchup in data.get("schedule", []) or []:
        try:
            if int(matchup.get("matchupPeriodId", -1)) != week:
                continue
        except (TypeError, ValueError):
            continue
        for side in matchup.get("teams") or []:
            try:
                team_id = int(side.get("teamId"))
            except (TypeError, ValueError):
                continue
            roster = (side.get("rosterForCurrentScoringPeriod") or {}).get("entries") or []
            player_rows = []
            for entry in roster:
                player = ((entry.get("playerPoolEntry") or {}).get("player") or {})
                stats = player.get("stats") or []
                if isinstance(stats, dict):
                    stats = list(stats.values())
                actual = next((stat for stat in stats
                               if stat.get("scoringPeriodId") == week
                               and str(stat.get("statSourceId")) == "0"), None)
                player_rows.append({
                    "lineup_slot_id": entry.get("lineupSlotId"),
                    "counts_for_team": entry.get("lineupSlotId") not in BENCH_SLOT_IDS,
                    "has_played": actual is not None,
                    "actual_points": float(actual.get("appliedTotal", 0)) if actual else None,
                })
            rosters[team_id] = player_rows
    return rosters


def simulate(teams: list[Team], live_scores: dict[int, dict[str, float | None]], simulations: int, seed: int | None) -> list[dict]:
    rng = random.Random(seed)
    last_count: defaultdict[str, int] = defaultdict(int)
    score_sum: defaultdict[str, float] = defaultdict(float)
    projections: dict[str, float] = {}
    score_sigmas: dict[str, float] = {}
    actual_scores: dict[str, float | None] = {}
    live_projected_scores: dict[str, float | None] = {}

    for team in teams:
        pregame_projection = sum(player.projection for player in team.starters)
        score_data = live_scores.get(team.team_id, {})
        actual = score_data.get("actual_points")
        if actual is None:
            # Fall back to actual starter scores also shown in the lineup.
            # This covers ESPN responses with player actuals but no team total.
            played_scores = [player.actual_points for player in team.starters
                             if player.has_played and player.actual_points is not None]
            if played_scores:
                actual = sum(played_scores)
        live_projection = score_data.get("live_projected_points")
        # ESPN publishes its live team projection while games are underway. Use it
        # as the simulation mean, and reduce uncertainty as the remaining projected
        # points shrink. Before kickoff, retain the regular player-projection model.
        projections[team.name] = (
            max(live_projection, actual) if actual is not None else live_projection
        ) if live_projection is not None else pregame_projection
        base_sigma = math.sqrt(sum(POSITION_SD.get(p.position, 7.0) ** 2 for p in team.starters))
        if live_projection is not None and actual is not None:
            remaining_fraction = max(0.0, min(1.0, (projections[team.name] - actual) / max(projections[team.name], 1.0)))
            base_sigma *= math.sqrt(remaining_fraction)
        score_sigmas[team.name] = base_sigma
        actual_scores[team.name] = actual
        live_projected_scores[team.name] = projections[team.name] if live_projection is not None else None

    for _ in range(simulations):
        scores = {}
        for team in teams:
            name = team.name
            score = rng.gauss(projections[name], score_sigmas[name])
            scores[name] = score
            score_sum[name] += score
        low = min(scores.values())
        # Split an exact tie for last evenly instead of arbitrarily assigning it.
        tied = [name for name, score in scores.items() if abs(score - low) < 1e-9]
        for name in tied:
            last_count[name] += 1 / len(tied)
    return sorted(
        ({"team": team.name,
          "projected_points": round(sum(p.projection for p in team.starters), 2),
          "live_projected_points": round(live_projected_scores[team.name], 2) if live_projected_scores[team.name] is not None else None,
          "display_projected_points": round(projections[team.name], 2),
          "actual_points": round(actual_scores[team.name], 2) if actual_scores[team.name] is not None else None,
          "players_played": sum(1 for player in team.starters if player.has_played),
          "players_remaining": sum(1 for player in team.starters if not player.has_played),
          "lineup": [{"name": player.name,
                      "position": player.position,
                      "projection": round(player.projection, 2),
                      "actual_points": round(player.actual_points, 2) if player.actual_points is not None else None,
                      "has_played": player.has_played}
                     for player in team.starters],
          "simulated_mean": round(score_sum[team.name] / simulations, 2),
          "last_place_probability": round(100 * last_count[team.name] / simulations, 2)}
         for team in teams),
        key=lambda row: row["last_place_probability"], reverse=True,
    )


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default=LEAGUE_ID)
    parser.add_argument("--season", type=int, default=SEASON)
    parser.add_argument("--week", type=int, help="ESPN scoring period; defaults to ESPN's current scoring period")
    parser.add_argument("--simulations", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    league = fetch_json(league_url(args.season, args.league, ["mSettings", "mTeam", "mRoster"]))
    week = args.week or (league.get("status") or {}).get("scoringPeriodId") or league.get("scoringPeriodId")
    if not week:
        raise RuntimeError("Could not determine ESPN scoring period. Pass --week N.")
    week = int(week)
    projections = fetch_json(league_url(args.season, args.league, ["kona_player_info"], {"scoringPeriodId": str(week)}))
    live_data = fetch_json(league_url(args.season, args.league, ["mMatchupScore"], {"scoringPeriodId": str(week), "matchupPeriodId": str(week)}))
    # Most responses contain a players array; some league-context responses instead
    # place stats directly on roster entries. Merge player info into roster entries.
    projection_players = {}
    for wrapper in projections.get("players", []) or []:
        pool = wrapper.get("playerPoolEntry") or wrapper
        player = pool.get("player") or pool
        pid = player.get("id")
        if pid is not None:
            projection_players[pid] = pool
    if projection_players:
        for team in league.get("teams", []) or []:
            for entry in ((team.get("roster") or {}).get("entries", []) or []):
                pid = ((entry.get("playerPoolEntry") or {}).get("player") or {}).get("id")
                if pid in projection_players:
                    entry["playerPoolEntry"] = projection_players[pid]

    live_scores = extract_live_scores(live_data, week)
    live_rosters = extract_live_rosters(live_data, week)
    # Some ESPN mMatchupScore responses omit the team-level totalPoints even
    # though player stats are present. Rebuild that total from actual starters
    # only; bench scores must never count toward a team's total.
    for team_id, player_rows in live_rosters.items():
        score = live_scores.setdefault(team_id, {})
        if score.get("actual_points") is not None:
            continue
        played_starters = [row for row in player_rows
                           if row.get("counts_for_team") and row.get("has_played")
                           and row.get("actual_points") is not None]
        if played_starters:
            score["actual_points"] = sum(row["actual_points"] for row in played_starters)
    teams, warnings = extract_teams(league, week, live_rosters)
    if not teams:
        raise RuntimeError("No active rosters were found. ESPN may have returned a different response shape; save/inspect the JSON before adapting the parser.")
    result = {
        "league_id": args.league,
        "season": args.season,
        "week": week,
        "calculated_at_utc": datetime.now(timezone.utc).isoformat(),
        "simulations": args.simulations,
        "model_note": "Provisional position-level standard deviations; replace with historical ESPN projection residuals for calibrated odds.",
        "live_scoring_active": any((score.get("actual_points") or 0) > 0 for score in live_scores.values()),
        "teams": simulate(teams, live_scores, args.simulations, args.seed),
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
