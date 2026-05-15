#!/usr/bin/env python3
"""Capture runtime surface for every scenario in a check-plan.

Inputs:
    check-plan JSON (see check-plan.schema.json)
    side (A or B)
    output run directory

Outputs:
    <out>/<branchName>/stamp.json
    <out>/<branchName>/<contextId>/pages/<scenarioId>/{capture.json, page.png}
    <out>/<branchName>/<contextId>/pages/<scenarioId>/flows/<flowId>/step-<N>/{step.json,capture.json,page.png}

pageId is always scenarioId. Route-based / discover-positional capture is
not supported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from contract import load_check_plan

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
    ap.add_argument("--out", required=True, help="Run directory; <out>/<branchName>/... is produced")
    ap.add_argument("--timeout", type=int, default=10000)
    ap.add_argument("--retries", type=int, default=1, help="Retry-candidate passes after a full side capture")
    ap.add_argument("--settled-snapshot-ms", type=int, default=1000,
                    help="Write a second settled snapshot after this delay; 0 disables it")
    return ap.parse_args()


def base_url_for_side(plan: dict, side: str) -> str:
    key = "baseline" if side == "A" else "candidate"
    return plan[key]["baseUrl"].rstrip("/")


def role_for_side(side: str) -> str:
    return "baseline" if side == "A" else "candidate"


def slug_dir_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return slug or "unknown"


def output_dir_name_for_side(plan: dict, side: str) -> str:
    role = role_for_side(side)
    branch = str(plan.get(role, {}).get("branch") or side)
    branch_slug = slug_dir_name(branch)
    other_role = "candidate" if role == "baseline" else "baseline"
    other_branch = str(plan.get(other_role, {}).get("branch") or "")
    if role == "candidate" and branch_slug == slug_dir_name(other_branch):
        return f"{branch_slug}-candidate"
    return branch_slug


def url_path(url: str) -> str:
    try:
        return urlsplit(url or "").path or "/"
    except ValueError:
        return ""


def absolute_target_url(base: str, path: str) -> str:
    if re.match(r"^https?://", path or ""):
        return path
    return f"{base.rstrip('/')}/{(path or '').lstrip('/')}"


def snapshot_page(page, extract_js: str) -> dict:
    surface = page.evaluate(extract_js, {"masks": []}) or {}
    return {
        "finalUrl": page.url,
        "finalPath": url_path(page.url),
        "meta": surface.get("meta", {}),
        "view": surface.get("view", {}),
        "actions": surface.get("actions", []),
    }


def capture_scenario_page(page, *, target_url: str, timeout: int) -> tuple[str, dict, list[dict]]:
    attempts: list[dict] = []
    status = "ok"
    surface = {"finalUrl": page.url, "finalPath": url_path(page.url), "meta": {}, "view": {}, "actions": []}
    try:
        page.goto(target_url, wait_until="domcontentloaded", timeout=timeout)
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
        except PWTimeout:
            pass
        page.wait_for_timeout(500)
        stability_timeout = min(max(timeout // 2, 2000), 5000)
        final_url = wait_for_route_stability(page, timeout_ms=stability_timeout)
        surface = snapshot_page(page, EXTRACT_JS)
        surface["finalUrl"] = surface.get("finalUrl") or final_url
        surface["finalPath"] = surface.get("finalPath") or url_path(final_url)
    except PWTimeout:
        status = "timeout"
        surface = {"finalUrl": page.url, "finalPath": url_path(page.url), "meta": {}, "view": {}, "actions": []}
    except Exception as e:
        status = "error"
        surface = {"finalUrl": page.url, "finalPath": url_path(page.url), "meta": {}, "view": {}, "actions": []}
        attempts.append({
            "attempt": 1,
            "status": status,
            "finalUrl": surface["finalUrl"],
            "finalPath": surface["finalPath"],
            "error": str(e),
        })
        return status, surface, attempts

    attempts.append({
        "attempt": 1,
        "status": status,
        "finalUrl": surface["finalUrl"],
        "finalPath": surface["finalPath"],
        "whiteScreen": len(surface.get("actions") or []) == 0,
    })
    return status, surface, attempts


def _matches_known_unstable_requestfailure(entry: dict, known_unstable: list[str]) -> bool:
    if not known_unstable:
        return False
    haystack = f"{entry.get('url', '')} {entry.get('failure', '')}"
    return any(pattern and pattern in haystack for pattern in known_unstable)


def is_retry_candidate(cap: dict, known_unstable: list[str] | None = None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    unstable = known_unstable or []
    if cap.get("status") != "ok":
        reasons.append(f"status={cap.get('status')}")
    if cap.get("finalUrl") == "about:blank" or cap.get("finalPath") == "blank":
        reasons.append("about:blank")
    if cap.get("expectedFinalPath") and cap.get("finalPath") != cap.get("expectedFinalPath"):
        reasons.append("expectedFinalPath-mismatch")
    if len(cap.get("actions") or []) == 0:
        reasons.append("zero-actions")
    if cap.get("pageerror"):
        reasons.append("pageerror")
    relevant_requestfailed = [
        entry for entry in (cap.get("requestfailed") or [])
        if not _matches_known_unstable_requestfailure(entry, unstable)
    ]
    if relevant_requestfailed:
        reasons.append("requestfailed")
    return bool(reasons), reasons


def wait_for_route_stability(
    page,
    *,
    stability_ms: int = 400,
    timeout_ms: int = 2000,
    poll_ms: int = 50,
    sleep: Callable[[int], None] | None = None,
    now: Callable[[], float] | None = None,
) -> str:
    """Wait until page.url stays unchanged for stability_ms or timeout_ms elapses.

    Bounded by timeout_ms. about:blank is never treated as stable; if the URL
    is still about:blank when the deadline fires, the current URL is returned
    anyway. Used after goto/networkidle fallback so client-side redirects /
    route guards have settled before evaluate/screenshot.
    """
    do_sleep = sleep if sleep is not None else page.wait_for_timeout
    clock = now if now is not None else time.monotonic
    deadline = clock() + timeout_ms / 1000.0
    last_url = page.url
    last_change = clock()
    while True:
        do_sleep(poll_ms)
        current = page.url
        if current != last_url:
            last_url = current
            last_change = clock()
        timed_out = clock() >= deadline
        if timed_out:
            return current
        is_blank = (current or "").startswith("about:blank")
        stable_for_ms = (clock() - last_change) * 1000.0
        if not is_blank and stable_for_ms >= stability_ms:
            return current


def resolve_storage_state(plan: dict, context_meta: dict) -> str | None:
    if context_meta.get("auth"):
        return context_meta["auth"]
    return plan.get("auth", {}).get("storageState")


UNSAFE_SELECTOR_PATTERNS = (".ng-", ".cdk-", ".mat-mdc-", "_ngcontent", "_nghost")


def is_unsafe_selector(selector: str) -> bool:
    return any(p in (selector or "") for p in UNSAFE_SELECTOR_PATTERNS)


def make_step_result(
    *,
    flow_id: str,
    step: int,
    step_type: str,
    selector: str,
    status: str,
    error: str | None = None,
    before_path: str = "",
    after_path: str = "",
) -> dict:
    """Build the step.json payload written next to each flow step snapshot.

    status ∈ {ok, selector-not-found, selector-ambiguous, unsafe-selector,
              navigation-detected, error, skipped}
    """
    return {
        "flowId": flow_id,
        "step": step,
        "type": step_type,
        "selector": selector,
        "status": status,
        "error": error,
        "beforeFinalPath": before_path,
        "afterFinalPath": after_path,
    }


def _runtime_delta(console_buf: list[dict], err_buf: list[str], req_fail: list[dict], marks: tuple[int, int, int]) -> dict:
    console_mark, err_mark, req_mark = marks
    return {
        "console": console_buf[console_mark:],
        "pageerror": err_buf[err_mark:],
        "requestfailed": req_fail[req_mark:],
    }


def run_flow_steps(
    page,
    flow: dict,
    base_dir: Path,
    extract_js: str,
    console_buf: list[dict],
    err_buf: list[str],
    req_fail: list[dict],
) -> None:
    """Execute a user flow's steps in order, write step evidence under base_dir.

    base_dir = <pageDir>/flows/<flowId>. step-1, step-2, ... subdirs created.
    Stops on first non-ok status. Locator policy: count() must be exactly 1.
    """
    snapshot_each = flow.get("snapshotAfterEachStep", True)
    aborted = False
    for i, step in enumerate(flow["steps"], start=1):
        step_dir = base_dir / f"step-{i}"
        step_dir.mkdir(parents=True, exist_ok=True)
        sel = step["selector"]
        before_path = url_path(page.url)
        marks = (len(console_buf), len(err_buf), len(req_fail))
        if aborted:
            result = make_step_result(
                flow_id=flow["id"], step=i, step_type=step["type"], selector=sel,
                status="skipped", error="previous step did not complete",
                before_path=before_path, after_path=before_path,
            )
            (step_dir / "step.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            continue

        # Unsafe selector guard — runs before any locator query.
        if is_unsafe_selector(sel):
            result = make_step_result(
                flow_id=flow["id"], step=i, step_type=step["type"], selector=sel,
                status="unsafe-selector",
                error="generated/framework selector is not allowed for safe-ui-flow",
                before_path=before_path, after_path=before_path,
            )
            (step_dir / "step.json").write_text(
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

        # Navigation guard — safe-ui-flow must not change finalPath.
        if status == "ok" and before_path != after_path:
            status = "navigation-detected"
            error = f"safe-ui-flow changed finalPath from {before_path} to {after_path}"

        result = make_step_result(
            flow_id=flow["id"], step=i, step_type=step["type"], selector=sel,
            status=status, error=error,
            before_path=before_path, after_path=after_path,
        )
        (step_dir / "step.json").write_text(
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
                    **_runtime_delta(console_buf, err_buf, req_fail, marks),
                }
                (step_dir / "capture.json").write_text(
                    json.dumps(step_cap, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as e:
                # Snapshot failure does not abort the flow; recorded as note in step.json.
                result["error"] = (result.get("error") or "") + f" | snapshot failed: {e}"
                (step_dir / "step.json").write_text(
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
    plan = load_check_plan(args.plan)
    scenarios: list[dict] = plan.get("scenarios") or []
    if not scenarios:
        print("[capture] check-plan has no scenarios", file=sys.stderr)
        return 2
    contexts_map: dict[str, dict] = {ctx["id"]: ctx for ctx in plan.get("contexts", [])}
    base = base_url_for_side(plan, args.side)
    role = role_for_side(args.side)
    branch = str(plan.get(role, {}).get("branch") or args.side)
    side_dir_name = output_dir_name_for_side(plan, args.side)

    side_dir = Path(args.out).resolve() / side_dir_name
    side_dir.mkdir(parents=True, exist_ok=True)

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

        def capture_one(sc: dict, *, pass_name: str, retry_of: dict | None = None) -> dict:
            scenario_id = sc["id"]
            ctx_id = sc["context"]
            ctx_meta = contexts_map.get(ctx_id, {"vars": {}, "labels": {}})
            storage_state = resolve_storage_state(plan, ctx_meta)
            target_path = sc["path"]
            expected = sc["expectedFinalPath"]
            print(f"[{args.side}] {pass_name} {scenario_id}  {target_path}", file=sys.stderr)

            pw_ctx = get_ctx(storage_state)
            page = pw_ctx.new_page()
            console_buf: list[dict] = []
            err_buf: list[str] = []
            req_fail: list[dict] = []
            page.on("console", lambda m: console_buf.append({"type": m.type, "text": m.text}))
            page.on("pageerror", lambda e: err_buf.append(str(e)))
            page.on("requestfailed", lambda req: req_fail.append({"url": req.url, "failure": req.failure}))

            status = "ok"
            target_url = absolute_target_url(base, target_path)
            status, surface, attempts = capture_scenario_page(
                page,
                target_url=target_url,
                timeout=args.timeout,
            )
            if attempts and attempts[-1].get("error"):
                err_buf.append(f"capture: {attempts[-1]['error']}")

            settled = None
            if args.settled_snapshot_ms > 0 and surface.get("finalUrl") != "about:blank":
                try:
                    page.wait_for_timeout(args.settled_snapshot_ms)
                    wait_for_route_stability(
                        page,
                        stability_ms=400,
                        timeout_ms=min(max(args.timeout // 2, 2000), 5000),
                    )
                    settled = snapshot_page(page, EXTRACT_JS)
                except Exception as e:
                    err_buf.append(f"settled snapshot: {e}")

            page_dir = side_dir / ctx_id / "pages" / scenario_id
            if retry_of is not None and page_dir.exists():
                shutil.rmtree(page_dir)
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
                "finalUrl": surface.get("finalUrl", ""),
                "finalPath": surface.get("finalPath", ""),
                "captureAttempts": attempts,
                "capturePass": pass_name,
                "retryOf": retry_of,
                "settled": settled,
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

            scenario_flows: list[dict] = sc.get("flows") or []
            for flow in scenario_flows:
                flow_dir = page_dir / "flows" / flow["id"]
                flow_dir.mkdir(parents=True, exist_ok=True)
                try:
                    run_flow_steps(page, flow, flow_dir, EXTRACT_JS, console_buf, err_buf, req_fail)
                except Exception as e:
                    err_buf.append(f"flow {flow.get('id')} crashed: {e}")
            page.close()
            retry_candidate, retry_reasons = is_retry_candidate(
                cap,
                known_unstable=list(plan.get("knownUnstable") or []),
            )
            cap["retryCandidate"] = retry_candidate
            cap["retryReasons"] = retry_reasons
            (page_dir / "capture.json").write_text(
                json.dumps(cap, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return {
                "scenarioId": scenario_id,
                "status": status,
                "finalPath": cap["finalPath"],
                "expected": expected,
                "reachedExpected": cap["finalPath"] == expected,
                "retryCandidate": retry_candidate,
                "retryReasons": retry_reasons,
            }

        summary_by_id: dict[str, dict[str, Any]] = {}
        retry_queue: list[tuple[dict, dict]] = []
        for sc in scenarios:
            item = capture_one(sc, pass_name="initial")
            summary_by_id[item["scenarioId"]] = item
            if item["retryCandidate"]:
                retry_queue.append((sc, item))

        retry_history: list[dict[str, Any]] = []
        (side_dir / "retry-candidates.json").write_text(
            json.dumps([item for _, item in retry_queue], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        retry_passes = max(args.retries, 0)
        for retry_index in range(1, retry_passes + 1):
            if not retry_queue:
                break
            current = retry_queue
            retry_queue = []
            for sc, previous in current:
                item = capture_one(sc, pass_name=f"retry-{retry_index}", retry_of=previous)
                summary_by_id[item["scenarioId"]] = item
                retry_history.append({
                    "retryPass": retry_index,
                    "scenarioId": item["scenarioId"],
                    "previous": previous,
                    "result": item,
                })
                if item["retryCandidate"]:
                    retry_queue.append((sc, item))
        (side_dir / "retry-history.json").write_text(
            json.dumps(retry_history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary = [summary_by_id[sc["id"]] for sc in scenarios if sc["id"] in summary_by_id]

        stamp = {
            "side": args.side,
            "role": role,
            "branch": branch,
            "dirName": side_dir_name,
            "baseUrl": base,
            "planPath": str(Path(args.plan).resolve()),
            "planSha256": hashlib.sha256(Path(args.plan).read_bytes()).hexdigest(),
            "viewport": {"width": 1440, "height": 900},
            "locale": "ko-KR",
            "timezone": "Asia/Seoul",
            "colorScheme": "light",
            "browser": "chromium",
            "browserVersion": browser.version,
            "retryPasses": max(args.retries, 0),
        }
        (side_dir / "stamp.json").write_text(
            json.dumps(stamp, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for c in pw_ctxs.values():
            c.close()
        browser.close()

    print(json.dumps({
        "side": args.side,
        "role": role,
        "branch": branch,
        "outDir": str(side_dir),
        "scenarios": summary,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
