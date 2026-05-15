"""
compare.py — A/B capture diff (signal dump, no judgment).

Usage:
    python3 -u compare.py <run-dir>

Inputs:
    <run-dir>/A/<pageId>/capture.json
    <run-dir>/B/<pageId>/capture.json

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


def load_side(run_dir: Path, side: str) -> dict[str, dict]:
    """Return {scenarioId: {"capture": <dict>, "page_dir": Path}}.

    Layout: <run>/<side>/pages/<scenarioId>/capture.json
    scenarioId is read from capture.json; falls back to dir name only when missing.
    """
    pages_dir = run_dir / side / "pages"
    if not pages_dir.is_dir():
        return {}
    out: dict[str, dict] = {}
    for page_dir in sorted(pages_dir.iterdir()):
        if not page_dir.is_dir():
            continue
        cap = page_dir / "capture.json"
        if not cap.is_file():
            continue
        data = json.loads(cap.read_text(encoding="utf-8"))
        sid = data.get("scenarioId") or page_dir.name
        out[sid] = {"capture": data, "page_dir": page_dir}
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
            invalid.append({
                "scenarioId": sid,
                "expected": expected,
                "finalPathA": final_a,
                "finalPathB": final_b,
                "mismatched": mismatched,
            })
            continue

        diff_entry = compare_page(a_cap, b_cap)
        noise = split_noise(diff_entry, patterns)
        a_dir = a_side[sid]["page_dir"]
        b_dir = b_side[sid]["page_dir"]
        pages[sid] = {
            "diff": diff_entry,
            "noise": noise,
            "screenshotA": _rel(a_dir / "page.png", run_dir),
            "screenshotB": _rel(b_dir / "page.png", run_dir),
            "context": {
                "auth": b_cap.get("auth"),
                "contextId": b_cap.get("contextId"),
                "vars": b_cap.get("vars", {}),
                "labels": b_cap.get("labels", {}),
            },
        }

    return {
        "aOnly": a_only,
        "bOnly": b_only,
        "invalidCaptures": invalid,
        "pages": pages,
    }


def has_noise(noise: dict) -> bool:
    return any(noise.get(k) for k in (
        "classes_added", "classes_removed", "classes_changed", "texts_added", "console_b_new"
    ))


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
    return [
        "Context:",
        f"- auth: {ctx.get('auth')}",
        f"- vars: {ctx.get('vars') or {}}",
        f"- labels: {ctx.get('labels') or {}}",
    ]


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
    cat_capture = 0
    cat_actions = 0
    cat_console = 0
    for sid, entry in diff["pages"].items():
        d = entry["diff"]
        if not page_has_signal(d):
            continue
        with_diff.append(sid)
        if has_page_capture_diff(d):
            cat_capture += 1
        if has_actions_diff(d):
            cat_actions += 1
        if has_console_diff(d):
            cat_console += 1

    lines.append("## Summary")
    lines.append(f"- total scenarios: {total + len(invalid)}")
    lines.append(f"- scenarios with differences: {len(with_diff)}")
    lines.append(f"- invalid captures: {len(invalid)}")
    lines.append(f"- A-only scenarios: {len(diff['aOnly'])}")
    lines.append(f"- B-only scenarios: {len(diff['bOnly'])}")
    lines.append("")
    lines.append("### Category counts (scenarios affected)")
    lines.append(f"- Page Capture: {cat_capture}")
    lines.append(f"- Actions: {cat_actions}")
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
            lines.append(f"- reason: {', '.join(inv['mismatched'])} did not reach expected path")
            lines.append("- deep diff: skipped")
            lines.append("")

    if with_diff:
        lines.append("## Differences")
        lines.append("")
        for sid in with_diff:
            entry = diff["pages"][sid]
            d = entry["diff"]
            lines.append(f"### {sid}")
            lines.extend(_render_context_header(entry["context"]))
            lines.append("")
            lines.extend(_render_page_capture(d, entry))
            lines.append("")
            if has_actions_diff(d):
                lines.extend(_render_actions(d))
                lines.append("")
            if has_console_diff(d):
                lines.extend(_render_console_runtime(d))
                lines.append("")
            if has_noise(entry["noise"]):
                lines.extend(_render_noise_candidates(entry["noise"]))
                lines.append("")
    elif not invalid:
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

    diff = build_diff(run_dir, plan=plan)
    (run_dir / "report.md").write_text(render_report(diff), encoding="utf-8")
    if ns.write_json:
        (run_dir / "diff.json").write_text(
            json.dumps(diff, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    with_diff = sum(
        1 for entry in diff["pages"].values() if page_has_signal(entry["diff"])
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
