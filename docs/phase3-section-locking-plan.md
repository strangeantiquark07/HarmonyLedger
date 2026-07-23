# Phase 3 — Section Locking & Targeted Regeneration Plan

## Top-Level Overview

**Goal:** Allow users to lock any song section (Verse 1, Chorus, Verse 2, Bridge, Outro) and regenerate only a single selected unlocked section while keeping every locked section exactly unchanged.

**Scope:**
- Lock/unlock toggle UI per section card
- "Regenerate this section" action per unlocked section
- New `regenerate_section()` function in `ai_engine.py`
- New `section_regen_v1.txt` prompt template for targeted regeneration
- Merge strategy: graft one section's new lyrics + reset provenance envelope into the existing `project.song`
- Drift-check: hash-compare locked sections before and after API call; abort and surface error if any locked section is modified
- Timeline events: `section_locked`, `section_unlocked`, `section_regenerated`
- No schema version bump needed (all fields already exist in the `song.sections` envelope)

**Non-goals:**
- Human-edit text boxes (Phase 3+ stretch, not in this phase)
- Bulk regeneration of all unlocked sections in one click
- Contribution dashboard or PDF export (Phase 4)

**Confirmed Design Decisions:**
- Song-level metadata (title, mood, tempo, key, style, lyrical_themes) is frozen during section regeneration — only the target section's lyrics change.
- Gemini receives only the **locked** sections as context during targeted regeneration. Unlocked sections are not sent (they may change in future regen cycles).

---

## Architecture

### Module Responsibilities (unchanged)

| Module | Existing Role | Phase 3 Addition |
|---|---|---|
| `utils/ai_engine.py` | Full-song generation | New `regenerate_section()` public function |
| `utils/gemini_client.py` | Gemini SDK wrapper | No change |
| `utils/timeline.py` | Event creation/append | No change (new event types already documented) |
| `utils/storage.py` | Atomic JSON persistence | No change |
| `utils/models.py` | Project + schema | No change (all section fields already exist) |
| `views/view_project.py` | Workspace UI | Lock/unlock toggles + Regen button per section |
| `prompts/` | Prompt templates | New `section_regen_v1.txt` |

### State Flow

```
User toggles lock icon on section
    → _toggle_lock(project, section_key) in view_project.py
    → sets section["locked"], locked_at, locked_by
    → appends section_locked / section_unlocked timeline event
    → save_project(project)
    → st.rerun()

User clicks "Regenerate" on an unlocked section
    → _run_section_regeneration(project, section_key) in view_project.py
    → calls ai_engine.regenerate_section(section_key, project.song)
    → drift_check_locked_sections() — hash locked section lyrics before call
    → Gemini call returns new lyrics for that section only
    → _merge_section(project.song, section_key, new_lyrics) — graft in
    → drift_check post-merge — verify locked sections still match pre-hashes
    → append section_regenerated timeline event
    → save_project(project)
    → st.rerun()
```

---

## Sub-Tasks

---

### Sub-Task 1 — New Prompt Template `prompts/section_regen_v1.txt`

**Intent:** Provide a focused prompt template that sends only the target section key plus surrounding song context (title, genre, style, mood, locked section lyrics for coherence) and asks Gemini to return one new section's lyrics as a minimal JSON object.

**Expected Outcomes:**
- `prompts/section_regen_v1.txt` exists
- Template accepts placeholders: `{genre}`, `{vibe}`, `{title}`, `{style}`, `{mood}`, `{section_key}`, `{section_label}`, `{locked_context}` (a formatted block of locked section lyrics for coherence)
- Gemini output schema is `{"lyrics": "<new lyrics>"}` — minimal, easy to validate
- No risk of Gemini accidentally returning or modifying other sections

**Todo List:**
1. Create `prompts/section_regen_v1.txt`
2. Write role instruction: professional songwriter, rewrite only the named section
3. Include song context block: genre, vibe, title, style, mood
4. Include `{locked_context}` block: list each locked section label + lyrics so Gemini stays coherent
5. Specify output schema: single JSON object `{"lyrics": "..."}`, no other fields
6. Include one-shot example for structural reference
7. Add `CRITICAL` output rule (pure JSON, nothing else)

**Relevant Context:**
- [`prompts/song_starter_v1.txt`](prompts/song_starter_v1.txt) — existing prompt structure and style conventions to mirror

**Status:** `[x] done`

---

### Sub-Task 2 — `regenerate_section()` in `utils/ai_engine.py`

