# Engineering Retrospective

Use this format after a meaningful Claude Code delegation when the user asks for a review of prediction versus actual behavior.

## Code-Reading Prediction Review

Describe what Codex predicted from static code inspection before delegation:

- predicted change point
- predicted execution path
- predicted risk
- evidence used
- where the prediction was correct
- where the prediction failed

Do not overstate static certainty. Separate direct evidence from inference.

## Actual Behavior Sequence Review

Describe what happened after Claude Code ran:

- files actually changed
- sequence of edits
- validation commands and results
- observed runtime or test behavior, if available
- scope violations or unexpected changes
- final explanation of the mechanism

## Judgment

End with a concise engineering judgment:

- keep, repair, or reject the Claude patch
- why
- what should be changed in future delegations
