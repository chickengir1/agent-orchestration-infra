# Handoff

Create a handoff document for the next agent to continue this work with fresh context.

## Trigger

When the user types `/handoff` or asks to create a handoff document.

## Instructions

1. Check if `HANDOFF.md` already exists in the current working directory. If it does, read it first for context.

2. Write `HANDOFF.md` in the current working directory with these sections:

```markdown
# Handoff

## Goal

What we are trying to accomplish (1-2 sentences)

## Progress

- What has been completed
- Current state of the work

## What Worked

- Approaches and solutions that succeeded

## What Didn't Work

- Approaches that were tried and failed (so the next agent doesn't repeat them)

## Next Steps

- Specific remaining tasks in order of priority

## Key Files

- List of files that are relevant to this work
```

3. After writing, tell the user: "Start a new conversation and paste the path `HANDOFF.md` to continue."
