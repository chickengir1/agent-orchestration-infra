"""Runtime contract checks for migration-runtime-check.

This module intentionally avoids third-party JSON Schema dependencies. The
schema file documents the public shape; these checks enforce the operational
contract that must hold before capture/compare can run.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


UNSAFE_SELECTOR_PATTERNS = (".ng-", ".cdk-", ".mat-mdc-", "_ngcontent", "_nghost")


class ContractError(ValueError):
    pass


def _fail(errors: list[str], path: str, message: str) -> None:
    errors.append(f"{path}: {message}")


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_url(value: Any) -> bool:
    if not _is_nonempty_string(value):
        return False
    parsed = urlsplit(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _is_path(value: Any) -> bool:
    return _is_nonempty_string(value) and (value.startswith("/") or value.startswith("http://") or value.startswith("https://"))


def _contains_unresolved_param(path: str) -> bool:
    return bool(re.search(r"/:[A-Za-z_][A-Za-z0-9_]*", path or ""))


def _check_exact_keys(errors: list[str], path: str, obj: dict, allowed: set[str], required: set[str]) -> None:
    missing = sorted(required - set(obj))
    extra = sorted(set(obj) - allowed)
    for key in missing:
        _fail(errors, path, f"missing required key {key!r}")
    for key in extra:
        _fail(errors, path, f"unknown key {key!r}")


def validate_check_plan(plan: dict) -> None:
    errors: list[str] = []
    if not isinstance(plan, dict):
        raise ContractError("check-plan must be a JSON object")

    top_allowed = {"app", "intent", "baseline", "candidate", "auth", "knownUnstable", "contexts", "scenarios"}
    top_required = {"app", "baseline", "candidate", "auth", "contexts", "scenarios"}
    _check_exact_keys(errors, "$", plan, top_allowed, top_required)

    if not _is_nonempty_string(plan.get("app")):
        _fail(errors, "$.app", "must be a non-empty string")

    for side in ("baseline", "candidate"):
        obj = plan.get(side)
        if not isinstance(obj, dict):
            _fail(errors, f"$.{side}", "must be an object")
            continue
        _check_exact_keys(errors, f"$.{side}", obj, {"branch", "baseUrl"}, {"branch", "baseUrl"})
        if not _is_nonempty_string(obj.get("branch")):
            _fail(errors, f"$.{side}.branch", "must be a non-empty string")
        if not _is_url(obj.get("baseUrl")):
            _fail(errors, f"$.{side}.baseUrl", "must be an http(s) URL")

    auth = plan.get("auth")
    if not isinstance(auth, dict):
        _fail(errors, "$.auth", "must be an object")
    else:
        _check_exact_keys(errors, "$.auth", auth, {"storageState", "actor", "role"}, {"storageState"})
        if auth.get("storageState") is not None and not _is_nonempty_string(auth.get("storageState")):
            _fail(errors, "$.auth.storageState", "must be null or a non-empty string")
        for key in ("actor", "role"):
            if key in auth and not _is_nonempty_string(auth.get(key)):
                _fail(errors, f"$.auth.{key}", "must be a non-empty string when present")

    known = plan.get("knownUnstable", [])
    if not isinstance(known, list) or not all(_is_nonempty_string(x) for x in known):
        _fail(errors, "$.knownUnstable", "must be an array of non-empty strings")

    contexts = plan.get("contexts")
    context_ids: set[str] = set()
    if not isinstance(contexts, list) or not contexts:
        _fail(errors, "$.contexts", "must be a non-empty array")
    else:
        for i, ctx in enumerate(contexts):
            p = f"$.contexts[{i}]"
            if not isinstance(ctx, dict):
                _fail(errors, p, "must be an object")
                continue
            _check_exact_keys(errors, p, ctx, {"id", "auth", "vars", "labels", "metadata"}, {"id", "vars"})
            ctx_id = ctx.get("id")
            if not _is_nonempty_string(ctx_id):
                _fail(errors, f"{p}.id", "must be a non-empty string")
            elif ctx_id in context_ids:
                _fail(errors, f"{p}.id", f"duplicate context id {ctx_id!r}")
            else:
                context_ids.add(ctx_id)
            if ctx.get("auth") is not None and not _is_nonempty_string(ctx.get("auth")):
                _fail(errors, f"{p}.auth", "must be null or a non-empty string")
            if not isinstance(ctx.get("vars"), dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in ctx.get("vars", {}).items()):
                _fail(errors, f"{p}.vars", "must be an object of string -> string")
            if "labels" in ctx and (not isinstance(ctx.get("labels"), list) or not all(isinstance(x, str) for x in ctx.get("labels", []))):
                _fail(errors, f"{p}.labels", "must be an array of strings")
            if "metadata" in ctx and not isinstance(ctx.get("metadata"), dict):
                _fail(errors, f"{p}.metadata", "must be an object")

    scenarios = plan.get("scenarios")
    scenario_ids: set[str] = set()
    if not isinstance(scenarios, list) or not scenarios:
        _fail(errors, "$.scenarios", "must be a non-empty array")
    else:
        for i, sc in enumerate(scenarios):
            p = f"$.scenarios[{i}]"
            if not isinstance(sc, dict):
                _fail(errors, p, "must be an object")
                continue
            allowed = {"id", "reason", "routeTemplate", "context", "path", "expectedFinalPath", "compare", "flows"}
            required = {"id", "routeTemplate", "context", "path", "expectedFinalPath"}
            _check_exact_keys(errors, p, sc, allowed, required)
            sid = sc.get("id")
            if not _is_nonempty_string(sid):
                _fail(errors, f"{p}.id", "must be a non-empty string")
            elif sid in scenario_ids:
                _fail(errors, f"{p}.id", f"duplicate scenario id {sid!r}")
            else:
                scenario_ids.add(sid)
            if sc.get("context") not in context_ids:
                _fail(errors, f"{p}.context", f"must reference contexts[].id; got {sc.get('context')!r}")
            for key in ("routeTemplate", "path", "expectedFinalPath"):
                if not _is_path(sc.get(key)):
                    _fail(errors, f"{p}.{key}", "must be a concrete path or URL")
            if isinstance(sc.get("path"), str) and _contains_unresolved_param(sc["path"]):
                _fail(errors, f"{p}.path", "must not contain unresolved :param placeholders")
            if isinstance(sc.get("expectedFinalPath"), str) and _contains_unresolved_param(sc["expectedFinalPath"]):
                _fail(errors, f"{p}.expectedFinalPath", "must not contain unresolved :param placeholders")
            compare = sc.get("compare", [])
            allowed_compare = {"page-capture", "action-surface", "user-flows", "console-runtime"}
            if compare and (not isinstance(compare, list) or any(x not in allowed_compare for x in compare)):
                _fail(errors, f"{p}.compare", f"must contain only {sorted(allowed_compare)}")
            _validate_flows(errors, p, sc)

    if errors:
        raise ContractError("check-plan contract violation:\n- " + "\n- ".join(errors))


def _validate_flows(errors: list[str], scenario_path: str, sc: dict) -> None:
    flows_present = "flows" in sc
    flows = sc.get("flows")
    reason = sc.get("reason") or ""
    if not flows_present:
        if "no flows selected" not in reason:
            _fail(errors, scenario_path, "must include flows[] or reason containing 'no flows selected'")
        return
    if not isinstance(flows, list):
        _fail(errors, f"{scenario_path}.flows", "must be an array")
        return
    if not flows and "no flows selected" not in reason:
        _fail(errors, scenario_path, "empty flows[] requires reason containing 'no flows selected'")
        return
    flow_ids: set[str] = set()
    for i, flow in enumerate(flows):
        p = f"{scenario_path}.flows[{i}]"
        if not isinstance(flow, dict):
            _fail(errors, p, "must be an object")
            continue
        allowed = {"id", "kind", "description", "intent", "expectedObservables", "snapshotAfterEachStep", "steps"}
        _check_exact_keys(errors, p, flow, allowed, {"id", "kind", "steps"})
        flow_id = flow.get("id")
        if not _is_nonempty_string(flow_id):
            _fail(errors, f"{p}.id", "must be a non-empty string")
        elif flow_id in flow_ids:
            _fail(errors, f"{p}.id", f"duplicate flow id {flow_id!r}")
        else:
            flow_ids.add(flow_id)
        if flow.get("kind") != "safe-ui-flow":
            _fail(errors, f"{p}.kind", "must be 'safe-ui-flow'")
        expected = flow.get("expectedObservables", [])
        if expected and (not isinstance(expected, list) or not all(isinstance(x, str) for x in expected)):
            _fail(errors, f"{p}.expectedObservables", "must be an array of strings")
        steps = flow.get("steps")
        if not isinstance(steps, list) or not steps:
            _fail(errors, f"{p}.steps", "must be a non-empty array")
            continue
        for j, step in enumerate(steps):
            sp = f"{p}.steps[{j}]"
            if not isinstance(step, dict):
                _fail(errors, sp, "must be an object")
                continue
            _check_exact_keys(errors, sp, step, {"type", "description", "selector"}, {"type", "selector"})
            if step.get("type") != "click":
                _fail(errors, f"{sp}.type", "must be 'click'")
            selector = step.get("selector")
            if not _is_nonempty_string(selector):
                _fail(errors, f"{sp}.selector", "must be a non-empty string")
            elif any(pat in selector for pat in UNSAFE_SELECTOR_PATTERNS):
                _fail(errors, f"{sp}.selector", "generated/framework selectors are not allowed")


def load_check_plan(path: str | Path) -> dict:
    import json
    p = Path(path)
    plan = json.loads(p.read_text(encoding="utf-8"))
    validate_check_plan(plan)
    return plan
