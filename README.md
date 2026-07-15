# HarmonyLedger
### The Creative Passport for Human–AI Songwriting

HarmonyLedger is an AI songwriting studio that doesn't just help you write a song — it **documents who wrote what**, so a human creator can prove they stayed the author while an AI co-wrote alongside them.

---

## The Problem

AI can now write a whole song from a one-line prompt. That creates a quiet crisis for creators: when a musician submits AI-assisted work, they cannot cleanly show which parts are theirs. Rights bodies, labels, sync-licensing buyers, and collaborators increasingly ask *"how much of this did a human actually write?"* — and creators have no honest way to answer.

Meanwhile, most AI songwriting tools regenerate the entire song on every click, quietly turning the creator into a passive selector rather than an author.

**HarmonyLedger addresses the trust gap, not just the generation gap.**

---

## What It Does

HarmonyLedger is built on a single principle: **the creator stays the author.** The AI is a co-writer that only ever touches what it is explicitly asked to touch, and every action — human or AI — is recorded.

When a song is finished, the app exports a **Creative Passport**: a document showing the timeline of how the song was made, an estimated human-vs-AI contribution split, and a transparency statement the creator can attach to their work.

### Core Design Principles

- **One JSON, many views.** A project is a single JSON object. The song, the timeline, the contribution split, and the exported passport are all just different views of that one file — keeping the architecture honest and easy to debug.
- **Lock and regenerate (signature feature).** The creator can lock every section they're happy with and regenerate only one — say, just the chorus. A drift check compares every other section against the saved copy and rejects the result if anything that should have stayed frozen changed. This is the literal, technical proof that the human stayed the author.

---

## The Two AIs in This Project

HarmonyLedger uses two distinct IBM AI systems on two different layers — a deliberate all-IBM stack.

| Layer | System | Role |
|---|---|---|
| **The builder** | IBM Bob | IBM's agentic coding assistant. Plans architecture, writes the integration and features, generates the test harness and docs. |
| **The runtime brain** | IBM Granite (via watsonx) | The model living inside the shipped app. Turns a creator's vibe into a structured song and regenerates individual sections on request. |

**Why it matters:** Bob builds it, Granite runs it. Every layer of the product is IBM — Bob integrating IBM's own model is a harder, more deliberate flex than integrating a third-party API.

---

## Runtime Model: Why IBM Granite

Granite models are smaller than GPT-4-class models, so reliable structured JSON output is harder. That's exactly what Phase 2's **backward control** (validate every reply, retry on failure) exists for. The app also uses watsonx's structured-output / JSON mode where available, plus a few-shot prompt strategy. The generation engine is tested in isolation before it touches the UI, so a bad song is never confused with a bad connection.

---

## Build Plan — Six Phases

Each phase has a concrete "done bar." Division of labor follows one rule: **humans make the decisions that define authorship** (product principles, acceptance bars, sign-offs); **IBM Bob builds and verifies everything else.**

### Phase 1 — Streamlit Skeleton + Project Storage
Create a project, enter a vibe, save/reload from JSON, view an empty timeline. No AI yet.
- **Human:** Set the "everything is a view of one project JSON" principle; approve final architecture/schema.
- **Bob:** Propose app architecture (Plan), design/stress-test the JSON schema (Ask), build the Streamlit shell, timeline structure, and save/load (Agent).
- **Done bar:** Project created → saved to JSON → reloads correctly in the browser.

### Phase 2 — AI Song Starter (Core Engine)
Replace the placeholder AI module with IBM Granite via watsonx. A vibe becomes a structured song (title, verse/chorus/bridge, mood, tempo, style, genre) as clean JSON.
- **Human:** Define what a "complete" song must contain and the pass bar.
- **Bob:** Design the AI integration workflow (Plan), draft/iterate the prompt template (Ask), build the watsonx/Granite wrapper, retry logic, JSON validation and error handling, and wire it into the UI (Agent).
- **Done bar:** 10 different vibes in a row return complete, valid JSON with no manual correction.
- 🏆 **Bob Showcase #1 — Best Technical Use of IBM Bob:** Bob builds the full generation pipeline that integrates IBM's own Granite model — "Bob using IBM to wire up IBM."

### Phase 3 — Section Locking & Targeted Regeneration (Signature Feature)
Lock sections you like; regenerate only the one you don't. Only the selected section plus context goes to the model; the result merges back into the JSON. A drift check verifies every locked section is byte-for-byte unchanged.
- **Human:** Define the drift-check contract (the authorship rule); sign off once the harness proves zero drift.
- **Bob:** Design the regeneration pipeline (Plan), build regeneration controls/JSON-merge/drift-check logic, generate the automated 10-edit test harness (Agent), surface failure scenarios to cover (Ask).
- **Done bar:** 10 consecutive targeted edits regenerate only the selected section, with zero drift.
- 🏆 **Bob Showcase #2 — Correctness & Verification:** Bob writes both the signature logic and the harness that proves it correct; the human reviews and signs off.

