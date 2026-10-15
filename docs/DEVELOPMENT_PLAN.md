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

### P1 add-on — Vision Twin prototype

- [x] Add an authenticated endpoint for one uploaded image with input size/type limits.
- [x] Run OpenCV HOG pedestrian detection by default; support a configured compatible YOLO ONNX model through OpenCV DNN.
- [x] Add the Vision Twin workspace route with uploaded-image preview, annotated output, detector/provenance, error state, and explicit non-live labeling.
- [x] Add focused API tests for authentication, unsupported image types, invalid images, successful result payload, and upload limits.
- [ ] Run CI and review the results before merging.
- [ ] Future: persist timestamped observations, implement retention policy, calibrate occupancy, and connect it to Campus Twin overlays only after schema and mapping are verified.

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
