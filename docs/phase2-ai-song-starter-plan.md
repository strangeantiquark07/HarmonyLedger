# Phase 2 — AI Song Starter: Architecture Plan

## Top-Level Overview

**Goal:** Replace the placeholder AI module with a Google Gemini-powered pipeline that turns
a user's vibe into a complete, validated song JSON and surfaces it in the Streamlit UI.

**Scope:** Two new utility modules (`ai_engine.py`, `gemini_client.py`), a versioned prompt
template (`prompts/song_starter_v1.txt`), a new project detail page (`views/view_project.py`),
navigation wiring in `app.py` and `open_project.py`, updated requirements, and a 10-vibe
test harness that proves the done bar.

**Approach:** `gemini_client.py` is a thin SDK wrapper. `ai_engine.py` owns everything else:
prompt loading, the API call, JSON parsing, validation, the retry loop, provenance stamping,
and the collaborator entry. The Streamlit page only calls `ai_engine.generate_song()` and
handles the result. Validation logic lives inside `ai_engine.py` — no separate validator module.
Prompt building is a single file-read inside `ai_engine.py` — no separate prompt-builder module.

**Model:** `gemini-flash-latest` (via `google-genai` SDK alias; stamped as `_MODEL_NAME` in `utils/gemini_client.py`)

**Done bar:** Ten completely different vibes in a row all return complete, valid JSON that
loads into the app with no manual correction.

---

## Final Folder Structure

```
HarmonyLedger/
│
├── utils/
│   ├── ai_engine.py        ← NEW: orchestrates generation; owns validation + retry
│   ├── gemini_client.py    ← NEW: thin Gemini SDK wrapper; returns raw text only
│   ├── models.py           (existing — unchanged)
│   ├── storage.py          (existing — unchanged)
│   ├── timeline.py         (existing — unchanged)
│   └── presets.py          (existing — unchanged)
│
├── prompts/
│   └── song_starter_v1.txt ← NEW: versioned prompt template with {vibe} and {genre}
│
├── tests/
│   └── test_ai_engine.py   ← NEW: 10-vibe done-bar harness
│
├── views/                  ← NOTE: final layout uses views/ (not pages/)
│   ├── create_project.py   (existing — unchanged)
│   ├── open_project.py     (existing — minor: card click navigates to view_project)
│   └── view_project.py     ← NEW: project detail + Generate button
│
├── app.py                  (existing — add "View Project" page route + session key)
├── .env                    (existing — GEMINI_API_KEY already present)
└── requirements.txt        (existing — add google-genai>=1.0)
```

---

## Complete Song Schema

Every successful generation must produce exactly these fields. All are required.

```json
{
  "title":              "string",
  "genre":              "string  (passed in from project, echoed back)",
  "style":              "string",
  "mood":               "string",
  "tempo":              "string  (e.g. 72 BPM, Slow, Moderate)",
  "key":                "string  (e.g. C major, A minor)",
  "time_signature":     "string  (e.g. 4/4, 3/4)",
  "generation_timestamp": "ISO-8601 string  (added by ai_engine, not Gemini)",
  "model_used":         "gemini-flash-latest   (added by ai_engine, not Gemini)",
  "sections": {
    "verse_1": { "lyrics": "..." },
    "chorus":  { "lyrics": "..." },
    "verse_2": { "lyrics": "..." },
    "bridge":  { "lyrics": "..." },
    "outro":   { "lyrics": "..." }
  }
}
```

**Notes:**
- `generation_timestamp` and `model_used` are stamped by `ai_engine.py` after validation —
  they are never requested from Gemini, so Gemini cannot produce them incorrectly.
- `genre` is already stored in `project.song["genre"]` (set at project creation). `ai_engine`
  passes it into the prompt and also writes it back into the returned dict, so the merged
  `project.song` always has a complete top-level block.
- The provenance envelope (`provenance`, `locked`, `locked_at`, `locked_by`,
  `last_edited_by`, `edit_count`) is added by `ai_engine` to every section after validation —
  again, never requested from Gemini.

