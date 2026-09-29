---
name: gherkin
description: "Concrete Given/When/Then scenarios with real values."
metadata:
  title: "Gherkin specifications"
  version: 1.2.0
  type: crossCutting
  applies_to:
    agents: ["rules-extractor", "functional-analyst", "test-engineer"]
    technologies: []
  conflicts: []
  requires: []
  status: published
  eval_score: 0.93
---
# Gherkin acceptance criteria

- One behavior per scenario: Given (context), When (a single action), Then (an observable outcome), in that order.
- Concrete values, never "valid data".
- Scenario Outline with Examples for variations; no UI mechanics in business scenarios.
- Trace each scenario to its rule or user story.
