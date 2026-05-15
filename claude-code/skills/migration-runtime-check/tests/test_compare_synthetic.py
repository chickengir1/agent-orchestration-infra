"""
Synthetic fixture tests for compare.py.

Runs without pytest. Each case mutates a deep copy of the baseline A
capture into a B variant, calls compare_page, and asserts the expected
signal field reflects the injected change.
"""

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(SKILL_DIR))

from compare import (  # noqa: E402
    build_diff,
    compare_page,
    page_has_signal,
    render_report,
)

BASELINE_PATH = HERE / "fixtures" / "compare-basic" / "A" / "page-1" / "capture.json"
BASELINE = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def diff_for(mutate) -> dict:
    b = copy.deepcopy(BASELINE)
    mutate(b)
    return compare_page(BASELINE, b)


def fail(case: str, msg: str, d: dict) -> None:
    print(f"FAIL {case}: {msg}")
    print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
    sys.exit(1)


def case_baseline_no_signal() -> None:
    d = diff_for(lambda _b: None)
    if page_has_signal(d):
        fail("baseline_no_signal", "baseline B==A should produce no signal", d)


def case_heading_text_changed() -> None:
    d = diff_for(lambda b: b["view"]["headings"].__setitem__(1, {"level": 2, "text": "Section B"}))
    if not (d["headings"]["removed"] and d["headings"]["added"]):
        fail("heading_text_changed", "expected added+removed in headings", d)
    if not page_has_signal(d):
        fail("heading_text_changed", "expected has-signal True", d)


def case_visible_text_added() -> None:
    d = diff_for(lambda b: b["view"]["texts"].append("Brand new line"))
    if "Brand new line" not in d["texts"]["added"]:
        fail("visible_text_added", "expected new text in texts.added", d)


def case_visible_text_removed() -> None:
    d = diff_for(lambda b: b["view"]["texts"].remove("Footer"))
    if "Footer" not in d["texts"]["removed"]:
        fail("visible_text_removed", "expected removed text in texts.removed", d)


def case_component_count_changed() -> None:
    d = diff_for(lambda b: b["view"]["components"].__setitem__("app-card", 5))
    if not any(c["name"] == "app-card" and c["a"] == 3 and c["b"] == 5 for c in d["components"]["changed"]):
        fail("component_count_changed", "expected app-card count change", d)


def case_action_name_changed() -> None:
    def mutate(b):
        b["actions"][0]["name"] = "Submit"
    d = diff_for(mutate)
    added_names = [k[1] for k in d["actions"]["added"]]
    removed_names = [k[1] for k in d["actions"]["removed"]]
    if "Submit" not in added_names or "Save" not in removed_names:
        fail("action_name_changed", "expected Save→Submit as removed+added pair", d)


def case_action_disabled_changed() -> None:
    def mutate(b):
        b["actions"][0]["state"]["disabled"] = True
    d = diff_for(mutate)
    keys = [tuple(c["key"]) for c in d["actions"]["state_changed"]]
    if ("button", "Save", "form") not in keys:
        fail("action_disabled_changed", "expected Save state_changed entry", d)


def case_action_target_changed() -> None:
    def mutate(b):
        b["actions"][1]["target"] = "/somewhere-else"
    d = diff_for(mutate)
    keys = [tuple(c["key"]) for c in d["actions"]["target_changed"]]
    if ("link", "Home", "nav") not in keys:
        fail("action_target_changed", "expected Home target_changed entry", d)


def case_finalurl_path_changed() -> None:
    d = diff_for(lambda b: b.__setitem__("finalUrl", "http://localhost:4200/different"))
    if d["finalUrl"]["equal"]:
        fail("finalurl_path_changed", "expected finalUrl.equal=False", d)


def case_finalurl_query_only_changed_is_noise() -> None:
    d = diff_for(lambda b: b.__setitem__("finalUrl", "http://localhost:4200/sample?nonce=abc123"))
    if not d["finalUrl"]["equal"]:
        fail("finalurl_query_only_changed_is_noise", "query-only change must be normalized away", d)


def case_console_first_line_added() -> None:
    def mutate(b):
        b["console"].append({"type": "error", "text": "TypeError: foo is not a function\n    at app.js:1:1"})
    d = diff_for(mutate)
    keys = [(typ, text) for typ, text in d["console"]["b_new"]]
    if ("error", "TypeError: foo is not a function") not in keys:
        fail("console_first_line_added", "expected error first-line in console.b_new", d)


def case_pageerror_added() -> None:
    def mutate(b):
        b["pageerror"].append("ReferenceError: ngcc not found")
    d = diff_for(mutate)
    if "ReferenceError: ngcc not found" not in d["pageerror"]["b_new"]:
        fail("pageerror_added", "expected pageerror.b_new entry", d)


def case_requestfailed_added() -> None:
    def mutate(b):
        b["requestfailed"].append({"url": "https://api.example.com/v1/items?ts=999", "failure": "net::ERR_FAILED"})
    d = diff_for(mutate)
    expected = ["https://api.example.com/v1/items", "net::ERR_FAILED"]
    if expected not in d["requestfailed"]["b_new"]:
        fail("requestfailed_added", "expected requestfailed.b_new normalized entry", d)


def case_classes_added() -> None:
    def mutate(b):
        b["view"]["classes"]["new-cls"] = 1
    d = diff_for(mutate)
    if "new-cls" not in d["classes"]["added"]:
        fail("classes_added", "expected new-cls in classes.added", d)


def case_classes_removed() -> None:
    def mutate(b):
        del b["view"]["classes"]["card"]
    d = diff_for(mutate)
    if "card" not in d["classes"]["removed"]:
        fail("classes_removed", "expected card in classes.removed", d)