### Phase 4 — Creative Ownership Intelligence
Every creative action logs once into a unified timeline, powering the Creative Timeline, Contribution Dashboard, and the exportable **Creative Passport (PDF)**.
- **Human:** Decide the contribution methodology (see below); approve the transparency statement and Passport look.
- **Bob:** Propose the timeline event taxonomy — generate, lock, regenerate, accept, reject, human-edit (Plan); build the single-source logger, contribution dashboard, and Passport PDF/layout with ReportLab (Agent); draft the AI Transparency Statement (Ask).
- **Done bar:** Finishing a song produces a timeline, a contribution split, and a downloadable Creative Passport PDF.
- 🏆 **Bob Showcase #3 — Most Innovative Use of IBM Bob:** The Creative Passport documents *how* a human and AI collaborated, not just the generated output.

### Phase 5 — Audio Preview (Stretch Goal)
Generate a spoken preview of the chorus (gTTS), optionally over a royalty-free ambient loop.
- **Human:** Pick the voice, ambient bed, and quality bar.
- **Bob:** Design the workflow (Plan); implement TTS generation and build the in-app audio player end to end (Agent).
- **Done bar:** Click Preview → spoken chorus plays in-app.
- ⭐ *End-to-end Bob feature* — a small, self-contained feature built almost entirely by Bob.

### Phase 6 — Testing, Documentation & Submission
- **Human:** Record the ≤3-minute demo (leading with the live lock-and-regenerate moment); submit one day early.
- **Bob:** Generate unit/integration tests; review the codebase and apply final UI polish (Ask); draft the README, install guide, architecture notes, and docstrings (Agent); help shape the demo script (Ask).
- **Done bar:** GitHub repo complete, README finalized, demo recorded, project submitted a day before the deadline.

---

## Contribution Methodology

"Estimated contribution" is computed **deterministically** from the timeline log — never hand-wavy — and reported as two complementary numbers:

1. **Section authorship split.** Each section carries a provenance state:
   - Human-written → 100% human
   - AI-generated and untouched → 100% AI
   - AI-generated then human-edited → 50/50

   Summed across sections, this gives the headline human-vs-AI percentage.

2. **Creative-direction split.** Every lock, regenerate request, accept, and reject is a human decision. These are counted separately as a "direction" score, since steering the AI is itself authorship — this is what makes the human's role visible even when the AI wrote the words.

Both numbers come from the same timeline log, so the dashboard and the exported Passport can never disagree.

---

## How IBM Bob Is Used Across the SDLC

| Stage | What Bob Did |
|---|---|
| **Planning** | Designed the application architecture, stress-tested the JSON schema, planned the AI integration workflow, designed the regeneration pipeline. |
| **Development** | Built the Granite/watsonx integration, the regeneration + drift-check logic, the timeline logger, the contribution dashboard, the Creative Passport PDF, and the audio-preview feature. |
| **Testing & QA** | Generated the regeneration test harness, produced unit and integration tests, and hunted edge cases. |
| **Documentation** | Drafted the README, architecture docs, and docstrings, and helped shape the demo narrative. |

### The Narrative

HarmonyLedger documents a human staying the author while an AI co-writes the music. The project's own build process mirrors this: **Bob is our AI co-writer, and the humans direct it, review it, and own the decisions.** This pre-empts the obvious judge question — *"if Bob built it, did you?"* — and answers it with the product's own thesis.

---

## Evidence for Judging

A running **Bob decision log** is kept throughout the build. For each significant interaction: a screenshot, one line on what was asked, what Bob produced, and what was changed. This converts the "how was IBM Bob used" claim into a documented, honest record spanning planning, implementation, testing, and documentation.

---

## Judging Criteria Mapping

| Criterion | How HarmonyLedger Scores |
|---|---|
| **Technical Execution** | All-IBM stack: Bob builds, Granite runs. A non-trivial signature feature (lock + drift check) verified by an automated harness Bob wrote. |
| **Innovation** | The Creative Passport reframes AI songwriting from "who generated the words" to "who authored the work" — a genuinely novel output. |
| **Challenge Fit** | Squarely in "Reimagine Creative Industries with AI"; tackles a real trust problem creators face right now, not just a generation gap. |
| **Implementation & Feasibility** | Runs today on free tiers; deterministic contribution methodology; a scoped stretch goal; realistic month-long plan with concrete done-bars. |

---

## Tech Stack

- **Frontend/App shell:** Streamlit
- **Runtime AI model:** IBM Granite via watsonx
- **Coding assistant:** IBM Bob (agentic — Plan / Ask / Agent modes)
- **Storage:** Single JSON file per project
- **PDF export:** ReportLab (Creative Passport)
- **Audio (stretch):** gTTS + royalty-free ambient loop

---

## Status

🚧 In active development — see phase checklist above for current progress.
