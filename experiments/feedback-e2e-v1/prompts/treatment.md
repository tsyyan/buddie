# Treatment: Verification Feedback v1

Tools: `feedback_start` and `feedback_resolve`.

1. Call `feedback_start` with the report, the options below, `iteration_limit: {iteration_limit}` and the task
   requirements. It returns a chain, a feedback (findings, at most one bounded action each) and a state.
2. If `state.disposition` is `repair_requested`, correct only what an action names, within its target lines, and
   call `feedback_resolve` with the chain, the feedback exactly as returned, a repair-submission-v1 (sha256 hex of the
   text before and after, `execution`: what happened to any action outside the text), the text before and the
   corrected text. It returns the decision and the next feedback.
3. Stop when the state is terminal. The text you hand in is the last one the chain accepted.

Options for `feedback_start`: {options}
