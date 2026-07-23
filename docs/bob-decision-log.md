# HarmonyLedger — IBM Bob Decision Log

This log documents the key human–AI interactions across the HarmonyLedger build.  
Each entry follows the format described in [`SPEC.md`](SPEC.md):  
**what we asked → what Bob produced → what we changed / accepted**.

It is the evidence record for the "effective use of IBM Bob" judging criterion.  
The parallel is intentional: HarmonyLedger documents a human staying the author while  
an AI co-writes the music. This log documents exactly the same thing with the code.

---

## Phase 1 — Streamlit Skeleton + Project Storage

### D-01: Architecture review — Plan Mode

**What we asked:**  
Review the intended folder structure (app.py + pages/ + utils/ + data/) and stress-test the project JSON schema for long-term extensibility. Identify edge cases we haven't thought about.

**What Bob produced:**  
- Recommended separating the schema version from the application version (now `schema_version` vs `project.version` — distinct fields).  
- Identified that mutable default arguments in Python dataclasses would cause aliasing bugs — recommended `field(default_factory=...)` for all list/dict fields in `models.py`.  
- Flagged that a plain `open().write()` call would leave a half-written file on crash or disk-full — recommended `os.replace()` atomic write pattern.  
- Recommended adding a `schema_migrations` list so the migration history is self-documenting inside each project file.  
- Suggested the `ext` dict extension envelope on both Project and TimelineEvent for future third-party integrations.

**What we changed:**  
Accepted all five recommendations. The `ext` envelope and `schema_migrations` list were direct Bob outputs. The atomic write in `storage.py` is Bob's design.

---

### D-02: Edge-case review — Ask Mode

**What we asked:**  
What edge cases should the project creation and storage layer handle that we haven't listed?

**What Bob produced:**  
- Duplicate project names (same name, different IDs) — should warn but not block.  
- Missing or corrupt JSON files at startup — `list_projects()` should return problem files separately, not crash.  
- Concurrent saves from two browser tabs — version-based conflict detection needed.  
- Very long project names breaking UI layout and filenames — `PROJECT_NAME_MAX_LENGTH` constant.

**What we changed:**  
All four accepted and implemented. `ProjectConflictError` with `disk_version` attribute, `PROJECT_NAME_MAX_LENGTH = 100`, soft duplicate-name warning, and the problems-list return from `list_projects()` are all direct Bob outputs.

---

## Phase 2 — AI Song Starter (Core Engine)

### D-03: Prompt design — Ask Mode (Bob Showcase #1 setup)

**What we asked:**  
Design the vibe-to-song prompt template. It must reliably produce structured JSON from a natural-language description. What are the failure modes and how do we guard against them?

**What Bob produced:**  
- Identified that Gemini frequently wraps JSON in markdown fences despite instructions — recommended both a strict prompt prohibition AND a defensive `_strip_fences()` fallback in the engine.  
- Recommended the `response_mime_type="application/json"` SDK parameter to signal JSON-only output.  
- Designed the one-shot example format in the prompt — providing a structural anchor reduces schema variance.  
- Flagged that `generation_timestamp` and `model_used` should be stamped by `ai_engine.py` after validation, never requested from Gemini (Gemini cannot produce them correctly).

**What we changed:**  
The prompt template (`prompts/song_starter_v1.txt`) is Bob's output. `_strip_fences()` in `ai_engine.py` is Bob's design. The decision to use `response_mime_type` is Bob's recommendation.

---

### D-04: Validation rules and retry logic — Agent Mode

**What we asked:**  
Build `utils/ai_engine.py`. The validation must be strict enough that downstream features (locking, drift check, passport) always receive complete song data. Retry on any failure.

**What Bob produced:**  
`utils/ai_engine.py` with `_validate()`, `generate_song()`, `MAX_RETRIES=3`, and `SongGenerationError`. The validation checks all required string fields before accepting a response.

**What we accepted:**  
The complete module as written. One small change: we confirmed `MAX_RETRIES=3` (Bob suggested 3 as a reasonable hackathon-scope default; we signed off).

---

### D-05: 10-vibe done-bar harness — Agent Mode

**What we asked:**  
Write a test harness that proves the done bar: 10 different vibes across all 10 genre presets must all return complete, valid JSON.

