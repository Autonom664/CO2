---
name: agent-collaboration
description: "Coordinate work between AI coding agents. Use when multiple agents share a project, repository, task, handoff, long-running job, or deliverable and need to work in parallel without conflicting edits or duplicate effort."
---

# Multi-agent collaboration

**Version:** 1.0 · 2026-10-08  
**Status:** Agreed by Copilot and Claude (M59/M60), 2026-10-08.

## Purpose

Deliver work faster through safe parallelism, clear ownership, and early
verification. Keep the human informed about decisions and approvals without
making them relay routine messages between agents. Open the project's shared
status with a concise human-readable view of what is running and who owns the
baton, the next milestone and ETA, and anything waiting on the human.

## Start with shared context

1. Read the project's current status, collaboration messages, relevant
   decisions, and instructions before claiming work.
2. Identify the active owner, dependencies, approvals, shared outputs, and
   any running jobs. Do not assume another agent's task is complete based
   only on an older summary.
3. Use the communication mechanism already established by the project.
   Do not migrate or replace it mid-task; propose a migration separately,
   and get agreement from all participants first.
4. When an agent's edit or result changes what you need to do, acknowledge
   it through the project's agreed read-receipt or message convention.
5. Give messages unique IDs per author (for example, `C-12` and `P-7`) so
   independently written messages cannot collide.

## Claim and bound work

Before implementation, make the task boundary clear:

```text
Task:
Owner:
Allowed files / outputs:
Files or outputs to leave untouched:
Dependencies / required approval:
Deliverable:
Acceptance checks:
```

- Assign one accountable owner to each task and one writer to each file or
  generated-output set. The owner may request review or diagnosis without
  transferring implementation ownership.
- Prefer parallel work only when scopes and outputs are genuinely
  independent. Do not have agents make competing edits to the same code,
  configuration, generated outputs, or coordination state.
- Keep agent roles flexible. Assign roles per task based on expertise,
  context, and availability; do not assume one agent is always builder or
  verifier.
- If a task depends on shared files, a long-running job, or a user decision,
  state that dependency before starting. Ask the human only for decisions or
  approvals that are actually theirs to make.

## Protect shared outputs and long-running work

- Use a baton or equivalent exclusive claim for outputs that multiple steps
  can overwrite. The claim identifies the owner, exact outputs, and the
  next handoff condition.
- Before a costly or consequential operation, state its command or action,
  target, expected side effects, outputs, and start time in the project's
  status mechanism.
- Do not start a competing job against the same outputs. Do not inspect,
  consume, or commit partial outputs while another agent owns the running
  job, unless the owner explicitly permits a safe read.
- Keep useful waiting-time work independent of the active job and its
  outputs: separate tests, documentation, review, or scratch experiments.
- Preserve approval boundaries. Permission for one dataset, model change,
  deployment, publication, or host does not authorize a broader action.

## Verify proportionately, before expensive steps

Use the cheapest checks that meaningfully reduce risk, escalating with the
impact and duration of the work:

1. Check syntax, unit tests, and affected consumers for the change.
2. For shared interfaces or cross-module behavior, run all relevant
   consumers' tests and request a bounded peer review when practical.
3. Before an expensive end-to-end run, exercise its exact command and
   configuration with a small, representative input if one is available.
   For pipelines over external data, prefer a small cut of the real sources;
   synthetic fixtures alone may miss source-specific failures.
4. Before deployment or publication, run the release checks and verify the
   actual target after the change.

Do not impose a full suite, a real-data fixture, or a fixed time limit on
every small task. Use the broader gate when the change can affect unrelated
modules, shared formats, or costly downstream runs. Create checked-in
fixtures only when licensing, size, maintenance, and reproducibility make
that appropriate. Never claim a check passed unless it was actually run.

For a shared interface, name its producer, consumers, format or type, and
compatibility checks before changing it. Prefer one canonical loader or
contract over duplicated interpretations. The implementation owner fixes
the code and reruns the checks, even when a peer found the issue.

