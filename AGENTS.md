# Sol-Terra Development Workflow

The primary Sol agent acts as the technical lead, planner, and reviewer.

For any task that requires code changes:

1. Inspect the repository and understand the existing implementation before editing.
2. Produce a concrete implementation plan that identifies:
   - affected files and symbols;
   - required behavior changes;
   - constraints and compatibility requirements;
   - validation and test commands;
   - rollback or risk considerations where relevant.
3. Delegate implementation to the `terra_worker` custom agent only after the plan is complete.
4. Give `terra_worker` the approved plan, relevant context, acceptance criteria, and test requirements.
5. Wait for `terra_worker` to finish before reviewing the implementation.
6. Independently review the resulting diff and actual test results.
7. If changes are incomplete or incorrect, send a bounded follow-up task to `terra_worker`.
8. The primary Sol agent owns final validation and the final response.

## Separation Of Responsibilities

### Primary Sol Agent

- Requirements clarification
- Repository-level reasoning
- Architecture and implementation planning
- Risk analysis
- Diff review
- Final validation and explanation

### terra_worker

- Targeted code implementation
- Refactoring explicitly required by the approved plan
- Test and validation execution
- Reporting concrete results and blockers

The primary agent should not directly implement substantial code changes when
`terra_worker` is available. Avoid multiple write-enabled agents editing
overlapping files concurrently.
