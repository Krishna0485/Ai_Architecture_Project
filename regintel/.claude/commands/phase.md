---
description: Load the phase checklist from docs/plan.md and propose the next small task
argument-hint: [phase number]
---
1. Read docs/plan.md and CLAUDE.md.
2. For phase $ARGUMENTS (or the first phase with unchecked items), list its done criteria and
   which are satisfied, verifying each against the repo (run the relevant make target if cheap).
3. Propose the next smallest task (one module / one PR): files to touch, tests to add, and how
   it will be measured. Plan only - do not edit files until I approve.
