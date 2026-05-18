"""Pure projection from reusable scenario pack to run check-plan."""
from __future__ import annotations


def project_check_plan(
    pack: dict,
    *,
    candidate_branch: str,
    run_auth: dict,
    candidate_base_url: str | None = None,
) -> dict:
    if not isinstance(candidate_branch, str) or not candidate_branch.strip():
        raise ValueError("candidate_branch must be a non-empty string")
    if not isinstance(run_auth, dict):
        raise ValueError("run_auth must be a check-plan auth object")

    baseline = pack["baseline"]
    base_url = candidate_base_url or baseline["baseUrl"]
    flows_by_scenario: dict[str, list[dict]] = {}
    for decision in pack.get("promotionDecisions", []):
        if decision.get("decision") == "promote-to-flow":
            flows_by_scenario.setdefault(decision["scenarioId"], []).append(decision["flow"])

    scenarios = []
    for scenario in pack["pageScenarios"]:
        flows = flows_by_scenario.get(scenario["id"], [])
        reason = scenario.get("reason") or "projected from runtime scenario pack"
        if not flows and "no flows selected" not in reason:
            reason = f"{reason}; no flows selected"
        scenarios.append({
            "id": scenario["id"],
            "reason": reason,
            "routeTemplate": scenario["routeTemplate"],
            "context": scenario["contextId"],
            "path": scenario["path"],
            "expectedFinalPath": scenario["expectedFinalPath"],
            "compare": ["page-capture", "action-surface", "user-flows", "console-runtime"],
            "flows": flows,
        })

    return {
        "app": pack["app"],
        "intent": f"Runtime parity run projected from scenario pack {pack['packId']}",
        "baseline": {"branch": "dev", "baseUrl": baseline["baseUrl"]},
        "candidate": {"branch": candidate_branch, "baseUrl": base_url},
        "auth": run_auth,
        "knownUnstable": list(pack.get("knownUnstable") or []),
        "contexts": pack["contexts"],
        "scenarios": scenarios,
    }
