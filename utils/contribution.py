"""
utils/contribution.py
─────────────────────
Phase 4 — Creative Ownership Intelligence.

Pure, stateless computation of the two contribution numbers described in
SPEC.md's "Contribution Methodology — the Defensible Version":

  1. Section-authorship split  — derived from each section's provenance field.
  2. Creative-direction score  — human steering decisions as a fraction of all
     timeline events.

compute_contribution() has no side effects: it does not mutate the project,
does not call save_project(), and has no Streamlit imports.  The caller in
views/view_project.py is responsible for caching the result and saving.
"""

from datetime import datetime


# Methodology version — bump this if the formula changes so that old exported
# passports remain valid against the version that produced them.
METHODOLOGY_VERSION = 1

# Provenance → (human_weight, ai_weight).  Must always sum to 1.0.
_PROVENANCE_WEIGHTS: dict[str, tuple[float, float]] = {
    "human_written":  (1.0, 0.0),
    "ai_generated":   (0.0, 1.0),
    "ai_then_human":  (0.5, 0.5),
}

# Timeline event types that count as human creative-direction decisions.
_DIRECTION_EVENT_TYPES: frozenset[str] = frozenset({
    "section_locked",
    "section_unlocked",
    "section_regenerated",
    "human_edit",
    "section_accepted",   # Sub-Task 2a — tolerated as zero until that lands
    "section_rejected",   # Sub-Task 2a — tolerated as zero until that lands
})


def compute_contribution(project) -> dict:
    """Return the contribution split for *project*.

    Args:
        project: A Project instance (utils.models.Project).

    Returns a dict with exactly the shape documented in utils/models.py:
        {
            "human_pct":          float,   # 0.0–100.0, rounded to 1 dp
            "ai_pct":             float,   # 0.0–100.0, rounded to 1 dp
            "direction_score":    float,   # 0.0–100.0, rounded to 1 dp
            "computed_at":        str,     # datetime.now().isoformat()
            "methodology_version": int,
        }

    Handles empty song / empty timeline without dividing by zero (returns 0s).
    Does not mutate *project*.
    """
    # ── Section-authorship split ──────────────────────────────────────────────
    sections = project.song.get("sections", {}) if project.song else {}
    human_weights: list[float] = []
    ai_weights:    list[float] = []

    for sec in sections.values():
        prov = sec.get("provenance", "ai_generated")
        h, a = _PROVENANCE_WEIGHTS.get(prov, (0.0, 1.0))
        human_weights.append(h)
        ai_weights.append(a)

    if human_weights:
        human_pct = round(sum(human_weights) / len(human_weights) * 100, 1)
        ai_pct    = round(100.0 - human_pct, 1)
    else:
        human_pct = 0.0
        ai_pct    = 0.0

    # ── Creative-direction score ──────────────────────────────────────────────
    timeline       = project.timeline or []
    total_events   = len(timeline)
    direction_events = sum(
        1 for e in timeline
        if e.get("event_type") in _DIRECTION_EVENT_TYPES
    )

    direction_score = (
        round(direction_events / total_events * 100, 1)
        if total_events > 0
        else 0.0
    )

    return {
        "human_pct":           human_pct,
        "ai_pct":              ai_pct,
        "direction_score":     direction_score,
        "computed_at":         datetime.now().isoformat(),
        "methodology_version": METHODOLOGY_VERSION,
    }
