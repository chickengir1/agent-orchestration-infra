# Trace Flow

Trace frontend data flow: fetch → transform → state management → branching/guards → render. Produces a state variable map, branch path table, and regression verdict.

## Trigger

`/trace-flow` or any request to investigate frontend data flow.

## Arguments

File path, method name, or feature description.
Example: `/trace-flow collection-machine.ts onFetchSuccess`

## Instructions

Run 3 Explore agents **sequentially**. Each agent's output feeds the next.

### Agent 1: Call Chain

Prompt:
> Starting from `{entry file:method}`, trace the full data flow path.
> 1. Find **all callers** of this method (file:line)
> 2. Find **all callees** — methods this one calls (file:line), recurse 1 level deep
> 3. At each step, document the data type transformation: API response type → domain type → VM type → component Input
> 4. If data passes through Observable/Subject/BehaviorSubject, trace to the subscription point
>
> Output: call chain tree (caller → entry → callee₁ → callee₂ ...) with file:line + data type at each node

### Agent 2: State Variables + Branch Map

Takes Agent 1's call chain:
> Read **every method** in the call chain in full. Collect:
> 1. **State variables**: class fields, Subjects, locals shared across methods or used in branch conditions
>    - Every write point (file:line, what value)
>    - Every read point (file:line, in what condition)
>    - Reset conditions (which path restores initial value)
> 2. **Branches/guards**: if, switch, early return, ternary
>    - Quote the full condition expression
>    - True path: where does it go, how does state change
>    - False path: same
> 3. **Exit points**: every point where this flow terminates (return, throw, updateServer, emit, etc.)
>    - Final value of each state variable at that exit
>
> Output:
> - State variable map: | variable | write points | read points | reset condition |
> - Branch path table: | branch (file:line) | condition | true result | false result |
> - Exit table: | exit (file:line) | state variable final values |

### Agent 3: Regression Verification

Takes Agent 1's call chain + Agent 2's state map:
> 1. Find **all consumers**: components/services that subscribe to or receive these state variables as Input — exhaustive grep
> 2. For each consumer, identify which state variables it depends on and what value range it expects
> 3. **Infinite loop check**: is there any exit path that re-triggers the entry point? If so, is termination guaranteed?
> 4. **Dead state check**: is there any exit where state becomes stuck (e.g. phase=loaded + noMore=false + no trigger available)?
> 5. **State leak check**: at every exit, is every temporary state variable (multiplier, flag, etc.) reset? Report any exit that misses a reset.
>
> Output: consumer list + infinite loop / dead state / leak verdict per exit path

### Final Assembly

Combine all 3 agent outputs:

1. **Flow diagram**: fetch → transform → state → branch → render summary
2. **State variable map**: exhaustive write/read/reset
3. **Branch path table**: condition + outcomes
4. **Regression verdict**: no infinite loop / no dead state / no leak (or findings list)

## Rules

- Do NOT infer branch outcomes. Quote the code.
- For generic machines (CollectionMachine etc.), check consumer-specific config (applyClientFilter, getPageSize). Same machine can behave differently per consumer.
- "Previous agent didn't find it, so it doesn't exist" is forbidden. Each agent searches independently.
- If even one exit path is unverified, it is a potential defect. Explicitly prove "all exits verified".
