# HarmonyLedger
### The Creative Passport for Human–AI Songwriting

HarmonyLedger is an AI songwriting studio that doesn't just help you write a song — it documents who wrote what, so a human creator can prove they stayed the author while an AI co-wrote alongside them.

---

## The Two AIs in This Project

HarmonyLedger uses two distinct AI systems, on two different layers. Keeping them separate is what makes the whole build coherent.

| Layer | System | Role |
|---|---|---|
| The builder | IBM Bob | IBM's agentic coding assistant. It builds the application — plans architecture, writes the integration and features, generates the test harness and docs. This is what the challenge means by "built using IBM Bob." |
| The runtime brain | Google Gemini API | The model inside the shipped app. It turns a creator's vibe into a structured song and regenerates individual sections on request.

**Why this matters for scoring**IBM Bob remains the project's primary software engineering assistant, while Google Gemini powers the runtime AI inside the application. This separation demonstrates Bob's ability to architect, build, validate, and integrate a production-ready AI system regardless of the underlying model.

---

## The Problem

AI can now write a whole song from a one-line prompt. That creates a quiet crisis for creators: when a musician submits AI-assisted work, they cannot cleanly show which parts are theirs. Rights bodies, labels, sync-licensing buyers, and collaborators increasingly ask "how much of this did a human actually write?" — and creators have no honest way to answer. Meanwhile most AI songwriting tools regenerate the entire song on every click, which quietly turns the creator into a passive selector rather than an author.

**Why it matters.** The creative industries are being reshaped by generative AI faster than the tools for proving authorship. HarmonyLedger addresses the trust gap, not just the generation gap — which is exactly the "real-world problem" lens the Challenge Fit criterion rewards.

---

## What HarmonyLedger Does

HarmonyLedger is a songwriting studio built on a single principle: the creator stays the author. The AI is a co-writer that only ever touches what it is explicitly asked to touch, and every action — human or AI — is recorded. When the song is finished, the app exports a **Creative Passport**: a document that shows the timeline of how the song was made, an estimated human-vs-AI contribution split, and a transparency statement the creator can attach to their work.

**The foundation: everything is a view of one JSON file.** A project is a single JSON object. The song, the timeline, the contribution split, and the exported passport are all just different views of that one file. This keeps the architecture honest: if something breaks, we always know whether the fault is in the application or in the AI layer.

**The signature feature: lock and regenerate.** The creator can lock every section they're happy with and regenerate only one — say, just the chorus. A drift check then compares every other section against the saved copy and rejects the result if anything that should have stayed frozen changed. This is the literal, technical proof that the human stayed the author, and it is the centrepiece of the live demo.

---

## Runtime Model:Why Google Gemini

**The one real risk, and how we handle it.**Gemini provides reliable structured generation suitable for JSON-based workflows. Phase 2 still validates every response and retries on failures to guarantee downstream components always receive complete, machine-readable song data. The AI engine is tested independently before integration with the UI.

---

## The Build Plan — Six Phases

Each phase has a concrete "done bar" present so progress is unambiguous. The division of labour is deliberate and follows one rule: humans make the decisions that define authorship — the product principles, the acceptance bars, the sign-offs — and IBM Bob builds and verifies everything else. In practice this means Bob writes the architecture, the AI integration, the signature feature, the tests, and the documentation; the human column is short by design, because it is limited to genuine creative and correctness judgements that a person must own.

Three phases carry a marked **Bob Showcase** — the artifacts documented most deeply for the judges.

**Why the human column is intentionally short.** This is not a plan where a person codes and Bob assists at the margins. It is the reverse: Bob is the primary engineer across the whole SDLC (Software Development Lifecycle), and the human directs and reviews. That maximises Bob's demonstrable contribution against the "effective use of IBM Bob" criterion, while keeping the human unmistakably the author — the exact principle the product itself embodies.

### Phase 1 — Streamlit Skeleton + Project Storage

**What it is.** The application shell. Create a songwriting project, enter a song vibe, save it to a JSON file, reload it, and view an empty creative timeline. No AI yet.

**Why it exists.** It proves the "everything is a view of one JSON" foundation before any AI complexity is added, so later bugs can be isolated to the app or the AI layer.

**Done bar.** Create a project → enter a vibe → project appears in the browser and is written to and reloaded from a JSON file.

**Human decisions — direction & sign-off**
- Review and approve Bob's architectural recommendations.
- Decide which improvements to implement before Phase 2.
- Approve the final architecture and JSON schema for AI integration.

