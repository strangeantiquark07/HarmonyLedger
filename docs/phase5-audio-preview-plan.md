# Phase 5 — Audio Preview Plan

## Top-Level Overview

**Goal:** Generate a spoken version of the chorus using gTTS and play it inside the Streamlit app.

**Scope:** A self-contained audio preview feature that:
- Adds one new utility module (`utils/audio_engine.py`) with a pure, side-effect-free generation function
- Adds minimal UI to the bottom of the left column in `views/view_project.py`
- Updates `app.py` to flip two cosmetic markers (Live Features badge + Build Progress dot)
- Adds `gTTS>=2.4` to `requirements.txt`
- Makes no schema changes to `Project` or the JSON file format
- Logs one new timeline event type: `"audio_preview_generated"`

**Approach:** Follows the same pattern as `utils/passport.py` (pure function returning bytes, no side effects) and `views/view_project.py`'s export-passport flow (button → spinner → bytes → Streamlit widget). gTTS generates an MP3 in memory via `io.BytesIO` — no file is written to disk. The audio bytes are held in Streamlit session state for the duration of the browser session and discarded on reload.

**Future extensibility — ambient music overlay:** The audio engine is structured so a second audio path can be added later. The public function signature accepts an optional `ambient` parameter (defaulting to `None`) that the initial implementation ignores. When ambient support is added, it fills that parameter without changing the call site in `view_project.py`.

**Non-goals:**
- No ambient music loop in Phase 5 (parameter reserved but unimplemented)
- No persistent audio files on disk
- No audio for any section other than the chorus
- No audio settings screen or voice selection UI in Phase 5
- No changes to `utils/models.py`, `utils/storage.py`, or the JSON schema

---

## Sub-Tasks

---

### Sub-Task 1 — Add gTTS dependency

**Intent:**
Register gTTS as a project dependency before any code that uses it is written, so the environment is in a known-good state from the start.

**Expected Outcomes:**
- `requirements.txt` contains `gTTS>=2.4`
- `gTTS` is importable in the venv

**Todo List:**
1. Append `gTTS>=2.4` to `requirements.txt`, after the `reportlab` line
2. Install it in the venv: `pip install "gTTS>=2.4"`
3. Verify: `python -c "from gtts import gTTS; print('OK')"`

**Relevant Context:**
- File to edit: `requirements.txt` (4 lines currently)
- Install target: `venv\Scripts\pip.exe install "gTTS>=2.4"`

**Status:** [x] done

---

### Sub-Task 2 — Create `utils/audio_engine.py`

**Intent:**
Implement the audio generation layer as a pure, side-effect-free utility module that mirrors the design of `utils/passport.py`. The caller in `views/view_project.py` is responsible for calling `st.audio()` on the returned bytes; this module has no Streamlit dependency.

**Expected Outcomes:**
- `utils/audio_engine.py` exists and is importable
- `generate_audio_preview(lyrics)` returns MP3 bytes for any non-empty lyrics string
- `AudioGenerationError` is raised (never a bare exception) when generation fails
- Passing an empty or whitespace-only string raises `AudioGenerationError` immediately (no gTTS call)
- The function accepts an `ambient=None` keyword argument (reserved, currently a no-op)
- No files are written to disk; all generation is in-memory via `io.BytesIO`

**Todo List:**
1. Create `utils/audio_engine.py` with a module-level docstring following the pattern established in `utils/passport.py` — document caller responsibilities, describe the "pure bytes" contract, note the `ambient` extension hook
2. Define `AudioGenerationError(Exception)` at the top of the module (same pattern as `SongGenerationError` in `utils/ai_engine.py`)
3. Define the single public function:
   ```
   generate_audio_preview(lyrics: str, lang: str = "en", ambient=None) -> bytes
   ```
   - Guard: raise `AudioGenerationError` immediately if `lyrics.strip()` is empty
   - Use `gTTS(text=lyrics, lang=lang)` to generate speech
   - Write to `io.BytesIO()` via `tts.write_to_fp(buf)`, then `buf.seek(0)`
   - Return `buf.read()` as bytes
   - Wrap all gTTS exceptions in `AudioGenerationError` so callers never need to import gTTS
   - The `ambient` parameter is accepted but not used; leave a `# TODO Phase 5+` comment
4. Add a module-level constant `_DEFAULT_LANG = "en"` for the voice language

