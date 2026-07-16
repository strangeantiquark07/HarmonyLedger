# HarmonyLedger

**The Creative Passport for Human–AI Songwriting**

HarmonyLedger is an AI songwriting studio that documents who wrote what — so a human creator can prove they stayed the author while an AI co-wrote alongside them. Every generation, lock, and regeneration is logged, and the finished song exports as a **Creative Passport**: a timeline, a contribution split, and a transparency statement the creator can attach to their work.

---

## Table of Contents

- [The Problem](#the-problem)
- [Features](#features)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [Contribution Methodology](#contribution-methodology)
- [Roadmap](#roadmap)
- [Built With IBM Bob](#built-with-ibm-bob)
- [License](#license)

---

## The Problem

AI can now write a whole song from a one-line prompt. That creates a quiet crisis for creators: when a musician submits AI-assisted work, they can't cleanly show which parts are theirs. Rights bodies, labels, sync-licensing buyers, and collaborators increasingly ask *"how much of this did a human actually write?"* — and creators have no honest way to answer.

Most AI songwriting tools also regenerate the entire song on every click, quietly turning the creator into a passive selector rather than an author.

**HarmonyLedger addresses the trust gap, not just the generation gap.**

---

## Features

- 🎼 **Vibe-to-song generation** — turn a one-line prompt into a structured song (title, verse/chorus/bridge, mood, tempo, style, genre) using using Google Gemini.
- 🔒 **Lock & regenerate** — lock the sections you're happy with and regenerate only the one you're not. A drift check guarantees locked sections never change.
- 📜 **Unified creative timeline** — every human and AI action (generate, lock, regenerate, accept, reject, edit) is logged in one place.
- 📊 **Contribution dashboard** — a deterministic, defensible human-vs-AI contribution split, computed straight from the timeline.
- 🪪 **Creative Passport export** — a downloadable PDF with the song's timeline, contribution split, and an authorship transparency statement.
- 🔊 **Audio preview** *(stretch goal)* — spoken preview of the chorus via text-to-speech, optionally over an ambient bed.

---

## How It Works

Everything in HarmonyLedger is a view of **one JSON file** per project. The song, the timeline, the contribution split, and the exported passport are all just different representations of that single source of truth — which keeps the app easy to debug and keeps the app layer cleanly separated from the AI layer.

The signature feature is **lock and regenerate**: when you regenerate a section, only that section (plus surrounding context) is sent to the model. The response is merged back into the project JSON, and a drift check compares every other section against its saved copy — rejecting the result if anything that should have stayed frozen changed.

---

## Tech Stack

| Layer | Technology |
|---|---|
| App / UI | Streamlit |
| AI (song generation) | Google Gemini API|
| Coding assistant used to build this project | IBM Bob (agentic — Plan / Ask / Agent modes) |
| Storage | Single JSON file per project |
| PDF export | ReportLab |
| Audio (stretch) | gTTS + royalty-free ambient loop |

---

## Architecture

```
project.json  ─┬─▶ Song View (verse/chorus/bridge, mood, tempo)
               ├─▶ Timeline View (generate/lock/regenerate/accept/reject/edit)
               ├─▶ Contribution Dashboard (section split + direction split)
               └─▶ Creative Passport (exported PDF)
```

All views read from the same project JSON, so they can never disagree with each other.

---

## Getting Started

### Prerequisites
- Python 3.10+
- A Google AI Studio account with a Gemini API key.
- `pip` for dependency installation

### Installation

```bash
git clone https://github.com/<your-org>/harmonyledger.git
cd harmonyledger
pip install -r requirements.txt
```

### Configuration

Create a `.env` file with your gemini api key credentials:

```
GEMINI_API_KEY=your_api_key

```

### Run the app

```bash
streamlit run app.py
```

---

## Usage

1. **Start a project** — enter a one-line "vibe" for your song.
2. **Generate** — Gemini returns a structured song (title, sections, mood, tempo, genre).
3. **Lock** any sections you're happy with.
4. **Regenerate** an unlocked section — only that section changes; everything locked stays byte-for-byte identical.
5. **Review the timeline and contribution dashboard** as you go.
6. **Export your Creative Passport** — a PDF with the full authorship record.

---

## Contribution Methodology

Contribution is computed deterministically from the timeline log — never estimated by hand — as two numbers:

- **Section authorship split** — each section is tagged human-written (100% human), AI-generated and untouched (100% AI), or AI-generated then human-edited (50/50); summed across sections for a headline percentage.
- **Creative-direction split** — every lock, regenerate, accept, and reject is counted as a human decision, since steering the AI is itself a form of authorship.

Both numbers are pulled from the same timeline, so the dashboard and the exported Passport always agree.

---

## Roadmap

- [x] Phase 1 — Streamlit skeleton + project storage
- [x] Phase 2 — AI Song Starter (Google Gemini API)
- [x] Phase 3 — Section locking & targeted regeneration
- [x] Phase 4 — Creative timeline, contribution dashboard, Passport export
- [ ] Phase 5 — Audio preview (stretch goal)
- [ ] Phase 6 — Final testing, docs, and submission polish

---

## Built With IBM Bob

This project was built end-to-end using **IBM Bob**, IBM's agentic coding assistant, across the full development lifecycle:

| Stage | What Bob Did |
|---|---|
| Planning | Application architecture, JSON schema design, AI integration workflow, regeneration pipeline design |
| Development | GGoogle Gemini API integration, regeneration + drift-check logic, timeline logger, contribution dashboard, Creative Passport PDF, audio-preview feature |
| Testing & QA | Regeneration test harness, unit/integration tests, edge-case hunting |
| Documentation | README, architecture notes, docstrings, demo narrative |

A running **Bob decision log** (screenshots + what was asked/produced/changed) is maintained throughout the build for full transparency.

---

## License

*Add your chosen license here (e.g. MIT, Apache 2.0).*