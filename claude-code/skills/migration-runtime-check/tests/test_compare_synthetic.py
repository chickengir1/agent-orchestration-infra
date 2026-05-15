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
    autoload_plan,
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


def _write_capture(run: Path, side: str, cap: dict) -> Path:
    d = run / side / "pages" / cap["scenarioId"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "capture.json").write_text(json.dumps(cap, ensure_ascii=False), encoding="utf-8")
    return d


def _scenario_cap(scenario_id: str, base: dict, expected_final_path: str | None = None, final_path: str | None = None) -> dict:
    cap = copy.deepcopy(base)
    cap["scenarioId"] = scenario_id
    cap["path"] = f"/{scenario_id}"
    if expected_final_path is not None:
        cap["expectedFinalPath"] = expected_final_path
    if final_path is not None:
        cap["finalPath"] = final_path
        cap["finalUrl"] = f"http://localhost:4200{final_path}"
    return cap


def case_scenarioid_ab_matching() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        a = _scenario_cap("scenario-1", BASELINE)
        b = _scenario_cap("scenario-1", BASELINE)
        b["view"]["headings"][0] = {"level": 1, "text": "Changed"}
        run = tmp / "run-x"
        _write_capture(run, "A", a)
        _write_capture(run, "B", b)
        diff = build_diff(run)
        if "scenario-1" not in diff["pages"]:
            fail("scenarioid_ab_matching", "scenario-1 not joined", {"pages": list(diff["pages"])})
        if diff["aOnly"] or diff["bOnly"]:
            fail("scenarioid_ab_matching", "should not be A/B-only", diff)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_expectedfinalpath_mismatch_skips_deep_diff() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        a = _scenario_cap("scenario-redirected", BASELINE,
                          expected_final_path="/group/2/settings/facultylist",
                          final_path="/error")
        b = _scenario_cap("scenario-redirected", BASELINE,
                          expected_final_path="/group/2/settings/facultylist",
                          final_path="/group/2/settings/facultylist")
        # Even if there were huge view differences, deep diff must not run
        b["view"]["headings"].append({"level": 9, "text": "MASSIVE-CHANGE"})
        run = tmp / "run-x"
        _write_capture(run, "A", a)
        _write_capture(run, "B", b)
        diff = build_diff(run)
        if "scenario-redirected" in diff["pages"]:
            fail("expectedfinalpath_mismatch_skips_deep_diff",
                 "mismatched scenario must not have deep diff", diff)
        invalid_ids = [inv["scenarioId"] for inv in diff["invalidCaptures"]]
        if "scenario-redirected" not in invalid_ids:
            fail("expectedfinalpath_mismatch_skips_deep_diff",
                 "expected entry in invalidCaptures", diff)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_invalid_capture_section_in_report() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        a = _scenario_cap("scenario-redirected", BASELINE,
                          expected_final_path="/sample", final_path="/error")
        b = _scenario_cap("scenario-redirected", BASELINE,
                          expected_final_path="/sample", final_path="/sample")
        run = tmp / "run-x"
        _write_capture(run, "A", a)
        _write_capture(run, "B", b)
        diff = build_diff(run)
        report = render_report(diff)
        if "## Invalid Captures" not in report:
            fail("invalid_capture_section_in_report", "missing section", {"report": report})
        if "scenario-redirected" not in report:
            fail("invalid_capture_section_in_report", "scenarioId not listed", {"report": report})
        if "deep diff: skipped" not in report:
            fail("invalid_capture_section_in_report", "missing skip note", {"report": report})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_no_signal_scenario_omitted_from_differences() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        # Two scenarios: one identical, one with heading diff
        same_a = _scenario_cap("scenario-same", BASELINE)
        same_b = _scenario_cap("scenario-same", BASELINE)
        diff_a = _scenario_cap("scenario-diff", BASELINE)
        diff_b = _scenario_cap("scenario-diff", BASELINE)
        diff_b["view"]["headings"][0] = {"level": 1, "text": "Changed"}
        run = tmp / "run-x"
        for cap in (same_a, diff_a):
            _write_capture(run, "A", cap)
        for cap in (same_b, diff_b):
            _write_capture(run, "B", cap)
        diff = build_diff(run)
        report = render_report(diff)
        diff_idx = report.find("## Differences")
        if diff_idx < 0:
            fail("no_signal_scenario_omitted_from_differences",
                 "Differences section missing", {"report": report})
        differences_block = report[diff_idx:]
        if "scenario-same" in differences_block:
            fail("no_signal_scenario_omitted_from_differences",
                 "signal-less scenario must not appear in Differences",
                 {"report": report})
        if "scenario-diff" not in differences_block:
            fail("no_signal_scenario_omitted_from_differences",
                 "signal scenario must appear in Differences",
                 {"report": report})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_schema_allows_label_array_and_metadata_object() -> None:
    """Structural shape check on the sample check-plan."""
    plan_path = SKILL_DIR / "tests" / "fixtures" / "sample-check-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    target = None
    for ctx in plan["contexts"]:
        if ctx["id"] == "group-2-admin":
            target = ctx
            break
    if target is None:
        fail("schema_allows_label_array_and_metadata_object",
             "group-2-admin context missing", plan)
    labels = target.get("labels")
    if not isinstance(labels, list) or not all(isinstance(s, str) for s in labels):
        fail("schema_allows_label_array_and_metadata_object",
             "labels must be array<string>", target)
    metadata = target.get("metadata")
    if not isinstance(metadata, dict):
        fail("schema_allows_label_array_and_metadata_object",
             "metadata must be object", target)
    # Korean key must be preserved verbatim
    if "접근 대상" not in metadata:
        fail("schema_allows_label_array_and_metadata_object",
             "Korean metadata key not preserved", metadata)