**Relevant Context:**
- Pattern: `utils/passport.py` — pure function, `io.BytesIO`, returns bytes, no Streamlit imports
- Exception pattern: `utils/ai_engine.py` lines 61–78 (`SongGenerationError`, `DriftError`)
- `io.BytesIO` is already used in `utils/passport.py` line 270
- gTTS API: `from gtts import gTTS; tts = gTTS(text=lyrics, lang="en"); tts.write_to_fp(buf)`

**Status:** [x] done

---

### Sub-Task 3 — Add `audio_preview_generated` to the timeline event taxonomy

**Intent:**
Register the new event type in the `_event_icon()` helper so it renders with a speaker icon in the Creative Timeline, consistent with all other event types.

**Expected Outcomes:**
- `_event_icon("audio_preview_generated")` returns `"🔊"` instead of the fallback `"◈"`
- The `_DIRECTION_EVENT_TYPES` set in `utils/contribution.py` is evaluated: audio preview is a human creative decision and should be counted toward the direction score

**Todo List:**
1. In `views/view_project.py`, add `"audio_preview_generated": "🔊"` to the `icons` dict inside `_event_icon()` (lines 134–146)
2. In `utils/contribution.py`, add `"audio_preview_generated"` to the `_DIRECTION_EVENT_TYPES` frozenset — previewing audio is a deliberate human creative decision

**Relevant Context:**
- `_event_icon()` at `views/view_project.py` lines 132–146 — add one dict entry
- `_DIRECTION_EVENT_TYPES` at `utils/contribution.py` lines 33–40 — add one string to the frozenset
- All existing event types: `project_created`, `ai_generated`, `section_locked`, `section_unlocked`, `section_regenerated`, `human_edit`, `section_accepted`, `section_rejected`, `contribution_computed`, `passport_exported`

**Status:** [x] done

---

### Sub-Task 4 — Add Audio Preview UI to `views/view_project.py`

**Intent:**
Wire the audio engine into the view layer. The Preview Chorus button lives at the bottom of the left column, below the last section card, visible only when a song has been generated. The generated audio bytes are stored in session state (`"vp_audio_bytes"`) so the player persists across re-renders without re-calling gTTS.

**Expected Outcomes:**
- A "🔊 Preview Chorus" button appears below the section cards when a song has been generated
- Clicking the button calls `generate_audio_preview()`, stores bytes in session state, and renders `st.audio()`
- If the chorus lyrics are empty or missing, an informative `st.warning()` is shown and no gTTS call is made
- If gTTS fails, `st.error()` is shown with the error detail; the audio state key is cleared
- The `st.audio()` player persists across re-renders (bytes stored in session state, not regenerated on every run)
- A "✕ Clear Preview" button clears the audio from session state
- A `"audio_preview_generated"` timeline event is logged on every successful generation; `save_project()` is called
- The section card render loop is unchanged

**Todo List:**

1. Add session-state keys to `app.py`'s `_DEFAULTS` dict:
   - `"vp_audio_bytes": None` — holds the raw MP3 bytes (or None)
   - `"vp_audio_project_id": None` — the project_id these bytes belong to (stale-audio guard)

2. Add the import to `views/view_project.py`:
   ```python
   from utils.audio_engine import generate_audio_preview, AudioGenerationError
   ```

3. Add a helper function `_render_audio_preview(project)` in `views/view_project.py` (before `render()`):
   - Stale-audio guard: if `st.session_state.vp_audio_project_id != project.project_id`, clear `vp_audio_bytes` and update the id key — prevents showing another project's audio after navigation
   - Retrieve chorus lyrics: `project.song.get("sections", {}).get("chorus", {}).get("lyrics", "")`
   - If chorus lyrics are empty: show `st.warning("No chorus lyrics available for preview.")` and an early return
   - Render `_label("🔊 Audio Preview")`
   - If `st.session_state.vp_audio_bytes` is not None: render `st.audio(st.session_state.vp_audio_bytes, format="audio/mp3")` and a "✕ Clear Preview" secondary button; do not re-generate
   - If `st.session_state.vp_audio_bytes` is None: render the "🔊 Preview Chorus" button; when clicked:
     - Wrap gTTS call in `with st.spinner("Generating audio preview…")`
     - Call `generate_audio_preview(chorus_lyrics)`
     - On `AudioGenerationError`: `st.error(...)`, keep audio bytes as None
     - On success: store bytes in `st.session_state.vp_audio_bytes`, log timeline event, increment `project.version`, call `save_project(project, check_conflict=True)`, call `st.rerun()`

