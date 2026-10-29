#!/usr/bin/env python3
"""Build a static, shareable snapshot using the local ESPN credentials."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", type=int, help="ESPN scoring week; defaults to the current week")
    parser.add_argument("--simulations", type=int, default=50000)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if args.simulations < 1:
        parser.error("--simulations must be at least 1")

    command = [sys.executable, str(ROOT / "guillotine_odds.py"), "--simulations", str(args.simulations)]
    if args.week is not None:
        command += ["--week", str(args.week)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=120)
    if result.returncode:
        message = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "Could not calculate ESPN odds."
        print(message, file=sys.stderr)
        return result.returncode

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("The odds command returned invalid JSON; no snapshot was written.", file=sys.stderr)
        return 1
    if not data.get("teams"):
        print("The odds command returned no teams; no snapshot was written.", file=sys.stderr)
        return 1

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    html = (ROOT / "dashboard.html").read_text()
    marker = 'data-static-snapshot="false"'
    if marker not in html:
        print("Could not find the static snapshot marker in dashboard.html.", file=sys.stderr)
        return 1
    (out / "index.html").write_text(html.replace(marker, 'data-static-snapshot="true"', 1))
    (out / "odds.json").write_text(json.dumps(data, indent=2) + "\n")
    print(f"Static dashboard built in {out}")
    print(f"Week {data['week']}: {len(data['teams'])} active teams")
    print("The output contains team names, projections, and modeled odds. Review it before publishing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
