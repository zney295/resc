# Claude / AI agent entry point

Read [AGENTS.md](AGENTS.md) for invariants, commands and the current tool matrix.
Follow [.agents/skills/recovery-triage/SKILL.md](.agents/skills/recovery-triage/SKILL.md)
and [docs/recovery-guide.vi.md](docs/recovery-guide.vi.md). Query `tools/list`.

Use the version-3 [case matrix](.agents/skills/recovery-triage/references/case-matrix.md)
before scanning. No Media, reader disagreement, 00/FF, zero-hit and persistence
need different evidence. Audit/compare stored images with evidence_audit.py;
do not interpret a copy hash or screenshot as proof of original USB contents.

Do not rely on historical claims of automatic physical repair, journal recovery,
PhotoRec integration or universal fragmented-file reconstruction. Repairs stay in
Copy-on-Write; extraction is asynchronous and produces provenance manifests.