4. In `render()`, call `_render_audio_preview(project)` at the bottom of the `with left:` block, after the section card loop, guarded by `if has_song`

**Relevant Context:**
- Left column ends at `views/view_project.py` line 1158
- `has_song = bool(project.song.get("sections"))` is already computed at line 1115
- Pattern for button → spinner → result: `_run_generation()` lines 153–231
- Pattern for post-action save: every action helper in `view_project.py` ends with `save_project(project, check_conflict=True)`
- Pattern for session-state audio stale guard: mirrors the way `active_project_id` is checked in `open_project.py` lines 243–246
- `st.audio(data, format="audio/mp3")` is the correct Streamlit call; `data` can be raw bytes
- `_DEFAULTS` dict in `app.py` lines 24–33 — the place to add new session-state keys

**Status:** [x] done

---

### Sub-Task 5 — Update `app.py` cosmetic markers

**Intent:**
Flip the two sidebar indicators that show Phase 5 is live: the "Audio Preview" Live Features badge (currently grayed out) and the Build Progress strip (currently showing P5 as the current/next phase).

**Expected Outcomes:**
- Sidebar "Audio Preview" entry shows a green ✓ and white text (#D4D4D8) instead of the gray dot and gray text
- Build Progress strip shows P5 Audio with a green dot and ✓ (done), P6 Launch with the amber → (current)
- Version footer reads `Phase 5 · v0.5.0`

**Todo List:**
1. In `app.py` line 437, change `("Audio Preview", False)` to `("Audio Preview", True)`
2. In `app.py` line 459, change `_completed = 4` to `_completed = 5`
3. In `app.py` line 483, change `Phase 4 · v0.4.0` to `Phase 5 · v0.5.0`

**Relevant Context:**
- `app.py` line 437: Live Features list entry
- `app.py` line 459: `_completed = 4` — change to 5
- `app.py` line 483: version footer string
- The `_phases` list on line 458 already includes `"Audio"` as P5 — no change needed there

**Status:** [x] done

---

### Sub-Task 6 — Tests for `utils/audio_engine.py`

**Intent:**
Add a test file that validates the audio engine's contract without making any network calls or depending on gTTS actually producing valid audio output. Tests should be runnable offline and deterministically.

**Expected Outcomes:**
- `tests/test_phase5.py` exists and all tests pass with `python tests/test_phase5.py`
- Tests cover: empty lyrics rejection, AudioGenerationError wrapping, bytes return type, valid MP3 header, ambient=None no-op
- Tests do NOT test the gTTS network call (that is a third-party library concern)
- All tests are compatible with the existing standalone runner pattern (no pytest required)

**Todo List:**
1. Create `tests/test_phase5.py` following the exact structure of `tests/test_phase4.py`:
   - Module docstring matching the established pattern
   - `sys.path.insert(0, ...)` to ensure project root is on path
   - Individual test functions using plain `assert` statements
   - `_TESTS` list + `run_tests()` runner + `if __name__ == "__main__": sys.exit(...)` entry point
2. Tests to implement — **two categories**:

   **Offline tests** (no network — run in standalone runner by default):
   - `test_empty_lyrics_raises_audio_generation_error`: empty string raises `AudioGenerationError`
   - `test_whitespace_lyrics_raises_audio_generation_error`: whitespace-only raises `AudioGenerationError`
   - `test_audio_generation_error_is_exception`: `AudioGenerationError` is a subclass of `Exception`
   - `test_ambient_param_accepted`: function signature accepts `ambient=None` without `TypeError`
   - `test_lang_param_accepted`: function signature accepts `lang="en"` without `TypeError`

   **Live/integration tests** (network-dependent — excluded from the standalone runner, available via `pytest -m integration`):
   - `test_valid_lyrics_returns_bytes`: valid lyrics returns a `bytes` object
   - `test_valid_lyrics_returns_nonempty_bytes`: returned bytes are non-empty
   - `test_output_is_valid_mp3`: first 3 bytes of returned bytes are the MP3 frame-sync header (`b'\xff\xfb'` or ID3 `b'ID3'`)
   - `test_ambient_none_is_noop`: `generate_audio_preview("test lyrics", ambient=None)` returns bytes without error

3. In the standalone `run_tests()` runner: run only the offline tests; print a clear note that live tests are skipped ("Run `pytest -m integration` to include live gTTS tests").
4. Mark each live test with `@pytest.mark.integration` so `pytest -m integration` picks them up.

**Relevant Context:**
- Pattern: `tests/test_phase4.py` — standalone runner, `_TESTS` list, `run_tests()`, `sys.exit()`
- `utils/audio_engine.py` — the module under test
- gTTS may fail if network is unavailable; catch `AudioGenerationError` in those tests and pass with a skip message

**Status:** [x] done

---

## Data Flow Diagram

```
User clicks "🔊 Preview Chorus"
        │
        ▼
views/view_project.py: _render_audio_preview(project)
        │
        ├── Extract chorus_lyrics from project.song["sections"]["chorus"]["lyrics"]
        │
        ├── [Empty lyrics?] → st.warning() → return
        │
        ▼
utils/audio_engine.generate_audio_preview(chorus_lyrics)
        │
        ├── [Empty?] → raise AudioGenerationError
        │
        ├── gTTS(text=lyrics, lang="en")
        │
        ├── tts.write_to_fp(io.BytesIO())
        │
        └── return mp3_bytes
        │
        ▼
views/view_project.py: _render_audio_preview() (continued)
        │
        ├── st.session_state["vp_audio_bytes"] = mp3_bytes
        │
        ├── append_event(timeline, "audio_preview_generated", "Human", ...)
        │
        ├── project.version += 1
        │
        ├── save_project(project, check_conflict=True)
        │
        └── st.rerun()
        │
        ▼
Next render: st.audio(st.session_state["vp_audio_bytes"], format="audio/mp3")
```

---

## Error Handling Matrix

| Scenario | Detection Point | Handling |
|---|---|---|
| Chorus section missing from song | `_render_audio_preview()`, before button | `st.warning("No chorus lyrics available.")` — no button shown |
| Chorus lyrics empty string | `generate_audio_preview()` guard | Raises `AudioGenerationError`; caller shows `st.error()` |
| gTTS network failure | Inside `generate_audio_preview()`, wrapped | Raises `AudioGenerationError`; caller shows `st.error()` |
| gTTS import error (not installed) | On `import gTTS` at module level | Import error propagates; surface as `st.error()` in view |
| `save_project()` fails after generation | In `_render_audio_preview()`, try/except | `st.warning("Audio generated but could not save event.")` — audio still plays |
| User navigates away and back | Session-state stale-audio guard in `_render_audio_preview()` | If `vp_audio_project_id != project.project_id`, clear bytes silently |

---

## Temporary File Management

**No disk files are written.** gTTS output is piped directly into an `io.BytesIO` buffer via `tts.write_to_fp(buf)`. The resulting bytes are returned to the caller and stored in Streamlit session state. Session state is cleared when:
- The user explicitly clicks "✕ Clear Preview"
- The user navigates to a different project (stale-audio guard)
- The Streamlit server restarts (session state is not persisted)

This matches the pattern used in `utils/passport.py` (PDF bytes via `io.BytesIO`) and avoids all temp-file lifecycle management concerns.

---

## Files Changed Summary

| File | Change Type | Summary |
|---|---|---|
| `requirements.txt` | Edit | Add `gTTS>=2.4` |
| `utils/audio_engine.py` | **Create** | Pure audio generation module — `generate_audio_preview()` + `AudioGenerationError` |
| `utils/contribution.py` | Edit | Add `"audio_preview_generated"` to `_DIRECTION_EVENT_TYPES` |
| `views/view_project.py` | Edit | Add import, `_render_audio_preview()` helper, call site at bottom of left column, new event icon |
| `app.py` | Edit | Flip `Audio Preview` feature flag, `_completed` counter, version footer |
| `tests/test_phase5.py` | **Create** | Test suite for `utils/audio_engine.py` |

**Files NOT changed:** `utils/models.py`, `utils/storage.py`, `utils/ai_engine.py`, `utils/gemini_client.py`, `utils/passport.py`, `utils/timeline.py`, `utils/presets.py`, `views/create_project.py`, `views/open_project.py`, all prompt templates, all data files.
