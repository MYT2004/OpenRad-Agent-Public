# Radiation physics workflow rules

- Every tool must pass the `@post_tool_call` checks in `src.hooks`.
- Require finite nonnegative doses and array dimensions consistent with physical axes.
- Require finite beam energy from 0.01 through 250 MeV and positive integer histories; these are application bounds.
- Prefer TG-263 primary ROI names and explicit DVH units. Legacy identities require reviewed mappings; laterality is never inferred.
- Use scrubbed in-memory analysis copies; never export original patient identifiers or source DICOMs.
- Preserve frame and course-reference mismatches as blockers. An omitted RTPLAN leaves course linkage unverified.
- Use session artifact directories. The CPU filesystem is ephemeral on Cloud Run; durable storage requires a separately configured service.
- Sampling restrictions, uncertainty and clinical release limits in MEDICAL_PHYSICS_AUDIT.md remain applicable.
