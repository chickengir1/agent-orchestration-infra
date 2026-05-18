"""Shared model constants for runtime-scenario-pack.

Keep this module side-effect free. Runtime data is represented as plain dicts so
artifacts can be loaded, validated, transformed, and written without object
serialization glue.
"""
from __future__ import annotations


SELECTOR_STRATEGIES = {
    "data-testid",
    "aria-label",
    "role+name",
    "router-link-text",
    "visible-text-with-unique-context",
}

ACTION_CLASSIFICATIONS = {
    "executable",
    "navigation-evidence",
    "rejected",
    "uncertain-manual-review",
}

ACTION_RISKS = {
    "safe-readonly",
    "navigation",
    "state-changing",
    "destructive",
    "external-side-effect",
    "unknown",
}

ACTION_VALUES = {"high", "medium", "low", "none", "unknown"}

ACTION_EFFECTS = {
    "opens-overlay",
    "opens-dialog",
    "toggles-tab",
    "expands-section",
    "reveals-hidden-content",
    "changes-action-surface",
    "changes-component-surface",
    "read-only-pagination",
    "navigation",
    "mutation",
    "unknown",
}

ALLOWED_FLOW_EFFECTS = {
    "opens-overlay",
    "opens-dialog",
    "toggles-tab",
    "expands-section",
    "reveals-hidden-content",
    "changes-action-surface",
    "changes-component-surface",
    "read-only-pagination",
}

VALUE_REASONS = {
    "user-requested",
    "opens-overlay",
    "opens-dialog",
    "toggles-tab",
    "expands-section",
    "reveals-hidden-content",
    "changes-action-surface",
    "changes-component-surface",
    "navigates-child-route",
    "permission-gated",
    "lazy-rendered",
    "runtime-risk-surface",
    "duplicate-pattern",
    "decorative-only",
    "external-link",
    "unsafe-mutation",
    "no-observable-delta",
}

PROMOTION_DECISIONS = {
    "promote-to-flow",
    "keep-as-page-only",
    "keep-as-navigation-evidence",
    "reject-no-stable-selector",
    "reject-unsafe-risk",
    "reject-low-value",
    "reject-not-visible",
    "reject-duplicate-coverage",
    "manual-review",
}

STATE_GRAPH_SOURCE = "dev-runtime-crawl"

JOIN_ROUTE_EVIDENCE = {"exact", "param-match", "none"}
JOIN_COMPONENT_EVIDENCE = {"source-ref", "runtime-dom-ref", "none"}
JOIN_SELECTOR_EVIDENCE = {"matched-runtime", "not-found"}
JOIN_STATE_DELTA_EVIDENCE = {"observed", "expected-only", "not-observed", "not-executed"}

CANDIDATE_CONFIDENCE = {"high", "medium", "low"}

UNSAFE_SELECTOR_PATTERNS = (
    ".ng-",
    ".cdk-",
    ".mat-mdc-",
    "_ngcontent",
    "_nghost",
    "nth-child",
)
