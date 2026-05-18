"""Runtime artifact validators for runtime-scenario-pack.

The schema is enforced semantically here instead of through a third-party JSON
Schema dependency. Validators are pure: they receive plain dicts and return
None or raise ContractError.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from models import (
    ACTION_CLASSIFICATIONS,
    ACTION_EFFECTS,
    ACTION_RISKS,
    ACTION_VALUES,
    ALLOWED_FLOW_EFFECTS,
    CANDIDATE_CONFIDENCE,
    JOIN_COMPONENT_EVIDENCE,
    JOIN_ROUTE_EVIDENCE,
    JOIN_SELECTOR_EVIDENCE,
    JOIN_STATE_DELTA_EVIDENCE,
    PROMOTION_DECISIONS,
    SELECTOR_STRATEGIES,
    STATE_GRAPH_SOURCE,
    UNSAFE_SELECTOR_PATTERNS,
    VALUE_REASONS,
)


class ContractError(ValueError):
    pass


def _fail(errors: list[str], path: str, message: str) -> None:
    errors.append(f"{path}: {message}")


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_keys(errors: list[str], path: str, obj: dict, allowed: set[str], required: set[str]) -> None:
    missing = sorted(required - set(obj))
    extra = sorted(set(obj) - allowed)
    for key in missing:
        _fail(errors, path, f"missing required key {key!r}")
    for key in extra:
        _fail(errors, path, f"unknown key {key!r}")


def _check_no_unresolved_params(errors: list[str], path: str, value: Any) -> None:
    if isinstance(value, str) and any(part.startswith(":") for part in value.split("/")):
        _fail(errors, path, "must not contain unresolved route parameters")


def _check_url(errors: list[str], path: str, value: Any) -> None:
    if not _is_nonempty_string(value):
        _fail(errors, path, "must be a non-empty string")
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        _fail(errors, path, "must be an absolute http(s) URL")


def _safe_rel_file(errors: list[str], path: str, value: Any, repo_root: Path | None) -> None:
    if not _is_nonempty_string(value):
        _fail(errors, path, "must be a non-empty string")
        return
    rel_path = Path(value)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        _fail(errors, path, "must be a safe relative path without parent traversal")
    if not (value.startswith("apps/") or value.startswith("libs/")):
        _fail(errors, path, "must be under apps/ or libs/")
    if repo_root is not None and not (repo_root / value).is_file():
        _fail(errors, path, "must reference an existing file")


def _positive_int(errors: list[str], path: str, value: Any) -> None:
    if not isinstance(value, int) or value <= 0:
        _fail(errors, path, "must be a positive integer")


def _selector_is_unsafe(selector: str) -> bool:
    return any(pattern in selector for pattern in UNSAFE_SELECTOR_PATTERNS)


def _validate_source(errors: list[str], path: str, obj: Any, repo_root: Path | None) -> None:
    if not isinstance(obj, dict):
        _fail(errors, path, "must be an object")
        return
    _check_keys(errors, path, obj, {"file", "line", "kind", "snippet"}, {"file", "line", "kind", "snippet"})
    _safe_rel_file(errors, f"{path}.file", obj.get("file"), repo_root)
    _positive_int(errors, f"{path}.line", obj.get("line"))
    if obj.get("kind") not in {"template", "component", "route", "runtime"}:
        _fail(errors, f"{path}.kind", "must be template/component/route/runtime")
    if not _is_nonempty_string(obj.get("snippet")):
        _fail(errors, f"{path}.snippet", "must be a non-empty string")
    elif len(obj["snippet"]) > 240:
        _fail(errors, f"{path}.snippet", "must be a short excerpt, not a full template")


def _validate_selector_evidence(
    errors: list[str],
    path: str,
    obj: Any,
    repo_root: Path | None,
    selector_strategy: str | None,
) -> None:
    if not isinstance(obj, dict):
        _fail(errors, path, "must be an object")
        return
    allowed = {"file", "line", "attribute", "value", "role", "name"}
    _check_keys(errors, path, obj, allowed, {"file", "line"})
    _safe_rel_file(errors, f"{path}.file", obj.get("file"), repo_root)
    _positive_int(errors, f"{path}.line", obj.get("line"))
    if selector_strategy in {"data-testid", "aria-label", "router-link-text", "visible-text-with-unique-context"}:
        expected_attribute = {
            "data-testid": "data-testid",
            "aria-label": "aria-label",
            "router-link-text": "routerLink",
            "visible-text-with-unique-context": "text",
        }[selector_strategy]
        if obj.get("attribute") != expected_attribute:
            _fail(errors, f"{path}.attribute", f"must be {expected_attribute!r} for selectorStrategy={selector_strategy}")
        if not _is_nonempty_string(obj.get("value")):
            _fail(errors, f"{path}.value", "must be a non-empty string")
    elif selector_strategy == "role+name":
        if not _is_nonempty_string(obj.get("role")):
            _fail(errors, f"{path}.role", "must be a non-empty string for selectorStrategy=role+name")
        if not _is_nonempty_string(obj.get("name")):
            _fail(errors, f"{path}.name", "must be a non-empty string for selectorStrategy=role+name")


def validate_static_action_graph(graph: dict, repo_root: str | Path | None = None) -> None:
    errors: list[str] = []
    root = Path(repo_root) if repo_root is not None else None
    if not isinstance(graph, dict):
        raise ContractError("static action graph must be an object")
    _check_keys(errors, "$", graph, {"app", "source", "items"}, {"app", "source", "items"})
    if not _is_nonempty_string(graph.get("app")):
        _fail(errors, "$.app", "must be a non-empty string")
    if graph.get("source") != "codebase-scan":
        _fail(errors, "$.source", "must be 'codebase-scan'")
    items = graph.get("items")
    ids: set[str] = set()
    if not isinstance(items, list):
        _fail(errors, "$.items", "must be an array")
    else:
        for i, action in enumerate(items):
            _validate_static_action(errors, f"$.items[{i}]", action, ids, root)
    if errors:
        raise ContractError("static action graph contract violation:\n- " + "\n- ".join(errors))


def validate_runtime_state_graph(graph: dict, context_ids: set[str] | None = None) -> set[str]:
    errors: list[str] = []
    if not isinstance(graph, dict):
        raise ContractError("runtime state graph must be an object")
    _check_keys(errors, "$", graph, {"app", "source", "states", "transitions"}, {"app", "source", "states", "transitions"})
    if not _is_nonempty_string(graph.get("app")):
        _fail(errors, "$.app", "must be a non-empty string")
    if graph.get("source") != STATE_GRAPH_SOURCE:
        _fail(errors, "$.source", f"must be {STATE_GRAPH_SOURCE!r}")
    states = graph.get("states")
    state_ids: set[str] = set()
    if not isinstance(states, list) or not states:
        _fail(errors, "$.states", "must be a non-empty array")
    else:
        for i, state in enumerate(states):
            _validate_runtime_state(errors, f"$.states[{i}]", state, state_ids, context_ids)
    transitions = graph.get("transitions")
    if not isinstance(transitions, list):
        _fail(errors, "$.transitions", "must be an array")
    else:
        transition_ids: set[str] = set()
        for i, transition in enumerate(transitions):
            _validate_runtime_transition(errors, f"$.transitions[{i}]", transition, transition_ids, state_ids)
    if errors:
        raise ContractError("runtime state graph contract violation:\n- " + "\n- ".join(errors))
    return state_ids


def validate_state_equivalence_index(index: dict, state_ids: set[str], state_by_id: dict[str, dict] | None = None) -> set[str]:
    errors: list[str] = []
    if not isinstance(index, dict):
        raise ContractError("state equivalence index must be an object")
    _check_keys(errors, "$", index, {"app", "source", "items"}, {"app", "source", "items"})
    if not _is_nonempty_string(index.get("app")):
        _fail(errors, "$.app", "must be a non-empty string")
    if index.get("source") != STATE_GRAPH_SOURCE:
        _fail(errors, "$.source", f"must be {STATE_GRAPH_SOURCE!r}")
    items = index.get("items")
    indexed_states: set[str] = set()
    equivalence_ids: set[str] = set()
    if not isinstance(items, list) or not items:
        _fail(errors, "$.items", "must be a non-empty array")
    else:
        for i, item in enumerate(items):
            _validate_state_equivalence_item(errors, f"$.items[{i}]", item, state_ids, indexed_states, equivalence_ids, state_by_id)
    missing = sorted(state_ids - indexed_states)
    for state_id in missing:
        _fail(errors, "$.items", f"missing equivalence entry for state {state_id!r}")
    if errors:
        raise ContractError("state equivalence index contract violation:\n- " + "\n- ".join(errors))
    return equivalence_ids


def validate_scenario_action_candidates(
    candidates: list[dict],
    scenario_ids: set[str],
    action_ids: set[str],
    state_ids: set[str],
) -> set[tuple[str, str]]:
    errors: list[str] = []
    if not isinstance(candidates, list):
        raise ContractError("scenario action candidates must be an array")
    seen: set[tuple[str, str]] = set()
    for i, candidate in enumerate(candidates):
        _validate_scenario_action_candidate(errors, f"$[{i}]", candidate, scenario_ids, action_ids, state_ids, seen)
    if errors:
        raise ContractError("scenario action candidates contract violation:\n- " + "\n- ".join(errors))
    return seen


def _validate_static_action(errors: list[str], path: str, action: Any, ids: set[str], repo_root: Path | None) -> None:
    if not isinstance(action, dict):
        _fail(errors, path, "must be an object")
        return
    allowed = {
        "id", "intentLabel", "routeTemplates", "componentRefs", "source",
        "selector", "selectorStrategy", "selectorEvidence", "classification",
        "risk", "effect", "value",
    }
    required = {"id", "intentLabel", "source", "classification", "risk", "effect", "value"}
    _check_keys(errors, path, action, allowed, required)
    action_id = action.get("id")
    if not _is_nonempty_string(action_id):
        _fail(errors, f"{path}.id", "must be a non-empty string")
    elif action_id in ids:
        _fail(errors, f"{path}.id", f"duplicate action id {action_id!r}")
    else:
        ids.add(action_id)
    if not _is_nonempty_string(action.get("intentLabel")):
        _fail(errors, f"{path}.intentLabel", "must be a non-empty string")
    _validate_source(errors, f"{path}.source", action.get("source"), repo_root)
    route_templates = action.get("routeTemplates", [])
    if route_templates and (not isinstance(route_templates, list) or not all(_is_nonempty_string(x) for x in route_templates)):
        _fail(errors, f"{path}.routeTemplates", "must be an array of strings")
    component_refs = action.get("componentRefs", [])
    if component_refs and not isinstance(component_refs, list):
        _fail(errors, f"{path}.componentRefs", "must be an array")
    elif isinstance(component_refs, list):
        for j, ref in enumerate(component_refs):
            _safe_rel_file(errors, f"{path}.componentRefs[{j}]", ref, repo_root)
    if not route_templates and not component_refs:
        _fail(errors, path, "action requires routeTemplates or componentRefs for scenario mapping")
    classification = action.get("classification")
    risk = action.get("risk")
    effect = action.get("effect")
    if classification not in ACTION_CLASSIFICATIONS:
        _fail(errors, f"{path}.classification", f"must be one of {sorted(ACTION_CLASSIFICATIONS)}")
    if risk not in ACTION_RISKS:
        _fail(errors, f"{path}.risk", f"must be one of {sorted(ACTION_RISKS)}")
    if effect not in ACTION_EFFECTS:
        _fail(errors, f"{path}.effect", f"must be one of {sorted(ACTION_EFFECTS)}")
    selector = action.get("selector")
    selector_strategy = action.get("selectorStrategy")
    if selector is not None:
        if not _is_nonempty_string(selector):
            _fail(errors, f"{path}.selector", "must be null or a non-empty string")
        elif _selector_is_unsafe(selector):
            _fail(errors, f"{path}.selector", "generated/framework selectors are not allowed")
    if selector_strategy is not None and selector_strategy not in SELECTOR_STRATEGIES:
        _fail(errors, f"{path}.selectorStrategy", f"must be one of {sorted(SELECTOR_STRATEGIES)}")
    if classification == "executable":
        if not selector:
            _fail(errors, path, "executable action requires selector")
        if not selector_strategy:
            _fail(errors, path, "executable action requires selectorStrategy")
        _validate_selector_evidence(errors, f"{path}.selectorEvidence", action.get("selectorEvidence"), repo_root, selector_strategy)
        if risk != "safe-readonly":
            _fail(errors, f"{path}.risk", "executable action must be safe-readonly")
    _validate_value(errors, f"{path}.value", action.get("value"))


def _validate_runtime_state(
    errors: list[str],
    path: str,
    state: Any,
    ids: set[str],
    context_ids: set[str] | None,
) -> None:
    if not isinstance(state, dict):
        _fail(errors, path, "must be an object")
        return
    allowed = {"id", "contextId", "routeTemplate", "path", "expectedFinalPath", "fragmentSignatureId", "url", "title"}
    required = {"id", "contextId", "routeTemplate", "path", "expectedFinalPath", "fragmentSignatureId"}
    _check_keys(errors, path, state, allowed, required)
    sid = state.get("id")
    if not _is_nonempty_string(sid):
        _fail(errors, f"{path}.id", "must be a non-empty string")
    elif sid in ids:
        _fail(errors, f"{path}.id", f"duplicate state id {sid!r}")
    else:
        ids.add(sid)
    if context_ids is not None and state.get("contextId") not in context_ids:
        _fail(errors, f"{path}.contextId", "must reference contexts[].id")
    for key in ("contextId", "routeTemplate", "path", "expectedFinalPath", "fragmentSignatureId"):
        if not _is_nonempty_string(state.get(key)):
            _fail(errors, f"{path}.{key}", "must be a non-empty string")
    _check_no_unresolved_params(errors, f"{path}.path", state.get("path"))
    _check_no_unresolved_params(errors, f"{path}.expectedFinalPath", state.get("expectedFinalPath"))
    if state.get("url") is not None:
        _check_url(errors, f"{path}.url", state.get("url"))
    if state.get("title") is not None and not isinstance(state.get("title"), str):
        _fail(errors, f"{path}.title", "must be a string")


def _validate_runtime_transition(
    errors: list[str],
    path: str,
    transition: Any,
    ids: set[str],
    state_ids: set[str],
) -> None:
    if not isinstance(transition, dict):
        _fail(errors, path, "must be an object")
        return
    allowed = {"id", "fromStateId", "toStateId", "actionId", "selector", "effect"}
    required = {"id", "fromStateId", "toStateId", "effect"}
    _check_keys(errors, path, transition, allowed, required)
    tid = transition.get("id")
    if not _is_nonempty_string(tid):
        _fail(errors, f"{path}.id", "must be a non-empty string")
    elif tid in ids:
        _fail(errors, f"{path}.id", f"duplicate transition id {tid!r}")
    else:
        ids.add(tid)
    for key in ("fromStateId", "toStateId"):
        if transition.get(key) not in state_ids:
            _fail(errors, f"{path}.{key}", "must reference runtimeStateGraph.states[].id")
    if transition.get("actionId") is not None and not _is_nonempty_string(transition.get("actionId")):
        _fail(errors, f"{path}.actionId", "must be null or a non-empty string")
    selector = transition.get("selector")
    if selector is not None:
        if not _is_nonempty_string(selector):
            _fail(errors, f"{path}.selector", "must be null or a non-empty string")
        elif _selector_is_unsafe(selector):
            _fail(errors, f"{path}.selector", "generated/framework selectors are not allowed")
    if transition.get("effect") not in ACTION_EFFECTS:
        _fail(errors, f"{path}.effect", f"must be one of {sorted(ACTION_EFFECTS)}")


def _validate_state_equivalence_item(
    errors: list[str],
    path: str,
    item: Any,
    state_ids: set[str],
    indexed_states: set[str],
    equivalence_ids: set[str],
    state_by_id: dict[str, dict] | None,
) -> None:
    if not isinstance(item, dict):
        _fail(errors, path, "must be an object")
        return
    allowed = {"stateId", "equivalenceId", "fragmentSignatureId", "stableFragments", "unstableFragments"}
    required = {"stateId", "equivalenceId", "fragmentSignatureId", "stableFragments", "unstableFragments"}
    _check_keys(errors, path, item, allowed, required)
    state_id = item.get("stateId")
    if state_id not in state_ids:
        _fail(errors, f"{path}.stateId", "must reference runtimeStateGraph.states[].id")
    elif state_id in indexed_states:
        _fail(errors, f"{path}.stateId", f"duplicate equivalence entry for state {state_id!r}")
    else:
        indexed_states.add(state_id)
    if not _is_nonempty_string(item.get("equivalenceId")):
        _fail(errors, f"{path}.equivalenceId", "must be a non-empty string")
    else:
        equivalence_ids.add(item["equivalenceId"])
    if not _is_nonempty_string(item.get("fragmentSignatureId")):
        _fail(errors, f"{path}.fragmentSignatureId", "must be a non-empty string")
    elif state_by_id is not None and state_id in state_by_id and item.get("fragmentSignatureId") != state_by_id[state_id].get("fragmentSignatureId"):
        _fail(errors, f"{path}.fragmentSignatureId", "must match the referenced runtime state")
    for key in ("stableFragments", "unstableFragments"):
        value = item.get(key)
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            _fail(errors, f"{path}.{key}", "must be an array of strings")


def _validate_scenario_action_candidate(
    errors: list[str],
    path: str,
    candidate: Any,
    scenario_ids: set[str],
    action_ids: set[str],
    state_ids: set[str],
    seen: set[tuple[str, str]],
) -> None:
    if not isinstance(candidate, dict):
        _fail(errors, path, "must be an object")
        return
    allowed = {"scenarioId", "actionId", "stateId", "runtimeVisible", "joinEvidence", "coverageKey", "confidence", "reasons"}
    required = allowed
    _check_keys(errors, path, candidate, allowed, required)
    scenario_id = candidate.get("scenarioId")
    action_id = candidate.get("actionId")
    key = (scenario_id, action_id)
    if scenario_id not in scenario_ids:
        _fail(errors, f"{path}.scenarioId", "must reference pageScenarios[].id")
    if action_id not in action_ids:
        _fail(errors, f"{path}.actionId", "must reference staticActions[].id")
    if scenario_id in scenario_ids and action_id in action_ids:
        if key in seen:
            _fail(errors, path, f"duplicate candidate for scenario/action {key!r}")
        else:
            seen.add(key)
    if candidate.get("stateId") not in state_ids:
        _fail(errors, f"{path}.stateId", "must reference runtimeStateGraph.states[].id")
    if not isinstance(candidate.get("runtimeVisible"), bool):
        _fail(errors, f"{path}.runtimeVisible", "must be a boolean")
    _validate_join_evidence(errors, f"{path}.joinEvidence", candidate.get("joinEvidence"))
    if not _is_nonempty_string(candidate.get("coverageKey")):
        _fail(errors, f"{path}.coverageKey", "must be a non-empty string")
    if candidate.get("confidence") not in CANDIDATE_CONFIDENCE:
        _fail(errors, f"{path}.confidence", f"must be one of {sorted(CANDIDATE_CONFIDENCE)}")
    if not isinstance(candidate.get("reasons"), list) or not all(isinstance(x, str) for x in candidate.get("reasons", [])):
        _fail(errors, f"{path}.reasons", "must be an array of strings")


def _validate_join_evidence(errors: list[str], path: str, evidence: Any) -> None:
    if not isinstance(evidence, dict):
        _fail(errors, path, "must be an object")
        return
    _check_keys(errors, path, evidence, {"route", "component", "selector", "stateDelta"}, {"route", "component", "selector", "stateDelta"})
    if evidence.get("route") not in JOIN_ROUTE_EVIDENCE:
        _fail(errors, f"{path}.route", f"must be one of {sorted(JOIN_ROUTE_EVIDENCE)}")
    if evidence.get("component") not in JOIN_COMPONENT_EVIDENCE:
        _fail(errors, f"{path}.component", f"must be one of {sorted(JOIN_COMPONENT_EVIDENCE)}")
    if evidence.get("selector") not in JOIN_SELECTOR_EVIDENCE:
        _fail(errors, f"{path}.selector", f"must be one of {sorted(JOIN_SELECTOR_EVIDENCE)}")
    if evidence.get("stateDelta") not in JOIN_STATE_DELTA_EVIDENCE:
        _fail(errors, f"{path}.stateDelta", f"must be one of {sorted(JOIN_STATE_DELTA_EVIDENCE)}")


def _validate_value(errors: list[str], path: str, value: Any) -> None:
    if not isinstance(value, dict):
        _fail(errors, path, "must be an object")
        return
    _check_keys(errors, path, value, {"class", "reasons", "observableAfterAction"}, {"class", "reasons"})
    if value.get("class") not in ACTION_VALUES:
        _fail(errors, f"{path}.class", f"must be one of {sorted(ACTION_VALUES)}")
    reasons = value.get("reasons")
    if not isinstance(reasons, list) or any(reason not in VALUE_REASONS for reason in reasons):
        _fail(errors, f"{path}.reasons", f"must contain only {sorted(VALUE_REASONS)}")
    observables = value.get("observableAfterAction", [])
    if observables and (not isinstance(observables, list) or not all(isinstance(x, str) for x in observables)):
        _fail(errors, f"{path}.observableAfterAction", "must be an array of strings")


def validate_scenario_pack(pack: dict, repo_root: str | Path | None = None) -> None:
    errors: list[str] = []
    if not isinstance(pack, dict):
        raise ContractError("scenario pack must be an object")
    allowed = {
        "schemaVersion", "app", "packId", "baseline", "contexts", "routeGraph",
        "runtimeStateGraph", "stateEquivalenceIndex", "pageScenarios", "staticActions", "runtimeActions",
        "scenarioActionCandidates", "promotionDecisions",
        "rejectedActions", "uncertainActions", "knownUnstable", "policy", "provenance",
    }
    required = {
        "schemaVersion", "app", "packId", "baseline", "contexts",
        "runtimeStateGraph", "stateEquivalenceIndex", "pageScenarios",
        "staticActions", "scenarioActionCandidates", "promotionDecisions", "provenance",
    }
    _check_keys(errors, "$", pack, allowed, required)
    for key in ("schemaVersion", "app", "packId"):
        if not _is_nonempty_string(pack.get(key)):
            _fail(errors, f"$.{key}", "must be a non-empty string")
    baseline = pack.get("baseline")
    if not isinstance(baseline, dict):
        _fail(errors, "$.baseline", "must be an object")
    else:
        _check_keys(errors, "$.baseline", baseline, {"branch", "baseUrl"}, {"branch", "baseUrl"})
        if baseline.get("branch") != "dev":
            _fail(errors, "$.baseline.branch", "scenario pack baseline must be dev")
        _check_url(errors, "$.baseline.baseUrl", baseline.get("baseUrl"))
    context_ids = _validate_contexts(errors, "$.contexts", pack.get("contexts"))
    state_ids: set[str] = set()
    state_by_id: dict[str, dict] = {
        s.get("id"): s
        for s in ((pack.get("runtimeStateGraph") or {}).get("states") or [])
        if isinstance(s, dict) and _is_nonempty_string(s.get("id"))
    } if isinstance(pack.get("runtimeStateGraph"), dict) else {}
    try:
        state_ids = validate_runtime_state_graph(pack.get("runtimeStateGraph"), context_ids)
    except ContractError as exc:
        _fail(errors, "$.runtimeStateGraph", str(exc))
    try:
        validate_state_equivalence_index(pack.get("stateEquivalenceIndex"), state_ids, state_by_id)
    except ContractError as exc:
        _fail(errors, "$.stateEquivalenceIndex", str(exc))
    scenarios = pack.get("pageScenarios")
    scenario_ids: set[str] = set()
    if not isinstance(scenarios, list) or not scenarios:
        _fail(errors, "$.pageScenarios", "must be a non-empty array")
    else:
        for i, scenario in enumerate(scenarios):
            if not isinstance(scenario, dict):
                _fail(errors, f"$.pageScenarios[{i}]", "must be an object")
                continue
            sid = scenario.get("id")
            if not _is_nonempty_string(sid):
                _fail(errors, f"$.pageScenarios[{i}].id", "must be a non-empty string")
            elif sid in scenario_ids:
                _fail(errors, f"$.pageScenarios[{i}].id", f"duplicate scenario id {sid!r}")
            else:
                scenario_ids.add(sid)
            _check_keys(
                errors,
                f"$.pageScenarios[{i}]",
                scenario,
                {"id", "stateId", "contextId", "routeTemplate", "path", "expectedFinalPath", "pageValue", "reason"},
                {"id", "stateId", "contextId", "routeTemplate", "path", "expectedFinalPath", "pageValue", "reason"},
            )
            if state_ids and scenario.get("stateId") not in state_ids:
                _fail(errors, f"$.pageScenarios[{i}].stateId", "must reference runtimeStateGraph.states[].id")
            state = state_by_id.get(scenario.get("stateId"))
            if state is not None:
                for key in ("contextId", "routeTemplate", "path", "expectedFinalPath"):
                    if scenario.get(key) != state.get(key):
                        _fail(errors, f"$.pageScenarios[{i}].{key}", "must match the referenced runtime state")
            if context_ids and scenario.get("contextId") not in context_ids:
                _fail(errors, f"$.pageScenarios[{i}].contextId", "must reference contexts[].id")
            for key in ("stateId", "contextId", "path", "expectedFinalPath"):
                if not _is_nonempty_string(scenario.get(key)):
                    _fail(errors, f"$.pageScenarios[{i}].{key}", "must be a non-empty string")
            if not _is_nonempty_string(scenario.get("routeTemplate")):
                _fail(errors, f"$.pageScenarios[{i}].routeTemplate", "must be a non-empty string")
            if scenario.get("pageValue") not in {"high", "medium", "low", "unknown"}:
                _fail(errors, f"$.pageScenarios[{i}].pageValue", "must be high/medium/low/unknown")
            if not _is_nonempty_string(scenario.get("reason")):
                _fail(errors, f"$.pageScenarios[{i}].reason", "must be a non-empty string")
            _check_no_unresolved_params(errors, f"$.pageScenarios[{i}].path", scenario.get("path"))
            _check_no_unresolved_params(errors, f"$.pageScenarios[{i}].expectedFinalPath", scenario.get("expectedFinalPath"))
    actions_graph = {"app": pack.get("app"), "source": "codebase-scan", "items": pack.get("staticActions", [])}
    try:
        validate_static_action_graph(actions_graph, repo_root)
    except ContractError as exc:
        _fail(errors, "$.staticActions", str(exc))
    action_by_id = {a.get("id"): a for a in pack.get("staticActions", []) if isinstance(a, dict) and _is_nonempty_string(a.get("id"))}
    candidate_by_pair: dict[tuple[str, str], dict] = {}
    try:
        validate_scenario_action_candidates(pack.get("scenarioActionCandidates"), scenario_ids, set(action_by_id), state_ids)
        candidate_by_pair = {
            (c.get("scenarioId"), c.get("actionId")): c
            for c in pack.get("scenarioActionCandidates", [])
            if isinstance(c, dict)
        }
    except ContractError as exc:
        _fail(errors, "$.scenarioActionCandidates", str(exc))
    _validate_promotion_decisions(errors, "$.promotionDecisions", pack.get("promotionDecisions"), scenario_ids, action_by_id, candidate_by_pair)
    if errors:
        raise ContractError("scenario pack contract violation:\n- " + "\n- ".join(errors))


def _validate_contexts(errors: list[str], path: str, contexts: Any) -> set[str]:
    ids: set[str] = set()
    if not isinstance(contexts, list) or not contexts:
        _fail(errors, path, "must be a non-empty array")
        return ids
    for i, context in enumerate(contexts):
        p = f"{path}[{i}]"
        if not isinstance(context, dict):
            _fail(errors, p, "must be an object")
            continue
        _check_keys(errors, p, context, {"id", "auth", "vars", "labels", "metadata"}, {"id", "auth", "vars", "labels", "metadata"})
        cid = context.get("id")
        if not _is_nonempty_string(cid):
            _fail(errors, f"{p}.id", "must be a non-empty string")
        elif cid in ids:
            _fail(errors, f"{p}.id", f"duplicate context id {cid!r}")
        else:
            ids.add(cid)
        if not isinstance(context.get("vars"), dict):
            _fail(errors, f"{p}.vars", "must be an object")
        labels = context.get("labels")
        if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
            _fail(errors, f"{p}.labels", "must be an array of strings")
        if not isinstance(context.get("metadata"), dict):
            _fail(errors, f"{p}.metadata", "must be an object")
    return ids


def _validate_promotion_decisions(
    errors: list[str],
    path: str,
    decisions: Any,
    scenario_ids: set[str],
    action_by_id: dict[str, dict],
    candidate_by_pair: dict[tuple[str, str], dict],
) -> None:
    if not isinstance(decisions, list):
        _fail(errors, path, "must be an array")
        return
    for i, decision in enumerate(decisions):
        p = f"{path}[{i}]"
        if not isinstance(decision, dict):
            _fail(errors, p, "must be an object")
            continue
        allowed = {"scenarioId", "actionId", "decision", "reasons", "flow"}
        required = {"scenarioId", "actionId", "decision", "reasons"}
        _check_keys(errors, p, decision, allowed, required)
        if decision.get("scenarioId") not in scenario_ids:
            _fail(errors, f"{p}.scenarioId", "must reference pageScenarios[].id")
        action = action_by_id.get(decision.get("actionId"))
        if action is None:
            _fail(errors, f"{p}.actionId", "must reference staticActions[].id")
        candidate = candidate_by_pair.get((decision.get("scenarioId"), decision.get("actionId")))
        if candidate is None:
            _fail(errors, p, "must reference a scenarioActionCandidates entry for the same scenario/action")
        if decision.get("decision") not in PROMOTION_DECISIONS:
            _fail(errors, f"{p}.decision", f"must be one of {sorted(PROMOTION_DECISIONS)}")
        if not isinstance(decision.get("reasons"), list) or not all(isinstance(x, str) for x in decision.get("reasons", [])):
            _fail(errors, f"{p}.reasons", "must be an array of strings")
        if decision.get("decision") == "promote-to-flow":
            _validate_promoted_flow_decision(errors, p, decision, action, candidate)
        elif "flow" in decision:
            _fail(errors, f"{p}.flow", "flow is only allowed for promote-to-flow")
        if decision.get("decision") == "keep-as-navigation-evidence" and action is not None and action.get("effect") != "navigation":
            _fail(errors, f"{p}.decision", "keep-as-navigation-evidence requires action.effect=navigation")


def _validate_promoted_flow_decision(errors: list[str], path: str, decision: dict, action: dict | None, candidate: dict | None) -> None:
    flow = decision.get("flow")
    if not isinstance(flow, dict):
        _fail(errors, f"{path}.flow", "promote-to-flow requires a flow object")
        return
    if action is None:
        return
    if candidate is not None:
        _validate_candidate_promotion_gate(errors, path, candidate)
    selector = action.get("selector")
    value_class = (action.get("value") or {}).get("class")
    if action.get("classification") != "executable":
        _fail(errors, f"{path}.decision", "promote-to-flow requires action.classification=executable")
    if action.get("risk") != "safe-readonly":
        _fail(errors, f"{path}.decision", "promote-to-flow requires action.risk=safe-readonly")
    if action.get("effect") not in ALLOWED_FLOW_EFFECTS:
        _fail(errors, f"{path}.decision", "promote-to-flow requires an allowed same-page effect")
    if value_class not in {"high", "medium"}:
        _fail(errors, f"{path}.decision", "promote-to-flow requires high/medium action value")
    if not _is_nonempty_string(selector) or _selector_is_unsafe(selector):
        _fail(errors, f"{path}.decision", "promote-to-flow requires a stable action selector")
    _check_keys(
        errors,
        f"{path}.flow",
        flow,
        {"id", "kind", "description", "intent", "expectedObservables", "snapshotAfterEachStep", "steps"},
        {"id", "kind", "description", "intent", "expectedObservables", "snapshotAfterEachStep", "steps"},
    )
    if flow.get("id") != action.get("id"):
        _fail(errors, f"{path}.flow.id", "must match actionId")
    if flow.get("kind") != "safe-ui-flow":
        _fail(errors, f"{path}.flow.kind", "must be 'safe-ui-flow'")
    if not _is_nonempty_string(flow.get("description")):
        _fail(errors, f"{path}.flow.description", "must be a non-empty string")
    if not _is_nonempty_string(flow.get("intent")):
        _fail(errors, f"{path}.flow.intent", "must be a non-empty string")
    if not isinstance(flow.get("expectedObservables"), list) or not all(isinstance(x, str) for x in flow.get("expectedObservables", [])):
        _fail(errors, f"{path}.flow.expectedObservables", "must be an array of strings")
    if flow.get("snapshotAfterEachStep") is not True:
        _fail(errors, f"{path}.flow.snapshotAfterEachStep", "must be true")
    steps = flow.get("steps")
    if not isinstance(steps, list) or not steps:
        _fail(errors, f"{path}.flow.steps", "must be a non-empty array")
        return
    for j, step in enumerate(steps):
        sp = f"{path}.flow.steps[{j}]"
        if not isinstance(step, dict):
            _fail(errors, sp, "must be an object")
            continue
        _check_keys(errors, sp, step, {"type", "description", "selector"}, {"type", "description", "selector"})
        if step.get("type") != "click":
            _fail(errors, f"{sp}.type", "safe-ui-flow currently allows click steps only")
        if step.get("selector") != selector:
            _fail(errors, f"{sp}.selector", "must match the promoted action selector")
        if not _is_nonempty_string(step.get("description")):
            _fail(errors, f"{sp}.description", "must be a non-empty string")


def _validate_candidate_promotion_gate(errors: list[str], path: str, candidate: dict) -> None:
    if candidate.get("runtimeVisible") is not True:
        _fail(errors, f"{path}.decision", "promote-to-flow requires candidate.runtimeVisible=true")
    if not _is_nonempty_string(candidate.get("coverageKey")):
        _fail(errors, f"{path}.decision", "promote-to-flow requires candidate.coverageKey")
    evidence = candidate.get("joinEvidence")
    if not isinstance(evidence, dict):
        _fail(errors, f"{path}.decision", "promote-to-flow requires candidate.joinEvidence")
        return
    if evidence.get("selector") != "matched-runtime":
        _fail(errors, f"{path}.decision", "promote-to-flow requires joinEvidence.selector=matched-runtime")
    if evidence.get("route") == "none" and evidence.get("component") == "none":
        _fail(errors, f"{path}.decision", "promote-to-flow requires route or component join evidence")
    if evidence.get("stateDelta") not in {"observed", "expected-only"}:
        _fail(errors, f"{path}.decision", "promote-to-flow requires observed or expected state delta evidence")