---

## Module Responsibilities

| Module | Single Responsibility |
|---|---|
| `utils/gemini_client.py` | Load API key, call Gemini SDK, return raw text. Raises `GeminiAPIError` on any SDK / network failure. Nothing else. |
| `utils/ai_engine.py` | Read prompt template → build prompt → call `gemini_client` → parse JSON → validate all required fields → add provenance envelope → stamp `generation_timestamp` and `model_used` → retry up to MAX_RETRIES → raise `SongGenerationError` on final failure → return clean `song_dict`. |
| `prompts/song_starter_v1.txt` | Versioned prompt text. Contains role instruction, JSON-only constraint, full schema, `{vibe}` and `{genre}` placeholders, and a one-shot example. Editable without touching Python. |
| `pages/view_project.py` | Render project detail. Show Generate button if no sections exist. Call `ai_engine.generate_song()`, merge result into `project.song`, log timeline event, save project. Render song sections once generated. |
| `tests/test_ai_engine.py` | Run 10 different vibes through `ai_engine.generate_song()`. Assert each returns a complete, valid dict. Print `[PASS]` / `[FAIL]` per vibe. Standalone script. |

---

## Sub-Tasks

---

### Sub-Task 1 — Add `google-genai` to requirements

**Intent**
Add the Google Gemini SDK as a project dependency so the rest of the build can import it.

**Expected Outcomes**
- `requirements.txt` contains `google-genai>=1.0`.
- `pip install -r requirements.txt` installs without errors.

**Todo List**
1. Open `requirements.txt`.
2. Append `google-genai>=1.0` on a new line.

**Relevant Context**
- `requirements.txt` currently contains `streamlit>=1.35` and `python-dotenv>=1.0`.
- **Note:** The SDK used is `google-genai` (new `genai.Client` API), not the older
  `google-generativeai` (`GenerativeModel` API). The module is imported as
  `from google import genai` and called via `genai.Client(api_key=...)`.

**Status:** [x] done

---

### Sub-Task 2 — Create the versioned prompt template

**Intent**
Encode the vibe-to-song instruction as a plain-text file so it can be iterated in Ask mode
without touching Python. The versioned filename (`song_starter_v1.txt`) means a Phase 3
regeneration template (`song_regen_v1.txt`) slots in alongside it cleanly.

**Expected Outcomes**
- `prompts/song_starter_v1.txt` exists and contains:
  - A professional songwriter role instruction.
  - A strict JSON-only output constraint (no prose, no markdown fences, no explanation).
  - The exact required schema: `title`, `genre`, `style`, `mood`, `tempo`, `key`,
    `time_signature`, and `sections` with `verse_1`, `chorus`, `verse_2`, `bridge`, `outro`.
  - `{vibe}` and `{genre}` placeholders that `ai_engine.py` fills with `str.format()`.
  - A one-shot example output so Gemini has a structural anchor.
- Note: `generation_timestamp` and `model_used` are **not** in the prompt — they are stamped
  by `ai_engine.py` after a successful response.

**Relevant Context**
- Gemini tends to wrap JSON in markdown fences; the prompt must explicitly forbid this.
- `ai_engine.py` will strip fences defensively as a secondary measure.
- Template is read from `prompts/song_starter_v1.txt` relative to the project root.

**Status:** [x] done

---

### Sub-Task 3 — Build `utils/gemini_client.py`

**Intent**
Isolate all Google Gemini SDK knowledge into one thin module. Nothing outside this file
imports the SDK. Swapping models in the future is a one-line change here.

**Expected Outcomes**
- `utils/gemini_client.py` exists with:
  - `GeminiAPIError(Exception)` — raised on any SDK or network failure.
  - `call_gemini(prompt: str) -> str` — the only public function.
    - Loads `.env` via `python-dotenv`.
    - Reads `GEMINI_API_KEY` from environment.
    - Initialises `genai.Client(api_key=...)` from the `google-genai` SDK.
    - Calls `client.models.generate_content(model=_MODEL_NAME, contents=prompt, config=...)`.
    - Returns `response.text`.
    - Catches all SDK exceptions; re-raises as `GeminiAPIError` with descriptive message.