**IBM Bob — builds & verifies**
- Plan Mode:Review the application architecture, folder structure, and scalability, Suggest architectural improvements for future AI features.
- Ask Mode: Stress-test the project JSON schema for future extensibility.
Perform a code review for readability, maintainability, error handling, and scalability, Review the user workflow and recommend UX improvements.
Identify and propose solutions for edge cases (duplicate project names, invalid/corrupted JSON files, missing files, invalid inputs, etc.)

### Phase 2 — AI Song Starter (Core Engine)

**What it is.** Replace the placeholder AI module with the Google Gemini API. A vibe becomes a structured song — title, verse / chorus / bridge, mood, tempo, style, genre — returned as clean JSON. Tested in isolation with a small script before wiring to the UI.


**Why it exists.** This is the heart of the product. Regeneration, contribution tracking, and the Creative Passport all depend on receiving reliable structured song data.

**Done bar.** Ten completely different vibes in a row all return complete, valid JSON that loads into the app with no manual correction.

**Human decisions — direction & sign-off**
- Define what a complete song must contain and the pass bar (ten valid JSONs in a row, no manual fixes).

**IBM Bob — builds & verifies**
- Plan Mode: design the AI integration workflow and the response schema.
- Ask Mode: draft and iterate the prompt template until outputs are consistently structured (forward control).
- Agent Mode: build the Google Gemini API wrapper.
- Agent Mode: implement retry logic, JSON validation, and error handling (backward control).
- Agent Mode: wire the validated responses into the Streamlit interface.


> **Bob Showcase #1 — Best Technical Use of IBM Bob.** Bob builds the complete AI generation pipeline that integrates the Google Gemini API. This demonstrates Bob's ability to architect, implement, validate, and integrate an end-to-end LLM-powered feature from prompt design to production-ready application integration


### Phase 3 — Section Locking & Targeted Regeneration (Signature Feature)

**What it is.** Lock the sections you like; regenerate only the one you don't. Only the selected section plus context is sent to the model, and the result is merged back into the JSON. A drift check verifies that every locked section is byte-for-byte unchanged, and rejects the result otherwise.

**Why it exists.** This is the defining innovation. Most tools regenerate the whole song and reduce the creator to a selector; HarmonyLedger keeps the human as author while still allowing AI iteration.

**Done bar.** Ten consecutive targeted edits regenerate only the selected section, with zero drift in any locked section.

**Human decisions — direction & sign-off**
- Define the drift-check contract — what a locked section is and what change counts as illegal. This is the authorship rule, so it must be a human decision.
- Review Bob's implementation and sign off once the harness proves zero drift.

**IBM Bob — builds & verifies**
- *Plan Mode:* design the regeneration pipeline and the section-locking workflow.
- *Agent Mode:* build the regeneration controls, the JSON-merge, and the drift-check logic.
- *Agent Mode:* generate the automated test harness that runs the 10-edit check and hunts edge cases.
- *Ask Mode:* surface the failure scenarios the harness should cover.

> **Bob Showcase #2 — the correctness-and-verification story.** We let Bob write the signature logic AND the harness that proves it. That is only safe because the drift check plus the automated 10-edit test are a built-in safety net — Bob writes it, Bob's own tests prove it correct, and the human reviews and signs off. Bob both builds and validates the feature the whole product rests on.

### Phase 4 — Creative Ownership Intelligence

**What it is.** Every creative action is logged once into a unified timeline. That single log powers three connected outputs: the Creative Timeline, the Contribution Dashboard, and the exportable HarmonyLedger Creative Passport (PDF).

**Why it exists.** Existing tools generate content; HarmonyLedger documents collaboration. This is what turns a song generator into a transparent AI co-writing platform.

**Done bar.** Finishing a song produces a timeline of events, a contribution split, and a downloadable Creative Passport PDF containing the transparency statement and authorship line.

**Human decisions — direction & sign-off**
- Decide the contribution methodology — the two-split formula below. This is the credibility core, so it must be defensible and human-owned.
- Approve the transparency statement wording and the Passport's final look.

**IBM Bob — builds & verifies**
- *Plan Mode:* propose the timeline event taxonomy (generate, lock, regenerate, accept, reject, human-edit).
- *Agent Mode:* build the single-source timeline logger.
- *Agent Mode:* implement the contribution dashboard from the agreed formula.
- *Agent Mode:* generate the Creative Passport PDF and layout with ReportLab.
- *Ask Mode:* draft and refine the AI Transparency Statement and authorship summary.

> **Bob Showcase #3 — Most Innovative Use of IBM Bob.** The Creative Passport is the project's defining output: it documents how a human and an AI collaborated, rather than just presenting AI-generated lyrics.

#### Contribution Methodology — the Defensible Version

"Estimated contribution" must not be hand-wavy, or it gets picked apart under Implementation & Feasibility. We compute it deterministically from the timeline, and we report two complementary numbers:

