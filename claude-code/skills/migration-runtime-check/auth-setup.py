#!/usr/bin/env python3
"""Open headed Chromium and wait for a trigger file to save storageState.

Designed for agent-driven flow:
  1. agent launches this in background
  2. user logs into the opened window
  3. user tells agent "done"
  4. agent `touch <trigger>` → script saves storageState + exits
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="URL to open (login or app home)")
    ap.add_argument("--out", required=True, help="Output storageState JSON path")
    ap.add_argument("--trigger", default="/tmp/mrc-auth-ready", help="Trigger file path")
    ap.add_argument("--max-wait", type=int, default=900, help="Max seconds to wait")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    trigger = Path(args.trigger)
    if trigger.exists():
        trigger.unlink()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(args.base)

        print(f"[auth-setup] opened {args.base}; waiting for trigger {trigger}", file=sys.stderr, flush=True)
        deadline = time.time() + args.max_wait
        while time.time() < deadline:
            if trigger.exists():
                break
            time.sleep(0.5)
        else:
            print(f"[auth-setup] timeout after {args.max_wait}s", file=sys.stderr)
            context.close()
            browser.close()
            return 2

        context.storage_state(path=str(out))
        print(f"[auth-setup] saved {out}", file=sys.stderr)
        try:
            trigger.unlink()
        except Exception:
            pass
        context.close()
        browser.close()

    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
