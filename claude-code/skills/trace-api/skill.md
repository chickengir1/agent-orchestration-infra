# Trace API

Trace the full chain of a backend API endpoint: route → controller → business logic → DB query. Produces a parameter spec matrix with LIVE/DEAD classification.

## Trigger

`/trace-api` or any request to investigate backend API behavior.

## Arguments

Endpoint URL, controller name, or frontend call site.
Example: `/trace-api /staff/credit/purchase/list`

## Instructions

Run 3 Explore agents **sequentially**. Each agent's output feeds the next.

### Agent 1: Route → Controller

Prompt:
> Find the route registration for `{endpoint URL}` in the backend repo.
> 1. Locate the route file mapping this URL pattern to a controller class:method (file:line)
> 2. Read the controller method **in full**
> 3. List **every** query/body parameter the controller extracts from the request (name, type, default value)
> 4. For each parameter, check whether the controller **actually forwards** it to the model/service call
> 5. Mark parameters that are received but NOT forwarded as DEAD candidates
>
> Output: parameter list with forward status + model method name and file path being called

### Agent 2: Model → DB Query

Takes Agent 1's output (model method name, file path):
> Read `{model file:method}` **in full**.
> 1. For each parameter from Agent 1, check if it **enters a WHERE clause** — quote the exact line
> 2. Document JOIN, ORDER BY, GROUP BY, LIMIT conditions
> 3. Check boolean column DB types (tinyint etc.) and serialization format (0/1 vs true/false)
> 4. Document response serialization: SELECT fields, type transformations in JSON output
> 5. If any DEAD candidate from Agent 1 actually enters WHERE, reclassify as LIVE
>
> Output: WHERE clause quotes + LIVE/DEAD confirmed per parameter + serialization type matrix

### Agent 3: Regression + Legacy Comparison

Takes Agent 2's matrix:
> 1. Grep **all call sites** for this endpoint in frontend code (staff-v2 + legacy)
> 2. For each call site, collect the parameters being sent
> 3. Identify LIVE parameters that legacy sends but staff-v2 does NOT (feature gap)
> 4. Identify DEAD parameters that staff-v2 sends (wasted transmission)
> 5. Verify boolean comparison patterns (`=== true` vs `Boolean(x)`) match the serialization format
>
> Output: call site list + legacy vs staff-v2 parameter diff + type mismatch warnings

### Final Assembly

Combine all 3 agent outputs into a single matrix:

```
| param | controller | forwarded | WHERE | serialization | legacy | staff-v2 | verdict |
|-------|-----------|-----------|-------|---------------|--------|----------|---------|
```

Plus: regression risk list + type mismatch warnings.

## Rules

- If backend repo path is unknown, ask the user.
- Do NOT skip between agents. Each agent's conclusion is the next agent's premise.
- LIVE/DEAD verdict MUST be backed by **quoted WHERE clause code**. No inference.
- When uncertain, mark as "unverified". Misclassifying LIVE as DEAD is the highest-risk error.