- **Section authorship split.** Each section carries a provenance state — human-written (100% human), AI-generated and untouched (100% AI), or AI-generated then human-edited (50/50). Summing across sections gives the headline human-vs-AI percentage.
- **Creative-direction split.** Every lock, regenerate request, accept, and reject is a human decision. We count these separately as a "direction" score, because steering the AI is itself authorship. This is the number that makes the human's role visible even when the AI wrote the words.

Both come straight from the timeline log, so the dashboard and the passport can never disagree — they read the same source.

### Phase 5 — Audio Preview (Stretch Goal)

**What it is.** Generate a spoken preview of the chorus with text-to-speech (gTTS), optionally over a royalty-free ambient loop, so the demo video has sound.

**Why it exists.** It lifts the demo experience and gives the video an emotional beat. Deliberately scoped as a stretch goal, attempted only after the core workflow is solid.

**Done bar.** Click Preview → the spoken chorus plays inside the app.

**Human decisions — direction & sign-off**
- Pick the voice and the ambient bed, and set the quality bar.

**IBM Bob — builds & verifies**
- *Plan Mode:* design the audio-preview workflow.
- *Agent Mode:* implement text-to-speech generation.
- *Agent Mode:* build and wire the in-app audio player end to end.

> **End-to-end Bob feature.** A small, self-contained feature built almost entirely by Bob — the clean "Bob shipped this whole thing itself" example for the README and demo.

### Phase 6 — Final Verification, Documentation & Submission

**What it is.** Final testing and verification of HarmonyLedger, followed by cleaning the GitHub repository and completing the documentation.

**Why it exists.** Ensure the final project is reliable, polished, consistent, and clearly communicates what was actually built.

**Done bar.** Core functionality verified, GitHub repository cleaned and finalized, README complete, and project ready for submission.

**Human decisions — direction & sign-off**

* Perform the final end-to-end acceptance test.
* Review the completed project and approve it for submission.
* Submit the project one day before the deadline.

**IBM Bob — final review & verification**

* *Ask Mode:* review the complete GitHub repository and identify outdated, redundant, or misleading files and documentation.
* *Ask Mode:* verify that the codebase and README accurately reflect the final implementation.
* *Ask Mode:* review the final architecture, code quality, and responsible-AI approach.
* *Agent Mode:* apply the approved cleanup, documentation updates, and final corrections.

**README must include:**

* Problem statement
* Solution description
* AI approach and architecture
* Selected challenge theme
* How IBM Bob was used
* Features and workflow
* Technology stack and setup instructions
* Responsible AI and authorship approach

**Final verification:** The final codebase, GitHub repository, and README accurately represent the finished HarmonyLedger project.


---

## How IBM Bob Is Used Across the SDLC

| Stage | What Bob Did |
|---|---|
| Planning | Designed the application architecture, stress-tested the JSON schema, planned the AI integration workflow, and designed the regeneration pipeline. |
| Development | Built the Google Gemini API integration, the regeneration + drift-check logic, the timeline logger, the contribution dashboard, the Creative Passport PDF, and the audio-preview feature. |
| Testing & QA | Generated the regeneration test harness, produced unit and integration tests, and hunted edge cases. |
| Documentation | Drafted the README, architecture docs, and docstrings, and helped shape the demo narrative. |

### The Narrative That Ties It Together

HarmonyLedger documents a human staying the author while an AI co-writes the music. We are doing exactly the same thing with the code: Bob is our AI co-writer, and we — the humans — direct it, review it, and own the decisions. That parallel is deliberate. It pre-empts the obvious judge question ("if Bob built it, did you?") and answers it with the product's own thesis.

---

## Evidence for Judging

We keep a running Bob decision log throughout the build. For each significant interaction: a screenshot, one line on what we asked, what Bob produced, and what we changed. This single habit is the highest-value thing we can do for the "how was IBM Bob used" question — it converts a claim into a documented, honest record spanning planning, implementation, testing, and documentation.

---

## How This Plan Maps to the Judging Criteria

| Criterion (1–5) | How HarmonyLedger Scores |
|---|---|
| Technical Execution | AI-powered architecture: IBM Bob builds the application while Google Gemini powers the runtime songwriting engine. A non-trivial lock-and-regenerate workflow is verified by an automated harness generated with Bob.|
| Innovation | The Creative Passport reframes AI songwriting from "who generated the words" to "who authored the work" — a genuinely novel output. |
| Challenge Fit | Squarely in "Reimagine Creative Industries with AI," and it tackles a real trust problem creators face right now, not just a generation gap. |
| Implementation & Feasibility | Runs today on free tiers; a deterministic contribution methodology; a scoped stretch goal; realistic month-long plan with concrete done-bars. |