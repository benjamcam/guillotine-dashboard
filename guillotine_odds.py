#!/usr/bin/env python3
"""Estimate ESPN guillotine-league last-place odds from weekly projections."""

from __future__ import annotations

import argparse
import json
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


def extract_teams(data: dict, week: int) -> tuple[list[tuple[str, list[Starter]]], list[str]]:
    teams = []
    warnings = []
    for team in data.get("teams", []) or []:
        team_name = team.get("name") or f"Team {team.get('id', '?')}"
        starters = []
        roster = team.get("roster") or {}
        for entry in roster.get("entries", []) or []:
            slot = entry.get("lineupSlotId")
            if slot in BENCH_SLOT_IDS:
                continue
            pool = entry.get("playerPoolEntry") or {}
            player = pool.get("player") or {}
            projection = get_projection(entry, week)
            if projection is None:
                warnings.append(f"No week {week} projection found for {player.get('fullName', 'unknown player')} on {team_name}.")
                continue
            starters.append(Starter(player.get("fullName", f"Player {player.get('id', '?')}"), position_for(entry), projection))
        if starters:
            teams.append((team_name, starters))
    return teams, warnings


def simulate(teams: list[tuple[str, list[Starter]]], simulations: int, seed: int | None) -> list[dict]:
    rng = random.Random(seed)
    last_count: defaultdict[str, int] = defaultdict(int)
    score_sum: defaultdict[str, float] = defaultdict(float)
    for _ in range(simulations):
        scores = {}
        for name, players in teams:
            score = 0.0
            for player in players:
                sd = POSITION_SD.get(player.position, 7.0)
                score += rng.gauss(player.projection, sd)
            scores[name] = score
            score_sum[name] += score
        low = min(scores.values())
        # Split an exact tie for last evenly instead of arbitrarily assigning it.
        tied = [name for name, score in scores.items() if abs(score - low) < 1e-9]
        for name in tied:
            last_count[name] += 1 / len(tied)
    return sorted(
        ({"team": name, "projected_points": round(sum(p.projection for p in players), 2),
          "simulated_mean": round(score_sum[name] / simulations, 2),
          "last_place_probability": round(100 * last_count[name] / simulations, 2)}
         for name, players in teams),
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

    teams, warnings = extract_teams(league, week)
    if not teams:
        raise RuntimeError("No active rosters were found. ESPN may have returned a different response shape; save/inspect the JSON before adapting the parser.")
    result = {
        "league_id": args.league,
        "season": args.season,
        "week": week,
        "calculated_at_utc": datetime.now(timezone.utc).isoformat(),
        "simulations": args.simulations,
        "model_note": "Provisional position-level standard deviations; replace with historical ESPN projection residuals for calibrated odds.",
        "teams": simulate(teams, args.simulations, args.seed),
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
