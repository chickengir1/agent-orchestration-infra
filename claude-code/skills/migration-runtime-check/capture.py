#!/usr/bin/env python3
"""Capture view/actions/console for each reachable route in a discover-*.json.

Inputs: discover-<app>.json, side (A or B), base URL, optional auth.
Outputs: <out>/<side>/<pageId>/{capture.json, page.png, stamp.json}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SKILL_DIR = Path(__file__).resolve().parent
EXTRACT_JS = (SKILL_DIR / "extract.js").read_text(encoding="utf-8")

ANTI_ANIM = """
*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;
 transition-duration:0s!important;transition-delay:0s!important;
 caret-color:transparent!important;scroll-behavior:auto!important;}
"""


def slug(route: str) -> str:
    s = route.strip("/").replace("/", "__").replace(":", "_") or "root"
    return re.sub(r"[^A-Za-z0-9_\-]", "_", s)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("discover_json", help="Path to discover-<app>.json")
    ap.add_argument("--side", required=True, choices=["A", "B"])
    ap.add_argument("--base", required=True)
    ap.add_argument("--auth", default=None)
    ap.add_argument("--out", required=True, help="Run directory; <out>/<side>/<pageId>/ produced")
    ap.add_argument("--timeout", type=int, default=10000)
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    disc = json.loads(Path(args.discover_json).read_text(encoding="utf-8"))
    reachable = disc.get("reachable") or []
    if not reachable:
        print("[capture] no reachable routes in discover JSON", file=sys.stderr)
        return 2

    side_dir = Path(args.out).resolve() / args.side
    side_dir.mkdir(parents=True, exist_ok=True)

    auth_path = Path(args.auth).resolve() if args.auth else None
    storage_state = str(auth_path) if auth_path and auth_path.exists() else None

    summary: list[dict[str, Any]] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx_kwargs: dict[str, Any] = {
            "base_url": args.base,
            "viewport": {"width": 1440, "height": 900},
            "locale": "ko-KR",
            "timezone_id": "Asia/Seoul",
            "color_scheme": "light",
            "reduced_motion": "reduce",
        }
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
        context = browser.new_context(**ctx_kwargs)
        context.add_init_script(
            f"(()=>{{const s=document.createElement('style');s.textContent=`{ANTI_ANIM}`;"
            "const ins=()=>document.documentElement&&document.documentElement.appendChild(s);"
            "if(document.documentElement)ins();else document.addEventListener('DOMContentLoaded',ins,{once:true});})();"
        )

        for r in reachable:
            route = r["route"]
            target = r.get("seededPath") or route
            pid = slug(route)
            print(f"[{args.side}] {pid}  {target}", file=sys.stderr)

            page = context.new_page()
            console_buf: list[dict] = []
            err_buf: list[str] = []
            req_fail: list[dict] = []
            page.on("console", lambda m: console_buf.append({"type": m.type, "text": m.text}))
            page.on("pageerror", lambda e: err_buf.append(str(e)))
            page.on("requestfailed", lambda req: req_fail.append({"url": req.url, "failure": req.failure}))

            status = "ok"
            final_url = ""
            surface = {"view": {}, "actions": [], "meta": {}}
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=args.timeout)
                try:
                    page.wait_for_load_state("networkidle", timeout=args.timeout)
                except PWTimeout:
                    pass
                page.wait_for_timeout(500)
                final_url = page.url
                surface = page.evaluate(EXTRACT_JS, {"masks": []}) or surface
            except PWTimeout:
                status = "timeout"
                final_url = page.url
            except Exception as e:
                status = "error"
                err_buf.append(f"capture: {e}")
                final_url = page.url

            page_dir = side_dir / pid
            page_dir.mkdir(parents=True, exist_ok=True)
            cap = {
                "pageId": pid,
                "route": route,
                "target": target,
                "status": status,
                "finalUrl": final_url,
                "view": surface.get("view", {}),
                "actions": surface.get("actions", []),
                "meta": surface.get("meta", {}),
                "console": console_buf,
                "pageerror": err_buf,
                "requestfailed": req_fail,
            }
            (page_dir / "capture.json").write_text(json.dumps(cap, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                page.screenshot(path=str(page_dir / "page.png"), full_page=True)
            except Exception:
                pass
            page.close()
            summary.append({"pageId": pid, "status": status})

        stamp = {
            "side": args.side,
            "baseUrl": args.base,
            "discoverPath": str(Path(args.discover_json).resolve()),
            "discoverSha256": hashlib.sha256(Path(args.discover_json).read_bytes()).hexdigest(),
            "viewport": {"width": 1440, "height": 900},
            "locale": "ko-KR",
            "timezone": "Asia/Seoul",
            "colorScheme": "light",
            "browser": "chromium",
            "browserVersion": browser.version,
            "authSha256": hashlib.sha256(auth_path.read_bytes()).hexdigest() if auth_path and auth_path.exists() else None,
        }
        (side_dir / "stamp.json").write_text(json.dumps(stamp, ensure_ascii=False, indent=2), encoding="utf-8")
        context.close()
        browser.close()

    print(json.dumps({"side": args.side, "outDir": str(side_dir), "pages": summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
