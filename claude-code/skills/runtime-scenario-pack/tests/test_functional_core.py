#!/usr/bin/env python3
"""Functional-core harness for runtime-scenario-pack.

Runs without pytest. These tests protect the new SSOT model:
scenario pack is reusable, check-plan is only a run projection, and flows are
created only by promotion decisions.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(SKILL_DIR))

from contract import (  # noqa: E402
    ContractError,
    validate_runtime_state_graph,
    validate_scenario_action_candidates,
    validate_scenario_pack,
    validate_state_equivalence_index,
    validate_static_action_graph,
)
from promotion import decide_promotion  # noqa: E402
from projection import project_check_plan  # noqa: E402


def fail(case: str, msg: str, payload=None) -> None:
    print(f"FAIL {case}: {msg}")
    if payload is not None:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    sys.exit(1)


def make_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="rsp-test-"))
    html = root / "apps" / "sample" / "src" / "app" / "home.component.html"
    html.parent.mkdir(parents=True, exist_ok=True)
    html.write_text('<button data-testid="open-menu">Open</button>\n', encoding="utf-8")
    return root


def action(**overrides) -> dict:
    base = {
        "id": "open-menu",
        "intentLabel": "open menu",
        "routeTemplates": ["/home"],
        "componentRefs": ["apps/sample/src/app/home.component.html"],
        "source": {
            "file": "apps/sample/src/app/home.component.html",
            "line": 1,
            "kind": "template",
            "snippet": '<button data-testid="open-menu">Open</button>',
        },
        "selector": "[data-testid='open-menu']",
        "selectorStrategy": "data-testid",
        "selectorEvidence": {
            "file": "apps/sample/src/app/home.component.html",
            "line": 1,
            "attribute": "data-testid",
            "value": "open-menu",
        },
        "classification": "executable",
        "risk": "safe-readonly",
        "effect": "opens-overlay",
        "value": {
            "class": "high",
            "reasons": ["user-requested", "opens-overlay"],
            "observableAfterAction": ["menu appears"],
        },
    }
    base.update(overrides)
    return base


def runtime_state_graph(**overrides) -> dict:
    base = {
        "app": "sample-app",
        "source": "dev-runtime-crawl",
        "states": [
            {
                "id": "state-home-default",
                "contextId": "default",
                "routeTemplate": "/home",
                "path": "/home",
                "expectedFinalPath": "/home",
                "fragmentSignatureId": "frag-home-main",
                "url": "http://localhost:4200/home",
                "title": "Home",
            }
        ],
        "transitions": [],
    }
    base.update(overrides)
    return base


def state_equivalence_index(**overrides) -> dict:
    base = {
        "app": "sample-app",
        "source": "dev-runtime-crawl",
        "items": [
            {
                "stateId": "state-home-default",
                "equivalenceId": "eq-home",
                "fragmentSignatureId": "frag-home-main",
                "stableFragments": ["main"],
                "unstableFragments": [],
            }
        ],
    }
    base.update(overrides)
    return base


def candidate(*, with_action: bool = False, **overrides) -> dict:
    base = {
        "scenarioId": "home-default",
        "actionId": "open-menu",
        "stateId": "state-home-default",
        "runtimeVisible": True,
        "joinEvidence": {
            "route": "exact",
            "component": "source-ref",
            "selector": "matched-runtime",
            "stateDelta": "observed",
        },
        "coverageKey": "home:menu:opens-overlay",
        "confidence": "high",
        "reasons": ["route/component/runtime selector joined"],
    }
    base.update(overrides)
    if with_action:
        base["action"] = action()
    return base


def scenario_pack(static_actions=None, decisions=None) -> dict:
    return {
        "schemaVersion": "1",
        "app": "sample-app",
        "packId": "sample-app-default",
        "baseline": {"branch": "dev", "baseUrl": "http://localhost:4200"},
        "contexts": [
            {
                "id": "default",
                "auth": None,
                "vars": {},
                "labels": ["default"],
                "metadata": {},
            }
        ],
        "routeGraph": {},
        "runtimeStateGraph": runtime_state_graph(),
        "stateEquivalenceIndex": state_equivalence_index(),
        "pageScenarios": [
            {
                "id": "home-default",
                "stateId": "state-home-default",
                "contextId": "default",
                "routeTemplate": "/home",
                "path": "/home",
                "expectedFinalPath": "/home",
                "pageValue": "high",
                "reason": "home page scenario",
            }
        ],
        "staticActions": static_actions if static_actions is not None else [action()],
        "runtimeActions": [],
        "scenarioActionCandidates": [candidate()],
        "promotionDecisions": decisions if decisions is not None else [],
        "rejectedActions": [],
        "uncertainActions": [],
        "knownUnstable": ["tawk.to"],
        "policy": {},
        "provenance": {
            "createdAt": "2026-05-18T00:00:00+09:00",
            "createdFromHead": "abc123",
            "lastVerifiedAt": "2026-05-18T00:00:00+09:00",
            "lastVerifiedHead": "abc123",
        },
    }


def case_static_action_requires_source() -> None:
    root = make_repo()
    try:
        bad = action()
        del bad["source"]
        graph = {"app": "sample-app", "source": "codebase-scan", "items": [bad]}
        try:
            validate_static_action_graph(graph, root)
        except ContractError:
            return
        fail("static_action_requires_source", "source-less action must fail")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_executable_requires_selector_provenance() -> None:
    root = make_repo()
    try:
        bad = action(selectorEvidence=None)
        graph = {"app": "sample-app", "source": "codebase-scan", "items": [bad]}
        try:
            validate_static_action_graph(graph, root)
        except ContractError:
            return
        fail("executable_requires_selector_provenance", "executable action without selectorEvidence must fail")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_unsafe_selector_rejected() -> None:
    root = make_repo()
    try:
        bad = action(selector=".ng-star-inserted")
        graph = {"app": "sample-app", "source": "codebase-scan", "items": [bad]}
        try:
            validate_static_action_graph(graph, root)
        except ContractError:
            return
        fail("unsafe_selector_rejected", "generated selector must fail")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_action_requires_mapping_evidence() -> None:
    root = make_repo()
    try:
        bad = action(routeTemplates=[], componentRefs=[])
        graph = {"app": "sample-app", "source": "codebase-scan", "items": [bad]}
        try:
            validate_static_action_graph(graph, root)
        except ContractError:
            return
        fail("action_requires_mapping_evidence", "action must have routeTemplates or componentRefs")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_source_file_rejects_parent_traversal() -> None:
    root = make_repo()
    try:
        bad = action()
        bad["source"]["file"] = "apps/../secrets.txt"
        graph = {"app": "sample-app", "source": "codebase-scan", "items": [bad]}
        try:
            validate_static_action_graph(graph, root)
        except ContractError:
            return
        fail("source_file_rejects_parent_traversal", "source file path must reject parent traversal")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_runtime_state_graph_and_equivalence_validate() -> None:
    state_ids = validate_runtime_state_graph(runtime_state_graph(), {"default"})
    if state_ids != {"state-home-default"}:
        fail("runtime_state_graph_and_equivalence_validate", "unexpected state ids", sorted(state_ids))
    state_by_id = {state["id"]: state for state in runtime_state_graph()["states"]}
    equivalence_ids = validate_state_equivalence_index(state_equivalence_index(), state_ids, state_by_id)
    if equivalence_ids != {"eq-home"}:
        fail("runtime_state_graph_and_equivalence_validate", "unexpected equivalence ids", sorted(equivalence_ids))


def case_state_equivalence_fragment_must_match_state() -> None:
    state_ids = validate_runtime_state_graph(runtime_state_graph(), {"default"})
    state_by_id = {state["id"]: state for state in runtime_state_graph()["states"]}
    bad = state_equivalence_index()
    bad["items"][0]["fragmentSignatureId"] = "frag-other"
    try:
        validate_state_equivalence_index(bad, state_ids, state_by_id)
    except ContractError:
        return
    fail("state_equivalence_fragment_must_match_state", "equivalence fragment must match runtime state")


def case_candidate_matrix_requires_runtime_state_and_join_evidence() -> None:
    try:
        validate_scenario_action_candidates(
            [candidate(stateId="missing-state")],
            {"home-default"},
            {"open-menu"},
            {"state-home-default"},
        )
    except ContractError:
        return
    fail("candidate_matrix_requires_runtime_state_and_join_evidence", "candidate must reference runtime state")


def case_promotes_safe_high_value_visible_action() -> None:
    decision = decide_promotion(candidate(with_action=True))
    if decision["decision"] != "promote-to-flow":
        fail("promotes_safe_high_value_visible_action", "expected promotion", decision)
    if decision["flow"]["steps"][0]["selector"] != "[data-testid='open-menu']":
        fail("promotes_safe_high_value_visible_action", "selector not preserved", decision)


def case_promotion_requires_runtime_selector_match() -> None:
    joined = candidate(with_action=True, joinEvidence={
        "route": "exact",
        "component": "source-ref",
        "selector": "not-found",
        "stateDelta": "observed",
    })
    decision = decide_promotion(joined)
    if decision["decision"] != "reject-not-visible":
        fail("promotion_requires_runtime_selector_match", "selector must be seen on dev state", decision)


def case_promotion_requires_state_delta_evidence() -> None:
    joined = candidate(with_action=True, joinEvidence={
        "route": "exact",
        "component": "source-ref",
        "selector": "matched-runtime",
        "stateDelta": "not-observed",
    })
    decision = decide_promotion(joined)
    if decision["decision"] != "manual-review":
        fail("promotion_requires_state_delta_evidence", "missing state delta must not auto-promote", decision)


def case_low_value_not_promoted() -> None:
    low = action(value={"class": "low", "reasons": ["decorative-only"]})
    joined = candidate(with_action=True)
    joined["action"] = low
    decision = decide_promotion(joined)
    if decision["decision"] != "reject-low-value":
        fail("low_value_not_promoted", "low value action must not be promoted", decision)


def case_navigation_not_safe_flow() -> None:
    nav = action(effect="navigation", risk="navigation", classification="navigation-evidence")
    joined = candidate(with_action=True)
    joined["action"] = nav
    decision = decide_promotion(joined)
    if decision["decision"] != "keep-as-navigation-evidence":
        fail("navigation_not_safe_flow", "navigation must remain navigation evidence", decision)


def case_selector_evidence_must_match_strategy() -> None:
    root = make_repo()
    try:
        bad = action(selectorEvidence={
            "file": "apps/sample/src/app/home.component.html",
            "line": 1,
            "attribute": "aria-label",
            "value": "open-menu",
        })
        graph = {"app": "sample-app", "source": "codebase-scan", "items": [bad]}
        try:
            validate_static_action_graph(graph, root)
        except ContractError:
            return
        fail("selector_evidence_must_match_strategy", "selectorEvidence must match selectorStrategy")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_pack_baseline_must_be_dev() -> None:
    root = make_repo()
    try:
        pack = scenario_pack()
        pack["baseline"]["branch"] = "feature"
        try:
            validate_scenario_pack(pack, root)
        except ContractError:
            return
        fail("pack_baseline_must_be_dev", "scenario pack baseline must be dev")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_pack_rejects_unknown_context_reference() -> None:
    root = make_repo()
    try:
        pack = scenario_pack()
        pack["pageScenarios"][0]["contextId"] = "missing"
        try:
            validate_scenario_pack(pack, root)
        except ContractError:
            return
        fail("pack_rejects_unknown_context_reference", "scenario context must reference contexts[].id")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_pack_rejects_unknown_scenario_state_reference() -> None:
    root = make_repo()
    try:
        pack = scenario_pack()
        pack["pageScenarios"][0]["stateId"] = "missing-state"
        try:
            validate_scenario_pack(pack, root)
        except ContractError:
            return
        fail("pack_rejects_unknown_scenario_state_reference", "scenario stateId must reference runtimeStateGraph")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_pack_rejects_scenario_state_field_mismatch() -> None:
    root = make_repo()
    try:
        pack = scenario_pack()
        pack["pageScenarios"][0]["path"] = "/different"
        try:
            validate_scenario_pack(pack, root)
        except ContractError:
            return
        fail("pack_rejects_scenario_state_field_mismatch", "scenario path must match referenced runtime state")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_pack_rejects_unresolved_concrete_path_param() -> None:
    root = make_repo()
    try:
        pack = scenario_pack()
        pack["pageScenarios"][0]["path"] = "/groups/:groupId/home"
        try:
            validate_scenario_pack(pack, root)
        except ContractError:
            return
        fail("pack_rejects_unresolved_concrete_path_param", "concrete path must not contain unresolved params")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_pack_rejects_promoted_flow_without_candidate_gate() -> None:
    root = make_repo()
    try:
        decision = decide_promotion(candidate(with_action=True))
        pack = scenario_pack(decisions=[decision])
        pack["scenarioActionCandidates"][0]["joinEvidence"]["selector"] = "not-found"
        try:
            validate_scenario_pack(pack, root)
        except ContractError:
            return
        fail("pack_rejects_promoted_flow_without_candidate_gate", "promote-to-flow must require candidate runtime selector evidence")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_pack_rejects_promoted_flow_for_low_value_action() -> None:
    root = make_repo()
    try:
        low = action(value={"class": "low", "reasons": ["decorative-only"]})
        decision = decide_promotion(candidate(with_action=True))
        decision["decision"] = "promote-to-flow"
        pack = scenario_pack(static_actions=[low], decisions=[decision])
        try:
            validate_scenario_pack(pack, root)
        except ContractError:
            return
        fail("pack_rejects_promoted_flow_for_low_value_action", "manual promote-to-flow must not bypass value gate")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_pack_rejects_promoted_flow_selector_mismatch() -> None:
    root = make_repo()
    try:
        decision = decide_promotion(candidate(with_action=True))
        decision["flow"]["steps"][0]["selector"] = "[data-testid='other']"
        pack = scenario_pack(decisions=[decision])
        try:
            validate_scenario_pack(pack, root)
        except ContractError:
            return
        fail("pack_rejects_promoted_flow_selector_mismatch", "flow selector must match action selector")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_pack_rejects_promoted_flows_dual_source_of_truth() -> None:
    root = make_repo()
    try:
        pack = scenario_pack()
        pack["promotedFlows"] = []
        try:
            validate_scenario_pack(pack, root)
        except ContractError:
            return
        fail("pack_rejects_promoted_flows_dual_source_of_truth", "promotedFlows must not be accepted as second SSOT")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_project_check_plan_from_pack() -> None:
    root = make_repo()
    try:
        decision = decide_promotion(candidate(with_action=True))
        pack = scenario_pack(decisions=[decision])
        validate_scenario_pack(pack, root)
        run_auth = {"storageState": ".auth/sample.json"}
        check_plan = project_check_plan(pack, candidate_branch="feature/x", run_auth=run_auth)
        if check_plan["baseline"]["branch"] != "dev":
            fail("project_check_plan_from_pack", "baseline branch must remain dev", check_plan)
        if check_plan["candidate"]["branch"] != "feature/x":
            fail("project_check_plan_from_pack", "candidate branch not projected", check_plan)
        if check_plan["auth"] != run_auth:
            fail("project_check_plan_from_pack", "run auth must come from projection input", check_plan)
        flows = check_plan["scenarios"][0]["flows"]
        if not flows or flows[0]["id"] != "open-menu":
            fail("project_check_plan_from_pack", "promoted flow not projected", check_plan)
    finally:
        shutil.rmtree(root, ignore_errors=True)


CASES = [
    case_static_action_requires_source,
    case_executable_requires_selector_provenance,
    case_unsafe_selector_rejected,
    case_action_requires_mapping_evidence,
    case_source_file_rejects_parent_traversal,
    case_runtime_state_graph_and_equivalence_validate,
    case_state_equivalence_fragment_must_match_state,
    case_candidate_matrix_requires_runtime_state_and_join_evidence,
    case_promotes_safe_high_value_visible_action,
    case_promotion_requires_runtime_selector_match,
    case_promotion_requires_state_delta_evidence,
    case_low_value_not_promoted,
    case_navigation_not_safe_flow,
    case_selector_evidence_must_match_strategy,
    case_pack_baseline_must_be_dev,
    case_pack_rejects_unknown_context_reference,
    case_pack_rejects_unknown_scenario_state_reference,
    case_pack_rejects_scenario_state_field_mismatch,
    case_pack_rejects_unresolved_concrete_path_param,
    case_pack_rejects_promoted_flow_without_candidate_gate,
    case_pack_rejects_promoted_flow_for_low_value_action,
    case_pack_rejects_promoted_flow_selector_mismatch,
    case_pack_rejects_promoted_flows_dual_source_of_truth,
    case_project_check_plan_from_pack,
]


def main() -> int:
    for fn in CASES:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(CASES)} cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
