# Phase 4 — Creative Ownership Intelligence Plan

## Top-Level Overview

**Goal:** Turn the existing timeline log into two concrete, human-visible outputs — a **Contribution Dashboard** (deterministic human-vs-AI split) and an exportable **Creative Passport** (PDF) — without changing anything about how the timeline is logged today.

**Scope (from `SPEC.md`, Phase 4 — "Creative Ownership Intelligence"):**
- `utils/contribution.py` — compute the section-authorship split and the creative-direction split from `project.timeline` and `project.song`
- Contribution Dashboard panel in `views/view_project.py`
- `utils/passport.py` — build a Creative Passport PDF (ReportLab) from the song, timeline, and contribution split
- "Export Passport" button + download flow in `views/view_project.py`
- Two new timeline events actually **fired**: `contribution_computed`, `passport_exported` (both already exist as icons/comments in the codebase — see Sub-Task 6 — but nothing calls `append_event()` with them yet)
- `reportlab` added to `requirements.txt` (documented in `README.md`/`SPEC.md` already, never installed)

**Non-goals:**
- Any change to lock/regenerate/drift-check logic (Phase 3, already correct and tested — do not touch `ai_engine.py`'s regeneration path)
- Any change to the JSON schema — `project.contribution`, `project.passport`, and `collaborators[].contribution_pct` already exist as empty placeholders (added in the v2 schema bump during Phase 1's post-review pass); Phase 4 populates them, it does not redesign them
- Audio preview (Phase 5, stretch goal, separate branch/effort)
- Fixing the pytest/`assert` issue in `tests/test_phase3*.py` — ~~tracked separately~~ **done and merged** (`fix/pytest-assert-format`); `tests/test_phase3.py` and `tests/test_phase3_comprehensive.py` now use real `assert` statements

**Confirmed Design Decisions:**
- Both contribution numbers are computed **on demand** from the timeline (not stored as the source of truth) and then **cached** into `project.contribution` with a `computed_at` timestamp and `methodology_version`, exactly as the schema comment in `utils/models.py` describes. The dashboard always shows a fresh computation; the cache exists so the Passport export can cite a stable, already-agreed number instead of recomputing mid-export.
- The Passport PDF is generated fully in-memory (`bytes`) and offered via `st.download_button` — no PDF file is ever written to `data/` or anywhere on disk automatically. This matches the "single JSON file per project" architecture principle in `README.md`: the PDF is a derived export, not a new source of truth.
- **`collaborators[].contribution_pct` population:** `compute_contribution()` return shape is unchanged (only `human_pct`, `ai_pct`, `direction_score`, `computed_at`, `methodology_version`). The caller in `views/view_project.py` — in the same block where it caches `project.contribution` — loops over `project.collaborators` and sets `contribution_pct = result["ai_pct"]` for every entry where `role == "ai_model"`. `compute_contribution()` does not know about collaborators at all.
- **Timestamp format for staleness check:** `compute_contribution()` stamps `computed_at` using `datetime.now().isoformat()` — the exact same call used by `utils/timeline.py`'s `create_event()`. Both are naive local-time ISO strings, so the staleness comparison (`computed_at >= last_event_timestamp`) is a plain string comparison with no timezone conversion needed.

**⚠️ Open question that needs your sign-off before Bob builds `utils/contribution.py` (this is a human decision, not Bob's to make — same principle `SPEC.md` uses for the Phase 3 drift-check contract):**

`SPEC.md`'s Contribution Methodology says the creative-direction split counts *"every lock, regenerate request, accept, and reject"* as a human decision. I checked the actual codebase: **`accept` and `reject` timeline events are never fired anywhere** — Phases 2–3 only ever log `project_created`, `ai_generated`, `section_locked`, `section_unlocked`, `section_regenerated`, and `human_edit`. There is no accept/reject step in the current UI (a generated song section is just... there; there's no explicit "accept this AI output" click).

You have two honest options — pick one and write it into this file before Bob starts, so it isn't quietly decided by whichever way Bob happens to code it:

- **Option A (recommended — no scope creep):** Direction score = `section_locked` + `section_unlocked` + `section_regenerated` + `human_edit` events ÷ total timeline events. Document in the Passport's transparency statement that "accept/reject" are implicitly represented by lock (accept) and regenerate (reject), since this build has no separate accept/reject step.
- **Option B (matches the spec literally):** Add explicit `accept`/`reject` buttons somewhere in the UI (e.g. on a freshly generated, unlocked section) that fire new timeline events — this is new scope beyond what Phase 2/3 built, and would need its own sub-task, prompt to Bob, and screenshot.

> **Decision: Option B.** We are building real `accept`/`reject` actions rather than approximating them from lock/regenerate. This matches `SPEC.md`'s Contribution Methodology literally, at the cost of one extra sub-task (Sub-Task 2a below) that touches `views/view_project.py`'s section-rendering logic. Because this adds a new UI interaction to a file that Phase 3's tested lock/regenerate flow also lives in, treat Sub-Task 2a as its own reviewable commit, separate from `compute_contribution()` itself, and re-run `tests/test_phase3.py` / `tests/test_phase3_comprehensive.py` after it lands to confirm nothing in the existing lock/regenerate/drift-check path regressed.

---

## Architecture

### Module Responsibilities

| Module | Existing Role | Phase 4 Addition |
|---|---|---|
| `utils/contribution.py` | *(does not exist)* | **New.** `compute_contribution(project) -> dict` |
| `utils/passport.py` | *(does not exist)* | **New.** `build_passport_pdf(project) -> bytes` |
| `utils/timeline.py` | Event creation/append | No change — `contribution_computed` and `passport_exported` are already valid `event_type` values per the docstring in `create_event()`; nothing to add here |
| `utils/models.py` | Project + schema | No change — `contribution`, `passport`, `collaborators[].contribution_pct` fields already exist |
| `utils/storage.py` | Atomic JSON persistence | No change |
| `views/view_project.py` | Workspace UI | Contribution Dashboard panel + Export Passport button |
| `requirements.txt` | Dependencies | Add `reportlab` |

### State Flow

```
User opens a project with a generated song
    → view_project.py calls compute_contribution(project)
    → if project.contribution is stale/empty: recompute, cache into project.contribution,
      append "contribution_computed" timeline event, save_project(project)
    → render Contribution Dashboard panel (human %, AI %, direction score)

User clicks "Export Passport"
    → view_project.py calls build_passport_pdf(project)
    → passport.py pulls: song title/metadata, full timeline, project.contribution
    → renders PDF in-memory via ReportLab, returns bytes
    → append "passport_exported" timeline event, save_project(project)
    → st.download_button offers the PDF bytes for download
```

---

## Sub-Tasks

---

### Sub-Task 1 — Add `reportlab` to `requirements.txt`

**Intent:** Install the PDF library that `README.md` and `SPEC.md` already document as the chosen tool, but which was never actually added to dependencies.

**Expected Outcomes:**
- `requirements.txt` includes `reportlab>=4.0`
- `pip install -r requirements.txt` succeeds and `import reportlab` works

**Relevant Context:**
- [`requirements.txt`](requirements.txt) — currently only `streamlit`, `python-dotenv`, `google-genai`

**Status:** `[ ] not started`

---

### Sub-Task 2 — `compute_contribution()` in `utils/contribution.py`

**Intent:** A pure, stateless function that reads `project.song["sections"]` and `project.timeline` and returns the two-number split described in `SPEC.md`'s Contribution Methodology, following whichever Option (A or B) was decided above.

**Expected Outcomes:**
- `compute_contribution(project) -> dict` is importable from `utils.contribution`
- Returns exactly the shape documented in `utils/models.py`'s `contribution` field comment:
  ```json
  {
    "human_pct": 0.0,
    "ai_pct": 0.0,
    "direction_score": 0.0,
    "computed_at": "ISO-8601",
    "methodology_version": 1
  }
  ```
- **Section-authorship split:** walk every section in `project.song["sections"]`; `provenance == "human_written"` counts 100% human, `"ai_generated"` counts 100% AI, `"ai_then_human"` counts 50/50; average across all five sections into `human_pct`/`ai_pct` (they must sum to 100).
- **Creative-direction split (Option B):** count `section_locked` + `section_unlocked` + `section_regenerated` + `human_edit` + `section_accepted` + `section_rejected` events as a fraction of total timeline events → `direction_score`. The `section_accepted`/`section_rejected` event types depend on Sub-Task 2a existing — if Sub-Task 2a hasn't landed yet, this function must still run correctly (those two event types simply won't appear in the timeline yet, contributing zero, not an error).
- Does **not** mutate `project` or call `save_project()` — pure function, no side effects, no Streamlit imports. Caller (`view_project.py`) is responsible for caching the result and saving.
- Handles a song with no sections yet (returns zeros, does not divide by zero) and a timeline with zero events (same).

**Implementation Notes:**
- Reuse the exact provenance labels already used in `views/view_project.py`'s `prov_label` dict (`"ai_generated"`, `"human_written"`, `"ai_then_human"`) — do not invent new provenance strings.
- Round percentages to 1 decimal place for display stability (avoid dashboard numbers jittering between renders due to floating-point noise).
- Build and land this sub-task **before** Sub-Task 2a — `compute_contribution()` should tolerate accept/reject events not existing yet, so the two sub-tasks can be tested and committed independently.
- `computed_at` must use `datetime.now().isoformat()` — identical to `create_event()`'s timestamp call. The staleness check in the caller compares `computed_at >= project.timeline[-1]["timestamp"]` as a plain string comparison; no timezone conversion needed.
- `collaborators[].contribution_pct` is **not** returned by this function. The caller sets it separately (see Confirmed Design Decisions above).

**Relevant Context:**
- [`utils/models.py` lines 101–113](utils/models.py:101) — `contribution` field shape this function must produce
- [`views/view_project.py` lines 588–592](views/view_project.py:588) — existing `prov_label` mapping to reuse verbatim
- `SPEC.md`, section "Contribution Methodology — the Defensible Version"

**Status:** `[ ] not started`

---

### Sub-Task 2a — Accept / Reject Actions in `views/view_project.py` (New scope — Option B)

**Intent:** Add the accept/reject step that `SPEC.md` describes but Phases 2–3 never built. A freshly AI-generated, unlocked section should offer an explicit "✓ Accept" / "✕ Reject" choice, distinct from locking — accepting/rejecting is a lightweight judgment call on the current draft; locking is the stronger "freeze this, never touch it again" commitment that Phase 3 already has.

**Expected Outcomes:**
- Two new timeline event types actually fired: `"section_accepted"`, `"section_rejected"` — added to the taxonomy comment in `utils/timeline.py` (`create_event()` docstring) alongside the existing Phase 2–4 event list, so the taxonomy stays documented in one place
- New buttons "✓ Accept" / "✕ Reject" shown on unlocked, AI-touched sections (i.e. `provenance in ("ai_generated", "ai_then_human")`) — not shown on `human_written` sections (nothing to accept/reject if a human wrote it from scratch) or on locked sections (already committed)
- **Accept:** logs `"section_accepted"` with `metadata={"section_key": ...}`; no change to the section's lyrics or provenance — it's a record of a decision, not a mutation
- **Reject:** logs `"section_rejected"` with `metadata={"section_key": ...}`, then immediately triggers the same regeneration path as the existing "↻ Regenerate" button (rejecting *is* asking for a new draft) — reuse `_run_section_regeneration()` as-is, don't duplicate its logic
- New `_event_icon()` entries for `"section_accepted"` and `"section_rejected"` (e.g. `"✓"` / `"✕"`) so the timeline renders them meaningfully
- **Regression check:** after this lands, re-run `tests/test_phase3.py` and `tests/test_phase3_comprehensive.py` — this sub-task edits the same file (`views/view_project.py`) as the tested lock/regenerate flow, so confirm nothing there broke

**Implementation Notes:**
- Keep Accept/Reject visually distinct from the existing Lock and Regenerate buttons (different row, or a labeled group) so users don't confuse "I'm happy with this" (Accept) with "freeze this forever" (Lock) — they are different strengths of commitment per the Intent above.
- This is new scope beyond the original Phase 2/3 build — call this out explicitly in the Bob decision log ("what we asked: add accept/reject per SPEC.md's literal wording; what Bob produced: ...; what we changed: ...") since it's the one place this branch adds a feature rather than just wiring up existing data.

**Relevant Context:**
- [`views/view_project.py` lines 543–712](views/view_project.py:543) — `_render_section_card()`, the function these buttons get added to
- [`views/view_project.py` lines 365–468](views/view_project.py:365) — `_run_section_regeneration()`, reused as-is for the Reject path
- [`utils/timeline.py` lines 36–65](utils/timeline.py:36) — `create_event()` docstring/taxonomy comment to extend
- `SPEC.md`, section "Contribution Methodology — the Defensible Version" — the literal spec wording this sub-task exists to satisfy

**Status:** `[ ] not started`

---

### Sub-Task 3 — Contribution Dashboard Panel in `views/view_project.py`

**Intent:** Render the numbers from Sub-Task 2 in the existing project workspace, near the Creative Timeline panel, and cache the computed result into `project.contribution` with a `contribution_computed` timeline event the first time it's computed for a given project state.

**Expected Outcomes:**
- New helper `_render_contribution_dashboard(project)` called from `render()`, positioned in the right-hand meta panel below the Creative Timeline (same visual language: dark card, accent border, matching the existing `_label()` / card styling used elsewhere in this file)
- Shows human % / AI % (e.g. as a simple two-segment bar or two metric chips) and the direction score
- On first computation for a project (i.e. `project.contribution` is empty or its `computed_at` predates the latest timeline event): call `compute_contribution()`, store the result in `project.contribution`, append a `"contribution_computed"` timeline event via `append_event()`, `save_project(project)`
- No dashboard shown (or a clear "Generate a song first" placeholder) when `project.song` has no sections yet — mirrors the existing pre-generation empty state already used for the song panel

**Relevant Context:**
- [`views/view_project.py` lines 853–869](views/view_project.py:853) — RIGHT column, existing Song Vibe + Creative Timeline layout to extend
- [`views/view_project.py` line 136](views/view_project.py:136) — `_event_icon()` already maps `"contribution_computed": "📊"`, so no icon work needed
- [`utils/timeline.py` line 67](utils/timeline.py:67) — `append_event()` usage pattern

**Status:** `[ ] not started`

---

### Sub-Task 4 — `build_passport_pdf()` in `utils/passport.py`

**Intent:** A pure function that renders a Creative Passport PDF entirely in memory using ReportLab: song title/metadata, the full timeline (chronological), the contribution split, and a transparency statement.

**Expected Outcomes:**
- `build_passport_pdf(project) -> bytes` is importable from `utils.passport`
- PDF contains, in order: song title + genre/mood/tempo header, a timeline section (event #, type, actor, description, timestamp — reuse the same data already rendered in `_render_timeline()`), the contribution numbers from `project.contribution`, and a transparency statement paragraph
- Transparency statement and `authorship_line` text are pulled from `project.passport` if already set (human-approved wording, per the schema comment), otherwise a sensible default is generated inline — do **not** silently overwrite human-approved wording on every export
- Returns raw `bytes` (use `io.BytesIO` + ReportLab's `SimpleDocTemplate`, return `buffer.getvalue()`) — no file written to disk inside this function
- Does not call `save_project()` — pure function, side-effect-free, same discipline as `compute_contribution()`

**Implementation Notes:**
- Reuse `_relative_time()`-equivalent formatting isn't necessary in a PDF — print absolute ISO timestamps for permanence (a PDF that says "3h ago" is meaningless once printed/archived).
- Keep layout simple: ReportLab `Paragraph` + `Table` flowables, one style sheet (`reportlab.lib.styles.getSampleStyleSheet()`), no custom fonts — this is a hackathon deliverable, not a print product.

**Relevant Context:**
- [`views/view_project.py` lines 714–777](views/view_project.py:714) — `_render_timeline()`, the data shape to mirror in the PDF's timeline section
- [`utils/models.py` lines 116–125](utils/models.py:116) — `passport` field shape (`transparency_statement`, `authorship_line`, `watermark_id`)
- `SPEC.md`, section "What HarmonyLedger Does" — describes the Passport's required contents (timeline + contribution split + transparency statement)

**Status:** `[ ] not started`

---

### Sub-Task 5 — Export Passport Button in `views/view_project.py`

**Intent:** Add the UI trigger that calls `build_passport_pdf()`, offers the result via `st.download_button`, stamps `project.passport` (export metadata, not the PDF itself), logs the event, and saves.

**Expected Outcomes:**
- A "🛂 Export Passport" button, placed near the Contribution Dashboard (Sub-Task 3)
- On click: calls `build_passport_pdf(project)`, then `st.download_button("Download Creative Passport", data=pdf_bytes, file_name=f"{project.name}_passport.pdf", mime="application/pdf")`
- Updates `project.passport` with `exported_at`, `export_format="pdf"`, and a fresh `watermark_id` (uuid4) — does **not** overwrite `transparency_statement`/`authorship_line` if a human already set them
- Appends a `"passport_exported"` timeline event via `append_event()`, increments `project.version`, `save_project(project)`
- Button is disabled (or shows a clear message) when `project.song` has no sections yet — can't export a Passport for a song that doesn't exist

**Relevant Context:**
- [`views/view_project.py` line 137](views/view_project.py:137) — `_event_icon()` already maps `"passport_exported": "🛂"`, so no icon work needed
- [`views/view_project.py` lines 894–902](views/view_project.py:894) — existing button + action pattern (`_run_generation`) to follow for the click handler shape

**Status:** `[ ] not started`

---

### Sub-Task 6 — Timeline Event Icons

**Intent:** Originally scoped as a sub-task, but already done.

**Expected Outcomes:** N/A — verified `_event_icon()` at [`views/view_project.py:136-137`](views/view_project.py:136) already returns `"📊"` for `contribution_computed` and `"🛂"` for `passport_exported`. Nothing to build here; Sub-Tasks 3 and 5 just need to actually *fire* these event types.

**Status:** `[x] already done (pre-existing)`

---

### Sub-Task 7 — Test Coverage

**Intent:** Extend the test harness with a Phase 4 file, following the exact style of `tests/test_phase3.py` (the plain-Python-script style with a `run_tests()` summary, per how this repo's tests are actually meant to be run — see the project's testing guide).

**Expected Outcomes:**
- `tests/test_phase4.py` (new file)
- Test: `compute_contribution()` on a song with all `human_written` sections returns `human_pct == 100`
- Test: all `ai_generated` sections returns `ai_pct == 100`
- Test: mixed `ai_then_human` sections returns the correct 50/50-weighted average
- Test: empty song / empty timeline does not raise (returns zeros, no division-by-zero)
- Test: `build_passport_pdf()` returns non-empty `bytes` starting with the PDF magic bytes (`%PDF`)
- Test: exporting twice does not overwrite an already-set `transparency_statement`
- Test (Option B): accepting a section logs `section_accepted` and leaves lyrics/provenance untouched
- Test (Option B): rejecting a section logs `section_rejected` and triggers regeneration (reuse the existing Phase 3 regeneration test fixtures)
- Test (Option B): `direction_score` reflects accept/reject events once Sub-Task 2a exists
- Write these as real **`assert`-based pytest tests** — the `return list[str]` pattern has been fixed and is gone. Do not use it in this new file. Follow the same style as the corrected `tests/test_phase3.py` (direct `assert` statements, standard pytest, no custom runner needed — though a `run_tests()` block for standalone execution is fine as a bonus if desired).

**Relevant Context:**
- [`tests/test_phase3.py`](tests/test_phase3.py) — structural pattern to follow (or improve on, per the note above)

**Status:** `[ ] not started`

---

## JSON Changes

No schema version bump required. Every field Phase 4 populates already exists in the v2 schema (added during Phase 1's post-review pass, per the schema version history comment in `utils/models.py`):

```json
{
  "contribution": {
    "human_pct": 0.0,
    "ai_pct": 0.0,
    "direction_score": 0.0,
    "computed_at": null,
    "methodology_version": 1
  },
  "passport": {
    "exported_at": null,
    "export_format": null,
    "transparency_statement": "",
    "authorship_line": "",
    "watermark_id": null
  }
}
```

The only runtime change is that these two objects go from empty placeholders to populated values, and `collaborators[].contribution_pct` (currently always `null`, per `views/view_project.py:196`) gets filled in by `compute_contribution()`.

---

## Files to Modify

| File | Change Type | Description |
|---|---|---|
| `requirements.txt` | **Extend** | Add `reportlab` |
| `utils/contribution.py` | **New** | `compute_contribution()` |
| `utils/passport.py` | **New** | `build_passport_pdf()` |
| `utils/timeline.py` | **Extend (Option B)** | Add `section_accepted`/`section_rejected` to the event-type taxonomy comment in `create_event()` — no function signature changes |
| `views/view_project.py` | **Extend** | Add `_render_contribution_dashboard()`, Export Passport button + handler, Accept/Reject buttons + handlers (Option B), new `_event_icon()` entries |
| `tests/test_phase4.py` | **New** | Phase 4 test harness |

**No changes needed to:** `utils/models.py`, `utils/storage.py`, `utils/ai_engine.py`, `utils/gemini_client.py`, `utils/presets.py`, `views/create_project.py`, `views/open_project.py`, `app.py`

---

## Step-by-Step Implementation Plan

Execute in this order (each is independently reviewable and commit-able):

1. **Decision** — Option B, confirmed above (human sign-off, already made — do not let Bob silently reinterpret this)
2. **Sub-Task 1** — Add `reportlab` to `requirements.txt`, reinstall (no Bob needed)
3. **Sub-Task 2** — Build `utils/contribution.py` (Plan mode to sanity-check structure, then Agent mode to write it; must tolerate accept/reject events not existing yet; test standalone against a real saved project JSON before touching the UI)
4. **Sub-Task 2a** — Add Accept/Reject actions to `views/view_project.py` + taxonomy comment in `utils/timeline.py` (Agent mode; this is the new-scope piece — screenshot the prompt + diff separately from Sub-Task 3's screenshot since it's a distinct feature, not just wiring; **re-run `tests/test_phase3.py` and `tests/test_phase3_comprehensive.py` afterward** to confirm the existing lock/regenerate/drift-check flow still passes)
5. **Sub-Task 3** — Wire the Contribution Dashboard into `views/view_project.py` (Agent mode; verify live in the running app; direction score should now reflect real accept/reject counts)
6. **Sub-Task 4** — Build `utils/passport.py` (Agent mode; test standalone, actually open the generated PDF before wiring it in)
7. **Sub-Task 5** — Add the Export Passport button (Agent mode; verify live — click it, confirm the download works and the PDF is correct)
8. **Sub-Task 6** — Nothing to do, already verified done
9. **Sub-Task 7** — Write `tests/test_phase4.py` (Agent mode; depends on Sub-Tasks 2, 2a, and 4 existing)
10. Update `README.md`'s Phase 4 roadmap line only once Sub-Tasks 1–7 work end-to-end in the running app (your own edit, not Bob's)
