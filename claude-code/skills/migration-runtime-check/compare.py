"""
compare.py — A/B capture diff (signal dump, no judgment).

Usage:
    python3 -u compare.py <run-dir>

Inputs:
    <run-dir>/<baselineBranch>/<contextId>/pages/<scenarioId>/capture.json
    <run-dir>/<candidateBranch>/<contextId>/pages/<scenarioId>/capture.json
    <run-dir>/<branchName>/<contextId>/pages/<scenarioId>/flows/<flowId>/step-<N>/{step.json,capture.json,page.png}

Outputs:
    <run-dir>/diff.json   (machine)
    <run-dir>/report.md   (human)
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


FRAMEWORK_CLASS_RE = re.compile(r"^(cdk-|ng-|mat-mdc-|_ngcontent|_nghost)")


def url_key(url: str) -> str:
    try:
        s = urlsplit(url or "")
        return f"{s.scheme}://{s.netloc}{s.path}"
    except ValueError:
        return url or ""


def drop_framework_classes(m: dict) -> dict:
    return {k: v for k, v in m.items() if not FRAMEWORK_CLASS_RE.match(k)}


def load_flow_snapshots(page_dir: Path) -> dict[tuple, dict]:
    """Return {(flowId, step): {"step": <dict>, "capture": <dict | None>, "step_dir": Path}}."""
    out: dict[tuple, dict] = {}
    flows_root = page_dir / "flows"
    if not flows_root.is_dir():
        return out
    for flow_dir in sorted(flows_root.iterdir()):
        if not flow_dir.is_dir():
            continue
        flow_id = flow_dir.name
        for step_dir in sorted(flow_dir.iterdir()):
            if not step_dir.is_dir():
                continue
            step_json = step_dir / "step.json"
            if not step_json.is_file():
                continue
            try:
                step = json.loads(step_json.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            cap_path = step_dir / "capture.json"
            capture = None
            if cap_path.is_file():
                try:
                    capture = json.loads(cap_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    capture = None
            step_number = step.get("step", 0)
            out[(flow_id, step_number)] = {
                "step": step,
                "capture": capture,
                "step_dir": step_dir,
            }
    return out


def compare_flow_step(a_cap: dict | None, b_cap: dict | None) -> dict | None:
    """Run compare_page over two user-flow step captures."""
    if a_cap is None or b_cap is None:
        return None

    def wrap(c: dict) -> dict:
        return {
            "status": "ok",
            "finalUrl": c.get("finalUrl", ""),
            "view": c.get("view", {}),
            "actions": c.get("actions", []),
            "console": c.get("console", []),
            "pageerror": c.get("pageerror", []),
            "requestfailed": c.get("requestfailed", []),
        }

    return compare_page(wrap(a_cap), wrap(b_cap))


def compare_settled_snapshot(a_cap: dict, b_cap: dict) -> dict | None:
    """Compare delayed settled snapshots when both sides captured one."""
    a_settled = a_cap.get("settled")
    b_settled = b_cap.get("settled")
    if not isinstance(a_settled, dict) or not isinstance(b_settled, dict):
        return None

    def wrap(parent: dict, settled: dict) -> dict:
        return {
            "status": parent.get("status"),
            "finalUrl": settled.get("finalUrl", ""),
            "view": settled.get("view", {}),
            "actions": settled.get("actions", []),
            "console": parent.get("console", []),
            "pageerror": parent.get("pageerror", []),
            "requestfailed": parent.get("requestfailed", []),
        }

    return compare_page(wrap(a_cap, a_settled), wrap(b_cap, b_settled))


def flow_step_has_signal(step_diff: dict | None) -> bool:
    if step_diff is None:
        return False
    return page_has_signal(step_diff)


def side_dirs_for_role(run_dir: Path, side: str) -> list[Path]:
    """Find branch-named side directories whose stamp.json declares side A/B."""
    out: list[Path] = []
    if not run_dir.is_dir():
        return out
    for child in sorted(run_dir.iterdir()):
        if not child.is_dir():
            continue
        stamp_path = child / "stamp.json"
        if not stamp_path.is_file():
            continue
        try:
            stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if stamp.get("side") == side:
            out.append(child)
    fallback = run_dir / side
    if not out and fallback.is_dir():
        out.append(fallback)
    return out


def load_side(run_dir: Path, side: str) -> dict[str, dict]:
    """Return {scenarioId: {"capture": <dict>, "page_dir": Path}}.

    Layout: <run>/<branchName>/<contextId>/pages/<scenarioId>/capture.json
    scenarioId is read from capture.json; falls back to dir name only when missing.
    """
    side_dirs = side_dirs_for_role(run_dir, side)
    if not side_dirs:
        return {}
    out: dict[str, dict] = {}
    for side_dir in side_dirs:
        for ctx_dir in sorted(side_dir.iterdir()):
            if not ctx_dir.is_dir():
                continue
            pages_dir = ctx_dir / "pages"
            if not pages_dir.is_dir():
                continue
            for page_dir in sorted(pages_dir.iterdir()):
                if not page_dir.is_dir():
                    continue
                cap = page_dir / "capture.json"
                if not cap.is_file():
                    continue
                data = json.loads(cap.read_text(encoding="utf-8"))
                sid = data.get("scenarioId") or page_dir.name
                ctx_id = data.get("contextId") or ctx_dir.name
                out[sid] = {"capture": data, "page_dir": page_dir, "contextId": ctx_id}
    return out


def first_line(text: str) -> str:
    return (text or "").split("\n", 1)[0].strip()


def action_key(a: dict) -> tuple:
    return (a.get("role", ""), a.get("name", ""), a.get("locus", ""))


def diff_components(a_comp: dict, b_comp: dict) -> dict:
    a_keys = set(a_comp)
    b_keys = set(b_comp)
    added = sorted(b_keys - a_keys)
    removed = sorted(a_keys - b_keys)
    changed = []
    for k in sorted(a_keys & b_keys):
        if a_comp[k] != b_comp[k]:
            changed.append({"name": k, "a": a_comp[k], "b": b_comp[k]})
    return {"added": added, "removed": removed, "changed": changed}


def diff_actions(a_actions: list, b_actions: list) -> dict:
    def first_by_key(actions: list) -> dict:
        m: dict = {}
        for act in actions:
            k = action_key(act)
            if k not in m:
                m[k] = act
        return m

    a_map = first_by_key(a_actions)
    b_map = first_by_key(b_actions)
    a_keys = set(a_map)
    b_keys = set(b_map)
    added = sorted(b_keys - a_keys)
    removed = sorted(a_keys - b_keys)
    state_changed = []
    target_changed = []
    for k in sorted(a_keys & b_keys):
        if a_map[k].get("state") != b_map[k].get("state"):
            state_changed.append({"key": list(k), "a": a_map[k].get("state"), "b": b_map[k].get("state")})
        if a_map[k].get("target") != b_map[k].get("target"):
            target_changed.append({"key": list(k), "a": a_map[k].get("target"), "b": b_map[k].get("target")})
    return {
        "a_count": len(a_actions),
        "b_count": len(b_actions),
        "added": [list(k) for k in added],
        "removed": [list(k) for k in removed],
        "state_changed": state_changed,
        "target_changed": target_changed,
    }


def diff_headings(a_h: list, b_h: list) -> dict:
    def keys(hs: list) -> set:
        return {(h.get("level"), h.get("text", "")) for h in hs}

    a_set = keys(a_h)
    b_set = keys(b_h)
    return {
        "added": [list(k) for k in sorted(b_set - a_set)],
        "removed": [list(k) for k in sorted(a_set - b_set)],
    }


def diff_texts(a_t: list, b_t: list) -> dict:
    a_set = set(a_t or [])
    b_set = set(b_t or [])
    return {
        "added": sorted(b_set - a_set),
        "removed": sorted(a_set - b_set),
    }


def diff_console(a_console: list, b_console: list) -> dict:
    def keys_of(entries: list) -> set:
        return {
            (e.get("type", ""), first_line(e.get("text", "")))
            for e in entries
            if e.get("type") in ("error", "warning")
        }

    a_keys = keys_of(a_console)
    b_keys = keys_of(b_console)
    new_in_b = sorted(b_keys - a_keys)
    return {"b_new": [list(k) for k in new_in_b]}


def diff_pageerror(a_pe: list, b_pe: list) -> dict:
    a_set = {first_line(e if isinstance(e, str) else e.get("text", str(e))) for e in a_pe}
    b_list = [first_line(e if isinstance(e, str) else e.get("text", str(e))) for e in b_pe]
    return {"b_new": sorted(set(b_list) - a_set)}


def diff_requestfailed(a_rf: list, b_rf: list) -> dict:
    def keys_of(entries: list) -> set:
        return {(url_key(e.get("url", "")), e.get("failure", "")) for e in entries}

    a_keys = keys_of(a_rf)
    b_keys = keys_of(b_rf)
    return {
        "b_new": [list(k) for k in sorted(b_keys - a_keys)],
        "a_only": [list(k) for k in sorted(a_keys - b_keys)],
    }


def compare_page(a: dict, b: dict) -> dict:
    view_a = a.get("view", {})
    view_b = b.get("view", {})
    a_url = a.get("finalUrl") or ""
    b_url = b.get("finalUrl") or ""
    return {
        "status": {"a": a.get("status"), "b": b.get("status")},
        "finalUrl": {
            "a": a_url,
            "b": b_url,
            "equal": url_key(a_url) == url_key(b_url),
        },
        "title": {
            "a": view_a.get("title"),
            "b": view_b.get("title"),
            "equal": view_a.get("title") == view_b.get("title"),
        },
        "components": diff_components(view_a.get("components", {}), view_b.get("components", {})),
        "classes": diff_components(
            drop_framework_classes(view_a.get("classes", {})),
            drop_framework_classes(view_b.get("classes", {})),
        ),
        "headings": diff_headings(view_a.get("headings", []), view_b.get("headings", [])),
        "texts": diff_texts(view_a.get("texts", []), view_b.get("texts", [])),
        "actions": diff_actions(a.get("actions", []), b.get("actions", [])),
        "console": diff_console(a.get("console", []), b.get("console", [])),
        "pageerror": diff_pageerror(a.get("pageerror", []), b.get("pageerror", [])),
        "requestfailed": diff_requestfailed(
            a.get("requestfailed", []), b.get("requestfailed", [])
        ),
        "whiteScreen": {
            "a": len(a.get("actions", [])) == 0,
            "b": len(b.get("actions", [])) == 0,
        },
    }


def page_has_signal(d: dict) -> bool:
    if d["status"]["a"] != d["status"]["b"]:
        return True
    if not d["finalUrl"]["equal"]:
        return True
    if not d["title"]["equal"]:
        return True
    c = d["components"]
    if c["added"] or c["removed"] or c["changed"]:
        return True
    cls = d["classes"]
    if cls["added"] or cls["removed"] or cls["changed"]:
        return True
    a = d["actions"]
    if a["added"] or a["removed"] or a["state_changed"] or a["target_changed"]:
        return True
    h = d["headings"]
    if h["added"] or h["removed"]:
        return True
    t = d["texts"]
    if t["added"] or t["removed"]:
        return True
    if d["console"]["b_new"]:
        return True
    if d["pageerror"]["b_new"]:
        return True
    if d["requestfailed"]["b_new"] or d["requestfailed"]["a_only"]:
        return True
    if d["whiteScreen"]["a"] != d["whiteScreen"]["b"]:
        return True
    return False


def invalid_capture_reason(expected: str | None, a_cap: dict, b_cap: dict, mismatched: list[str]) -> dict:
    final_a = a_cap.get("finalPath")
    final_b = b_cap.get("finalPath")
    actions_a = len(a_cap.get("actions") or [])
    actions_b = len(b_cap.get("actions") or [])
    attempts_a = a_cap.get("captureAttempts") or []
    attempts_b = b_cap.get("captureAttempts") or []
    if final_a == "blank" and final_b == "blank" and actions_a == 0 and actions_b == 0:
        kind = "capture-not-ready"
        message = "A and B stayed on about:blank with zero actions; likely capture timing or navigation setup failure"
    elif final_a == final_b and final_a != expected:
        kind = "plan-expectedFinalPath-mismatch"
        message = "A and B reached the same non-expected path; expectedFinalPath likely needs correction"
    elif len(mismatched) == 1:
        kind = "side-specific-navigation"
        message = f"{mismatched[0]} did not reach expected path"
    else:
        kind = "both-sides-navigation"
        message = "A and B did not reach expected path"
    return {
        "kind": kind,
        "message": message,
        "actionsA": actions_a,
        "actionsB": actions_b,
        "attemptsA": attempts_a,
        "attemptsB": attempts_b,
    }


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def split_noise(diff_entry: dict, patterns: list[str]) -> dict:
    """Move knownUnstable-matched signal items out of main diff into noise bucket.

    Eligible axes: classes (added/removed/changed), texts (added),
    console b_new where type != error. All others stay in main diff.
    """
    noise: dict = {
        "classes_added": [],
        "classes_removed": [],
        "classes_changed": [],
        "texts_added": [],
        "console_b_new": [],
    }
    if not patterns:
        return noise

    def match(s: str) -> bool:
        return any(p in s for p in patterns)

    cls = diff_entry["classes"]
    kept_added = []
    for name in cls["added"]:
        (noise["classes_added"] if match(name) else kept_added).append(name)
    cls["added"] = kept_added
    kept_removed = []
    for name in cls["removed"]:
        (noise["classes_removed"] if match(name) else kept_removed).append(name)
    cls["removed"] = kept_removed
    kept_changed = []
    for ch in cls["changed"]:
        (noise["classes_changed"] if match(ch["name"]) else kept_changed).append(ch)
    cls["changed"] = kept_changed

    texts = diff_entry["texts"]
    kept_texts = []
    for s in texts["added"]:
        (noise["texts_added"] if match(s) else kept_texts).append(s)
    texts["added"] = kept_texts

    console = diff_entry["console"]
    kept_console = []
    for entry in console["b_new"]:
        typ, text = entry[0], entry[1]
        if typ != "error" and match(text):
            noise["console_b_new"].append(entry)
        else:
            kept_console.append(entry)
    console["b_new"] = kept_console

    return noise


def autoload_plan(run_dir: Path) -> dict | None:
    """Try to load the check-plan referenced by any side stamp.json.

    Returns None if no plan path is recorded or the file is missing.
    """
    stamp_paths: list[Path] = []
    if run_dir.is_dir():
        for child in sorted(run_dir.iterdir()):
            if child.is_dir():
                stamp_paths.append(child / "stamp.json")
    # Compatibility fallback for old/incomplete synthetic fixtures.
    stamp_paths.extend([run_dir / "A" / "stamp.json", run_dir / "B" / "stamp.json"])

    seen: set[Path] = set()
    for stamp_path in stamp_paths:
        if stamp_path in seen:
            continue
        seen.add(stamp_path)
        if not stamp_path.is_file():
            continue
        try:
            stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        plan_path = stamp.get("planPath")
        if not plan_path:
            continue
        p = Path(plan_path)
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return None


def build_diff(run_dir: Path, plan: dict | None = None) -> dict:
    patterns: list[str] = list((plan or {}).get("knownUnstable") or [])
    a_side = load_side(run_dir, "A")
    b_side = load_side(run_dir, "B")
    scenario_ids = sorted(set(a_side) | set(b_side))

    pages: dict[str, dict] = {}
    invalid: list[dict] = []
    a_only: list[str] = []
    b_only: list[str] = []
    for sid in scenario_ids:
        if sid not in a_side:
            b_only.append(sid)
            continue
        if sid not in b_side:
            a_only.append(sid)
            continue
        a_cap = a_side[sid]["capture"]
        b_cap = b_side[sid]["capture"]
        expected = a_cap.get("expectedFinalPath") or b_cap.get("expectedFinalPath")
        final_a = a_cap.get("finalPath")
        final_b = b_cap.get("finalPath")
        mismatched: list[str] = []
        if expected is not None:
            if final_a != expected:
                mismatched.append("A")
            if final_b != expected:
                mismatched.append("B")
        if mismatched:
            reason = invalid_capture_reason(expected, a_cap, b_cap, mismatched)
            invalid.append({
                "scenarioId": sid,
                "expected": expected,
                "finalPathA": final_a,
                "finalPathB": final_b,
                "mismatched": mismatched,
                "reasonKind": reason["kind"],
                "reason": reason["message"],
                "actionsA": reason["actionsA"],
                "actionsB": reason["actionsB"],
                "attemptsA": reason["attemptsA"],
                "attemptsB": reason["attemptsB"],
            })
            continue

        diff_entry = compare_page(a_cap, b_cap)
        noise = split_noise(diff_entry, patterns)
        settled_diff = compare_settled_snapshot(a_cap, b_cap)
        settled_noise = None
        transient_page_diff = False
        if settled_diff is not None:
            settled_noise = split_noise(settled_diff, patterns)
            transient_page_diff = page_has_signal(diff_entry) and not page_has_signal(settled_diff)
        a_dir = a_side[sid]["page_dir"]
        b_dir = b_side[sid]["page_dir"]

        a_flows = load_flow_snapshots(a_dir)
        b_flows = load_flow_snapshots(b_dir)
        flow_results: list[dict] = []
        for key in sorted(set(a_flows) | set(b_flows)):
            a_step = a_flows.get(key)
            b_step = b_flows.get(key)
            if a_step is None or b_step is None:
                # Only one side ran this step. Record as a status mismatch.
                a_status = a_step["step"]["status"] if a_step else "missing"
                b_status = b_step["step"]["status"] if b_step else "missing"
                flow_results.append({
                    "flowId": key[0],
                    "step": key[1],
                    "statusA": a_status,
                    "statusB": b_status,
                    "errorA": (a_step and a_step["step"].get("error")) or None,
                    "errorB": (b_step and b_step["step"].get("error")) or None,
                    "screenshotA": _rel(a_step["step_dir"] / "page.png", run_dir) if a_step else None,
                    "screenshotB": _rel(b_step["step_dir"] / "page.png", run_dir) if b_step else None,
                    "stepDiff": None,
                    "stepNoise": None,
                })
                continue
            a_flow_step = a_step["step"]
            b_flow_step = b_step["step"]
            step_diff = None
            step_noise = None
            if a_flow_step["status"] == "ok" and b_flow_step["status"] == "ok":
                step_diff = compare_flow_step(a_step["capture"], b_step["capture"])
                if step_diff is not None:
                    step_noise = split_noise(step_diff, patterns)
            flow_results.append({
                "flowId": key[0],
                "step": key[1],
                "statusA": a_flow_step["status"],
                "statusB": b_flow_step["status"],
                "errorA": a_flow_step.get("error"),
                "errorB": b_flow_step.get("error"),
                "screenshotA": _rel(a_step["step_dir"] / "page.png", run_dir),
                "screenshotB": _rel(b_step["step_dir"] / "page.png", run_dir),
                "stepDiff": step_diff,
                "stepNoise": step_noise,
            })

        pages[sid] = {
            "diff": diff_entry,
            "noise": noise,
            "settledDiff": settled_diff,
            "settledNoise": settled_noise,
            "transientPageDiff": transient_page_diff,
            "flowResults": flow_results,
            "screenshotA": _rel(a_dir / "page.png", run_dir),
            "screenshotB": _rel(b_dir / "page.png", run_dir),
            "context": {
                "auth": b_cap.get("auth"),
                "contextId": b_cap.get("contextId"),
                "vars": b_cap.get("vars", {}),
                "labels": b_cap.get("labels", []),
                "metadata": b_cap.get("metadata", {}),
            },
        }

    return {
        "aOnly": a_only,
        "bOnly": b_only,
        "invalidCaptures": invalid,
        "pages": pages,
        "planLoaded": plan is not None,
    }


def has_noise(noise: dict) -> bool:
    return any(noise.get(k) for k in (
        "classes_added", "classes_removed", "classes_changed", "texts_added", "console_b_new"
    ))


def has_flow_signal(flow_results: list[dict]) -> bool:
    for r in flow_results:
        if r["statusA"] != r["statusB"]:
            return True
        if flow_step_has_signal(r.get("stepDiff")):
            return True
    return False


def has_flow_noise(flow_results: list[dict]) -> bool:
    return any(has_noise(r.get("stepNoise") or {}) for r in flow_results)


def has_page_capture_diff(d: dict) -> bool:
    if d["status"]["a"] != d["status"]["b"]:
        return True
    if not d["finalUrl"]["equal"]:
        return True
    if not d["title"]["equal"]:
        return True
    if d["whiteScreen"]["a"] != d["whiteScreen"]["b"]:
        return True
    for axis in ("components", "classes"):
        x = d[axis]
        if x["added"] or x["removed"] or x["changed"]:
            return True
    for axis in ("headings", "texts"):
        x = d[axis]
        if x["added"] or x["removed"]:
            return True
    return False


def has_actions_diff(d: dict) -> bool:
    a = d["actions"]
    return bool(a["added"] or a["removed"] or a["state_changed"] or a["target_changed"])


def has_console_diff(d: dict) -> bool:
    return bool(
        d["console"]["b_new"]
        or d["pageerror"]["b_new"]
        or d["requestfailed"]["b_new"]
        or d["requestfailed"]["a_only"]
    )


def _render_page_capture(d: dict, page_entry: dict) -> list[str]:
    out: list[str] = ["#### Page Capture"]
    out.append("- screenshot path:")
    out.append(f"  - A: {page_entry['screenshotA']}")
    out.append(f"  - B: {page_entry['screenshotB']}")
    if page_entry.get("transientPageDiff"):
        out.append("- timing: initial snapshot differs, delayed settled snapshot has no remaining page/action/runtime diff")

    if d["status"]["a"] != d["status"]["b"]:
        out.append(f"- status: A={d['status']['a']} / B={d['status']['b']}")
    if not d["finalUrl"]["equal"]:
        out.append(f"- finalUrl: A={d['finalUrl']['a']!r} B={d['finalUrl']['b']!r}")
    if not d["title"]["equal"]:
        out.append(f"- title: A={d['title']['a']!r} B={d['title']['b']!r}")
    if d["whiteScreen"]["a"] != d["whiteScreen"]["b"]:
        out.append(f"- whiteScreen: A={d['whiteScreen']['a']} B={d['whiteScreen']['b']}")

    c = d["components"]
    if c["added"] or c["removed"] or c["changed"]:
        out.append(f"- components: +{len(c['added'])} -{len(c['removed'])} Δ{len(c['changed'])}")
        for name in c["added"]:
            out.append(f"  - added: `{name}`")
        for name in c["removed"]:
            out.append(f"  - removed: `{name}`")
        for ch in c["changed"]:
            out.append(f"  - count Δ `{ch['name']}`: A={ch['a']} B={ch['b']}")

    cls = d["classes"]
    if cls["added"] or cls["removed"] or cls["changed"]:
        out.append(f"- classes: +{len(cls['added'])} -{len(cls['removed'])} Δ{len(cls['changed'])}")
        for name in cls["added"]:
            out.append(f"  - added: `.{name}`")
        for name in cls["removed"]:
            out.append(f"  - removed: `.{name}`")
        for ch in cls["changed"]:
            out.append(f"  - count Δ `.{ch['name']}`: A={ch['a']} B={ch['b']}")

    h = d["headings"]
    if h["added"] or h["removed"]:
        out.append(f"- headings: +{len(h['added'])} -{len(h['removed'])}")
        for level, text in h["added"]:
            out.append(f"  - added: h{level} {text!r}")
        for level, text in h["removed"]:
            out.append(f"  - removed: h{level} {text!r}")

    t = d["texts"]
    if t["added"] or t["removed"]:
        out.append(f"- texts: +{len(t['added'])} -{len(t['removed'])}")
        for s in t["added"][:20]:
            out.append(f"  - added: {s!r}")
        for s in t["removed"][:20]:
            out.append(f"  - removed: {s!r}")

    return out


def _render_actions(d: dict) -> list[str]:
    a = d["actions"]
    out: list[str] = ["#### Actions"]
    out.append(
        f"- counts: A={a['a_count']} B={a['b_count']} "
        f"(+{len(a['added'])} -{len(a['removed'])} "
        f"stateΔ{len(a['state_changed'])} targetΔ{len(a['target_changed'])})"
    )
    for k in a["added"]:
        out.append(f"  - added: role={k[0]!r} name={k[1]!r} locus={k[2]!r}")
    for k in a["removed"]:
        out.append(f"  - removed: role={k[0]!r} name={k[1]!r} locus={k[2]!r}")
    for ch in a["state_changed"]:
        k = ch["key"]
        out.append(f"  - state Δ: role={k[0]!r} name={k[1]!r} locus={k[2]!r} A={ch['a']} B={ch['b']}")
    for ch in a["target_changed"]:
        k = ch["key"]
        out.append(f"  - target Δ: role={k[0]!r} name={k[1]!r} locus={k[2]!r} A={ch['a']!r} B={ch['b']!r}")
    return out


def _render_console_runtime(d: dict) -> list[str]:
    out: list[str] = ["#### Console / Runtime"]
    if d["console"]["b_new"]:
        out.append(f"- console (B-new): {len(d['console']['b_new'])}")
        for typ, text in d["console"]["b_new"]:
            out.append(f"  - [{typ}] {text}")
    if d["pageerror"]["b_new"]:
        out.append(f"- pageerror (B-new): {len(d['pageerror']['b_new'])}")
        for msg in d["pageerror"]["b_new"]:
            out.append(f"  - {msg}")
    rf = d["requestfailed"]
    if rf["b_new"] or rf["a_only"]:
        out.append(f"- requestfailed: B-new={len(rf['b_new'])} A-only={len(rf['a_only'])}")
        for url, failure in rf["b_new"]:
            out.append(f"  - B-new: {url} ({failure})")
        for url, failure in rf["a_only"]:
            out.append(f"  - A-only: {url} ({failure})")
    return out


def _render_context_header(ctx: dict) -> list[str]:
    lines = [
        "Context:",
        f"- auth: {ctx.get('auth')}",
        f"- vars: {ctx.get('vars') or {}}",
    ]
    labels = ctx.get("labels") or []
    if labels:
        lines.append(f"- labels: {', '.join(labels)}")
    else:
        lines.append("- labels: (none)")
    metadata = ctx.get("metadata") or {}
    if metadata:
        lines.append("- metadata:")
        for key, value in metadata.items():
            rendered = json.dumps(value, ensure_ascii=False)
            lines.append(f"  - {key}: {rendered}")
    else:
        lines.append("- metadata: (none)")
    return lines


def _render_noise_candidates(noise: dict) -> list[str]:
    out: list[str] = ["#### Noise Candidates"]
    if noise["classes_added"] or noise["classes_removed"] or noise["classes_changed"]:
        out.append(
            f"- classes: +{len(noise['classes_added'])} "
            f"-{len(noise['classes_removed'])} Δ{len(noise['classes_changed'])}"
        )
        for name in noise["classes_added"]:
            out.append(f"  - added: `.{name}`")
        for name in noise["classes_removed"]:
            out.append(f"  - removed: `.{name}`")
        for ch in noise["classes_changed"]:
            out.append(f"  - count Δ `.{ch['name']}`: A={ch['a']} B={ch['b']}")
    if noise["texts_added"]:
        out.append(f"- texts (added): {len(noise['texts_added'])}")
        for s in noise["texts_added"][:20]:
            out.append(f"  - {s!r}")
    if noise["console_b_new"]:
        out.append(f"- console (non-error B-new): {len(noise['console_b_new'])}")
        for typ, text in noise["console_b_new"]:
            out.append(f"  - [{typ}] {text}")
    return out


def _render_flow_results(results: list[dict]) -> list[str]:
    out: list[str] = ["#### User Flows"]
    for r in results:
        out.append(f"##### {r['flowId']} / step-{r['step']}")
        out.append("- step:")
        out.append(f"  - A: {r['statusA']}")
        if r.get("errorA"):
            out.append(f"    - error: {r['errorA']}")
        out.append(f"  - B: {r['statusB']}")
        if r.get("errorB"):
            out.append(f"    - error: {r['errorB']}")
        if r.get("screenshotA") or r.get("screenshotB"):
            out.append("- screenshot:")
            if r.get("screenshotA"):
                out.append(f"  - A: {r['screenshotA']}")
            if r.get("screenshotB"):
                out.append(f"  - B: {r['screenshotB']}")
        step_diff = r.get("stepDiff")
        if step_diff is not None and flow_step_has_signal(step_diff):
            out.append("- differences:")
            v = step_diff
            if not v["finalUrl"]["equal"]:
                out.append(f"  - finalUrl: A={v['finalUrl']['a']!r} B={v['finalUrl']['b']!r}")
            if not v["title"]["equal"]:
                out.append(f"  - title: A={v['title']['a']!r} B={v['title']['b']!r}")
            for axis_name, axis in (("components", v["components"]), ("classes", v["classes"])):
                if axis["added"] or axis["removed"] or axis["changed"]:
                    out.append(
                        f"  - {axis_name}: +{len(axis['added'])} "
                        f"-{len(axis['removed'])} Δ{len(axis['changed'])}"
                    )
            h = v["headings"]
            if h["added"] or h["removed"]:
                out.append(f"  - headings: +{len(h['added'])} -{len(h['removed'])}")
            t = v["texts"]
            if t["added"] or t["removed"]:
                out.append(f"  - texts: +{len(t['added'])} -{len(t['removed'])}")
            act = v["actions"]
            if act["added"] or act["removed"] or act["state_changed"] or act["target_changed"]:
                out.append(
                    f"  - actions: +{len(act['added'])} -{len(act['removed'])} "
                    f"stateΔ{len(act['state_changed'])} targetΔ{len(act['target_changed'])})"
                )
            if has_console_diff(v):
                if v["console"]["b_new"]:
                    out.append(f"  - console (B-new): {len(v['console']['b_new'])}")
                if v["pageerror"]["b_new"]:
                    out.append(f"  - pageerror (B-new): {len(v['pageerror']['b_new'])}")
                if v["requestfailed"]["b_new"] or v["requestfailed"]["a_only"]:
                    out.append(
                        f"  - requestfailed: B-new={len(v['requestfailed']['b_new'])} "
                        f"A-only={len(v['requestfailed']['a_only'])}"
                    )
        step_noise = r.get("stepNoise") or {}
        if has_noise(step_noise):
            out.append("- noise candidates:")
            tags: list[str] = []
            if step_noise["classes_added"] or step_noise["classes_removed"] or step_noise["classes_changed"]:
                tags.append(
                    f"classes +{len(step_noise['classes_added'])} "
                    f"-{len(step_noise['classes_removed'])} Δ{len(step_noise['classes_changed'])}"
                )
            if step_noise["texts_added"]:
                tags.append(f"texts +{len(step_noise['texts_added'])}")
            if step_noise["console_b_new"]:
                tags.append(f"console (non-error) +{len(step_noise['console_b_new'])}")
            out.append(f"  - {'; '.join(tags)}")
    return out


_RETROSPECTIVE_TEMPLATE = """## Engineering Retrospective