**Relevant Context**
- `.env` already contains `GEMINI_API_KEY`.
- SDK package: `google-genai>=1.0`; imported as `from google import genai`.
- Model name constant: `"gemini-flash-latest"` (alias kept stable by Google).
- Follow the project convention of private helpers prefixed with `_`.

**Status:** [x] done

---

### Sub-Task 4 — Build `utils/ai_engine.py`

**Intent**
Own the complete generation pipeline. This is the only module the Streamlit page calls.
It reads the prompt template, calls `gemini_client`, validates the response, adds
provenance/metadata fields, and retries on failure.

**Expected Outcomes**
- `utils/ai_engine.py` exists with:
  - `SongGenerationError(Exception)` — raised when all retries are exhausted.
  - `MAX_RETRIES = 3` module-level constant.
  - `_PROMPT_TEMPLATE_PATH` module-level constant pointing to `prompts/song_starter_v1.txt`.
  - `generate_song(vibe: str, genre: str) -> dict` — the only public function.

**`generate_song` behaviour:**
1. Read `prompts/song_starter_v1.txt`; substitute `{vibe}` and `{genre}` via `str.format()`.
2. Call `gemini_client.call_gemini(prompt)` → raw text.
3. Strip markdown fences (` ```json … ``` ` or ` ``` … ``` `) from raw text.
4. Parse JSON; on `json.JSONDecodeError` → treat as validation failure.
5. Validate all required top-level fields: `title`, `genre`, `style`, `mood`, `tempo`,
   `key`, `time_signature`. Each must be a non-empty string.
6. Validate `sections` is a dict containing exactly the keys:
   `verse_1`, `chorus`, `verse_2`, `bridge`, `outro`.
7. Validate each section has a non-empty `"lyrics"` string.
8. On any validation failure or `GeminiAPIError`: retry. After `MAX_RETRIES` total
   attempts raise `SongGenerationError` with the last error detail.
9. On success:
   - Add provenance envelope to each section:
     `provenance="ai_generated"`, `locked=False`, `locked_at=None`,
     `locked_by=None`, `last_edited_by="AI"`, `edit_count=0`.
   - Stamp `generation_timestamp` with `datetime.now().isoformat()`.
   - Stamp `model_used = "gemini-flash-latest"` (the `_MODEL_NAME` constant in `ai_engine.py`).
   - Return the complete `song_dict`.

**Forward-compatibility:**
- Function signature should accept an optional `locked_sections: dict = None` parameter,
  unused in Phase 2 but reserved for Phase 3 targeted regeneration. Document in docstring.

**Relevant Context**
- Imports: `gemini_client` (same package), `json`, `datetime`, `pathlib.Path`, `os`.
- Path resolution: use `Path(__file__).parent.parent / "prompts" / "song_starter_v1.txt"`
  so the path is correct regardless of where the script is run from.
- Provenance values defined in `utils/models.py` comments (lines 77–89).

**Status:** [x] done

---

### Sub-Task 5 — Create `pages/view_project.py`

**Intent**
Provide a dedicated project detail page where the user generates a song, views the result,
and will eventually lock/regenerate sections (Phase 3). Separating this from `open_project.py`
now makes Phase 3 additions clean and contained.

