# Development Plan & Definition of Done

## Urutan prioritas

Pembagian kerja paralel untuk tiga anggota tim, ownership, checkpoint, dan tata kelola GitHub dijelaskan di [`TEAM_DEVELOPMENT_PLAN.md`](TEAM_DEVELOPMENT_PLAN.md). Dokumen ini tetap menjadi sumber urutan prioritas dan Definition of Done fitur.

### P0 — Foundation and workflow

1. Audit repository, current branch, current changes, package/lock files, existing UI, tests, and deployment configuration.
2. Set up/confirm design system using current stack.
3. Create/confirm workspace navigation for eight roles.
4. Establish task persistence and task/run/step state.
5. Integrate organizer-provided API using verified endpoint/model details and secret-safe environment configuration.
6. Implement chat input and new task creation.
7. Implement document upload and real parsing for at least the formats selected by the team.
8. Implement IT Helpdesk flow with at least one working external-to-LLM data source/tool.
9. Implement execution inspector and persisted task history.
10. Implement output with evidence/sources and failure states.

### P1 — Campus Twin and evaluation

1. Create an initial 2D map/view for the available demo building/zone/device data.
2. Connect incident/task to relevant device/location records where data relations exist.
3. Show synthetic/demo labels.
4. Add token usage capture and task metrics.
5. Add tests for expected cases, missing data, invalid input, provider failure, and tool failure.

### P1 add-on — Vision Twin video MVP

- [x] Pin OpenCV contrib Python distribution to 5.0.0.93 and add a runtime OpenCV 5.x version gate for video jobs.
- [x] Add authenticated video upload with format/size/duration/resolution checks and configurable frame sampling.
- [x] Add normalized polygon zones, person-to-zone mapping, annotated evidence frames, and SQLite job/observation/twin state.
- [x] Add deterministic agent trace whose next tool depends on evidence (follow-up window, comparison, draft ticket, human review, or no action).
- [x] Add human approve/reject endpoint for draft tickets; no external actions are executed.
- [x] Add workspace UI for video upload, version gate, state, frame evidence, job history, events, agent trace, and approval queue.
- [x] Add API tests for version gate, upload authentication/validation, state persistence, triggered/no-trigger scenarios, trace, frame retrieval, and ticket review.
- [x] Run CI and review actual test/type-check/build outcomes before merge: commit `8e975517`, OpenCV 5 smoke passed, backend 120 passed/1 skipped, frontend typecheck/unit tests/production build passed.
- [ ] Calibrate polygons with licensed test clips and evaluate against manually annotated ground truth.
- [ ] Deploy the vision pipeline on AWS and verify its public health/demo endpoint.
- [ ] Add retention policy, bounded job concurrency, and verified camera-to-building mapping before real camera integration.

### P2 — Extend campus workers

After the IT Helpdesk workflow is stable, extend shared services to document search, PMB, Quality Assurance, or other role workflows based on time and data availability. Prioritization among these additional workers: `TBD`.

## Audit-before-build checklist

- [ ] Inspect repository tree, branch, status, and recent commits.
- [ ] Identify frontend/backend framework and package manager.
- [ ] Identify database/storage already configured.
- [ ] Inspect existing UI and reusable components.
- [ ] Find tests, lint, type-check, build, and run commands.
- [ ] Inspect `.gitignore` and secret-handling patterns.
- [ ] Verify organizer API documentation and model availability; never infer from an API key alone.
- [ ] Record actual current state before changing architecture.

## Definition of Done for a feature

A feature can be considered done only when:

- Its scope and UI/backend behavior are implemented, not only mocked.
- Inputs are validated and relevant failure cases are handled.
- Output and state persist where required.
- Source/evidence is displayed when the task relies on external data.
- Loading, empty, success, and error states are usable.
- Relevant tests or manual test steps are recorded with actual results.
- No secrets/personal data are accidentally committed.
- Documentation is updated if setup, API, workflow, or product behavior changes.
- Any mock/simulated component is labeled in the application and README.

## Demo readiness checklist

- [ ] One complete IT Helpdesk scenario works end-to-end.
- [ ] A fresh input can be submitted live.
- [ ] At least one source/tool beyond the LLM is exercised.
- [ ] User can see steps/status and supporting evidence.
- [ ] Final result and history survive refresh.
- [ ] One failure case is handled and presented clearly.
- [ ] Token usage is measured or marked unavailable if provider does not expose it.
- [ ] New/synthetic data is disclosed.
- [ ] Video backup is recorded.
- [ ] Final commit is recorded before submission cutoff.