**Intent:** Add a new public function that handles targeted single-section regeneration: build a focused prompt from the section key + song context, call Gemini, validate the single-field response, and return the new lyrics string. Drift checking lives in the caller (view layer), not here.

**Expected Outcomes:**
- `regenerate_section(section_key: str, song: dict) -> str` is importable from `utils.ai_engine`
- Builds the context block from currently locked sections in `song["sections"]`
- Renders `prompts/section_regen_v1.txt` with all placeholders
- Calls `gemini_client.call_gemini()` (reuse existing client)
- Strips fences (reuse `_strip_fences()`)
- Parses JSON, validates `{"lyrics": "<non-empty string>"}` only
- Retries up to `MAX_RETRIES` (reuse constant)
- Raises `SongGenerationError` on exhausted retries
- Does NOT touch or return any locked section data

**Implementation Notes:**
- New internal helper `_build_section_context(song: dict, target_key: str) -> str` — returns a formatted multiline string of all sections that are locked (excluding the target section itself), suitable for the `{locked_context}` placeholder. If no locked sections, returns an empty string or a minimal note.
- New internal helper `_validate_section_response(data: dict) -> None` — checks `"lyrics"` key is present and non-empty string.
- Reuse `_SECTION_ORDER` for friendly label lookup (e.g. `"verse_1"` → `"Verse 1"`).
- `section_key` must be one of `_REQUIRED_SECTIONS`; raise `ValueError` immediately if not.

**Relevant Context:**
- [`utils/ai_engine.py` lines 265–373](utils/ai_engine.py:265) — existing `generate_song()` pattern to follow
- [`utils/ai_engine.py` lines 108–119](utils/ai_engine.py:108) — `_build_prompt()` pattern
- [`utils/ai_engine.py` lines 71–77](utils/ai_engine.py:71) — `_REQUIRED_SECTIONS` constant

**Status:** `[x] done`

---

### Sub-Task 3 — Drift-Check Utility in `utils/ai_engine.py`

**Intent:** Add two pure utility functions that hash locked section lyrics before and after a Gemini call, so the caller can detect if any locked content was accidentally mutated. These functions are stateless and have no side effects.

**Expected Outcomes:**
- `snapshot_locked_sections(song: dict) -> dict[str, str]` — returns `{section_key: sha256_hex}` for every section where `locked == True`
- `assert_locked_sections_unchanged(song: dict, snapshot: dict) -> None` — re-hashes locked sections and raises `DriftError` (new exception) if any hash differs from the snapshot
- `DriftError` is a new public exception importable from `utils.ai_engine`
- Both functions handle an empty snapshot (no locked sections) gracefully — no-op

**Implementation Notes:**
- Hash input: `section["lyrics"].encode("utf-8")` — lyrics content only (not the full envelope, so lock metadata changes do not false-trigger)
- If a section present in `snapshot` is missing from the post-merge song, that also raises `DriftError`
- These two functions are also useful for the test harness

**Relevant Context:**
- [`utils/ai_engine.py` lines 40–46](utils/ai_engine.py:40) — existing `SongGenerationError` exception pattern

**Status:** `[x] done`

---

### Sub-Task 4 — Lock/Unlock Logic in `views/view_project.py`

**Intent:** Add `_toggle_lock(project, section_key, lock: bool)` — a pure state-mutation function that updates the section's lock fields, appends the correct timeline event, increments project version, and saves. No UI code in this function.

**Expected Outcomes:**
- `_toggle_lock(project, section_key, lock: bool) -> bool` mutates `project.song["sections"][section_key]`
- When `lock=True`: sets `locked=True`, `locked_at=now ISO-8601`, `locked_by="Human"`
- When `lock=False`: sets `locked=False`, `locked_at=None`, `locked_by=None`
- Appends `"section_locked"` or `"section_unlocked"` timeline event with `metadata={"section_key": section_key}`
- Increments `project.version`
- Calls `save_project(project)` atomically
- Returns `True` on success, `False` on save failure (error displayed by caller)

**Relevant Context:**
- [`views/view_project.py` line 131](views/view_project.py:131) — `_run_generation()` pattern for save + timeline + return bool
- [`utils/timeline.py` line 67](utils/timeline.py:67) — `append_event()` usage

**Status:** `[x] done`

---

### Sub-Task 5 — Section Regeneration Orchestration in `views/view_project.py`

**Intent:** Add `_run_section_regeneration(project, section_key) -> bool` — the orchestration function that calls the drift-check, calls `ai_engine.regenerate_section()`, merges the result, verifies post-merge drift, logs timeline, saves. No UI code in this function.

