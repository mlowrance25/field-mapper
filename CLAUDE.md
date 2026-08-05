<!-- Plugin: i2i-workflow v1 -->
# CLAUDE.md

This project uses the **i2i-workflow** plugin for SDLC management.

## Workflow

All project artifacts live in `_i2i/`. The pipeline runs in order:

```
/i2i-prd          → capture requirements as a versioned PRD
/i2i-plan         → create implementation plan from PRD
/i2i-ticket       → generate developer-ready ticket from a PRD
/i2i-test-gen     → generate test cases from a ticket
[dev implements]
/i2i-pr-review    → review PR against ticket acceptance criteria
/i2i-roadmap-sync → close out ticket on the roadmap
/i2i-tradeoff     → log any technical debt decisions made
```

## Plan Management Workflow

### IMPORTANT: Plan Execution Rules

⚠️ **STRICT ADHERENCE REQUIRED** ⚠️

1. **NEVER execute or implement tasks from plans in the `draft/` folder**
   - Draft plans are for review and refinement only
   - If asked to work on a draft plan, inform the user that the plan must be moved to `in_progress/` first

2. **Only work on plans in the `in_progress/` folder**
   - These are the only plans approved for active development
   - Always verify a plan is in the correct folder before starting work

3. **If a user asks you to work on a draft plan:**
   - Politely explain that draft plans cannot be executed
   - Offer to move the plan to `in_progress/` if they approve
   - Wait for explicit confirmation before moving any plans

4. **Actions outside of existing plans require explicit permission**
   - If a request is NOT part of any existing plan, ASK THE USER before executing
   - Questions are for information gathering, NOT permission to act
   - Only proceed with implementation when the user explicitly says to do it

5. **Understanding user intent**
   - "Can you..." or "How would..." questions are requests for information, not action
   - "Please..." or "Go ahead and..." or "Implement..." are explicit action requests
   - When in doubt, clarify what the user wants before proceeding

### Plan Status Workflow

1. **Create Plan**: `/i2i-plan [context]` creates numbered plan in `draft/`
2. **Review**: Examine the plan — identify improvements or missing details
3. **Refine** (optional): `/i2i-plan @_i2i/plans/draft/NNN-plan.md [changes]`
4. **Move to Active**: Move from `draft/` to `in_progress/` when ready to implement
5. **Implement**: Work through plan phases systematically
6. **Complete**: Move from `in_progress/` to `completed/` when finished

## Task Completion Protocol

When working on tasks from an implementation plan, follow this protocol **for each phase**:

1. **Work through one phase at a time** following the plan's phase order
2. **Complete all tasks in the phase** and verify each works
3. **Update the plan file immediately** after completing the phase:
   - Check the boxes (`[x]`) for all completed tasks
   - Check the boxes for completed test verification items
4. **Report to the user** with a summary of what was completed and what phase is next
5. **Proceed to the next phase** or wait for user direction

The plan file must always reflect the current state of implementation. Never leave completed tasks unchecked.

## Configuration

Integration settings are in `_i2i/config.yml` (gitignored).
Required environment variables:

```
JIRA_API_TOKEN
JIRA_BASE_URL
JIRA_PROJECT_KEY
GITHUB_TOKEN
```

## Project Structure

```
_i2i/
├── config.yml          # Integration config (gitignored)
├── prd/                # PRDs — PRD-NNN format
├── plans/              # Implementation plans
│   ├── draft/
│   ├── in_progress/
│   └── completed/
├── tickets/            # Promoted tickets — CC-NNN/ or TICKET-NNN/
├── roadmap/            # Roadmap
├── tech-debt/          # Technical debt register
└── research/           # Auto-generated and manual docs
    ├── platform-workflow.md   # Cross-repo state (i2i-status)
    ├── jira-backlog.md        # Backlog snapshot (i2i-ticket-import)
    ├── api-routes.md          # BE route index (i2i-status --scan)
    ├── navigation-map.md      # FE + Dashboard paths (i2i-status --scan)
    └── integration-map.md     # Screen → route mapping (i2i-status --scan)
```

## Commands

### Setup & Workspace