**Expected Outcomes**
- `views/view_project.py` renders:
  - **Header row:** project name, status badge, genre badge.
  - **Vibe card:** the user's original vibe text.
  - **If no song sections yet:**
    - A "Generate Song" button.
    - On click: spinner → calls `ai_engine.generate_song(project.vibe, project.song["genre"])`.
    - On success: merges `song_dict` into `project.song` (preserving `genre`), sets
      `project.status = "In Progress"`, increments `project.version`, appends
      `"ai_generated"` timeline event with `metadata = {"model_id": "gemini-flash-latest",
      "prompt_version": "song_starter_v1", "section_count": 5}`, adds Gemini collaborator
      entry to `project.collaborators` (if not already present), calls `save_project(project)`.
    - On failure: `st.error(str(e))`.
  - **If song sections exist:**
    - Song metadata row: title, mood, tempo, key, time_signature, style.
    - Section cards for `verse_1`, `chorus`, `verse_2`, `bridge`, `outro` (in order).
    - Each card shows the section name and lyrics.
    - Provenance tag on each card ("AI Generated").
  - **Back button:** sets `st.session_state.active_project_id = None`, sets
    `st.session_state.page = "Open Project"`, calls `st.rerun()`.
- Reads project using `st.session_state.active_project_id` (existing session key — do NOT
  introduce a new `current_project_id` key).

**Relevant Context**
- Session state key is `active_project_id` (set in `app.py` `_DEFAULTS` line 25).
- `append_event` from `utils/timeline.py`.
- `save_project`, `load_project` from `utils/storage.py`.
- `ai_engine.generate_song` from `utils/ai_engine.py`.
- Match dark-theme CSS from `app.py` (`#18181B` cards, `#2D2D31` borders, `#FAFAFA` text).
- The `_label()` helper pattern (uppercase section labels) is established in
  `views/create_project.py` and `views/open_project.py` — replicate it here.
- The collaborator entry shape is defined in `utils/models.py` lines 122–135:
  `collaborator_id` (uuid4), `name`, `role="ai_model"`, `model_id`, `contribution_pct=None`.

**Status:** [ ] pending

---

### Sub-Task 6 — Wire navigation in `app.py` and `open_project.py`

**Intent**
Connect the project library to the new detail page so clicking a project card navigates
to `view_project.py` instead of expanding an inline detail panel.

**Expected Outcomes**
- **`app.py` changes:**
  - Import `views.view_project as view_project_page`.
  - Add `"View Project"` to `_VALID_PAGES` set (line 470).
  - Add routing: `elif st.session_state.page == "View Project": view_project_page.render()`.
  - No new session state keys needed — `active_project_id` already exists.
  - Update sidebar "Build Progress" `_completed = 2` (Phase 2 done).
  - Update sidebar version footer to `"Phase 2 · v0.2.0"`.
  - Update "Coming in Phase 2+" label to "Coming in Phase 3+".
  - Remove "🤖  AI Studio" from the coming-soon list (it now exists as view_project).
- **`open_project.py` changes:**
  - On project card click (line 243): after setting `active_project_id`, also set
    `st.session_state.page = "View Project"` before `st.rerun()`.
  - This means the existing inline detail view block (lines 246–end) in `open_project.py`
    becomes dead code. Keep it for now — remove in a later cleanup phase.

**Relevant Context**
- Exact router pattern in `app.py` lines 470–477.
- Card click handler in `open_project.py` lines 242–244.
- `_VALID_PAGES` set at `app.py` line 470.
- Read both files carefully before editing — the inline detail view in `open_project.py`
  must not be broken for projects that may still navigate to it directly.

**Status:** [ ] pending

---

### Sub-Task 7 — Write `tests/test_ai_engine.py` (done-bar harness)

**Intent**
Prove the done bar: 10 different vibes → 10 valid, complete song dicts, no exceptions,
no manual correction. This is the official acceptance gate for Phase 2.

**Expected Outcomes**
- `tests/test_ai_engine.py` defines 10 vibe strings paired with genres, spanning
  all 10 genres in `utils/presets.py`:
  Indie Folk, Dark R&B, Alt-Pop, Neo-Soul, Chillwave,
  Trap Soul, Ethereal Pop, Jazz Noir, Orchestral, Afrobeats.
- For each vibe:
  - Calls `ai_engine.generate_song(vibe, genre)`.
  - Asserts: no exception raised.
  - Asserts `"title"` is a non-empty string.
  - Asserts `"sections"` contains exactly `verse_1`, `chorus`, `verse_2`, `bridge`, `outro`.
  - Asserts each section has a non-empty `"lyrics"` string.
  - Asserts each section has `"provenance" == "ai_generated"` and `"locked" == False`.
  - Asserts `"generation_timestamp"` and `"model_used"` are present and non-empty.
  - Prints `[PASS] Vibe N — <title>` or `[FAIL] Vibe N — <error>`.