**Expected Outcomes:**
- Snapshots locked sections before the API call
- Calls `regenerate_section(section_key, project.song)` from `ai_engine`
- On `SongGenerationError`: displays error, returns `False`
- Grafts new lyrics into `project.song["sections"][section_key]["lyrics"]`
- Resets the regenerated section's provenance envelope:
  - `provenance = "ai_generated"` (was ai_generated before, stays ai_generated)
  - `last_edited_by = "AI"`
  - `edit_count` reset to `0`
  - `locked`, `locked_at`, `locked_by` — unchanged (section was unlocked when regenerated)
- Runs post-merge drift check with `assert_locked_sections_unchanged()`
- On `DriftError`: surface error to user, do NOT save (abort entirely), return `False`
- Appends `"section_regenerated"` timeline event with `metadata={"section_key": section_key, "model_id": ..., "prompt_version": "section_regen_v1"}`
- Increments `project.version`
- Calls `save_project(project)` atomically
- Returns `True` on success

**Relevant Context:**
- [`views/view_project.py` line 131](views/view_project.py:131) — `_run_generation()` pattern
- [`utils/ai_engine.py` lines 265–373](utils/ai_engine.py:265) — `generate_song()` reference

**Status:** `[x] done`

---

### Sub-Task 6 — Updated Section Card UI in `views/view_project.py`

**Intent:** Replace the static `_render_section_card()` with an interactive version that shows a lock/unlock toggle button and a "Regenerate" button (only on unlocked sections). Replace the Phase 3 placeholder banner with the actual controls.

**Expected Outcomes:**
- Each section card shows a 🔒/🔓 icon button inline with the section header
- Locked sections display a distinct locked state (e.g. amber left border, lock badge)
- Unlocked sections display a "↻ Regenerate" button below the lyrics
- Clicking lock toggles: calls `_toggle_lock()`, then `st.rerun()`
- Clicking Regenerate: calls `_run_section_regeneration()` with a `st.spinner`, then `st.rerun()`
- The Phase 3 placeholder banner at the bottom of the song is removed
- Locked sections' Regenerate button is absent (cannot regenerate a locked section)
- While a spinner is active for one section, other sections remain visible

**Implementation Notes:**
- Streamlit `st.button()` keys must be unique per section: `f"lock_{section_key}"`, `f"regen_{section_key}"`
- Use `st.columns()` inside the section card area to position the lock button and label side by side
- Keep all HTML rendering for the lyrics block; only the interactive controls are native Streamlit widgets (buttons live outside the HTML string)
- Locked state visual: change left border color to `#F59E0B` (amber) and add a `🔒 Locked` badge in the header

**Relevant Context:**
- [`views/view_project.py` lines 284–317](views/view_project.py:284) — existing `_render_section_card()` to extend
- [`views/view_project.py` lines 39–58](views/view_project.py:39) — `_SECTION_ORDER` and `_SECTION_COLORS`
- [`views/view_project.py` lines 520–538](views/view_project.py:520) — placeholder banner to remove

**Status:** `[x] done`

---

### Sub-Task 7 — Timeline Event Icon for New Event Types

**Intent:** Add icon mappings for the two new event types (`section_locked`, `section_unlocked`, `section_regenerated`) in the `_event_icon()` helper so the timeline renders meaningful icons.

**Expected Outcomes:**
- `_event_icon("section_locked")` returns `"🔒"`
- `_event_icon("section_unlocked")` returns `"🔓"`
- `_event_icon("section_regenerated")` returns `"↻"` or `"🔄"`
- No visual regression on existing event types

**Relevant Context:**
- [`views/view_project.py` line 114](views/view_project.py:114) — `_event_icon()` function to extend

**Status:** `[x] done`

---

### Sub-Task 8 — Test Coverage

**Intent:** Extend the test harness with targeted tests that verify the new Phase 3 logic: lock toggle, drift check, section regeneration merge, and error cases.

**Expected Outcomes:**
- `tests/test_phase3.py` (new file) with a done-bar style harness
- Test: lock a section → reload project → verify section.locked == True and timeline has `section_locked` event
- Test: unlock → verify section.locked == False and timeline has `section_unlocked` event
- Test: `snapshot_locked_sections()` returns correct hashes; mutating a locked section's lyrics triggers `DriftError`
- Test: `regenerate_section()` returns a non-empty string for a real Gemini call on one section (integration)
- Test: merge graft — verify only the target section changes; all other sections are byte-identical to before
- Test: post-merge drift check passes when no locked sections were modified

