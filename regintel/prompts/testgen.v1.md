---
id: testgen.v1
task: testgen
---
## system
Generate automated compliance test scenarios for each checklist item:
- "pytest": a valid Python test function named test_<slug>(policy_text: str) -> None
- "gherkin": a BDD scenario (Scenario/Given/When/Then)
Return JSON: {"tests": [{"item_id": "<id>", "pytest": "<code>", "gherkin": "<text>"}]}.

## user
Checklist items:
{{items}}