- Final summary line: `N/10 passed`.
- Exits with code `0` if all pass, `1` if any fail.
- Runnable standalone: `python tests/test_ai_engine.py`.

**Relevant Context**
- No test framework needed — plain `assert` + `print` + `sys.exit`.
- Must load `.env` before running (or set `GEMINI_API_KEY` in the environment).
- The harness exercises the real API — it is an integration test, not a unit test.

**Status:** [ ] pending

---

## Data Flow

```
User vibe (str) + project.song["genre"] (str)
  │
  ▼  ai_engine.generate_song(vibe, genre)
  │
  ├─▶ Read prompts/song_starter_v1.txt
  │    str.format(vibe=vibe, genre=genre) → prompt_str
  │
  ├─▶ gemini_client.call_gemini(prompt_str)
  │    → raw_text (possibly with markdown fences)
  │
  ├─▶ Strip fences → parse JSON → validate all required fields
  │    [on failure] retry up to MAX_RETRIES=3
  │    [all retries fail] raise SongGenerationError
  │
  ├─▶ Add to each section: provenance envelope
  ├─▶ Stamp: generation_timestamp, model_used
  │
  └─▶ return song_dict (clean, complete)

  Back in view_project.py:
  ├─▶ project.song = {**song_dict, "genre": project.song["genre"]}
  ├─▶ project.status = "In Progress"
  ├─▶ project.version += 1
  ├─▶ append_event("ai_generated", metadata={model_id, prompt_version, section_count})
  ├─▶ project.collaborators ← add Gemini model entry (if not already present)
  └─▶ save_project(project)  ← atomic write
```

---

## Validation Rules (inside `ai_engine.py`)

| Check | Condition | Action on failure |
|---|---|---|
| JSON parseable | `json.loads()` succeeds | Retry |
| Top-level string fields | `title`, `genre`, `style`, `mood`, `tempo`, `key`, `time_signature` all non-empty str | Retry |
| sections present | `sections` is a dict | Retry |
| sections completeness | all of `verse_1`, `chorus`, `verse_2`, `bridge`, `outro` present | Retry |
| lyrics non-empty | each section's `"lyrics"` is a non-empty str | Retry |
| GeminiAPIError | raised by `gemini_client` | Retry |
| All retries exhausted | after MAX_RETRIES=3 attempts | Raise `SongGenerationError` |

---

## Retry Strategy

- `MAX_RETRIES = 3` (total attempts, including the first).
- Retry on: `json.JSONDecodeError`, `ValidationError` (internal), `GeminiAPIError`.
- No back-off — hackathon scope.
- After MAX_RETRIES: raise `SongGenerationError(f"Generation failed after {MAX_RETRIES} attempts: {last_error}")`.

---

## Future Compatibility

| Future phase | How Phase 2 accommodates it |
|---|---|
| Phase 3 — Targeted regeneration | `generate_song` accepts `locked_sections: dict = None` (unused, documented). A Phase 3 regeneration prompt can be added as `prompts/song_regen_v1.txt` with zero changes to the engine interface. |
| Phase 3 — Drift check | Every section gets `locked=False` and the full provenance envelope in Phase 2 so Phase 3 has all the fields it needs immediately. |
| Phase 4 — Contribution tracking | The `ai_generated` timeline event carries `model_id` and `prompt_version` in `metadata`. The contribution formula reads these directly. |
| Phase 4 — Creative Passport | The Gemini collaborator entry (with `model_id`) is written to `project.collaborators` on first generation so the Passport can reference exactly which model wrote the song. |
| Phase 4 — Passport model reference | `model_used` is stored directly in `project.song` so `open_project.py` and future Passport code can display it without re-walking the timeline. |
