"""Run the gold-set evaluation from the command line.

    python evaluate.py            # print the report
    python evaluate.py --json     # machine-readable output

Exits non-zero if the run itself failed, so it can be wired into CI.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services import evaluation  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Evaluate extraction accuracy against the gold set.")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--goldset", default=str(evaluation.GOLDSET_DIR), help="path to the gold set directory")
    parser.add_argument("--min-case-accuracy", type=float, default=None,
                        help="fail the run if case accuracy drops below this fraction")
    args = parser.parse_args()

    report = evaluation.run_all(Path(args.goldset))

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(evaluation.format_report(report))

    if report.get("error"):
        return 2
    threshold = args.min_case_accuracy
    if threshold is not None:
        accuracy = report.get("case_accuracy")
        if accuracy is None or accuracy < threshold:
            print(f"\nFAIL: case accuracy {accuracy} is below the required {threshold}")
            return 1
        print(f"\nPASS: case accuracy {accuracy} meets the required {threshold}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
