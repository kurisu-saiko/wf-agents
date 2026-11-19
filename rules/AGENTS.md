# WF Agents Plugin Rules

When the user invokes `/wf`, `/wf-plan`, `/wf-report`, or asks to run the wf open-source research & assembly workflow:

1. **Panel Lifecycle (Strict)**:
   - Call `wf_start` (or `wf_stage.py init`) **once** on the first interaction of a workflow to calibrate capabilities and open the local config panel.
   - **Never** reopen the config panel during Gate 1 requirement revisions or follow-up turns.
   - **Always** call `wf_enter_plan` (or `wf_stage.py enter-plan`) as soon as requirements are confirmed and before starting external research — this automatically closes the config panel.
   - Keep the panel closed in plan/research and report stages (`wf_enter_report`).

2. **Two Human Gates & Read-Only Discipline**:
   - Gate 1 (Requirements Confirmation) and Gate 2 (Plan Confirmation) must obtain explicit user confirmation before advancing.
   - Stay strictly read-only throughout `/wf` (do not edit workspace files, install packages, or deploy) unless the user explicitly authorizes implementation after Gate 2 / report delivery.

3. **Evidence-First Research**:
   - Combine `wf_*` tools (`wf_project_search`, `wf_web_search`, `wf_web_extract`, `wf_repo_inspect`, `wf_repo_health`, `wf_package_meta`, `wf_package_security`, `wf_license_scan`, `wf_project_analyze`, `wf_structural_search`) with native read-only file/search tools.
   - Never fabricate repository URLs, star counts, licenses, release versions, CVE IDs, or file paths. Clearly separate verified evidence from unverified gaps.