_사람이 작성. 도구가 자동 생성하지 않음._

### Prediction From Code / Plan
- 어떤 scenario 가 위험하다고 봤는지
- 왜 그 scenario 를 골랐는지
- 어떤 차이를 예상했는지

### Actual Runtime Evidence
- 실제 캡처에서 나온 차이
- invalid capture
- noise
- 진짜 확인 필요한 항목

### Judgment
- 도구가 신뢰 가능하게 동작했는지
- migration 회귀로 단정 가능한 항목이 있는지
- 다음 보강점
"""


def render_report(diff: dict) -> str:
    lines: list[str] = ["# Migration Runtime Check Report", ""]

    total = len(diff["pages"])
    invalid = diff.get("invalidCaptures") or []
    with_diff: list[str] = []
    noise_only: list[str] = []
    cat_capture = 0
    cat_actions = 0
    cat_flows = 0
    cat_console = 0
    transient_pages = 0
    for sid, entry in diff["pages"].items():
        d = entry["diff"]
        flow_results = entry.get("flowResults") or []
        flow_signal = has_flow_signal(flow_results)
        if entry.get("transientPageDiff"):
            transient_pages += 1
        if page_has_signal(d) or flow_signal:
            with_diff.append(sid)
            if has_page_capture_diff(d):
                cat_capture += 1
            if has_actions_diff(d):
                cat_actions += 1
            if flow_signal:
                cat_flows += 1
            if has_console_diff(d):
                cat_console += 1
        elif has_noise(entry["noise"]) or has_flow_noise(flow_results):
            noise_only.append(sid)

    lines.append("## Summary")
    lines.append(f"- total scenarios: {total + len(invalid)}")
    lines.append(f"- scenarios with differences: {len(with_diff)}")
    lines.append(f"- noise-only scenarios: {len(noise_only)}")
    lines.append(f"- invalid captures: {len(invalid)}")
    lines.append(f"- transient page diffs: {transient_pages}")
    lines.append(f"- A-only scenarios: {len(diff['aOnly'])}")
    lines.append(f"- B-only scenarios: {len(diff['bOnly'])}")
    if not diff.get("planLoaded"):
        lines.append("- check-plan not loaded (knownUnstable patterns disabled)")
    lines.append("")
    lines.append("### Category counts (scenarios affected)")
    lines.append(f"- Page Capture: {cat_capture}")
    lines.append(f"- Action Surface: {cat_actions}")
    lines.append(f"- User Flows: {cat_flows}")
    lines.append(f"- Console / Runtime: {cat_console}")
    lines.append("")

    if diff["aOnly"]:
        lines.append("## A-only scenarios")
        for sid in diff["aOnly"]:
            lines.append(f"- {sid}")
        lines.append("")
    if diff["bOnly"]:
        lines.append("## B-only scenarios")
        for sid in diff["bOnly"]:
            lines.append(f"- {sid}")
        lines.append("")

    if invalid:
        lines.append("## Invalid Captures")
        lines.append("")
        for inv in invalid:
            lines.append(f"### {inv['scenarioId']}")
            lines.append(f"- expected: {inv['expected']}")
            lines.append(f"- A finalPath: {inv['finalPathA']}")
            lines.append(f"- B finalPath: {inv['finalPathB']}")
            lines.append(f"- reason: {inv.get('reason') or ', '.join(inv['mismatched']) + ' did not reach expected path'}")
            if inv.get("reasonKind"):
                lines.append(f"- reasonKind: {inv['reasonKind']}")
            lines.append(f"- actions: A={inv.get('actionsA')} B={inv.get('actionsB')}")
            lines.append("- deep diff: skipped")
            lines.append("")

    if with_diff:
        lines.append("## Differences")
        lines.append("")
        for sid in with_diff:
            entry = diff["pages"][sid]
            d = entry["diff"]
            flow_results = entry.get("flowResults") or []
            lines.append(f"### {sid}")
            lines.extend(_render_context_header(entry["context"]))
            lines.append("")
            if has_page_capture_diff(d):
                lines.extend(_render_page_capture(d, entry))
                lines.append("")
            else:
                # Page Capture sub-section still anchors screenshot evidence
                lines.append("#### Page Capture")
                lines.append("- screenshot path:")
                lines.append(f"  - A: {entry['screenshotA']}")
                lines.append(f"  - B: {entry['screenshotB']}")
                lines.append("")
            if has_actions_diff(d):
                lines.extend(_render_actions(d))
                lines.append("")
            if has_console_diff(d):
                lines.extend(_render_console_runtime(d))
                lines.append("")
            if has_flow_signal(flow_results) or has_flow_noise(flow_results):
                lines.extend(_render_flow_results(flow_results))
                lines.append("")
            if has_noise(entry["noise"]):
                lines.extend(_render_noise_candidates(entry["noise"]))
                lines.append("")

    if noise_only:
        lines.append("## Noise-only Scenarios")
        lines.append("")
        for sid in noise_only:
            entry = diff["pages"][sid]
            noise = entry["noise"]
            tags: list[str] = []
            if noise["classes_added"] or noise["classes_removed"] or noise["classes_changed"]:
                tags.append(
                    f"classes +{len(noise['classes_added'])} "
                    f"-{len(noise['classes_removed'])} Δ{len(noise['classes_changed'])}"
                )
            if noise["texts_added"]:
                tags.append(f"texts +{len(noise['texts_added'])}")
            if noise["console_b_new"]:
                tags.append(f"console (non-error) +{len(noise['console_b_new'])}")
            flow_noise_count = sum(1 for result in entry.get("flowResults", []) if has_noise(result.get("stepNoise") or {}))
            if flow_noise_count:
                tags.append(f"user-flow noise steps +{flow_noise_count}")
            lines.append(f"- {sid}: {'; '.join(tags) or '(empty)'}")
        lines.append("")

    if not with_diff and not invalid and not noise_only:
        lines.append("_No differences detected on any compared scenario._")
        lines.append("")

    lines.append(_RETROSPECTIVE_TEMPLATE)
    return "\n".join(lines)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--plan", default=None, help="check-plan path; supplies knownUnstable patterns")
    ap.add_argument("--write-json", action="store_true", dest="write_json")
    ns = ap.parse_args()

    run_dir = Path(ns.run_dir).resolve()
    if not run_dir.is_dir():
        print(f"run-dir not found: {run_dir}", file=sys.stderr)
        return 2
    plan = None
    if ns.plan:
        plan = json.loads(Path(ns.plan).read_text(encoding="utf-8"))
    else:
        plan = autoload_plan(run_dir)

    diff = build_diff(run_dir, plan=plan)
    (run_dir / "report.md").write_text(render_report(diff), encoding="utf-8")
    if ns.write_json:
        (run_dir / "diff.json").write_text(
            json.dumps(diff, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    with_diff = sum(
        1
        for entry in diff["pages"].values()
        if page_has_signal(entry["diff"]) or has_flow_signal(entry.get("flowResults") or [])
    )
    print(json.dumps({
        "runDir": str(run_dir),
        "totalScenarios": len(diff["pages"]) + len(diff.get("invalidCaptures", [])),
        "scenariosWithDifferences": with_diff,
        "invalidCaptures": len(diff.get("invalidCaptures", [])),
        "aOnly": len(diff["aOnly"]),
        "bOnly": len(diff["bOnly"]),
        "wroteJson": ns.write_json,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
