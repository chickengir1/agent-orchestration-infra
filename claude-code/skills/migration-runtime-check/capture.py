#!/usr/bin/env python3
"""Capture runtime surface for every scenario in a check-plan.

Inputs:
    check-plan JSON (see check-plan.schema.json)
    side (A or B)
    output run directory

Outputs:
    <out>/<side>/stamp.json
    <out>/<side>/pages/<scenarioId>/{capture.json, page.png}

pageId is always scenarioId. Route-based / discover-positional capture is
not supported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SKILL_DIR = Path(__file__).resolve().parent
EXTRACT_JS = (SKILL_DIR / "extract.js").read_text(encoding="utf-8")

ANTI_ANIM = """
*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;
 transition-duration:0s!important;transition-delay:0s!important;
 caret-color:transparent!important;scroll-behavior:auto!important;}
"""


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, help="Path to check-plan JSON")
    ap.add_argument("--side", required=True, choices=["A", "B"])
    ap.add_argument("--out", required=True, help="Run directory; <out>/<side>/... is produced")
    ap.add_argument("--timeout", type=int, default=10000)
    return ap.parse_args()


def base_url_for_side(plan: dict, side: str) -> str:
    key = "baseline" if side == "A" else "candidate"
    return plan[key]["baseUrl"].rstrip("/")


def url_path(url: str) -> str:
    try:
        return urlsplit(url or "").path or "/"
    except ValueError:
        return ""


def resolve_storage_state(plan: dict, context_meta: dict) -> str | None:
    if context_meta.get("auth"):
        return context_meta["auth"]
    return plan.get("auth", {}).get("storageState")


UNSAFE_SELECTOR_PATTERNS = (".ng-", ".cdk-", ".mat-mdc-", "._ngcontent", "._nghost")


def is_unsafe_selector(selector: str) -> bool:
    return any(p in (selector or "") for p in UNSAFE_SELECTOR_PATTERNS)


def make_action_result(
    *,
    action_id: str,
    step: int,
    step_type: str,
    selector: str,
    status: str,
    error: str | None = None,
    before_path: str = "",
    after_path: str = "",
) -> dict:
    """Build the action.json payload written next to each step snapshot.

    status ∈ {ok, selector-not-found, selector-ambiguous, unsafe-selector,
              navigation-detected, error, skipped}
    """
    return {
        "actionId": action_id,
        "step": step,
        "type": step_type,
        "selector": selector,
        "status": status,
        "error": error,
        "beforeFinalPath": before_path,
        "afterFinalPath": after_path,
    }


def run_action_steps(page, action: dict, base_dir: Path, extract_js: str) -> None:
    """Execute an action's steps in order, write step snapshots under base_dir.

    base_dir = <pageDir>/actions/<actionId>. step-1, step-2, ... subdirs created.
    Stops on first non-ok status. Locator policy: count() must be exactly 1.
    """
    snapshot_each = action.get("snapshotAfterEachStep", True)
    aborted = False
    for i, step in enumerate(action["steps"], start=1):
        step_dir = base_dir / f"step-{i}"
        step_dir.mkdir(parents=True, exist_ok=True)
        sel = step["selector"]
        before_path = url_path(page.url)
        if aborted:
            result = make_action_result(
                action_id=action["id"], step=i, step_type=step["type"], selector=sel,
                status="skipped", error="previous step did not complete",
                before_path=before_path, after_path=before_path,
            )
            (step_dir / "action.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            continue

        # Unsafe selector guard — runs before any locator query.
        if is_unsafe_selector(sel):
            result = make_action_result(
                action_id=action["id"], step=i, step_type=step["type"], selector=sel,
                status="unsafe-selector",
                error="generated/framework class selector is not allowed for safe-ui-action",
                before_path=before_path, after_path=before_path,
            )
            (step_dir / "action.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            aborted = True
            continue

        status = "ok"
        error: str | None = None
        try:
            count = page.locator(sel).count()
        except Exception as e:
            count = -1
            status = "error"
            error = f"selector evaluation failed: {e}"
        if status == "ok":
            if count == 0:
                status = "selector-not-found"
                error = "0 elements matched"
            elif count > 1:
                status = "selector-ambiguous"
                error = f"{count} elements matched; expected exactly 1"

        if status == "ok":
            try:
                if step["type"] == "click":
                    page.locator(sel).click(timeout=5000)
                else:
                    status = "error"
                    error = f"unsupported step type: {step['type']}"
            except Exception as e:
                status = "error"
                error = f"action execution failed: {e}"

        if status == "ok":
            page.wait_for_timeout(300)

        after_path = url_path(page.url)

        # Navigation guard — safe-ui-action must not change finalPath.
        if status == "ok" and before_path != after_path:
            status = "navigation-detected"
            error = f"safe-ui-action changed finalPath from {before_path} to {after_path}"

        result = make_action_result(
            action_id=action["id"], step=i, step_type=step["type"], selector=sel,
            status=status, error=error,
            before_path=before_path, after_path=after_path,
        )
        (step_dir / "action.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if snapshot_each:
            try:
                surface = page.evaluate(extract_js, {"masks": []}) or {}
                step_cap = {
                    "view": surface.get("view", {}),
                    "actions": surface.get("actions", []),
                    "meta": surface.get("meta", {}),
                    "finalUrl": page.url,
                    "finalPath": after_path,
                }
                (step_dir / "capture.json").write_text(
                    json.dumps(step_cap, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as e:
                # Snapshot failure does not abort the action sequence; recorded as note in action.json
                result["error"] = (result.get("error") or "") + f" | snapshot failed: {e}"
                (step_dir / "action.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            try:
                page.screenshot(path=str(step_dir / "page.png"), full_page=True)
            except Exception:
                pass

        if status != "ok":
            aborted = True


def main() -> int:
    args = parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    scenarios: list[dict] = plan.get("scenarios") or []
    if not scenarios:
        print("[capture] check-plan has no scenarios", file=sys.stderr)
        return 2
    contexts_map: dict[str, dict] = {ctx["id"]: ctx for ctx in plan.get("contexts", [])}
    base = base_url_for_side(plan, args.side)

    side_dir = Path(args.out).resolve() / args.side
    side_dir.mkdir(parents=True, exist_ok=True)
    pages_root = side_dir / "pages"
    pages_root.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, Any]] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        pw_ctxs: dict[str | None, Any] = {}

        def get_ctx(storage_state: str | None):
            if storage_state in pw_ctxs:
                return pw_ctxs[storage_state]
            kwargs: dict[str, Any] = {
                "base_url": base,
                "viewport": {"width": 1440, "height": 900},
                "locale": "ko-KR",
                "timezone_id": "Asia/Seoul",
                "color_scheme": "light",
                "reduced_motion": "reduce",
            }
            if storage_state:
                kwargs["storage_state"] = storage_state
            c = browser.new_context(**kwargs)
            c.add_init_script(
                f"(()=>{{const s=document.createElement('style');s.textContent=`{ANTI_ANIM}`;"
                "const ins=()=>document.documentElement&&document.documentElement.appendChild(s);"
                "if(document.documentElement)ins();else document.addEventListener('DOMContentLoaded',ins,{once:true});})();"
            )
            pw_ctxs[storage_state] = c
            return c

        for sc in scenarios:
            scenario_id = sc["id"]
            ctx_id = sc["context"]
            ctx_meta = contexts_map.get(ctx_id, {"vars": {}, "labels": {}})
            storage_state = resolve_storage_state(plan, ctx_meta)
            target_path = sc["path"]
            expected = sc["expectedFinalPath"]
            print(f"[{args.side}] {scenario_id}  {target_path}", file=sys.stderr)

            pw_ctx = get_ctx(storage_state)
            page = pw_ctx.new_page()
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
                page.goto(target_path, wait_until="domcontentloaded", timeout=args.timeout)
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

            page_dir = pages_root / scenario_id
            page_dir.mkdir(parents=True, exist_ok=True)
            cap = {
                "scenarioId": scenario_id,
                "routeTemplate": sc["routeTemplate"],
                "contextId": ctx_id,
                "vars": ctx_meta.get("vars", {}),
                "labels": list(ctx_meta.get("labels") or []),
                "metadata": ctx_meta.get("metadata") or {},
                "auth": storage_state,
                "path": target_path,
                "expectedFinalPath": expected,
                "status": status,
                "finalUrl": final_url,
                "finalPath": url_path(final_url),
                "meta": surface.get("meta", {}),
                "view": surface.get("view", {}),
                "actions": surface.get("actions", []),
                "console": console_buf,
                "pageerror": err_buf,
                "requestfailed": req_fail,
            }
            (page_dir / "capture.json").write_text(
                json.dumps(cap, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            try:
                page.screenshot(path=str(page_dir / "page.png"), full_page=True)
            except Exception:
                pass

            scenario_actions: list[dict] = sc.get("actions") or []
            for action in scenario_actions:
                action_dir = page_dir / "actions" / action["id"]
                action_dir.mkdir(parents=True, exist_ok=True)
                try:
                    run_action_steps(page, action, action_dir, EXTRACT_JS)
                except Exception as e:
                    err_buf.append(f"action {action.get('id')} crashed: {e}")
            page.close()
            summary.append({
                "scenarioId": scenario_id,
                "status": status,
                "finalPath": cap["finalPath"],
                "expected": expected,
                "reachedExpected": cap["finalPath"] == expected,
            })

        stamp = {
            "side": args.side,
            "baseUrl": base,
            "planPath": str(Path(args.plan).resolve()),
            "planSha256": hashlib.sha256(Path(args.plan).read_bytes()).hexdigest(),
            "viewport": {"width": 1440, "height": 900},
            "locale": "ko-KR",
            "timezone": "Asia/Seoul",
            "colorScheme": "light",
            "browser": "chromium",
            "browserVersion": browser.version,
        }
        (side_dir / "stamp.json").write_text(
            json.dumps(stamp, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for c in pw_ctxs.values():
            c.close()
        browser.close()

    print(json.dumps({
        "side": args.side,
        "outDir": str(side_dir),
        "scenarios": summary,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