def case_plan_helper_labels_and_metadata() -> None:
    import subprocess
    discover_fixture = SKILL_DIR / "tests" / "fixtures" / "discover-sample.json"
    py = SKILL_DIR / ".venv" / "bin" / "python3"
    if not py.exists():
        py = Path(sys.executable)
    result = subprocess.run(
        [
            str(py),
            str(SKILL_DIR / "plan_helper.py"),
            "--discover", str(discover_fixture),
            "--app", "libs-app",
            "--baseline-branch", "dev",
            "--candidate-branch", "mig",
            "--base-url", "http://localhost:4200",
            "--context-id", "ctx-A",
            "--labels", "유료 학교,설정 가능 계정",
            "--metadata-json", '{"접근 대상":"2번 그룹","그룹 내 권한":"관리자"}',
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        fail("plan_helper_labels_and_metadata",
             f"helper exited {result.returncode}",
             {"stdout": result.stdout, "stderr": result.stderr})
    plan = json.loads(result.stdout)
    ctx = plan["contexts"][0]
    if ctx["labels"] != ["유료 학교", "설정 가능 계정"]:
        fail("plan_helper_labels_and_metadata",
             "labels not parsed as array", ctx)
    if ctx["metadata"] != {"접근 대상": "2번 그룹", "그룹 내 권한": "관리자"}:
        fail("plan_helper_labels_and_metadata",
             "metadata not parsed as object", ctx)


def case_capture_preserves_labels_and_metadata() -> None:
    """build_diff must propagate capture.json labels/metadata into entry context."""
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        a = _scenario_cap("scenario-meta", BASELINE)
        b = _scenario_cap("scenario-meta", BASELINE)
        b["view"]["headings"][0] = {"level": 1, "text": "Changed"}
        for cap in (a, b):
            cap["labels"] = ["유료 학교", "설정 가능 계정"]
            cap["metadata"] = {"접근 대상": "2번 그룹", "그룹 내 권한": "관리자"}
        run = tmp / "run-x"
        _write_capture(run, "A", a)
        _write_capture(run, "B", b)
        diff = build_diff(run)
        ctx = diff["pages"]["scenario-meta"]["context"]
        if ctx["labels"] != ["유료 학교", "설정 가능 계정"]:
            fail("capture_preserves_labels_and_metadata", "labels lost", ctx)
        if ctx["metadata"].get("접근 대상") != "2번 그룹":
            fail("capture_preserves_labels_and_metadata", "metadata lost", ctx)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_report_shows_labels_and_metadata() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        a = _scenario_cap("scenario-meta", BASELINE)
        b = _scenario_cap("scenario-meta", BASELINE)
        b["view"]["headings"][0] = {"level": 1, "text": "Changed"}
        for cap in (a, b):
            cap["labels"] = ["유료 학교", "설정 가능 계정"]
            cap["metadata"] = {"접근 대상": "2번 그룹", "그룹 내 권한": "관리자"}
        run = tmp / "run-x"
        _write_capture(run, "A", a)
        _write_capture(run, "B", b)
        diff = build_diff(run)
        report = render_report(diff)
        for needle in ("유료 학교", "설정 가능 계정", "접근 대상", "그룹 내 권한"):
            if needle not in report:
                fail("report_shows_labels_and_metadata",
                     f"missing {needle!r} in report", {"report": report})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_compare_autoloads_plan_from_stamp() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        run = tmp / "run-x"
        a = _scenario_cap("scenario-noise", BASELINE)
        b = _scenario_cap("scenario-noise", BASELINE)
        b["view"]["classes"]["lds-bars"] = 3
        _write_capture(run, "A", a)
        _write_capture(run, "B", b)
        plan_path = tmp / "check-plan.json"
        plan_path.write_text(json.dumps({"knownUnstable": ["lds-bars"]}), encoding="utf-8")
        (run / "A").mkdir(parents=True, exist_ok=True)
        (run / "A" / "stamp.json").write_text(
            json.dumps({"planPath": str(plan_path)}), encoding="utf-8"
        )
        # autoload_plan must read planPath and return plan dict
        loaded = autoload_plan(run)
        if loaded is None or "lds-bars" not in loaded.get("knownUnstable", []):
            fail("compare_autoloads_plan_from_stamp",
                 "plan not autoloaded", {"loaded": loaded})
        diff = build_diff(run, plan=loaded)
        entry = diff["pages"].get("scenario-noise")
        if entry is None:
            fail("compare_autoloads_plan_from_stamp",
                 "scenario missing", diff)
        if "lds-bars" not in entry["noise"]["classes_added"]:
            fail("compare_autoloads_plan_from_stamp",
                 "noise not separated after autoload", entry)
        report = render_report(diff)
        if "check-plan not loaded" in report:
            fail("compare_autoloads_plan_from_stamp",
                 "report must not say plan missing when autoloaded",
                 {"report": report})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_schema_allows_scenario_actions() -> None:
    """Sample plan must remain shape-valid; ensure we can attach actions to a scenario."""
    plan_path = SKILL_DIR / "tests" / "fixtures" / "sample-check-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    sc = plan["scenarios"][0]
    sc["actions"] = [
        {
            "id": "open-permission-dropdown",
            "kind": "safe-ui-action",
            "description": "권한 드롭다운 펼치기",
            "snapshotAfterEachStep": True,
            "steps": [
                {"type": "click", "selector": "[data-testid='permission-dropdown']"}
            ],
        }
    ]
    # Shape assertions reflect schema constraints
    action = sc["actions"][0]
    if action["kind"] != "safe-ui-action":
        fail("schema_allows_scenario_actions", "kind must be safe-ui-action", action)
    if not isinstance(action["steps"], list) or len(action["steps"]) < 1:
        fail("schema_allows_scenario_actions", "steps must be non-empty array", action)
    step = action["steps"][0]
    if step["type"] != "click" or not step["selector"]:
        fail("schema_allows_scenario_actions", "step must be click+selector", step)


def case_action_result_builder_shapes() -> None:
    """make_action_result returns the documented JSON shape for ok and failure."""
    sys.path.insert(0, str(SKILL_DIR))
    import importlib
    capture_mod = importlib.import_module("capture")
    ok = capture_mod.make_action_result(
        action_id="a1", step=1, step_type="click",
        selector="[data-testid='x']",
        status="ok",
        before_path="/p", after_path="/p",
    )
    for key in ("actionId", "step", "type", "selector", "status", "error",
                "beforeFinalPath", "afterFinalPath"):
        if key not in ok:
            fail("action_result_builder_shapes", f"missing key {key} on ok", ok)
    if ok["status"] != "ok" or ok["error"] is not None:
        fail("action_result_builder_shapes", "ok shape wrong", ok)
    fail_res = capture_mod.make_action_result(
        action_id="a1", step=1, step_type="click",
        selector="[data-testid='missing']",
        status="selector-not-found",
        error="0 elements matched",
        before_path="/p", after_path="/p",
    )
    if fail_res["status"] != "selector-not-found":
        fail("action_result_builder_shapes", "failure status wrong", fail_res)
    if "0 elements matched" not in (fail_res["error"] or ""):
        fail("action_result_builder_shapes", "failure error wrong", fail_res)


def _write_action_step(
    run: Path, side: str, scenario_id: str, action_id: str, step: int,
    *, status: str, error: str | None = None,
    step_capture: dict | None = None,
) -> Path:
    sd = run / side / "pages" / scenario_id / "actions" / action_id / f"step-{step}"
    sd.mkdir(parents=True, exist_ok=True)
    action_json = {
        "actionId": action_id,
        "step": step,
        "type": "click",
        "selector": "[data-testid='t']",
        "status": status,
        "error": error,
        "beforeFinalPath": "/p",
        "afterFinalPath": "/p",
    }
    (sd / "action.json").write_text(json.dumps(action_json), encoding="utf-8")
    if step_capture is not None:
        (sd / "capture.json").write_text(json.dumps(step_capture), encoding="utf-8")
    return sd


def case_compare_reports_action_status_mismatch() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        a = _scenario_cap("scenario-act", BASELINE)
        b = _scenario_cap("scenario-act", BASELINE)
        run = tmp / "run-x"
        _write_capture(run, "A", a)
        _write_capture(run, "B", b)
        _write_action_step(run, "A", "scenario-act", "open-dd", 1, status="ok")
        _write_action_step(run, "B", "scenario-act", "open-dd", 1,
                           status="selector-not-found", error="0 elements matched")
        diff = build_diff(run)
        entry = diff["pages"]["scenario-act"]
        results = entry.get("actionResults") or []
        if not results:
            fail("compare_reports_action_status_mismatch", "no action results", entry)
        r = results[0]
        if r["statusA"] != "ok" or r["statusB"] != "selector-not-found":
            fail("compare_reports_action_status_mismatch", "status pair wrong", r)
        report = render_report(diff)
        if "##### open-dd / step-1" not in report:
            fail("compare_reports_action_status_mismatch",
                 "step header missing in report", {"report": report})
        if "selector-not-found" not in report:
            fail("compare_reports_action_status_mismatch",
                 "failure status not surfaced", {"report": report})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_compare_reports_action_step_snapshot_diff() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        a = _scenario_cap("scenario-step", BASELINE)
        b = _scenario_cap("scenario-step", BASELINE)
        run = tmp / "run-x"
        _write_capture(run, "A", a)
        _write_capture(run, "B", b)
        # Step capture differs on headings between A and B
        a_step_cap = {
            "view": {
                "title": "S",
                "headings": [{"level": 1, "text": "Step A"}],
                "landmarks": [], "texts": [], "components": {}, "classes": {}, "emptyStates": [],
            },
            "actions": [],
            "finalUrl": "http://localhost:4200/p",
            "finalPath": "/p",
        }
        b_step_cap = {
            "view": {
                "title": "S",
                "headings": [{"level": 1, "text": "Step B"}],
                "landmarks": [], "texts": [], "components": {}, "classes": {}, "emptyStates": [],
            },
            "actions": [],
            "finalUrl": "http://localhost:4200/p",
            "finalPath": "/p",
        }
        _write_action_step(run, "A", "scenario-step", "open-dd", 1,
                           status="ok", step_capture=a_step_cap)
        _write_action_step(run, "B", "scenario-step", "open-dd", 1,
                           status="ok", step_capture=b_step_cap)
        diff = build_diff(run)
        entry = diff["pages"]["scenario-step"]
        results = entry.get("actionResults") or []
        if not results or results[0]["stepDiff"] is None:
            fail("compare_reports_action_step_snapshot_diff",
                 "stepDiff missing", entry)
        step_diff = results[0]["stepDiff"]
        if not (step_diff["headings"]["added"] and step_diff["headings"]["removed"]):
            fail("compare_reports_action_step_snapshot_diff",
                 "heading diff not detected", step_diff)
        report = render_report(diff)
        if "- differences:" not in report:
            fail("compare_reports_action_step_snapshot_diff",
                 "differences subsection not rendered", {"report": report})
        if "headings:" not in report:
            fail("compare_reports_action_step_snapshot_diff",
                 "headings line missing", {"report": report})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_action_only_diff_keeps_scenario_in_report() -> None:
    """Scenario with no main diff but an action status mismatch must appear in Differences."""
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        a = _scenario_cap("scenario-action-only", BASELINE)
        b = _scenario_cap("scenario-action-only", BASELINE)
        # No mutation on b — main diff = 0
        run = tmp / "run-x"
        _write_capture(run, "A", a)
        _write_capture(run, "B", b)
        _write_action_step(run, "A", "scenario-action-only", "open-dd", 1, status="ok")
        _write_action_step(run, "B", "scenario-action-only", "open-dd", 1,
                           status="selector-not-found")
        diff = build_diff(run)
        if not page_has_signal(diff["pages"]["scenario-action-only"]["diff"]):
            pass  # main signal 0 as intended
        report = render_report(diff)
        diff_idx = report.find("## Differences")
        if diff_idx < 0:
            fail("action_only_diff_keeps_scenario_in_report",
                 "Differences section missing", {"report": report})
        if "scenario-action-only" not in report[diff_idx:]:
            fail("action_only_diff_keeps_scenario_in_report",
                 "scenario must appear in Differences even without main diff",
                 {"report": report})
        if "## Noise-only Scenarios" in report:
            fail("action_only_diff_keeps_scenario_in_report",
                 "scenario must not be misclassified as noise-only",
                 {"report": report})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _load_capture_mod():
    sys.path.insert(0, str(SKILL_DIR))
    import importlib
    return importlib.import_module("capture")


class _StubLocator:
    def __init__(self, count_val: int = 1, on_click=None):
        self._count = count_val
        self._on_click = on_click

    def count(self) -> int:
        return self._count

    def click(self, timeout: int = 5000) -> None:
        if self._on_click is not None:
            self._on_click()


class _StubPage:
    def __init__(self, url: str, locator_factory):
        self._url = url
        self._locator_factory = locator_factory
        self.evaluations: list = []

    @property
    def url(self) -> str:
        return self._url

    def set_url(self, url: str) -> None:
        self._url = url

    def locator(self, sel: str):
        return self._locator_factory(self, sel)

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def evaluate(self, js: str, args: dict):
        return {"view": {}, "actions": [], "meta": {}}

    def screenshot(self, **kwargs) -> None:
        pass


def case_unsafe_selector_guard() -> None:
    cap = _load_capture_mod()
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        action = {
            "id": "open-dd",
            "kind": "safe-ui-action",
            "snapshotAfterEachStep": True,
            "steps": [
                {"type": "click", "selector": ".ng-tns-c123"},
                {"type": "click", "selector": "[data-testid='next']"},
            ],
        }
        called = {"locator": 0}

        def locator_factory(page, sel):
            called["locator"] += 1
            return _StubLocator(count_val=1)

        page = _StubPage("http://x/p", locator_factory)
        base = tmp / "actions" / action["id"]
        base.mkdir(parents=True)
        cap.run_action_steps(page, action, base, extract_js="")
        step1 = json.loads((base / "step-1" / "action.json").read_text(encoding="utf-8"))
        if step1["status"] != "unsafe-selector":
            fail("unsafe_selector_guard", "status must be unsafe-selector", step1)
        if "generated/framework class selector" not in (step1.get("error") or ""):
            fail("unsafe_selector_guard", "error message missing", step1)
        # locator must not have been queried — guard fires before count()
        if called["locator"] != 0:
            fail("unsafe_selector_guard",
                 "locator was queried despite unsafe selector",
                 called)
        # subsequent step must be skipped
        step2 = json.loads((base / "step-2" / "action.json").read_text(encoding="utf-8"))
        if step2["status"] != "skipped":
            fail("unsafe_selector_guard", "follow-up step must be skipped", step2)
        # snapshot for unsafe-selector step should NOT be written (page unchanged)
        if (base / "step-1" / "capture.json").exists():
            fail("unsafe_selector_guard",
                 "snapshot must not be written for unsafe-selector",
                 {})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_navigation_detected_guard() -> None:
    cap = _load_capture_mod()
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        action = {
            "id": "open-dd",
            "kind": "safe-ui-action",
            "snapshotAfterEachStep": True,
            "steps": [
                {"type": "click", "selector": "[data-testid='nav-link']"},
                {"type": "click", "selector": "[data-testid='other']"},
            ],
        }

        def locator_factory(page, sel):
            def navigate():
                page.set_url("http://x/q")  # click causes nav
            return _StubLocator(count_val=1, on_click=navigate)

        page = _StubPage("http://x/p", locator_factory)
        base = tmp / "actions" / action["id"]
        base.mkdir(parents=True)
        cap.run_action_steps(page, action, base, extract_js="")
        step1 = json.loads((base / "step-1" / "action.json").read_text(encoding="utf-8"))
        if step1["status"] != "navigation-detected":
            fail("navigation_detected_guard", "status must be navigation-detected", step1)
        if "/p" not in (step1.get("error") or "") or "/q" not in (step1.get("error") or ""):
            fail("navigation_detected_guard", "error must mention before/after paths", step1)
        if step1["beforeFinalPath"] != "/p" or step1["afterFinalPath"] != "/q":
            fail("navigation_detected_guard", "before/after path fields wrong", step1)
        # snapshot for navigation-detected step IS written (it captures new page state)
        if not (base / "step-1" / "capture.json").exists():
            fail("navigation_detected_guard",
                 "snapshot must be written for navigation-detected", {})
        # subsequent step must be skipped
        step2 = json.loads((base / "step-2" / "action.json").read_text(encoding="utf-8"))
        if step2["status"] != "skipped":
            fail("navigation_detected_guard", "follow-up step must be skipped", step2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_noise_only_scenario_listed_in_dedicated_section() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        a = _scenario_cap("scenario-noise-only", BASELINE)
        b = _scenario_cap("scenario-noise-only", BASELINE)
        # ONLY a knownUnstable signal — no other diff
        b["view"]["classes"]["lds-bars"] = 5
        plan = {"knownUnstable": ["lds-bars"]}
        run = tmp / "run-x"
        _write_capture(run, "A", a)
        _write_capture(run, "B", b)
        diff = build_diff(run, plan=plan)
        report = render_report(diff)
        if "## Differences" in report:
            fail("noise_only_scenario_listed_in_dedicated_section",
                 "noise-only must not appear in Differences",
                 {"report": report})
        if "## Noise-only Scenarios" not in report:
            fail("noise_only_scenario_listed_in_dedicated_section",
                 "missing Noise-only Scenarios section",
                 {"report": report})
        if "scenario-noise-only" not in report:
            fail("noise_only_scenario_listed_in_dedicated_section",
                 "scenarioId not listed", {"report": report})
        if "noise-only scenarios: 1" not in report:
            fail("noise_only_scenario_listed_in_dedicated_section",
                 "Summary count missing", {"report": report})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_noise_candidate_separated() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="mrc-test-"))
    try:
        a = _scenario_cap("scenario-noise", BASELINE)
        b = _scenario_cap("scenario-noise", BASELINE)
        # Inject noise (matches knownUnstable) and one main signal
        b["view"]["classes"]["lds-bars"] = 3                # noise (classes.added)
        b["view"]["classes"]["lds-css"] = 1                 # noise (classes.added)
        b["view"]["texts"].append("Fetching info...")        # noise (texts.added)
        b["console"].append({"type": "warning", "text": "ngucarousel-xyz mounted"})  # noise (non-error console)
        b["view"]["classes"]["genuinely-new"] = 1            # main signal
        # Error console must NOT be filtered as noise even if pattern matches
        b["console"].append({"type": "error", "text": "Fetching info failed catastrophically"})
        plan = {"knownUnstable": ["lds-bars", "lds-css", "Fetching", "ngucarousel"]}
        run = tmp / "run-x"
        _write_capture(run, "A", a)
        _write_capture(run, "B", b)
        diff = build_diff(run, plan=plan)
        entry = diff["pages"].get("scenario-noise")
        if entry is None:
            fail("noise_candidate_separated", "scenario not joined", diff)
        d = entry["diff"]
        noise = entry["noise"]
        if "lds-bars" not in noise["classes_added"] or "lds-css" not in noise["classes_added"]:
            fail("noise_candidate_separated", "noise classes not separated", noise)
        if "lds-bars" in d["classes"]["added"] or "lds-css" in d["classes"]["added"]:
            fail("noise_candidate_separated", "noise leaked into main diff", d["classes"])
        if "genuinely-new" not in d["classes"]["added"]:
            fail("noise_candidate_separated", "main class signal lost", d["classes"])
        if not any("Fetching" in s for s in noise["texts_added"]):
            fail("noise_candidate_separated", "noise text not separated", noise)
        if not any(typ == "warning" and "ngucarousel" in text for typ, text in noise["console_b_new"]):
            fail("noise_candidate_separated", "warning console not separated", noise)
        # Error console with matching substring must remain in main diff
        if not any(typ == "error" and "Fetching" in text for typ, text in d["console"]["b_new"]):
            fail("noise_candidate_separated", "error console must not be classified as noise", d["console"])
        # Render report and confirm noise lives in Noise Candidates subsection only
        report = render_report(diff)
        if "#### Noise Candidates" not in report:
            fail("noise_candidate_separated", "Noise Candidates subsection missing", {"report": report})
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
    case_scenarioid_ab_matching,
    case_expectedfinalpath_mismatch_skips_deep_diff,
    case_invalid_capture_section_in_report,
    case_no_signal_scenario_omitted_from_differences,
    case_noise_candidate_separated,
    case_schema_allows_label_array_and_metadata_object,
    case_plan_helper_labels_and_metadata,
    case_capture_preserves_labels_and_metadata,
    case_report_shows_labels_and_metadata,
    case_compare_autoloads_plan_from_stamp,
    case_noise_only_scenario_listed_in_dedicated_section,
    case_schema_allows_scenario_actions,
    case_action_result_builder_shapes,
    case_compare_reports_action_status_mismatch,
    case_compare_reports_action_step_snapshot_diff,
    case_action_only_diff_keeps_scenario_in_report,
    case_unsafe_selector_guard,
    case_navigation_detected_guard,
]


def main() -> int:
    for fn in CASES:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(CASES)} cases passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
