"""Pure promotion logic for scenario-action candidates."""
from __future__ import annotations

from models import ALLOWED_FLOW_EFFECTS, UNSAFE_SELECTOR_PATTERNS


def selector_is_safe(selector: str | None) -> bool:
    return bool(selector) and not any(pattern in selector for pattern in UNSAFE_SELECTOR_PATTERNS)


def decide_promotion(candidate: dict, promoted_coverage_keys: set[str] | None = None) -> dict:
    """Return a promotion decision for one scenario/action candidate.

    `candidate` is an already joined artifact containing:
      scenarioId, actionId, stateId, runtimeVisible, joinEvidence, coverageKey, action
    The function is pure and does not inspect files or runtime state.
    """
    promoted_coverage_keys = promoted_coverage_keys or set()
    action = candidate.get("action") or {}
    scenario_id = candidate.get("scenarioId")
    action_id = candidate.get("actionId") or action.get("id")
    coverage_key = candidate.get("coverageKey")
    join_evidence = candidate.get("joinEvidence") or {}
    reasons: list[str] = []

    if not candidate.get("runtimeVisible"):
        return _decision(scenario_id, action_id, "reject-not-visible", ["not-runtime-visible"])
    reasons.append("runtime-visible")

    if not coverage_key:
        return _decision(scenario_id, action_id, "manual-review", ["missing-coverage-key"])
    if coverage_key in promoted_coverage_keys:
        return _decision(scenario_id, action_id, "reject-duplicate-coverage", ["duplicate-coverage"])
    reasons.append(f"coverage={coverage_key}")

    classification = action.get("classification")
    risk = action.get("risk")
    effect = action.get("effect")
    value_class = (action.get("value") or {}).get("class")

    if effect == "navigation":
        return _decision(scenario_id, action_id, "keep-as-navigation-evidence", ["effect=navigation"])

    if join_evidence.get("selector") != "matched-runtime":
        return _decision(scenario_id, action_id, "reject-not-visible", ["selector-not-matched-runtime"])
    if join_evidence.get("route") == "none" and join_evidence.get("component") == "none":
        return _decision(scenario_id, action_id, "manual-review", ["missing-route-component-join"])
    if join_evidence.get("stateDelta") not in {"observed", "expected-only"}:
        return _decision(scenario_id, action_id, "manual-review", [f"stateDelta={join_evidence.get('stateDelta')}"])
    reasons.extend([
        f"route={join_evidence.get('route')}",
        f"component={join_evidence.get('component')}",
        f"stateDelta={join_evidence.get('stateDelta')}",
    ])

    selector = action.get("selector")
    if not selector_is_safe(selector) or not action.get("selectorStrategy") or not action.get("selectorEvidence"):
        return _decision(scenario_id, action_id, "reject-no-stable-selector", ["missing-or-unsafe-selector"])
    reasons.append("stable-selector")

    if classification != "executable" or risk != "safe-readonly":
        return _decision(scenario_id, action_id, "reject-unsafe-risk", [f"classification={classification}", f"risk={risk}"])
    reasons.extend(["classification=executable", "risk=safe-readonly"])

    if value_class not in {"high", "medium"}:
        return _decision(scenario_id, action_id, "reject-low-value", [f"value={value_class}"])
    reasons.append(f"value={value_class}")

    if effect not in ALLOWED_FLOW_EFFECTS:
        return _decision(scenario_id, action_id, "manual-review", [f"effect={effect}"])
    reasons.append(f"effect={effect}")

    return {
        "scenarioId": scenario_id,
        "actionId": action_id,
        "decision": "promote-to-flow",
        "reasons": reasons,
        "flow": {
            "id": str(action_id),
            "kind": "safe-ui-flow",
            "description": action.get("intentLabel") or str(action_id),
            "intent": "Promoted from runtime scenario pack candidate",
            "expectedObservables": list((action.get("value") or {}).get("observableAfterAction") or []),
            "snapshotAfterEachStep": True,
            "steps": [
                {
                    "type": "click",
                    "description": action.get("intentLabel") or str(action_id),
                    "selector": selector,
                }
            ],
        },
    }


def _decision(scenario_id: str | None, action_id: str | None, decision: str, reasons: list[str]) -> dict:
    return {
        "scenarioId": scenario_id,
        "actionId": action_id,
        "decision": decision,
        "reasons": reasons,
    }