**Relevant Context:**
- [`tests/test_ai_engine.py`](tests/test_ai_engine.py) — existing test harness pattern (done-bar, exit code, real Gemini calls)

**Status:** `[x] done`

---

## JSON Changes

No schema version bump is required. All the fields needed for Phase 3 are already present in the section provenance envelope stamped by Phase 2:

```json
{
  "lyrics":         "...",
  "provenance":     "ai_generated",
  "locked":         false,
  "locked_at":      null,
  "locked_by":      null,
  "last_edited_by": "AI",
  "edit_count":     0
}
```

The only runtime change is that `locked`, `locked_at`, and `locked_by` will now be set to non-null values when a user locks a section.

---

## Merge Strategy

When `regenerate_section()` returns new lyrics for `section_key`:

1. Preserve the entire `project.song` dict (title, genre, style, mood, tempo, key, time_signature, lyrical_themes, generation_timestamp, model_used, song_schema_version) — unchanged.
2. Preserve all **other** sections in `project.song["sections"]` — byte-identical.
3. For the **target section only**:
   - Replace `lyrics` with the new string from Gemini
   - Reset `provenance = "ai_generated"`
   - Reset `last_edited_by = "AI"`
   - Reset `edit_count = 0`
   - Keep `locked = False` (was unlocked to allow regeneration)
   - Keep `locked_at = None`, `locked_by = None`
4. Stamp `project.song["generation_timestamp"]` with the current time (reflects last regeneration).

This is a targeted in-place graft — no full song replacement, no re-parsing of other sections.

---

## Drift-Check Strategy

**Why:** Gemini occasionally ignores instructions and may return content beyond the requested section. The drift check catches this before saving.

**Mechanism:**
1. **Before** the API call: `snapshot = snapshot_locked_sections(project.song)` — SHA-256 hash of `section["lyrics"]` for every locked section.
2. Build new lyrics via `regenerate_section()` — only touches one section.
3. Apply merge graft (step above).
4. **After** the merge: `assert_locked_sections_unchanged(project.song, snapshot)` — re-hash all locked sections; compare with snapshot.
5. If any hash differs → raise `DriftError` → UI surfaces an error, save is **not** called → song state is rolled back (never persisted).

**Roll-back:** Because the merge graft mutates `project.song` in memory but `save_project()` has not been called yet, simply not calling save is sufficient roll-back. The next `st.rerun()` will reload from disk (unchanged).

---

## Files to Modify

| File | Change Type | Description |
|---|---|---|
| `prompts/section_regen_v1.txt` | **New** | Targeted section-regeneration prompt template |
| `utils/ai_engine.py` | **Extend** | Add `regenerate_section()`, `snapshot_locked_sections()`, `assert_locked_sections_unchanged()`, `DriftError`, `_build_section_context()`, `_validate_section_response()` |
| `views/view_project.py` | **Extend** | Add `_toggle_lock()`, `_run_section_regeneration()`, update `_render_section_card()`, update `_event_icon()`, remove placeholder banner |
| `tests/test_phase3.py` | **New** | Phase 3 test harness |

**No changes needed to:** `utils/models.py`, `utils/storage.py`, `utils/timeline.py`, `utils/gemini_client.py`, `utils/presets.py`, `views/create_project.py`, `views/open_project.py`, `app.py`

---

## Step-by-Step Implementation Plan

Execute sub-tasks in this order (each is independently reviewable):

1. **Sub-Task 1** — Write `prompts/section_regen_v1.txt` (no code dependencies)
2. **Sub-Task 2** — Add `regenerate_section()` to `utils/ai_engine.py` (depends on prompt from step 1)
3. **Sub-Task 3** — Add drift-check utilities to `utils/ai_engine.py` (independent, can be done alongside step 2)
4. **Sub-Task 4** — Add `_toggle_lock()` to `views/view_project.py` (depends on timeline.py, storage.py — no new engine code needed)
5. **Sub-Task 5** — Add `_run_section_regeneration()` to `views/view_project.py` (depends on steps 2, 3, 4)
6. **Sub-Task 6** — Update section card UI in `views/view_project.py` (depends on steps 4, 5)
7. **Sub-Task 7** — Add timeline event icons in `views/view_project.py` (tiny, can bundle with step 6)
8. **Sub-Task 8** — Write `tests/test_phase3.py` (depends on steps 1–5)