def case_classes_count_changed() -> None:
    def mutate(b):
        b["view"]["classes"]["btn"] = 9
    d = diff_for(mutate)
    if not any(c["name"] == "btn" and c["a"] == 4 and c["b"] == 9 for c in d["classes"]["changed"]):
        fail("classes_count_changed", "expected btn count Δ", d)


def case_framework_class_drop() -> None:
    def mutate(b):
        b["view"]["classes"]["cdk-overlay-1024"] = 7
        b["view"]["classes"]["ng-tns-c123"] = 4
        b["view"]["classes"]["mat-mdc-button-base"] = 2
        b["view"]["classes"]["_ngcontent-abc"] = 3
        b["view"]["classes"]["_nghost-xyz"] = 1
    d = diff_for(mutate)
    if d["classes"]["added"] or d["classes"]["removed"] or d["classes"]["changed"]:
        fail("framework_class_drop", "framework-prefix classes must be dropped", d)
    if page_has_signal(d):
        fail("framework_class_drop", "framework-only noise must not surface as signal", d)


def _build_run(tmp: Path, a_cap: dict, b_cap: dict) -> Path:
    run = tmp / "run-x"
    for side, cap in (("A", a_cap), ("B", b_cap)):
        d = run / side / "pages" / cap["scenarioId"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "capture.json").write_text(json.dumps(cap, ensure_ascii=False), encoding="utf-8")
    return run


def case_report_omits_signal_less_pages() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        same = copy.deepcopy(BASELINE)
        diff_cap = copy.deepcopy(BASELINE)
        diff_cap["scenarioId"] = "page-2"
        diff_cap["view"]["headings"][0] = {"level": 1, "text": "Changed"}
        a1, b1 = copy.deepcopy(BASELINE), copy.deepcopy(same)
        a2, b2 = copy.deepcopy(BASELINE), copy.deepcopy(diff_cap)
        a2["pageId"] = "page-2"
        # Build a run with: page-1 (no diff), page-2 (heading diff)
        run = tmp / "run-x"
        for pid, ca, cb in (("page-1", a1, b1), ("page-2", a2, b2)):
            for side, cap in (("A", ca), ("B", cb)):
                pd = run / side / "pages" / pid
                pd.mkdir(parents=True, exist_ok=True)
                (pd / "capture.json").write_text(json.dumps(cap), encoding="utf-8")
        diff = build_diff(run)
        report = render_report(diff)
        if "## page-1\n" in report or "\n## page-1\n" in report:
            fail("report_omits_signal_less_pages", "page-1 (no signal) must not appear", {"report": report})
        if "## page-2" not in report:
            fail("report_omits_signal_less_pages", "page-2 (signal) must appear", {"report": report})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_report_section_order() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        b = copy.deepcopy(BASELINE)
        b["view"]["headings"][0] = {"level": 1, "text": "Changed"}
        b["actions"][0]["state"]["disabled"] = True
        b["pageerror"].append("Oops")
        run = _build_run(tmp, BASELINE, b)
        diff = build_diff(run)
        report = render_report(diff)
        # Section order must be Page Capture -> Actions -> Console / Runtime -> UI Changes
        idx_pc = report.find("### Page Capture")
        idx_ac = report.find("### Actions")
        idx_cr = report.find("### Console / Runtime")
        idx_ui = report.find("### UI Changes After Actions")
        if not (0 <= idx_pc < idx_ac < idx_cr < idx_ui):
            fail("report_section_order", "section order must be PC<Actions<Console<UI", {
                "page_capture": idx_pc, "actions": idx_ac, "console": idx_cr, "ui": idx_ui,
                "report": report,
            })
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_report_ui_after_actions_not_collected() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        b = copy.deepcopy(BASELINE)
        b["view"]["headings"][0] = {"level": 1, "text": "Changed"}
        run = _build_run(tmp, BASELINE, b)
        diff = build_diff(run)
        report = render_report(diff)
        if "### UI Changes After Actions" not in report:
            fail("report_ui_after_actions_not_collected", "section must exist", {"report": report})
        if "not collected" not in report:
            fail("report_ui_after_actions_not_collected", "must contain 'not collected'", {"report": report})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_report_summary_has_category_counts() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        b = copy.deepcopy(BASELINE)
        b["view"]["headings"][0] = {"level": 1, "text": "Changed"}
        run = _build_run(tmp, BASELINE, b)
        diff = build_diff(run)
        report = render_report(diff)
        for needle in (
            "## Summary",
            "total pages compared:",
            "pages with differences:",
            "### Category counts",
            "Page Capture:",
            "Actions:",
            "Console / Runtime:",
        ):
            if needle not in report:
                fail("report_summary_has_category_counts", f"missing {needle!r}", {"report": report})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


CASES = [
    case_baseline_no_signal,
    case_heading_text_changed,
    case_visible_text_added,
    case_visible_text_removed,
    case_component_count_changed,
    case_action_name_changed,
    case_action_disabled_changed,
    case_action_target_changed,
    case_finalurl_path_changed,
    case_finalurl_query_only_changed_is_noise,
    case_console_first_line_added,
    case_pageerror_added,
    case_requestfailed_added,
    case_classes_added,
    case_classes_removed,
    case_classes_count_changed,
    case_framework_class_drop,
    case_report_omits_signal_less_pages,
    case_report_section_order,
    case_report_ui_after_actions_not_collected,
    case_report_summary_has_category_counts,
]


def main() -> int:
    for fn in CASES:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(CASES)} cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