**What Bob produced:**  
`tests/test_ai_engine.py` — 10 vibes, each asserting the full schema contract including provenance envelopes.

**Done bar result:**  
10/10 vibes passed on first run after the `response_mime_type` parameter was added. This is the acceptance gate for Phase 2.

---

## Phase 3 — Section Locking & Targeted Regeneration (Signature Feature)

### D-06: Drift-check contract — human sign-off required

**What we asked:**  
Before building, we need to define the drift-check contract. What exactly counts as a locked section change? This is an authorship rule, so it must be a human decision.

**Human decision (not Bob's):**  
A locked section change is ANY byte-level difference in the `lyrics` string — including whitespace-only changes and case-only changes. The SHA-256 hash is over the full UTF-8-encoded lyrics string. No exceptions.

**What Bob produced after sign-off:**  
`snapshot_locked_sections()` and `assert_locked_sections_unchanged()` in `ai_engine.py`, implementing the exact contract above. `DriftError` is raised if any locked section's hash differs, or if a section that was locked before the API call is missing after.

**What we changed:**  
None — the contract was defined first, then Bob built exactly to it.

---

### D-07: Test harness for drift check — Agent Mode (Bob Showcase #2)

**What we asked:**  
Write a test harness that both proves the drift check works correctly AND hunts edge cases. The drift check is the centrepiece of the product — Bob writes it, Bob's tests prove it, we review and sign off.

**What Bob produced:**  
`tests/test_phase3_comprehensive.py` — 57 tests covering:  
- 10 consecutive targeted regeneration cycles with zero drift in locked sections (C-series)  
- 8 explicit drift-injection tests including whitespace-only, case-only, and removal (D-series)  
- Lock/unlock state transitions (L-series)  
- Human edit storage round-trips (H-series)  
- Unicode and emoji in locked sections (U/E-series)  
- Long lyrics, concurrent-lock simulation, section ordering

**What we changed:**  
Reviewed each test group and confirmed the edge cases were meaningful. No tests removed. One adjustment: the `D06_drift_check_noop_empty_snapshot` test was Bob's own suggestion for an edge case we hadn't thought of.

---

### D-08: Accept/Reject actions — Option B decision

**What we asked:**  
SPEC.md says direction score should count "every lock, regenerate request, accept, and reject." The build so far has no explicit accept/reject step. Do we approximate (Option A) or build it (Option B)?

**Human decision:**  
Option B. We build real accept/reject actions. This matches the spec literally and produces a more defensible contribution methodology.

**What Bob produced:**  
Accept/Reject buttons in `views/view_project.py` that log `section_accepted` / `section_rejected` timeline events. Reject immediately triggers the same regeneration path as the Regenerate button (rejecting is asking for a new draft).

---

## Phase 4 — Creative Ownership Intelligence

### D-09: Transparency statement — Ask Mode (Bob Showcase #3 setup)

**What we asked:**  
Draft the AI transparency statement for the Creative Passport. It must be factually accurate about the contribution methodology, include the required non-legal disclaimer, and be written in a register suitable for rights-body submission.

**What Bob produced:**  
The `_DEFAULT_TRANSPARENCY` constant in `utils/passport.py` (attributed in the code comment: *"Drafted by IBM Bob (Ask/Agent mode) per SPEC.md Phase 4"*). The statement explains:  
- The provenance model (human_written, ai_generated, ai_then_human)  
- The direction score methodology  
- The non-legal disclaimer ("not a legal determination of copyright ownership")  
- The audit trail claim

**What we changed:**  
Added the `{version}` placeholder after Bob's draft so it can reference the current methodology version. Approved wording as written.

---

### D-10: Contribution methodology — human sign-off required

**What we asked:**  
Confirm the two-split formula before Bob implements it. This is "the credibility core" per SPEC.md — must be human-owned.

**Human decision:**  
- Section-authorship split: `human_written` = 100% human, `ai_generated` = 100% AI, `ai_then_human` = 50/50. Average across all 5 sections.  
- Direction score: count human steering decisions (lock, unlock, regen, edit, accept, reject, audio_preview) ÷ total timeline events.  
- `computed_at` excluded from the integrity hash (computed on every recompute; not an authorship field).

**What Bob produced after sign-off:**  
`utils/contribution.py` implementing the formula exactly as specified. `METHODOLOGY_VERSION = 1` for forward compatibility.

---

### D-11: Creative Passport PDF — Agent Mode

**What we asked:**  
Build the PDF export. It must be a certificate-quality document, not a plain text dump. Use a light "certificate" palette. Draw the donut chart and score bar as vector shapes (not emoji glyphs, which the base-14 PDF fonts can't render).

**What Bob produced:**  
`utils/passport.py` — 2-page PDF layout with:  
- Navy header band with project name and metadata  
- Contribution donut chart (vector-drawn as `Wedge` shapes)  
- Direction score bar (vector-drawn as `Rect` shapes)  
- Section authorship table with colour-coded swatches  
- Full creative timeline table  
- Transparency statement with left-border gold rule  
- Provenance stamp with watermark ID

**What we changed:**  
The design direction (light certificate palette, no dark-mode colours) was a human instruction. The specific palette values and vector shape implementations are Bob's output.

---

## Phase 5 — Unicode PDF Fix (Post-phase addition)

### D-12: Unicode font support — Agent Mode

**What we asked:**  
The Creative Passport renders non-Latin scripts (Hindi, Marathi, Telugu, Tamil, Japanese) as black boxes. Fix this without changing the PDF architecture.

**What Bob produced:**  
- Language → font family mapping (`_LANG_FONT_BASE`)  
- Graceful fallback chain in `_font()` for missing font files  
- Decision to use `HeiseiKakuGo-W5` CIDFont for Japanese (avoids a ReportLab TTF subsetting bug with large CJK fonts that Bob diagnosed from the stack trace)  
- `tests/test_unicode_pdf.py` — 41 tests covering all 8 languages, font registration, fallback, and PDF generation

**What we changed:**  
Bob identified the root cause (`unpack requires a buffer of 2 bytes` from ReportLab's TTF subsetter failing on the downloaded NotoSansJP variable font). The Japanese fallback to `HeiseiKakuGo-W5` was Bob's diagnostic decision.

---

## Phase 6 — Integrity Hash (Post-phase addition)

### D-13: Canonical record and SHA-256 integrity marker — Agent Mode

**What we asked:**  
Add a lightweight cryptographic integrity marker to the Creative Passport without blockchain or external databases. Use the existing SHA-256 approach from the drift check.

**What Bob produced:**  
- `canonical_record()` — deterministic, ordering-stable representation spec (what to include, what to exclude, and why)  
- `compute_record_hash()` — SHA-256 of the serialised canonical record  
- `tests/test_passport_integrity.py` — 61 tests covering determinism, sensitivity, ordering stability, backward compatibility, and non-interaction with the drift check

**What we changed:**  
The decision to exclude `contribution.computed_at` from the hash (it changes on every recompute without affecting authorship) and to include `watermark_id` + `exported_at` (so the hash ties to this specific export instance) were confirmed by us before Bob implemented. These are the same category of authorship-rule decisions as the drift-check contract.

---

## Phase 6 — Audit (this session)

### D-14: Final submission audit — Ask Mode

**What we asked:**  
Perform a focused audit against the five IBM AI Builders Challenge judging criteria. Identify gaps between documentation and implementation. Determine whether a direct IBM AI capability adds genuine value or is forced branding.

**What Bob produced:**  
This audit report (in the README changes) and this decision log file.

**Human decision:**  
No IBM AI runtime integration. The `watsonx.ai` free tier is not reliably accessible within challenge constraints, and adding an AI-generated narrative summary would conflict with HarmonyLedger's thesis that authorship accounting is *deterministic, not estimated*. Bob's role is best evidenced by the architecture, tests, and this log — not by adding a second runtime AI call.

---

## Summary of Human Decisions vs. Bob Outputs

| Decision | Owner | Why human-owned |
|---|---|---|
| Drift-check contract (any byte change = drift) | Human | Defines what authorship means |
| Option B (real accept/reject) over Option A | Human | Defines contribution methodology scope |
| Contribution formula (provenance weights, direction events) | Human | Defines the credibility core |
| `computed_at` excluded from integrity hash | Human | Defines what counts as authorship data |
| No IBM AI runtime call | Human | Strategic submission decision |
| Certificate palette direction for PDF | Human | Creative/design decision |
| All architecture, code, tests, docstrings, prompts | **IBM Bob** | Engineering execution |
