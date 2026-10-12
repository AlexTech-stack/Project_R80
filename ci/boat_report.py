#!/usr/bin/env python3
"""Summarise a BoAt report folder as Markdown (for $GITHUB_STEP_SUMMARY or the terminal).

    python3 ci/boat_report.py <reports dir> [--title TEXT] [--issue-template]

Reads each <reports dir>/*/report.json (one per test) and, for tests that did not pass,
the end of their stdout.txt. With --issue-template it adds a draft entry in the format
of BoAt's test/foundIssues.md (what was done / expected / what happened), to fill in
once it is clear the failure is caused by BoAt.

Uses report.json, not report.junit.xml: the JUnit file is empty for script tests
(AlexTech-stack/BoAt#50). Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TAIL = 20


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reports")
    ap.add_argument("--title", default="BoAt smoke tests")
    ap.add_argument("--issue-template", action="store_true")
    a = ap.parse_args()

    runs = []
    for f in sorted(Path(a.reports).glob("*/report.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out = f.parent / "stdout.txt"
        runs.append({
            "id": d.get("test", {}).get("id", f.parent.name),
            "name": d.get("test", {}).get("name", ""),
            "verdict": d.get("verdict", "?"),
            "ms": d.get("execution", {}).get("duration_ms"),
            "stdout": out.read_text(encoding="utf-8", errors="replace") if out.exists() else "",
        })

    print(f"### {a.title}\n")
    if not runs:
        print("No BoAt reports were written: the environment did not come up. See the job log and `logs/`.\n")
        return 0
    failed = [r for r in runs if r["verdict"] != "PASS"]
    print(f"{len(runs) - len(failed)}/{len(runs)} passed\n")
    print("| Test | Name | Verdict | ms |\n|---|---|---|---|")
    for r in runs:
        print(f"| {r['id']} | {r['name']} | {'✅' if r['verdict'] == 'PASS' else '❌'} {r['verdict']} | {r['ms']} |")
    print()
    for r in failed:
        tail = "\n".join(r["stdout"].rstrip().splitlines()[-TAIL:])
        print(f"<details><summary>{r['id']} output (last {TAIL} lines)</summary>\n\n```\n{tail}\n```\n</details>\n")

    if a.issue_template and failed:
        ids = ", ".join(r["id"] for r in failed)
        print("#### Draft for BoAt's `test/foundIssues.md` (only if the cause is in BoAt)\n")
        print("```markdown")
        print(f"## <date>: <one-line summary> ({ids} fail)\n")
        print("**What I did**\n\n- BoAt: <version and commit from the job summary>\n"
              "- Project R80 `ci/run_boat_sil.sh --install` with BOAT_VERSION=<...>, Ubuntu 24.04 runner\n")
        print("**What I expected**\n\nAll R80 smoke tests pass, as they do with the BoAt release in `ci/boat.version`.\n")
        print(f"**What actually happened**\n\n{ids} failed. <exact error text from the output above>")
        print("```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
