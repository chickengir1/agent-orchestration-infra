#!/usr/bin/env python3
"""Generate a check-plan draft from a discover JSON + context metadata.

Reads:
    discover-<app>.json (output of discover.py)

Writes (stdout):
    check-plan JSON conforming to check-plan.schema.json

Usage:
    python3 plan_helper.py \
        --discover discover-libs-app.json \
        --app libs-app \
        --baseline-branch dev \
        --candidate-branch sbe-web-v4-angular-migration \
        --base-url http://localhost:4200 \
        --auth .auth/libs-app.json \
        --context-id group-2-default \
        --vars group_id=2 \
        --labels "유료 학교,설정 가능 계정" \
        --metadata-json '{"접근 대상":"2번 그룹","그룹 내 권한":"관리자"}' \
        --known-unstable "lds-bars,lds-css,ngucarousel,Fetching" \
        > check-plan-libs-app.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SLUG_RE = re.compile(r"[^a-z0-9-]+")
PLACEHOLDER_RE = re.compile(r":[A-Za-z_][A-Za-z0-9_]*")


def slug(s: str) -> str:
    s = s.strip("/").replace("/", "-").replace(":", "")
    return SLUG_RE.sub("-", s.lower()).strip("-") or "root"


def parse_kv(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"expected key=value, got {pair!r}")
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


def apply_vars(route_template: str, vars_dict: dict[str, str], fallback: str) -> str:
    out = route_template
    for k, v in vars_dict.items():
        out = out.replace(f":{k}", v)
    if PLACEHOLDER_RE.search(out):
        return fallback
    return out


def matches_any(s: str, patterns: list[str]) -> bool:
    return any(p in s for p in patterns)


def build_plan(args: argparse.Namespace) -> dict:
    discover = json.loads(Path(args.discover).read_text(encoding="utf-8"))
    reachable = discover.get("reachable") or []

    vars_dict = parse_kv(args.vars)
    labels = parse_csv(args.labels)
    metadata: dict = {}
    if args.metadata_json:
        try:
            metadata = json.loads(args.metadata_json)
        except json.JSONDecodeError as e:
            raise SystemExit(f"--metadata-json is not valid JSON: {e}") from e
        if not isinstance(metadata, dict):
            raise SystemExit("--metadata-json must be a JSON object")
    known_unstable = parse_csv(args.known_unstable)
    must_cover = parse_csv(args.must_cover)
    skip = parse_csv(args.skip)

    scenarios: list[dict] = []
    seen_ids: set[str] = set()
    for entry in reachable:
        route = entry.get("route") or ""
        seeded = entry.get("seededPath") or route
        if must_cover and not matches_any(route, must_cover):
            continue
        if skip and matches_any(route, skip):
            continue
        concrete = apply_vars(route, vars_dict, seeded)
        scenario_id = f"{slug(route)}-{args.context_id}"
        if scenario_id in seen_ids:
            continue
        seen_ids.add(scenario_id)
        scenarios.append({
            "id": scenario_id,
            "reason": "auto-generated from discover; review before approval",
            "routeTemplate": route,
            "context": args.context_id,
            "path": concrete,
            "expectedFinalPath": concrete,
            "compare": ["page-capture", "actions", "console-runtime"],
        })

    plan = {
        "app": args.app,
        "intent": args.intent or "Migration runtime parity check (auto-draft)",
        "baseline": {"branch": args.baseline_branch, "baseUrl": args.base_url},
        "candidate": {"branch": args.candidate_branch, "baseUrl": args.base_url},
        "auth": {
            "storageState": args.auth,
            "actor": args.actor or "default",
            "role": args.role or "unknown",
        },
        "knownUnstable": known_unstable,
        "contexts": [
            {
                "id": args.context_id,
                "auth": None,
                "vars": vars_dict,
                "labels": labels,
                "metadata": metadata,
            }
        ],
        "scenarios": scenarios,
    }
    return plan


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", required=True)
    ap.add_argument("--app", required=True)
    ap.add_argument("--baseline-branch", required=True)
    ap.add_argument("--candidate-branch", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--auth", default=None, help="storageState path or omit for unauthenticated")
    ap.add_argument("--actor", default=None)
    ap.add_argument("--context-id", required=True)
    ap.add_argument("--vars", default=None, help="comma-separated k=v pairs")
    ap.add_argument("--labels", default=None, help="comma-separated opaque string tags")
    ap.add_argument("--metadata-json", dest="metadata_json", default=None,
                    help="JSON object string; preserved verbatim in contexts[].metadata")
    ap.add_argument("--role", default=None, help="value for plan.auth.role; defaults to 'unknown'")
    ap.add_argument("--known-unstable", default=None, help="comma-separated substring patterns")
    ap.add_argument("--must-cover", default=None, help="comma-separated route substrings to keep")
    ap.add_argument("--skip", default=None, help="comma-separated route substrings to drop")
    ap.add_argument("--intent", default=None)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    plan = build_plan(args)
    json.dump(plan, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
