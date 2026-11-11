"""Shared concurrency runner: fires a scenario's contested requests and checks its rule.

    uv run python tests/concurrency/run.py --scenario same-order --mode real
    uv run python tests/concurrency/run.py --scenario last-portions --mode naive

Each scenario is a module next to this file (A: same_order.py and vehicle_limit.py,
B: last_portions.py) with
    fixture() -> ctx                              reset and create the data in PostgreSQL
    await attack(ctx, mode, base_url) -> codes    fire the requests at the same time
    check(ctx) -> (holds, detail)                 does the rule hold in PostgreSQL?
Exit code: 1 if the rule is broken, or if real mode got any 5xx; otherwise 0.
"""

import argparse
import asyncio
import importlib
import sys

# Scenario name on the command line -> module in this folder.
SCENARIOS = {
    "same-order": "same_order",
    "last-portions": "last_portions",
    "vehicle-limit": "vehicle_limit",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    parser.add_argument("--mode", required=True, choices=["naive", "real"])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    try:
        scenario = importlib.import_module(SCENARIOS[args.scenario])
    except ModuleNotFoundError as exc:
        print(f"scenario {args.scenario} is not written yet ({exc.name})")
        return 2

    ctx = scenario.fixture()
    codes = asyncio.run(scenario.attack(ctx, args.mode, args.base_url))
    holds, detail = scenario.check(ctx)

    succeeded = sum(1 for c in codes if 200 <= c < 300)
    refused = sum(1 for c in codes if 400 <= c < 500)
    failed = sum(1 for c in codes if c >= 500)
    print(f"scenario:   {args.scenario}")
    print(f"mode:       {args.mode}")
    print(f"requests:   {len(codes)}")
    print(f"succeeded:  {succeeded} (2xx)")
    print(f"refused:    {refused} (4xx)")
    print(f"failed:     {failed} (5xx)")
    print(f"rule holds: {'yes' if holds else 'NO'} ({detail})")

    # In naive mode a 5xx is the race showing up; in real mode it is a bug.
    broken = not holds or (args.mode == "real" and failed > 0)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
