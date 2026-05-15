---
name: trace-api
description: Produce a frontend consumption contract for one backend API endpoint by tracing route, middleware, controller, validation, service/model logic, data access, serialization, and callers. Use for `/trace-api`, API spec recovery, parameter effect classification, endpoint archaeology, and frontend integration guidance.
---

# Trace API

Deep-dive one API and produce the spec a frontend caller can safely consume. The output is not just a backend trace; it must answer what the frontend should send, what it can trust in the response, what it must not rely on, and which behavior is unverified.

## Identity

Trace API is a frontend consumption contract generator.

Use it to answer:

- Which path/query/body/header fields are accepted?
- Which fields actually affect behavior?
- Which fields are ignored, response-only, auth-only, or unverified?
- What response shape, nullability, boolean serialization, and enum/wire values should the frontend expect?
- What fallback/error behavior should the frontend implement?
- Which existing frontend/legacy callers already depend on this contract?

## Workflow

1. Identify one endpoint URL, route name, controller method, or frontend call site. If the backend repo path is unknown, ask for it.
2. Locate route registration:
   - URL pattern
   - HTTP method
   - middleware/auth/guards/interceptors
   - controller class/function and line
3. Read the request boundary in full:
   - path/query/body/header fields
   - type coercions and defaults
   - validation schemas, DTOs, pipes, guards, or manual checks
   - auth/authorization checks
   - fields forwarded to service/model/use-case calls
4. Read downstream behavior in full:
   - service/model/use-case methods
   - repository/query code
   - WHERE/JOIN/ORDER/GROUP/LIMIT clauses when SQL exists
   - ORM filters, query builders, raw SQL fragments, API client calls, cache keys, feature flags, and branch conditions
   - selected fields, response mapping, nullability, enum/wire values, boolean serialization
   - side effects, cache invalidation, events, or downstream calls
5. Classify request fields:
   - REQUIRED: missing field fails validation/routing or prevents meaningful execution
   - OPTIONAL: accepted and has a default or optional behavior
   - BEHAVIOR-LIVE: proven to affect selection, branch behavior, cache key, side effect, or downstream call
   - RESPONSE-ONLY: affects response mapping/serialization but not selection or side effects
   - AUTH-ONLY: affects authorization/visibility but not query shape directly
   - FORWARDED-UNVERIFIED: forwarded but downstream effect was not proven
   - DEAD: received but no effect found in validation, auth, behavior, response, side effects, or downstream calls
   - UNVERIFIED: evidence is incomplete
6. Compare callers:
   - grep current frontend callers
   - grep legacy callers only when the repo has a legacy path or the user asks for regression comparison
   - list fields sent by each caller
   - flag required/effective fields missing in a caller
   - flag DEAD fields still sent
   - check response assumptions in frontend code

## Optional Subagents

Use Codex subagents only when the user explicitly asks for agents, teams, or parallel work. Suggested split:

- explorer 1: route, middleware, controller, validation
- explorer 2: service/model/data access/serialization
- explorer 3: frontend callers and consumption assumptions

If subagents are not explicitly authorized, perform the trace locally in the same order.

## Output

### Endpoint

```markdown
- method:
- path:
- controller:
- auth/middleware:
- source files:
```

### Request Contract

```markdown
| field | location | required | default | forwarded | effect | evidence |
|---|---|---:|---|---:|---|---|
```

### Response Contract

```markdown
| field | type/wire value | nullable | source | frontend note |
|---|---|---:|---|---|
```

### Parameter Verdicts

```markdown
| field | verdict | evidence | frontend action |
|---|---|---|---|
```

### Frontend Consumption Spec

Include:

- payload/query/header shape to send
- fields the frontend can trust
- fields the frontend must not infer from
- fallback/error policy
- serialization notes such as `0/1` vs `true/false`, string enum wire values, nullable arrays/objects
- sample request when useful
- existing caller gaps or regression risks

## Rules

- Back every field verdict with file:line evidence.
- Do not infer behavior from field names.
- Do not call a field DEAD if it affects validation, auth, response mapping, cache, side effects, feature flags, or downstream calls.
- Mark uncertain behavior as UNVERIFIED.
- Read the full request boundary and downstream method before deciding a field is unused.
- Label external service behavior as unverified unless the called implementation is read.
- The final answer should be usable by a frontend engineer without rereading the backend trace.