| Command | Params | What it does |
|---------|--------|--------------|
| `/i2i-init` | _(none)_ | Scaffold `_i2i/` structure, prompt for project name, workspace type, and repos |
| `/i2i-link` | `<workspace-path> [--name repo-name]` | Write `.i2i.yml` in a child repo so `/i2i-*` commands work from within it |

### Requirements & Planning

| Command | Params | What it does |
|---------|--------|--------------|
| `/i2i-prd` | `[description]` | Create or refine a versioned PRD with extended thinking |
| `/i2i-prd-update` | `PRD-NNN [changes]` | Update a PRD, add changelog entry, flag downstream tickets |
| `/i2i-plan` | `[context or @prd-file] [changes]` | Create or refine an implementation plan in `draft/` |

### Tickets

| Command | Params | What it does |
|---------|--------|--------------|
| `/i2i-ticket` | `PRD-NNN [scope hint] [--dry-run] [--no-push]` | Generate a developer-ready ticket from a PRD and push to tracker |
| `/i2i-ticket-import` | `[--status "..."] [--limit N] [--filter "jql"]` | Refresh backlog snapshot from issue tracker → `_i2i/research/jira-backlog.md` |
| `/i2i-ticket-pull` | `<TICKET-KEY>` | Promote one ticket to `_i2i/tickets/` with full developer-ready structure |
| `/i2i-ticket-update` | `<TICKET-KEY>` | Enrich ticket with code-aware implementation plan |
| `/i2i-ticket-update --push` | `<TICKET-KEY> --push` | Push existing local ticket to Jira as a comment (no scan) |
| `/i2i-ticket-start` | `<TICKET-KEY>` | Orient to the code, surface blockers before implementing |
| `/i2i-test-gen` | `<TICKET-KEY> [--mode descriptions\|code]` | Generate test cases from a ticket |

### Review & Delivery

| Command | Params | What it does |
|---------|--------|--------------|
| `/i2i-pr-review` | `[PR-URL or branch]` | Review a PR against original ticket acceptance criteria |
| `/i2i-roadmap` | `[add\|update\|show] [args]` | View or update the roadmap |
| `/i2i-roadmap-sync` | `<TICKET-KEY>` | Close out a ticket on the roadmap after PR merge |
| `/i2i-tradeoff` | `[description]` | Log a technical debt decision with context and traceability |

### Status & Publishing

| Command | Params | What it does |
|---------|--------|--------------|
| `/i2i-status` | _(none)_ • `--update` • `--scan [repo-name]` | Show, smart-update, or force-scan platform state and research docs |
| `/i2i-publish` | `[roadmap\|status\|prd PRD-NNN]` | Publish docs to Confluence |

---

<!-- Add project-specific instructions below -->

## Current Implementation State

FieldMapper V2 (`PRD-002`) — Relationship Analysis page (`pages/3_Relationship_Analysis.py`):

- **Cardinality analyzer** (`utils/cardinality.py`) — shipped (PLAN-002). Field pair mapping shape, conformance rate, violations, directional expectations.
- **Completeness Comparison** (`utils/completeness.py`: `analyze_completeness`, `analyze_completeness_batch`) — shipped (PLAN-003). Declare 5+ units concurrently (1+ columns each); single-column units auto-generate from any multi-column unit's constituents (deduped); results render as one comparison table (Complete/Partial/Empty), single-column units first then multi-column. Null/empty-string/whitespace-only values are all treated as "not present" via `_presence_mask`.
- **Coverage Expressions** (`utils/coverage.py`: `evaluate_coverage`, `validate_expression`) — shipped (PLAN-003). Boolean AND/OR expressions (one level of parens, no NOT) over units declared in the completeness comparison; separate results table (Expression / Rows Satisfied / %); terms are cumulative, not a mutually-exclusive partition.
- **Superseded**: PLAN-008 (co-presence + derivation analyzers, ordered fallback ladder with cost tiers) — see `_i2i/plans/draft/008-...md` for the superseded-banner and rationale. Its exclusive-bucket sized work-plan and expectation/alarm ideas are deferred, not solved by Coverage Expressions.
