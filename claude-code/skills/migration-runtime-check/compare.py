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
    """Return {pageId: {"capture": <dict>, "page_dir": Path}}.

    Supports both layouts:
      <run>/<side>/<pageId>/capture.json          (legacy flat)
      <run>/<side>/pages/<pageId>/capture.json    (current)
    """
    side_dir = run_dir / side
    if not side_dir.is_dir():
        return {}
    pages_dir = side_dir / "pages"
    base = pages_dir if pages_dir.is_dir() else side_dir
    out: dict[str, dict] = {}
    for page_dir in sorted(base.iterdir()):
        if not page_dir.is_dir():
            continue
        cap = page_dir / "capture.json"
        if cap.is_file():
            out[page_dir.name] = {
                "capture": json.loads(cap.read_text(encoding="utf-8")),
                "page_dir": page_dir,
            }
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


def build_diff(run_dir: Path) -> dict:
    a_side = load_side(run_dir, "A")
    b_side = load_side(run_dir, "B")
    page_ids = sorted(set(a_side) | set(b_side))

    pages: dict[str, dict] = {}
    a_only: list[str] = []
    b_only: list[str] = []
    for pid in page_ids:
        if pid not in a_side:
            b_only.append(pid)
            continue
        if pid not in b_side:
            a_only.append(pid)
            continue
        a_dir = a_side[pid]["page_dir"]
        b_dir = b_side[pid]["page_dir"]
        pages[pid] = {
            "diff": compare_page(a_side[pid]["capture"], b_side[pid]["capture"]),
            "screenshotA": _rel(a_dir / "page.png", run_dir),
            "screenshotB": _rel(b_dir / "page.png", run_dir),
        }

    return {
        "aOnly": a_only,
        "bOnly": b_only,
        "pages": pages,
    }


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
    out: list[str] = ["### Page Capture"]
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
    out: list[str] = ["### Actions"]
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
    out: list[str] = ["### Console / Runtime"]
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


def _render_ui_after_actions() -> list[str]:
    return [
        "### UI Changes After Actions",
        "- not collected (action simulation is out of scope for v0)",
    ]


def render_report(diff: dict) -> str:
    lines: list[str] = ["# migration-runtime-check report", ""]

    total = len(diff["pages"])
    with_diff: list[str] = []
    cat_capture = 0
    cat_actions = 0
    cat_console = 0
    for pid, entry in diff["pages"].items():
        d = entry["diff"]
        if not page_has_signal(d):
            continue
        with_diff.append(pid)
        if has_page_capture_diff(d):
            cat_capture += 1
        if has_actions_diff(d):
            cat_actions += 1
        if has_console_diff(d):
            cat_console += 1

    lines.append("## Summary")
    lines.append(f"- total pages compared: {total}")
    lines.append(f"- pages with differences: {len(with_diff)}")
    lines.append(f"- A-only pages: {len(diff['aOnly'])}")
    lines.append(f"- B-only pages: {len(diff['bOnly'])}")
    lines.append("")
    lines.append("### Category counts (pages affected)")
    lines.append(f"- Page Capture: {cat_capture}")
    lines.append(f"- Actions: {cat_actions}")
    lines.append(f"- Console / Runtime: {cat_console}")
    lines.append("")

    if diff["aOnly"]:
        lines.append("## A-only pages")
        for pid in diff["aOnly"]:
            lines.append(f"- {pid}")
        lines.append("")
    if diff["bOnly"]:
        lines.append("## B-only pages")
        for pid in diff["bOnly"]:
            lines.append(f"- {pid}")
        lines.append("")

    if not with_diff:
        lines.append("_No differences detected on any compared page._")
        lines.append("")
        return "\n".join(lines)

    for pid in with_diff:
        entry = diff["pages"][pid]
        d = entry["diff"]
        lines.append(f"## {pid}")
        lines.extend(_render_page_capture(d, entry))
        lines.append("")
        if has_actions_diff(d):
            lines.extend(_render_actions(d))
            lines.append("")
        if has_console_diff(d):
            lines.extend(_render_console_runtime(d))
            lines.append("")
        lines.extend(_render_ui_after_actions())
        lines.append("")

    return "\n".join(lines)


def _diff_for_json(diff: dict) -> dict:
    """build_diff returns Path objects via page_dir? Already stringified. Safe."""
    return diff


def main() -> int:
    args = sys.argv[1:]
    write_json = False
    if "--write-json" in args:
        args.remove("--write-json")
        write_json = True
    if len(args) != 1:
        print("usage: compare.py <run-dir> [--write-json]", file=sys.stderr)
        return 2
    run_dir = Path(args[0]).resolve()
    if not run_dir.is_dir():
        print(f"run-dir not found: {run_dir}", file=sys.stderr)
        return 2

    diff = build_diff(run_dir)
    (run_dir / "report.md").write_text(render_report(diff), encoding="utf-8")
    if write_json:
        (run_dir / "diff.json").write_text(
            json.dumps(_diff_for_json(diff), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    with_diff = sum(
        1 for entry in diff["pages"].values() if page_has_signal(entry["diff"])
    )
    print(json.dumps({
        "runDir": str(run_dir),
        "totalPages": len(diff["pages"]),
        "pagesWithDifferences": with_diff,
        "aOnly": len(diff["aOnly"]),
        "bOnly": len(diff["bOnly"]),
        "wroteJson": write_json,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
