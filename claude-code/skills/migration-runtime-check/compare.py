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
    side_dir = run_dir / side
    if not side_dir.is_dir():
        return {}
    out = {}
    for page_dir in sorted(side_dir.iterdir()):
        cap = page_dir / "capture.json"
        if cap.is_file():
            out[page_dir.name] = json.loads(cap.read_text(encoding="utf-8"))
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


def build_diff(run_dir: Path) -> dict:
    a_side = load_side(run_dir, "A")
    b_side = load_side(run_dir, "B")
    page_ids = sorted(set(a_side) | set(b_side))

    pages = {}
    a_only = []
    b_only = []
    for pid in page_ids:
        if pid not in a_side:
            b_only.append(pid)
            continue
        if pid not in b_side:
            a_only.append(pid)
            continue
        pages[pid] = compare_page(a_side[pid], b_side[pid])

    return {
        "aOnly": a_only,
        "bOnly": b_only,
        "pages": pages,
    }


def render_report(diff: dict) -> str:
    lines: list[str] = []
    lines.append("# migration-runtime-check report")
    lines.append("")

    total = len(diff["pages"])
    with_signal = [pid for pid, d in diff["pages"].items() if page_has_signal(d)]
    lines.append(f"- pages compared: {total}")
    lines.append(f"- pages with signal: {len(with_signal)}")
    lines.append(f"- A-only pages: {len(diff['aOnly'])}")
    lines.append(f"- B-only pages: {len(diff['bOnly'])}")
    lines.append("")

    if diff["aOnly"]:
        lines.append("## A-only")
        for pid in diff["aOnly"]:
            lines.append(f"- {pid}")
        lines.append("")
    if diff["bOnly"]:
        lines.append("## B-only")
        for pid in diff["bOnly"]:
            lines.append(f"- {pid}")
        lines.append("")

    lines.append("## Pages with signal")
    lines.append("")
    if not with_signal:
        lines.append("_No signal detected._")
        lines.append("")

    for pid in with_signal:
        d = diff["pages"][pid]
        lines.append(f"### {pid}")

        if d["status"]["a"] != d["status"]["b"]:
            lines.append(f"- status: A={d['status']['a']} / B={d['status']['b']}")
        if not d["finalUrl"]["equal"]:
            lines.append(f"- finalUrl A: {d['finalUrl']['a']}")
            lines.append(f"- finalUrl B: {d['finalUrl']['b']}")
        if not d["title"]["equal"]:
            lines.append(f"- title A: {d['title']['a']}")
            lines.append(f"- title B: {d['title']['b']}")

        ws_a, ws_b = d["whiteScreen"]["a"], d["whiteScreen"]["b"]
        if ws_a != ws_b:
            lines.append(f"- whiteScreen: A={ws_a} / B={ws_b}")

        c = d["components"]
        if c["added"] or c["removed"] or c["changed"]:
            lines.append(f"- components: +{len(c['added'])} -{len(c['removed'])} Δ{len(c['changed'])}")
            for name in c["added"]:
                lines.append(f"  - added: `{name}`")
            for name in c["removed"]:
                lines.append(f"  - removed: `{name}`")
            for ch in c["changed"]:
                lines.append(f"  - count Δ `{ch['name']}`: A={ch['a']} B={ch['b']}")

        cls = d["classes"]
        if cls["added"] or cls["removed"] or cls["changed"]:
            lines.append(f"- classes: +{len(cls['added'])} -{len(cls['removed'])} Δ{len(cls['changed'])}")
            for name in cls["added"]:
                lines.append(f"  - added: `.{name}`")
            for name in cls["removed"]:
                lines.append(f"  - removed: `.{name}`")
            for ch in cls["changed"]:
                lines.append(f"  - count Δ `.{ch['name']}`: A={ch['a']} B={ch['b']}")

        a = d["actions"]
        if a["added"] or a["removed"] or a["state_changed"] or a["target_changed"]:
            lines.append(
                f"- actions: A={a['a_count']} B={a['b_count']} "
                f"(+{len(a['added'])} -{len(a['removed'])} "
                f"stateΔ{len(a['state_changed'])} targetΔ{len(a['target_changed'])})"
            )
            for k in a["added"]:
                lines.append(f"  - added: role={k[0]!r} name={k[1]!r} locus={k[2]!r}")
            for k in a["removed"]:
                lines.append(f"  - removed: role={k[0]!r} name={k[1]!r} locus={k[2]!r}")
            for ch in a["state_changed"]:
                k = ch["key"]
                lines.append(f"  - state Δ: role={k[0]!r} name={k[1]!r} locus={k[2]!r} A={ch['a']} B={ch['b']}")
            for ch in a["target_changed"]:
                k = ch["key"]
                lines.append(f"  - target Δ: role={k[0]!r} name={k[1]!r} locus={k[2]!r} A={ch['a']!r} B={ch['b']!r}")

        h = d["headings"]
        if h["added"] or h["removed"]:
            lines.append(f"- headings: +{len(h['added'])} -{len(h['removed'])}")
            for level, text in h["added"]:
                lines.append(f"  - added: h{level} {text!r}")
            for level, text in h["removed"]:
                lines.append(f"  - removed: h{level} {text!r}")

        t = d["texts"]
        if t["added"] or t["removed"]:
            lines.append(f"- texts: +{len(t['added'])} -{len(t['removed'])}")
            for s in t["added"][:20]:
                lines.append(f"  - added: {s!r}")
            for s in t["removed"][:20]:
                lines.append(f"  - removed: {s!r}")

        if d["console"]["b_new"]:
            lines.append(f"- console (B-new): {len(d['console']['b_new'])}")
            for typ, text in d["console"]["b_new"]:
                lines.append(f"  - [{typ}] {text}")

        if d["pageerror"]["b_new"]:
            lines.append(f"- pageerror (B-new): {len(d['pageerror']['b_new'])}")
            for msg in d["pageerror"]["b_new"]:
                lines.append(f"  - {msg}")

        rf = d["requestfailed"]
        if rf["b_new"] or rf["a_only"]:
            lines.append(f"- requestfailed: B-new={len(rf['b_new'])} A-only={len(rf['a_only'])}")
            for url, failure in rf["b_new"]:
                lines.append(f"  - B-new: {url} ({failure})")
            for url, failure in rf["a_only"]:
                lines.append(f"  - A-only: {url} ({failure})")

        lines.append("")

    lines.append("## Pages without signal")
    lines.append("")
    no_signal = [pid for pid in diff["pages"] if pid not in with_signal]
    for pid in no_signal:
        lines.append(f"- {pid}")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: compare.py <run-dir>", file=sys.stderr)
        return 2
    run_dir = Path(sys.argv[1]).resolve()
    if not run_dir.is_dir():
        print(f"run-dir not found: {run_dir}", file=sys.stderr)
        return 2

    diff = build_diff(run_dir)
    (run_dir / "diff.json").write_text(
        json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "report.md").write_text(render_report(diff), encoding="utf-8")
    print(json.dumps({
        "runDir": str(run_dir),
        "pages": len(diff["pages"]),
        "withSignal": sum(1 for d in diff["pages"].values() if page_has_signal(d)),
        "aOnly": len(diff["aOnly"]),
        "bOnly": len(diff["bOnly"]),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