## Coordinate messages and handoffs

Use the project's existing message types and IDs. A request that needs action
must say who should act and what outcome counts as done. A result or handoff
should include:

- completed work and remaining work;
- exact deliverable paths or target URL;
- commands/checks actually run and their results;
- known failures, limitations, and partial outputs;
- the recipient's next action and acceptance criterion.

Keep routine messages short. Put detailed evidence in a linked artifact.
Use read receipts where supported; do not create redundant acknowledgements
or status pings when a meaningful milestone update will answer the question.
Each agent should state its check cadence, what wakes it, and expected
reaction time; allow for the slower agent's interval before treating a
request as missed. If there is no reliable watcher, agree on a reasonable
check-in point rather than assuming instant delivery.

When asking the human for a decision, offer at most three options, include
measured evidence when available, recommend one option, and say what work
can continue while the decision is pending.

## Diagnose failures without duplicating effort

1. The owner of the failing code first obtains a minimal reproduction and
   identifies the failing step and any partial outputs.
2. If peer help is needed, request one bounded diagnosis and specify whether
   it is read-only or may edit. Do not let two agents independently change
   the same failure.
3. Keep the fix with the owner of the affected files. Rerun the failed step
   and downstream steps that depend on it; preserve verified earlier work.
4. Report the evidence and any remaining uncertainty explicitly.

## Use waiting time and finish cleanly

- Maintain a short list of independent work that can proceed while blocked
  or while another agent owns a long-running job.
- Do not start that work if it could affect the active task's files,
  configuration, outputs, or machine state.
- Before ending a task or session, record the current owner, running work,
  verified deliverables, blockers, and next action in the existing shared
  status mechanism.
- Update durable project documentation for decisions and interfaces; do not
  let transient chat summaries become the only record of important facts.
- When committing, follow the repository's policy; stage only owned files by
  explicit path, use the agreed agent prefix, and never use `add -A`. For a
  shared coordination file, preserve the other agent's text.

## Optional mechanisms: scale to the project

For a small task, the core agreement with a simple shared board and focused
checks may be enough. Adopt additional mechanisms only when their benefit
outweighs their setup and maintenance cost.

| Mechanism | Use when |
|---|---|
| Per-agent outboxes plus a single-writer state file with read receipts | Both agents are active frequently or message volume makes a shared board hard to manage. |
| One shared board with targeted edits and a clear edit-lock convention | Coordination is light or one agent is mostly idle. |
| A small, end-to-end smoke cut of real source data | A pipeline consumes external data or an upcoming step is costly. |
| An interface registry listing producers and all consumers (including tests) | Several modules or agents depend on the same schemas, formats, flags, or outputs. |
| Peer review of shared-interface changes | A shared contract is changing before expensive or consequential work. |
| Resumable stages with completion markers and progress logs | Jobs are long-running or pipelines have multiple stages. |
| Watchers with declared cadence, triggers, and reaction expectations | The human should not need to relay messages between agents. |
| Explicit builder and verifier/integrator roles, swappable per project | Work naturally separates into producing and independently checking results. |
| A run-sequence table with owners, completion criteria, and handoff paths | A multi-step workflow passes work or a baton between agents. |

## Collaboration checklist

- [ ] I read the current shared status and relevant decisions.
- [ ] The task owner, scope, dependencies, and acceptance checks are clear.
- [ ] No other agent owns the same files or outputs.
- [ ] Required user approval is explicit and within scope.
- [ ] I ran the checks appropriate to the risk and stated the actual results.
- [ ] The handoff names the deliverable, limitations, and next action.

## Adoption and versioning

- Each participating agent installs the agreed skill unchanged.
- Change it only by agreement, with a version bump and a dated changelog
  entry.
- Keep an existing project's collaboration protocol until its human lead
  approves a migration.

## Changelog

- v1.0 (2026-10-08): agreed by Copilot and Claude (M59/M60); based on the
  Copilot proposal with seven additions requested in M58.
