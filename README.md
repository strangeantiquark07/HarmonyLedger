# HarmonyLedger

**The Creative Passport for Human–AI Songwriting**

HarmonyLedger is an AI songwriting studio built on a single principle: **the creator stays the author**. It doesn't just generate a song — it documents who wrote what, so a human can prove they stayed the author even with an AI co-writing alongside them. Every generation, lock, edit, and regeneration is logged in an append-only timeline. When the song is finished, the app exports a **Creative Passport**: a signed PDF with the full timeline, a human-vs-AI contribution split, and a transparency statement the creator can attach to their work.

---

## Table of Contents

- [The Problem](#the-problem)
- [Solution](#solution)
- [Challenge Theme](#challenge-theme)
- [Features](#features)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [Contribution Methodology](#contribution-methodology)
- [Responsible AI & Authorship](#responsible-ai--authorship)
- [Built With IBM Bob](#built-with-ibm-bob)
- [License](#license)

---

## The Problem

AI can write a whole song from a one-line prompt now. That's a problem for creators: when a musician submits AI-assisted work, they can't cleanly show which parts are theirs. Rights bodies, labels, sync-licensing buyers, and collaborators keep asking *"how much of this did a human actually write?"* — and there's no honest way to answer.

Most AI songwriting tools also regenerate the **entire** song on every click, which turns the creator into a passive selector rather than an author.

HarmonyLedger is built to close that **trust gap**, not just to generate more songs.

---

## Solution

HarmonyLedger treats the AI as a co-writer that **only ever touches what it is explicitly asked to touch**. Every action — human or AI — is recorded. The creator stays in control at every step: they can lock sections they love, edit lyrics directly, regenerate only what they don't like, and explicitly accept or reject AI drafts. The finished song exports as a Creative Passport: a PDF document that proves authorship.

The foundation is simple: **everything is a view of one JSON file**. The song, the timeline, the contribution split, and the exported passport are all just different representations of the same source of truth. This keeps the architecture honest and debuggable.

---

## Challenge Theme

**Reimagine Creative Industries with AI** — HarmonyLedger addresses the **authorship trust crisis** created by generative AI in music. It doesn't just generate content; it documents collaboration. This is the gap the creative industry actually faces right now: not a shortage of generated songs, but a shortage of tools that let creators prove their creative contribution.

---

## Features

### Core Workflow
- 🎼 **Vibe-to-song generation** — describe a mood, genre, or feeling and Google Gemini returns a complete structured song: title, verse/chorus/bridge/outro, mood, tempo, musical key, time signature, style, and lyrical themes.
- 🌍 **Multilingual generation** — generate songs in 8 languages: English, Hindi, Marathi, Telugu, Tamil, Spanish, French, and Japanese. The title and all lyrics are written in the selected language; metadata (genre, tempo, key) always stays in English.
- 🎯 **Genre presets** — 10 one-click genre presets (Indie Folk, Dark R&B, Alt-Pop, Neo-Soul, Chillwave, Trap Soul, Ethereal Pop, Jazz Noir, Cinematic Orchestral, Afrobeats) pre-fill the vibe field. Edit freely after.
- ✦ **Vibe modifiers** — 10 toggleable texture tags (Rain/Storm, Golden Hour, Heartbreak, Euphoric, etc.) that append descriptors to the vibe rather than replacing it.

### Authorship & Control
- 🔒 **Lock & regenerate** — lock the sections you're happy with and regenerate only the one you're not. A SHA-256 drift check verifies that every locked section is byte-for-byte identical after regeneration, and rejects the result (without saving) if anything frozen changed.
- ✏️ **Inline human editing** — edit any unlocked section's lyrics directly inside the app. Provenance tracks the transition from `ai_generated` to `ai_then_human` automatically.
- ✓✕ **Accept / Reject** — explicitly accept an AI draft (logs a human decision) or reject it to trigger immediate targeted regeneration. Accept is idempotent — repeated clicks don't inflate the authorship score.

### Ownership Documentation
- 📜 **Unified creative timeline** — every action logged in one append-only, sequence-numbered timeline: project_created, ai_generated, section_locked, section_unlocked, section_regenerated, human_edit, section_accepted, section_rejected, contribution_computed, passport_exported, audio_preview_generated.
- 📊 **Contribution dashboard** — a deterministic human-vs-AI split computed directly from the timeline. Two numbers: section-authorship split (based on provenance) and creative-direction score (based on steering decisions). Stale-aware: auto-refreshes when the timeline changes.
- 🪪 **Creative Passport export** — a downloadable, watermarked PDF with the song's full timeline, contribution split, a transparency statement, and a SHA-256 integrity marker. The integrity marker is a hash of the canonical authorship record (provenance, timeline, contribution data, and export identity) computed at export time and printed on the provenance stamp. Human-approved statement text is never overwritten on re-export. The hash is an integrity marker for the recorded data — not a blockchain record or legal certification.

### Audio & Project Management
- 🔊 **Audio preview** — generate a spoken preview of any song section (not just chorus) using Google Text-to-Speech. Cached in session; downloadable as a named `.mp3` file.
- 📂 **Project library** — searchable grid of all projects with status badges, genre tags, event counts, and relative timestamps. Supports project deletion with a confirmation step.

### Reliability & Storage
- ⚡ **Atomic JSON writes** — every save uses a temp-file + `os.replace()` for atomic persistence. No half-written files on crash or disk-full.
- 🔄 **Schema migrations** — old project files are automatically migrated when opened. Migration history is recorded in the file.
- 🔐 **Conflict detection** — version-based concurrent-edit detection prevents one session from silently overwriting another session's save.

---

## How It Works

Everything in HarmonyLedger is a view of **one JSON file per project**. The song, the timeline, the contribution split, and the exported passport all read from the same source. That keeps the app debuggable and keeps the app layer cleanly separated from the AI layer.

### The Core Loop

1. **Create a project** — choose a name, language, and vibe (free text, genre preset, or vibe modifier mix).
2. **Generate** — Gemini returns a complete structured song (title, 5 sections, metadata). A provenance envelope is added to every section: `ai_generated`, `locked: false`, `edit_count: 0`.
3. **Lock** — lock the sections you're happy with. The lock state, timestamp, and actor are stored per section.
4. **Regenerate** — click Regenerate on an unlocked section. Only that section's lyrics change; a drift check verifies all locked sections are byte-identical before saving.
5. **Edit** — click Edit on any unlocked section to write your own lyrics. Provenance transitions to `ai_then_human`. The `edit_count` increments.
6. **Accept / Reject** — explicitly accept an AI draft (records a human decision) or reject it (triggers immediate regeneration).
7. **Review** — the timeline shows every action; the contribution dashboard shows the live human/AI split and direction score.
8. **Export** — click Export Passport to download a signed PDF with the complete authorship record.
9. **Preview** — generate a spoken TTS preview of any section; download as `.mp3`.

### Drift Check

When a section is regenerated, HarmonyLedger:
1. Takes SHA-256 hashes of all currently-locked sections' lyrics **before** the API call.
2. Calls Gemini for the target section only.
3. Grafts the new lyrics into the project (in memory only — not yet saved).
4. Re-hashes all locked sections and compares against the pre-call snapshot.
5. If any locked section's hash differs → raises `DriftError` → the save is **aborted entirely** → the in-memory graft is discarded on the next page reload. Nothing is ever persisted if drift is detected.

---

## Architecture

```
project.json  ─┬─▶ Song View        (title, sections, mood, tempo, key, lyrical_themes)
               ├─▶ Timeline View    (generate / lock / regen / edit / accept / reject / export)
               ├─▶ Contribution     (section-authorship split + creative-direction score)
               └─▶ Creative Passport (exported PDF — derived view, never stored back)
```

All views read from the same project JSON, so they can never disagree with each other.

### Project JSON Shape (key fields)

```json
{
  "project_id":      "uuid4",
  "name":            "string",
  "vibe":            "string",
  "language":        "English | Hindi | Marathi | Telugu | Tamil | Spanish | French | Japanese",
  "status":          "Draft | In Progress | Complete",
  "version":         1,
  "schema_version":  2,
  "song": {
    "title": "string", "genre": "string", "style": "string",
    "mood": "string",  "tempo": "string", "key": "string",
    "time_signature": "string", "lyrical_themes": ["string"],
    "model_used": "string", "generation_timestamp": "ISO-8601",
    "sections": {
      "verse_1|chorus|verse_2|bridge|outro": {
        "lyrics": "string",
        "provenance": "ai_generated | human_written | ai_then_human",
        "locked": false,
        "locked_at": null,
        "locked_by": null,
        "last_edited_by": "AI | Human",
        "edit_count": 0
      }
    }
  },
  "timeline":      [{ "seq": 0, "event_type": "...", "actor": "...", "timestamp": "...", "metadata": {} }],
  "contribution":  { "human_pct": 0.0, "ai_pct": 0.0, "direction_score": 0.0, "computed_at": "...", "methodology_version": 1 },
  "passport":      { "exported_at": null, "export_format": null, "transparency_statement": "", "watermark_id": null },
  "collaborators": [{ "name": "Google Gemini", "role": "ai_model", "model_id": "...", "contribution_pct": null }]
}
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| App / UI | Streamlit (Python) |
| AI — song generation | Google Gemini API (`gemini-flash-latest`) |
| Text-to-Speech | gTTS (Google Text-to-Speech) |
| PDF export | ReportLab + Unicode Noto Sans fonts (bundled in `assets/fonts/`) |
| Unicode font — Latin (English, Spanish, French) | Noto Sans TTF (bundled) |
| Unicode font — Devanagari (Hindi, Marathi) | Noto Sans Devanagari TTF (bundled) |
| Unicode font — Telugu | Noto Sans Telugu TTF (bundled) |
| Unicode font — Tamil | Noto Sans Tamil TTF (bundled) |
| Unicode font — Japanese | HeiseiKakuGo-W5 (ReportLab built-in CIDFont) |
| Storage | Single JSON file per project (atomic writes via `os.replace`) |
| AI — coding assistant used to build this project | IBM Bob (Plan / Ask / Agent modes) |
| API key management | python-dotenv |

---

## Getting Started

### Prerequisites
- Python 3.10+
- A Google AI Studio account with a free Gemini API key
- `pip` for dependency installation

### Installation

```bash
git clone https://github.com/your-org/harmonyledger.git
cd harmonyledger
pip install -r requirements.txt
```

### Unicode Font Setup

The Creative Passport PDF uses bundled Noto Sans font files for Unicode support. These files are included in the repository under `assets/fonts/` and require no separate download or system installation. The full set of bundled fonts:

| File | Script / Languages |
|---|---|
| `NotoSans-Regular.ttf` / `NotoSans-Bold.ttf` | Latin — English, Spanish, French |
| `NotoSansDevanagari-Regular.ttf` / `NotoSansDevanagari-Bold.ttf` | Devanagari — Hindi, Marathi |
| `NotoSansTelugu-Regular.ttf` / `NotoSansTelugu-Bold.ttf` | Telugu |
| `NotoSansTamil-Regular.ttf` / `NotoSansTamil-Bold.ttf` | Tamil |
| *(HeiseiKakuGo-W5 — ReportLab built-in)* | Japanese (CJK — no font file needed) |

If you are deploying HarmonyLedger in an environment where the `assets/fonts/` directory is stripped, re-run the font download script:

```bash
python scripts/download_fonts.py
```

Or download each TTF from [Google Fonts](https://fonts.google.com/noto) and place them in `assets/fonts/`.

### Configuration

Create a `.env` file in the project root with your Gemini API key:

```
GEMINI_API_KEY=your_api_key_here
```

### Run the app

```bash
streamlit run app.py
```

The app opens in your browser at `http://localhost:8501`.

---

## Usage

1. **New Project** — click "＋ New Project" in the sidebar.
2. **Choose a language** — English is the default; select Hindi, Spanish, or any of the 8 supported languages.
3. **Pick a genre preset** (optional) — one click fills the vibe field. Edit it freely afterward.
4. **Add vibe modifiers** (optional) — toggle texture tags to append descriptors to the vibe.
5. **Enter a project name** and click **Create Project →** — the project is saved immediately.
6. **Generate Song** — click the Generate button in the workspace. Gemini returns a structured song in a few seconds.
7. **Review sections** — each section shows provenance (AI Generated), edit count, and lock state.
8. **Lock** any section you're happy with (🔒 button).
9. **Regenerate** an unlocked section (↻ button) — only that section changes; all locked sections are verified unchanged.
10. **Edit** a section manually (✏️ button) — type your changes and save. Provenance updates automatically.
11. **Accept** (✓) to record approval of an AI draft, or **Reject** (✕) to log the rejection and trigger immediate regeneration.
12. **Check the timeline and contribution dashboard** in the right panel as you go.
13. **Export your Creative Passport** — click "🛂 Export Passport" to download a PDF with the full authorship record.
14. **Preview audio** — click "🔊 Preview [Section]" to generate a spoken TTS preview. Use the radio selector to choose any section. Download the audio as `.mp3`.

---

## Contribution Methodology

Contribution is computed **deterministically from the timeline log**, never estimated by hand. Two numbers come out of it:

**Section-authorship split** — each section is tagged at all times:
- `human_written` → counts 100% human
- `ai_generated` (untouched) → counts 100% AI
- `ai_then_human` (AI-generated then human-edited) → counts 50% human / 50% AI

The five sections are averaged to produce the headline human vs. AI percentage.

**Creative-direction score** — every human steering decision counts: `section_locked`, `section_unlocked`, `section_regenerated` (requesting a new draft is a decision), `human_edit`, `section_accepted`, `section_rejected`, and `audio_preview_generated`. These are expressed as a percentage of all timeline events. Steering the AI is itself a form of authorship.

Both numbers come from the **same timeline**, so the dashboard and the exported Passport can never disagree with each other.

---

## Responsible AI & Authorship

HarmonyLedger is built around a specific principle: **the human is always the author, even when the AI writes the words**.

This isn't just a claim — it's enforced by the mechanics:

- **The AI only touches what it is explicitly asked to touch.** Locked sections are cryptographically verified (SHA-256 drift check) before every save. If Gemini accidentally modifies a locked section, the result is rejected and nothing is persisted.
- **Every action is logged.** There is no "undo" that erases history. The append-only timeline is the source of truth for authorship claims.
- **The contribution methodology is deterministic, not estimated.** The human/AI split is computed from provenance fields and timeline events with a documented formula (methodology_version: 1). Old exports stay valid if the formula changes.
- **Human-approved text is never overwritten.** If a creator writes their own transparency statement, re-exporting the Passport always preserves their wording.
- **The AI is listed as a collaborator, not hidden.** The Gemini model entry (including which model version was used) is stored in the project's collaborators list and appears in the exported Passport.

The application's core thesis: *the act of directing, locking, editing, accepting, and rejecting AI output is itself creative authorship*. HarmonyLedger makes that authorship visible, documented, and exportable.

---

## Built With IBM Bob

This project was built with **IBM Bob**, IBM's agentic coding assistant, acting as the primary software engineer across the full development lifecycle. The human directed and reviewed; Bob planned, built, tested, and documented.

HarmonyLedger uses two distinct AI systems on two different layers — keeping them separate is what makes the submission coherent:

| Layer | System | Role |
|---|---|---|
| **The builder** | IBM Bob | Builds the application — architects, codes, generates test suites, writes docs. This is what the challenge means by "built using IBM Bob." |
| **The runtime** | Google Gemini API | The model inside the shipped app. Turns a creator's vibe into a structured song and regenerates sections on request. |

### What Bob Did Across the SDLC

| Stage | What Bob Did |
|---|---|
| Planning (Plan Mode) | Designed the application architecture, stress-tested the JSON schema for extensibility, planned the AI integration workflow and prompt template, designed the regeneration and drift-check pipeline |
| Development (Agent Mode) | Built the Google Gemini API integration and retry logic, the section lock/unlock system, the SHA-256 drift check, the JSON merge strategy, the inline human edit feature, the accept/reject pipeline, the unified timeline logger, the contribution dashboard, the Creative Passport PDF (ReportLab), the Unicode font support for all 8 languages, the audio preview engine (gTTS), the multilingual generation system, the canonical authorship record and SHA-256 integrity hash, the genre presets and vibe modifiers |
| Testing & QA (Agent Mode) | Generated the 10-vibe Phase 2 integration harness, the Phase 3 lock/regeneration/drift test suite (57 tests across edge cases including Unicode, case-only drift, whitespace-only drift), the Phase 4 contribution and passport test suites, the Phase 5 audio engine test suite (164 total offline tests), the multilingual test suite, the 61-test passport integrity suite |
| Documentation | Drafted this README, architecture notes, module docstrings, the phase planning documents in `docs/`, the AI transparency statement in the Creative Passport |
| Phase 6 Audit (Ask + Agent Mode) | Reviewed the complete codebase, audited against judging criteria, identified and resolved the Unicode rendering bug, added the SHA-256 integrity marker, produced the Bob decision log. Final release audit (D-15): corrected stale model names and SDK references in phase2 docs, updated phase5 audio docs to reflect any-section implementation, created `conftest.py` for pytest mark registration, added `test_output/` to `.gitignore`. |

### Three Bob Showcase Moments

These are the three interactions that best demonstrate Bob's engineering contribution:

**Showcase 1 — AI pipeline (Phase 2):** Bob designed and built the complete Gemini API integration pipeline: prompt template design, JSON-only output constraints, fence-stripping fallback, validation rules, retry logic, and the 10-vibe acceptance harness. Bob both built and validated the feature that powers the entire app.

**Showcase 2 — Drift check + test harness (Phase 3):** The signature feature — lock sections, regenerate only the one you don't — rests on a SHA-256 drift check that guarantees locked content is byte-for-byte unchanged. The human defined the contract ("any byte change = drift, including whitespace"). Bob built the check, then wrote 57 tests including adversarial cases (whitespace-only injection, case-only change, removal of a locked section) to prove it. Bob builds it, Bob's tests prove it, the human signs off.

**Showcase 3 — Creative Passport (Phase 4):** The Creative Passport is the product's defining output — it documents how a human and an AI collaborated. Bob designed and built the certificate-quality PDF (vector donut chart, section authorship table, full timeline, transparency statement), the contribution dashboard, the canonical authorship record, and the SHA-256 integrity marker. The transparency statement text itself was drafted by Bob in Ask mode.

### Human Decisions vs. Bob Outputs

The human column in this build is intentionally short — limited to genuine authorship and correctness judgements that a person must own:

| Decision | Owner |
|---|---|
| Drift-check contract: any byte change counts | Human |
| Option B: real accept/reject (not approximated from lock/regen) | Human |
| Contribution formula (provenance weights, direction events) | Human |
| `computed_at` excluded from the integrity hash | Human |
| No IBM AI runtime call (would conflict with determinism thesis) | Human |
| Final release audit scope and approval of all fixes | Human |
| All architecture, code, tests, docstrings, prompts, PDF design, phase docs | **IBM Bob** |

Phase planning documents and the full Bob decision log (15 entries covering every significant human–Bob interaction) are in [`docs/`](docs/).

The parallel is intentional: HarmonyLedger documents a human staying the author while an AI co-writes the music. This project documents exactly the same thing with the code — Bob is the AI co-writer, the human directs it and owns the decisions.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

