# WF Agents Plugin Rules

When the user invokes `/wf`, `/wf-plan`, `/wf-assemble`, `/wf-report`, or asks to run the 6-step Open-Source Reuse & Assembly Pipeline:

1. **Panel Lifecycle (Strict)**:
   - Call `wf_start` (or `wf_stage.py init`) **once** on the first interaction of a workflow to calibrate capabilities and open the local config panel.
   - **Never** reopen the config panel during Gate 1 requirement revisions or follow-up turns.
   - **Always** close the panel via `wf_gate_commit(gate="GATE_1", ...)` or `wf_enter_plan` before starting external research, and keep it closed throughout planning, assembly, and reporting.

2. **Six Human Gates & Controlled Write Discipline (Human-in-the-Loop)**:
   - Gates 1–3 (`GATE_1` discovery/requirements, `GATE_2` license/security audit, `GATE_3` 5-way reuse strategy) are **strictly read-only**. Do not modify project files during Steps 1–3.
   - Never invoke `wf_assemble_apply` or write reused code into the workspace without explicit human approval recorded via `wf_gate_commit` (`GATE_4` integration contract / `GATE_5` chunked diff) and an automatic safety checkpoint (`wf_checkpoint`).
   - Record every gate decision to `.wf/decisions/<sessionId>.json` & `ADR-<sessionId>.md` via `wf_gate_commit`.

3. **Decision-Useful, Evidence-First Output**:
   - Every gate proposal must answer the 4 Decision Brief questions: requirement fit, verifiable evidence (URL/Commit/License/CVE/LOC), limitations & tradeoffs, and actionable options.
   - Never fabricate repository URLs, star counts, licenses, release versions, CVE IDs, or file paths. Always preserve SPDX headers and update `THIRD_PARTY_NOTICES.md` when assembling upstream code.
