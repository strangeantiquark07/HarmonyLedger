"""
utils/passport.py
─────────────────
Phase 4 — Creative Ownership Intelligence.

Builds a Creative Passport PDF entirely in memory using ReportLab and
returns the raw bytes.  No file is written to disk inside this function.

Design note: this is a printed/exported document, not a screen inside the
Streamlit app — it renders on a plain white page in any PDF viewer or on
paper. It deliberately does NOT reuse the app's dark-mode colours (light
gray text on near-black cards); on a white page that combination is close
to unreadable. Instead this uses a light "certificate" palette: a navy
header band, strong accent colours for real content (never pastel-on-white
for anything that must stay legible), and vector-drawn shapes instead of
emoji glyphs, since the base-14 PDF fonts used here don't have emoji glyphs
and silently render them as an invisible/blank box.

Unicode font support
────────────────────
All user-generated text (song title, project name, lyrics, timeline
descriptions, transparency statement, metadata) is rendered using the
appropriate Unicode-capable font for the project language so that non-Latin
scripts (Devanagari, Telugu, Tamil, CJK) display as readable characters
rather than black boxes.

Font strategy:
  • Latin scripts (English, Spanish, French):
      NotoSans TTF — bundled in assets/fonts/
  • Devanagari (Hindi, Marathi):
      NotoSansDevanagari TTF — bundled in assets/fonts/
  • Telugu, Tamil:
      NotoSansTelugu / NotoSansTamil TTF — bundled in assets/fonts/
  • Japanese (CJK):
      HeiseiKakuGo-W5 — a UnicodeCIDFont built into ReportLab, no TTF
      required, and not affected by the ReportLab TTF subsetting bug that
      causes "unpack requires a buffer of 2 bytes" for large CJK fonts.

  Language       Font family used
  ─────────────────────────────────────────────
  English        NotoSans (bundled TTF)
  Spanish        NotoSans (bundled TTF)
  French         NotoSans (bundled TTF)
  Hindi          NotoSansDevanagari (bundled TTF)
  Marathi        NotoSansDevanagari (bundled TTF)
  Telugu         NotoSansTelugu (bundled TTF)
  Tamil          NotoSansTamil (bundled TTF)
  Japanese       HeiseiKakuGo-W5 (ReportLab built-in CIDFont)

Pure chrome / system text (field labels, page numbers, footer rule) continues
to use the built-in Helvetica family, which is always available in ReportLab
without a font file and is never used for user-entered content.

The caller (views/view_project.py) is responsible for:
  - Offering the bytes via st.download_button
  - Stamping project.passport with exported_at / watermark_id
  - Logging the passport_exported timeline event
  - Calling save_project()

build_passport_pdf() is pure: no side effects, no Streamlit imports.
"""

import io
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfgen import canvas as canvas_mod
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    BaseDocTemplate,
    PageTemplate,
    Frame,
    PageBreak,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Circle, Wedge, Line, String, Rect


# ── Unicode font registration ─────────────────────────────────────────────────
# Fonts live in assets/fonts/ relative to the project root (one level above
# this file). The path is resolved at import time so it is independent of the
# working directory when the app is started.

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")

# Mapping: (internal_alias, filename)
# TTF files bundled in the repository; no system fonts required.
# Note: Japanese uses HeiseiKakuGo-W5 (ReportLab built-in CIDFont) instead of
# a TTF because large CJK TrueType fonts trigger a ReportLab glyph-subsetting
# bug ("unpack requires a buffer of 2 bytes") during PDF serialisation.
_FONT_FILES = [
    ("NotoSans",                  "NotoSans-Regular.ttf"),
    ("NotoSans-Bold",             "NotoSans-Bold.ttf"),
    ("NotoSansDevanagari",        "NotoSansDevanagari-Regular.ttf"),
    ("NotoSansDevanagari-Bold",   "NotoSansDevanagari-Bold.ttf"),
    ("NotoSansTamil",             "NotoSansTamil-Regular.ttf"),
    ("NotoSansTamil-Bold",        "NotoSansTamil-Bold.ttf"),
    ("NotoSansTelugu",            "NotoSansTelugu-Regular.ttf"),
    ("NotoSansTelugu-Bold",       "NotoSansTelugu-Bold.ttf"),
]

# Track which TTF aliases were successfully registered (so _font() can fall
# back gracefully if a file is somehow missing in an unusual deployment).
_REGISTERED_FONTS: set[str] = set()

for _alias, _filename in _FONT_FILES:
    _path = os.path.join(_FONTS_DIR, _filename)
    if os.path.isfile(_path):
        try:
            pdfmetrics.registerFont(TTFont(_alias, _path))
            _REGISTERED_FONTS.add(_alias)
        except Exception:
            pass  # Fall back to NotoSans or Helvetica at render time

# Register Japanese CID font — built into ReportLab, no font file needed.
# HeiseiKakuGo-W5 is the standard sans-serif Japanese CIDFont shipped with
# every ReportLab install. Using UnicodeCIDFont avoids TTF glyph-subsetting.
_JP_FONT      = "HeiseiKakuGo-W5"
_JP_FONT_BOLD = "HeiseiKakuGo-W5"   # CIDFont has no separate bold variant
try:
    pdfmetrics.registerFont(UnicodeCIDFont(_JP_FONT))
    _REGISTERED_FONTS.add(_JP_FONT)
except Exception:
    pass  # Unusually stripped ReportLab install — will fall back to NotoSans

# ── Language → font family mapping ───────────────────────────────────────────

_LANG_FONT_BASE: dict[str, str] = {
    # Latin-script languages — Noto Sans covers full Latin + extended Unicode
    "English": "NotoSans",
    "Spanish": "NotoSans",
    "French":  "NotoSans",
    # Devanagari script
    "Hindi":   "NotoSansDevanagari",
    "Marathi": "NotoSansDevanagari",
    # South Indian scripts
    "Telugu":  "NotoSansTelugu",
    "Tamil":   "NotoSansTamil",
    # CJK — use built-in CIDFont (no subsetting, no TTF file dependency)
    "Japanese": _JP_FONT,
}

_FALLBACK_FONT      = "NotoSans"       # always registered (file always present)
_FALLBACK_BOLD_FONT = "NotoSans-Bold"


def _font(language: str, bold: bool = False) -> str:
    """Return the registered ReportLab font name for *language*.

    If the ideal font wasn't successfully registered (e.g. file missing on an
    unusual deployment), falls back to NotoSans which covers Latin + extended
    Unicode, or ultimately to Helvetica so the PDF always builds.
    """
    base = _LANG_FONT_BASE.get(language, _FALLBACK_FONT)
    name = f"{base}-Bold" if bold else base
    if name in _REGISTERED_FONTS:
        return name
    # Bold variant missing → try regular
    if bold and base in _REGISTERED_FONTS:
        return base
    # Desired font missing entirely → NotoSans fallback
    fb = _FALLBACK_BOLD_FONT if bold else _FALLBACK_FONT
    if fb in _REGISTERED_FONTS:
        return fb
    # Last resort — always present in ReportLab
    return "Helvetica-Bold" if bold else "Helvetica"


# ── Palette — a light "certificate" theme, tuned for a white printed page ────
_NAVY       = colors.HexColor("#16233A")   # header band / primary dark ink
_NAVY_SOFT  = colors.HexColor("#1F2F4D")   # secondary dark panels
_INK        = colors.HexColor("#111827")   # body text on white
_SUBTLE     = colors.HexColor("#6B7280")   # secondary text on white (legible!)
_BORDER     = colors.HexColor("#E2E5EA")   # table grid / hairlines
_ROW_ALT    = colors.HexColor("#F6F7F9")   # zebra row tint
_WHITE      = colors.HexColor("#FFFFFF")
_GREEN      = colors.HexColor("#12A454")   # human authorship
_PURPLE     = colors.HexColor("#7C4DFF")   # AI authorship
_GOLD       = colors.HexColor("#B8862B")   # seal / accent rule

# Section accent colours — match the app's own section colour-coding exactly.
_SECTION_COLORS = {
    "verse_1": colors.HexColor("#12A454"),
    "chorus":  colors.HexColor("#2F6FE4"),
    "verse_2": colors.HexColor("#12A454"),
    "bridge":  colors.HexColor("#C8790E"),
    "outro":   colors.HexColor("#7C4DFF"),
}
_SECTION_ORDER  = ("verse_1", "chorus", "verse_2", "bridge", "outro")
_SECTION_LABELS = {
    "verse_1": "Verse 1", "chorus": "Chorus", "verse_2": "Verse 2",
    "bridge": "Bridge",   "outro":  "Outro",
}
_PROV_LABELS = {
    "ai_generated":  "AI Generated",
    "human_written": "Human Written",
    "ai_then_human": "AI + Human Edit",
}

# Event types that are bookkeeping/derived, not creative decisions — these
# recompute after nearly every action and would otherwise spam the printed
# timeline with near-duplicate rows. They stay in the underlying JSON for a
# full audit trail; the human-facing document just doesn't repeat them.
_TIMELINE_NOISE_EVENTS = {"contribution_computed"}

# Non-legal disclaimer — required on every export per responsible-AI policy.
# Must appear on the summary page and in the transparency statement.
CONTRIBUTION_DISCLAIMER = (
    "Contribution percentages are a transparent accounting model based on "
    "recorded creative actions. They are not a legal determination of "
    "copyright ownership."
)

_ACTOR_COLORS = {"Human": _GREEN, "AI": _PURPLE}

# Default transparency statement used when no human-approved text exists yet.
# Drafted by IBM Bob (Ask/Agent mode) per SPEC.md Phase 4, which assigns
# "draft and refine the AI Transparency Statement" explicitly to Bob.
# The creator may replace this with their own approved wording in the app;
# that wording is stored in project.passport["transparency_statement"] and
# will be used verbatim in place of this text on every subsequent export.
_DEFAULT_TRANSPARENCY = (
    "This Creative Passport is produced by HarmonyLedger — a provenance "
    "and authorship system for AI-assisted creative work — and documents "
    "the collaborative process between a human creator and a generative AI "
    "model (Google Gemini). It records the creative process and preserves "
    "an auditable history of human-AI collaboration. It may be attached to "
    "a song submission, sync-licensing application, or rights-body "
    "registration to provide a transparent contribution accounting.\n\n"

    "IMPORTANT: Contribution percentages are a transparent accounting model "
    "based on recorded creative actions. They are not a legal determination "
    "of copyright ownership.\n\n"

    "Contribution figures are computed deterministically from an "
    "append-only event log that records every action taken during the "
    "project — by the human creator and by the AI — in the order they "
    "occurred. No contribution figure is hand-entered or estimated after "
    "the fact; each number is a direct arithmetic result of the logged "
    "record. Methodology v{version} is in use for this export.\n\n"

    "Section authorship is derived from the provenance state each song "
    "section carries at the time of export. A section marked "
    "human_written is attributed 100% to the human creator. A section "
    "marked ai_generated — meaning the AI produced it and the creator "
    "accepted it without textual change — is attributed 100% to the AI. "
    "A section marked ai_then_human — meaning the AI produced a draft "
    "that the creator then edited — is attributed 50% to each party. "
    "The headline human/AI percentage shown on this passport is the "
    "average of those per-section attributions across all sections "
    "present in the song.\n\n"

    "The Direction Score measures creative steering: every deliberate "
    "human decision logged in the timeline (locking a section, "
    "requesting a regeneration, accepting or rejecting an AI draft, "
    "making a direct edit) is counted as a human-direction event. The "
    "Direction Score is the ratio of those events to all timeline events, "
    "expressed as a percentage. A higher Direction Score indicates that "
    "the creator exercised more active editorial control over the AI's "
    "output.\n\n"

    "The full event log, including events omitted from the printed "
    "timeline for readability, is retained in the project's source data "
    "file and is available for independent audit on request."
)


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_ts(raw: str, fallback: str = "—") -> str:
    """Format an ISO-8601 timestamp as a short human-readable string.

    Falls back to the raw string (or *fallback*) if it can't be parsed —
    this must never raise, since malformed/missing timestamps shouldn't
    break PDF generation.
    """
    if not raw:
        return fallback
    try:
        dt = datetime.fromisoformat(str(raw))
        return dt.strftime("%b %d, %Y · %I:%M %p").replace(" 0", " ")
    except (ValueError, TypeError):
        return str(raw)[:19] or fallback


def _seal_drawing(size_mm: float = 15) -> Drawing:
    """A small vector-drawn circular seal with a checkmark.

    Deliberately drawn as shapes, not a Unicode glyph — base-14 PDF fonts
    have no checkmark/emoji glyph and silently render one as a blank box.
    """
    s = size_mm * mm
    d = Drawing(s, s)
    cx = cy = s / 2
    r = s / 2 - 1
    d.add(Circle(cx, cy, r, fillColor=None, strokeColor=_GOLD, strokeWidth=1.4))
    d.add(Circle(cx, cy, r - 3, fillColor=None, strokeColor=_GOLD, strokeWidth=0.6))
    # Checkmark, drawn as two line segments.
    d.add(Line(cx - r * 0.42, cy - r * 0.02, cx - r * 0.10, cy - r * 0.34,
               strokeColor=_GOLD, strokeWidth=1.8, strokeLineCap=1))
    d.add(Line(cx - r * 0.10, cy - r * 0.34, cx + r * 0.46, cy + r * 0.36,
               strokeColor=_GOLD, strokeWidth=1.8, strokeLineCap=1))
    return d


def _contribution_donut(human_pct: float, ai_pct: float, size_mm: float = 40) -> Drawing:
    """A donut chart showing the human/AI authorship split.

    Drawn as a full AI-coloured disc with a human-coloured wedge on top
    (rather than two abutting wedges) so a 0% or 100% split never leaves a
    seam-math edge case — the "background" colour always covers the full
    circle first.
    """
    s = size_mm * mm
    d = Drawing(s, s)
    cx = cy = s / 2
    r = s / 2 - 1

    # Full AI-coloured base disc.
    d.add(Wedge(cx, cy, r, 0, 360, fillColor=_PURPLE, strokeColor=None))
    # Human wedge on top, starting at 12 o'clock, sweeping clockwise.
    human_deg = max(0.0, min(360.0, (human_pct / 100.0) * 360.0))
    if human_deg > 0:
        d.add(Wedge(cx, cy, r, 90 - human_deg, 90, fillColor=_GREEN, strokeColor=None))
    # Punch the donut hole.
    d.add(Circle(cx, cy, r * 0.56, fillColor=_WHITE, strokeColor=None))

    # On a tie the human wedge is drawn on top and is visually dominant,
    # so always prefer the human percentage when the split is exactly equal.
    label = f"{human_pct:g}%" if human_pct >= ai_pct else f"{ai_pct:g}%"
    d.add(String(cx, cy - 3, label, fontName="Helvetica-Bold", fontSize=11,
                 fillColor=_INK, textAnchor="middle"))
    return d


def _score_bar(pct: float, width_mm: float = 70, height_mm: float = 3.2) -> Drawing:
    """A horizontal proportional-fill bar (used for the direction score)."""
    w, h = width_mm * mm, height_mm * mm
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, fillColor=_BORDER, strokeColor=None))
    fill_w = max(0.0, min(1.0, pct / 100.0)) * w
    if fill_w > 0:
        d.add(Rect(0, 0, fill_w, h, fillColor=_NAVY, strokeColor=None))
    return d


class _NumberedCanvas(canvas_mod.Canvas):
    """Canvas that stamps 'Page N of Total' + a footer rule on every page.

    Standard two-pass ReportLab pattern: page draws are buffered until the
    total page count is known, then each buffered page gets the footer
    drawn before it's actually written out.
    """

    def __init__(self, *args, **kwargs):
        canvas_mod.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            canvas_mod.Canvas.showPage(self)
        canvas_mod.Canvas.save(self)

    def _draw_footer(self, total_pages: int) -> None:
        w, _ = A4
        self.setStrokeColor(_BORDER)
        self.setLineWidth(0.6)
        self.line(20 * mm, 14 * mm, w - 20 * mm, 14 * mm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(_SUBTLE)
        self.drawString(20 * mm, 9 * mm, "HarmonyLedger · Creative Passport")
        self.drawRightString(
            w - 20 * mm, 9 * mm, f"Page {self._pageNumber} of {total_pages}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def build_passport_pdf(project) -> bytes:
    """Build a Creative Passport PDF for *project* and return raw bytes.

    The PDF is structured as two logical sections:

    Page 1 — Summary / Cover
        A concise, human-readable overview of the project: song title, language,
        genre, AI model, section counts, edit counts, contribution figures, and
        the non-legal disclaimer.

    Page 2+ — Detail
        The full contribution split, section authorship table, creative timeline,
        and human-approved transparency statement — identical to the previous
        single-page layout, preserved for completeness and auditability.

    All user-generated text (title, project name, lyrics, timeline
    descriptions, transparency statement) is rendered using the Unicode-capable
    Noto Sans font family appropriate for the project's language, so that
    non-Latin scripts (Devanagari for Hindi/Marathi, Telugu, Tamil, CJK for
    Japanese) are displayed as readable characters rather than black boxes.

    Args:
        project: A Project instance (utils.models.Project).

    Returns:
        bytes — the PDF content starting with b'%PDF'.

    Does not mutate *project* or call save_project().
    """
    buf = io.BytesIO()
    frame = Frame(
        20 * mm, 18 * mm, A4[0] - 40 * mm, A4[1] - 18 * mm - 14 * mm,
        id="main", topPadding=0, bottomPadding=0, leftPadding=0, rightPadding=0,
    )
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        title=f"Creative Passport — {project.name}",
    )
    doc.addPageTemplates([PageTemplate(id="passport", frames=[frame])])

    styles = getSampleStyleSheet()
    story  = []

    # ── Collect all project data up-front ────────────────────────────────────
    # Using existing project data model fields; no new fields are introduced.
    song          = project.song or {}
    ai_title      = song.get("title", "")       # creative title from Gemini
    project_title = project.name                # user's own project name
    language      = getattr(project, "language", "") or "English"
    genre         = song.get("genre", "")
    style         = song.get("style", "")
    mood          = song.get("mood", "")
    tempo         = song.get("tempo", "")
    key           = song.get("key", "")
    time_sig      = song.get("time_signature", "")
    model_used    = song.get("model_used", "")

    sections      = song.get("sections", {})
    num_sections  = len(sections)
    num_locked    = sum(1 for s in sections.values() if s.get("locked"))
    timeline      = project.timeline or []
    num_human_edits = sum(
        1 for e in timeline if e.get("event_type") == "human_edit"
    )
    num_ai_regen  = sum(
        1 for e in timeline if e.get("event_type") == "section_regenerated"
    )
    # Human creative-direction events (steering decisions)
    _DIRECTION_TYPES = frozenset({
        "section_locked", "section_unlocked", "section_regenerated",
        "human_edit", "section_accepted", "section_rejected",
    })
    num_direction = sum(
        1 for e in timeline if e.get("event_type") in _DIRECTION_TYPES
    )

    contrib       = project.contribution or {}
    human_pct     = contrib.get("human_pct", 0.0)
    ai_pct        = contrib.get("ai_pct", 0.0)
    dir_score     = contrib.get("direction_score", 0.0)
    meth_version  = contrib.get("methodology_version", 1)
    computed_at   = _fmt_ts(contrib.get("computed_at", ""), fallback="Not yet computed")

    passport      = project.passport or {}
    watermark_id  = passport.get("watermark_id") or "unassigned until export"
    # Use the timestamp already stamped by the caller (view_project.py) so the
    # value printed on the page matches the one saved to the project file and
    # the timeline event — not a second datetime.now() call made milliseconds later.
    exported_at   = _fmt_ts(passport.get("exported_at") or datetime.now().isoformat())

    frame_w = A4[0] - 40 * mm  # 170 mm usable width

    # ── Unicode-aware font names for this project's language ─────────────────
    # These are used for all user-generated text throughout the document.
    uf_regular  = _font(language, bold=False)   # user-content regular weight
    uf_bold     = _font(language, bold=True)    # user-content bold weight

    # ── Shared paragraph styles ───────────────────────────────────────────────
    # NOTE: h2, body, muted, stat_label, stat_value are used for chrome/system
    # labels that are always ASCII — they keep Helvetica.  The styles that
    # render user-generated text (title_style, subtitle_style, band_meta_style,
    # quote_style, timeline description cells) use uf_regular / uf_bold so the
    # correct Unicode font is selected per language.
    h2 = ParagraphStyle(
        "h2", parent=styles["Heading2"],
        fontSize=12.5, textColor=_NAVY, spaceBefore=12, spaceAfter=5,
        fontName="Helvetica-Bold",
    )
    body = ParagraphStyle(
        "body", parent=styles["Normal"],
        fontSize=9.3, textColor=_INK, leading=15,
        fontName=uf_regular,
    )
    muted = ParagraphStyle(
        "muted", parent=styles["Normal"],
        fontSize=8, textColor=_SUBTLE, leading=12,
        fontName="Helvetica",
    )
    stat_label = ParagraphStyle(
        "stat_label", parent=styles["Normal"],
        fontSize=8, textColor=_SUBTLE, leading=11,
        fontName="Helvetica",
    )
    stat_value = ParagraphStyle(
        "stat_value", parent=styles["Normal"],
        fontSize=10, textColor=_INK, leading=13, fontName="Helvetica-Bold",
    )
    watermark_style = ParagraphStyle(
        "watermark", parent=styles["Normal"], fontSize=7,
        textColor=colors.HexColor("#8DA0BA"),
        fontName="Helvetica", leading=10, alignment=2,  # TA_RIGHT
    )
    # Title and subtitle in the header band: user-generated, must use Unicode font
    title_style = ParagraphStyle(
        "title", parent=styles["Normal"], fontSize=21, textColor=_WHITE,
        fontName=uf_bold, leading=24, spaceBefore=0,
    )
    subtitle_style = ParagraphStyle(
        "subtitle", parent=styles["Normal"], fontSize=9.5,
        textColor=colors.HexColor("#C8D4E3"),
        fontName=uf_regular, leading=13, spaceBefore=5,
    )
    band_meta_style = ParagraphStyle(
        "band_meta", parent=styles["Normal"], fontSize=8.5,
        textColor=colors.HexColor("#8FA4BA"),
        fontName="Helvetica", leading=12, spaceBefore=8,
    )

    # ── Helper: shared header band ────────────────────────────────────────────
    def _build_header_band() -> Table:
        meta_parts = [p for p in [genre, mood, tempo, key, time_sig] if p]
        btc = [Paragraph(project_title, title_style)]
        if ai_title and ai_title != project_title:
            btc.append(Paragraph(f"\u201c{ai_title}\u201d", subtitle_style))
        if meta_parts:
            btc.append(HRFlowable(
                width="38%", thickness=0.5, color=colors.HexColor("#3A4A63"),
                spaceBefore=7, spaceAfter=7, hAlign="LEFT",
            ))
            btc.append(Paragraph("  \u00b7  ".join(meta_parts), band_meta_style))
        wmc = [Paragraph("HARMONYLEDGER  \u00b7  CREATIVE PASSPORT", watermark_style)]
        b = Table(
            [[btc, wmc]],
            colWidths=[frame_w - 66 * mm, 66 * mm],
        )
        b.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), _NAVY),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN",         (1, 0), (1, 0), "RIGHT"),
            ("TOPPADDING",    (0, 0), (-1, -1), 16),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
            ("LEFTPADDING",   (0, 0), (0, 0), 14),
            ("RIGHTPADDING",  (1, 0), (1, 0), 12),
        ]))
        return b

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 1 — Summary / Cover
    # ═════════════════════════════════════════════════════════════════════════

    story.append(_build_header_band())
    story.append(Spacer(1, 7 * mm))

    # Product positioning sub-heading
    story.append(Paragraph(
        "A provenance and authorship system for AI-assisted creative work",
        ParagraphStyle(
            "positioning", parent=styles["Normal"],
            fontSize=9, textColor=_SUBTLE, leading=14,
            fontName="Helvetica",
        ),
    ))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=0.75, color=_BORDER))
    story.append(Spacer(1, 5 * mm))

    # ── Summary stat grid ─────────────────────────────────────────────────────
    # Each cell is a two-row unit: small muted label above large bold value.
    # Only cells with real data are included — no invented placeholders.
    # NOTE: stat labels (SONG TITLE, LANGUAGE …) are always ASCII → Helvetica.
    #       stat values for user-generated fields (song title, project name)
    #       use the Unicode font so the actual text renders correctly.
    sum_label_style = ParagraphStyle(
        "sum_label", parent=styles["Normal"],
        fontSize=7.5, textColor=_SUBTLE, leading=10,
        fontName="Helvetica",
    )
    # Generic value style for non-user-text fields (dates, numbers, status)
    sum_value_style = ParagraphStyle(
        "sum_value", parent=styles["Normal"],
        fontSize=11.5, textColor=_INK, leading=14, fontName="Helvetica-Bold",
    )
    # Value style for fields that contain user-generated text (title, etc.)
    sum_value_unicode = ParagraphStyle(
        "sum_value_unicode", parent=styles["Normal"],
        fontSize=11.5, textColor=_INK, leading=14, fontName=uf_bold,
    )
    sum_value_green = ParagraphStyle(
        "sum_value_green", parent=sum_value_style, textColor=_GREEN,
    )
    sum_value_purple = ParagraphStyle(
        "sum_value_purple", parent=sum_value_style, textColor=_PURPLE,
    )

    _grid_ts = TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",   (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ])

    def _stat_cell(label: str, value: str, vstyle=None) -> list:
        return [Paragraph(label, sum_label_style),
                Paragraph(value, vstyle or sum_value_style)]

    def _even_cols(n: int) -> list:
        return [frame_w / n] * n

    # Row 1: song metadata
    # Song title is user-generated → use Unicode value style
    row1 = []
    if ai_title:
        row1.append(_stat_cell("SONG TITLE", ai_title, sum_value_unicode))
    if language:
        row1.append(_stat_cell("LANGUAGE", language))
    if genre:
        row1.append(_stat_cell("GENRE / STYLE", f"{genre}" + (f"  ·  {style}" if style and style != genre else "")))
    if model_used:
        row1.append(_stat_cell("AI MODEL", model_used))

    # Row 2: project provenance metadata (all ASCII / system values)
    row2 = []
    row2.append(_stat_cell("EXPORTED", exported_at))
    row2.append(_stat_cell("PROJECT STATUS", getattr(project, "status", "") or "—"))
    row2.append(_stat_cell("REVISION", str(project.version)))
    created_at_fmt = _fmt_ts(getattr(project, "created_at", ""), fallback="")
    if created_at_fmt:
        row2.append(_stat_cell("CREATED", created_at_fmt))

    # Row 3: creative action counts (all numeric)
    row3 = []
    if num_sections:
        row3.append(_stat_cell("SONG SECTIONS", str(num_sections)))
        row3.append(_stat_cell("LOCKED SECTIONS", str(num_locked)))
    row3.append(_stat_cell("HUMAN EDITS", str(num_human_edits)))
    row3.append(_stat_cell("AI REGENERATIONS", str(num_ai_regen)))
    row3.append(_stat_cell("CREATIVE DECISIONS", str(num_direction)))

    for row_cells in [row1, row2, row3]:
        if row_cells:
            row_tbl = Table([row_cells], colWidths=_even_cols(len(row_cells)))
            row_tbl.setStyle(_grid_ts)
            story.append(row_tbl)
            story.append(Spacer(1, 5 * mm))

    # ── Contribution summary (donut + stat grid) ──────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=_BORDER))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "Contribution Summary",
        ParagraphStyle("cs_h", parent=styles["Normal"],
                       fontSize=9, textColor=_NAVY,
                       fontName="Helvetica-Bold", leading=12, spaceAfter=4),
    ))

    sum_stat_rows = [
        [Paragraph("HUMAN AUTHORSHIP", sum_label_style),
         Paragraph(f"{human_pct:g}%", sum_value_green)],
        [Paragraph("AI AUTHORSHIP", sum_label_style),
         Paragraph(f"{ai_pct:g}%", sum_value_purple)],
        [Paragraph("DIRECTION SCORE", sum_label_style),
         Paragraph(f"{dir_score:g}%", sum_value_style)],
        [Paragraph("METHODOLOGY", sum_label_style),
         Paragraph(f"v{meth_version}", sum_value_style)],
    ]
    sum_stat_tbl = Table(sum_stat_rows, colWidths=[55 * mm, 65 * mm])
    sum_stat_tbl.setStyle(TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",   (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
    ]))
    sum_donut = _contribution_donut(human_pct, ai_pct, size_mm=40)
    sum_contrib_row = Table(
        [[sum_donut, sum_stat_tbl]],
        colWidths=[50 * mm, frame_w - 50 * mm],
    )
    sum_contrib_row.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(sum_contrib_row)
    story.append(Spacer(1, 5 * mm))

    # ── Non-legal disclaimer box ──────────────────────────────────────────────
    disclaimer_box = Table(
        [[Paragraph(
            CONTRIBUTION_DISCLAIMER,
            ParagraphStyle("disc_sum", parent=styles["Normal"],
                           fontSize=8, textColor=_INK, leading=12,
                           fontName="Helvetica-Oblique"),
        )]],
        colWidths=[frame_w],
    )
    disclaimer_box.setStyle(TableStyle([
        ("BOX",          (0, 0), (-1, -1), 0.75, _GOLD),
        ("BACKGROUND",   (0, 0), (-1, -1), colors.HexColor("#FDFBF5")),
        ("TOPPADDING",   (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 7),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(disclaimer_box)

    # Integrity line — only shown after at least one export
    if passport.get("exported_at"):
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(
            f"<b>Integrity:</b> source is project.json (append-only timeline)  "
            f"\u00b7  Passport ID: {watermark_id}  "
            f"\u00b7  Methodology v{meth_version}",
            ParagraphStyle("integrity", parent=styles["Normal"],
                           fontSize=7.5, textColor=_SUBTLE, leading=11,
                           fontName="Helvetica"),
        ))

    # Page break — detail pages follow
    story.append(PageBreak())

    # ═════════════════════════════════════════════════════════════════════════
    # PAGE 2+ — Detail: contribution split, sections, timeline, statement
    # ═════════════════════════════════════════════════════════════════════════

    story.append(_build_header_band())
    story.append(Spacer(1, 6 * mm))

    # ── Contribution Split ────────────────────────────────────────────────────
    story.append(Paragraph("Contribution Split", h2))

    stat_block = Table(
        [
            [Paragraph("HUMAN AUTHORSHIP", stat_label)],
            [Paragraph(f"{human_pct:g}%", ParagraphStyle(
                "hv", parent=stat_value, textColor=_GREEN, fontSize=15))],
            [Spacer(1, 2 * mm)],
            [Paragraph("AI AUTHORSHIP", stat_label)],
            [Paragraph(f"{ai_pct:g}%", ParagraphStyle(
                "av", parent=stat_value, textColor=_PURPLE, fontSize=15))],
            [Spacer(1, 2 * mm)],
            [Paragraph("DIRECTION SCORE — how much you steered the AI", stat_label)],
            [_score_bar(dir_score)],
            [Paragraph(f"{dir_score:g}%", stat_value)],
        ],
        colWidths=[70 * mm],
    )
    stat_block.setStyle(TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING",   (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 1),
    ]))

    donut_cell = Table(
        [[_contribution_donut(human_pct, ai_pct)]],
        colWidths=[45 * mm],
    )
    donut_cell.setStyle(TableStyle([("ALIGN", (0, 0), (0, 0), "CENTER")]))

    contrib_row = Table(
        [[donut_cell, stat_block]],
        colWidths=[45 * mm, frame_w - 45 * mm],
    )
    contrib_row.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(contrib_row)
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        f"Methodology v{meth_version} · last computed {computed_at}", muted,
    ))
    story.append(Spacer(1, 3 * mm))
    # Non-legal disclaimer on the detail page as well
    story.append(Paragraph(
        CONTRIBUTION_DISCLAIMER,
        ParagraphStyle("detail_disc", parent=styles["Normal"],
                       fontSize=7.5, textColor=_SUBTLE, leading=11,
                       fontName="Helvetica-Oblique"),
    ))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=0.75, color=_BORDER))
    story.append(Spacer(1, 4 * mm))

    # ── Section Authorship ────────────────────────────────────────────────────
    if sections:
        story.append(Paragraph("Section Authorship", h2))
        sec_data = [["", "Section", "Provenance", "Last Edited By"]]
        swatches = []
        for sec_key in _SECTION_ORDER:
            if sec_key not in sections:
                continue
            sec  = sections[sec_key]
            prov = _PROV_LABELS.get(sec.get("provenance", ""), sec.get("provenance", "—"))
            by   = sec.get("last_edited_by", "—")
            sec_data.append(["", _SECTION_LABELS.get(sec_key, sec_key), prov, by])
            swatches.append(_SECTION_COLORS.get(sec_key, _SUBTLE))

        # Widths sum to 170mm — the full frame width — so the table's right
        # edge aligns with the header band and the other tables.
        col_widths = [4 * mm, 45 * mm, 75 * mm, 46 * mm]
        sec_table = Table(sec_data, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND",   (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",    (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 9),
            ("TEXTCOLOR",    (1, 1), (-1, -1), _INK),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _ROW_ALT]),
            ("GRID",         (0, 0), (-1, -1), 0.5, _BORDER),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ]
        for i, swatch_color in enumerate(swatches, start=1):
            style_cmds.append(("BACKGROUND", (0, i), (0, i), swatch_color))
        sec_table.setStyle(TableStyle(style_cmds))
        story.append(sec_table)
        story.append(Spacer(1, 5 * mm))

    # ── Creative Timeline ─────────────────────────────────────────────────────
    story.append(Paragraph("Creative Timeline", h2))
    visible_events = [e for e in timeline if e.get("event_type") not in _TIMELINE_NOISE_EVENTS]
    omitted = len(timeline) - len(visible_events)

    if visible_events:
        # Rows are renumbered 1..N for print — the raw seq numbers have gaps
        # where filtered bookkeeping events sat, which reads as an error.
        tl_data = [["#", "Event", "Actor", "Description", "When"]]
        for row_no, event in enumerate(visible_events, start=1):
            tl_data.append([
                str(row_no),
                str(event.get("event_type", "")).replace("_", " "),
                str(event.get("actor", "")),
                (lambda d: d[:57] + "\u2026" if len(d) > 58 else d)(
                    str(event.get("description", ""))
                ),
                _fmt_ts(event.get("timestamp", "")),
            ])
        # Sums to 170mm (full frame width); "When" gets 36mm so a full
        # "Jul 18, 2026 · 9:00 PM" timestamp fits without clipping.
        col_widths = [8 * mm, 34 * mm, 16 * mm, 76 * mm, 36 * mm]
        tl_table = Table(tl_data, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND",   (0, 0), (-1, 0), _NAVY),
            ("TEXTCOLOR",    (0, 0), (-1, 0), _WHITE),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, 0), 8.5),
            ("TEXTCOLOR",    (0, 1), (-1, -1), _INK),
            # Description column uses Unicode font for user-generated text
            ("FONTNAME",     (3, 1), (3, -1), uf_regular),
            ("FONTSIZE",     (0, 1), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_WHITE, _ROW_ALT]),
            ("GRID",         (0, 0), (-1, -1), 0.5, _BORDER),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("LEFTPADDING",  (0, 0), (-1, -1), 5),
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ]
        for i, event in enumerate(visible_events, start=1):
            actor_color = _ACTOR_COLORS.get(event.get("actor"), _SUBTLE)
            style_cmds.append(("TEXTCOLOR", (2, i), (2, i), actor_color))
            style_cmds.append(("FONTNAME",  (2, i), (2, i), "Helvetica-Bold"))
        tl_table.setStyle(TableStyle(style_cmds))
        story.append(tl_table)
        if omitted:
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(
                f"({omitted} automatic contribution-recalculation event"
                f"{'s' if omitted != 1 else ''} omitted above for readability "
                f"— retained in full in the project's data file.)",
                muted,
            ))
    else:
        story.append(Paragraph("No timeline events recorded.", muted))

    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=0.75, color=_BORDER))
    story.append(Spacer(1, 4 * mm))

    # ── Transparency Statement ────────────────────────────────────────────────
    custom_statement = passport.get("transparency_statement", "").strip()
    authorship_line  = passport.get("authorship_line", "").strip()
    statement_text   = custom_statement or _DEFAULT_TRANSPARENCY.format(version=meth_version)

    # The transparency statement may be user-written in any language; use the
    # Unicode font so all scripts render correctly.
    quote_style = ParagraphStyle(
        "quote", parent=body, textColor=_INK, leftIndent=10, leading=15,
        fontName=uf_regular,
    )
    quote_cell = Table(
        [[Paragraph("Transparency Statement", h2)],
         [Paragraph(statement_text, quote_style)]],
        colWidths=[frame_w - 8],
    )
    quote_cell.setStyle(TableStyle([
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (0, 0), 4),
        ("BOTTOMPADDING",(0, -1), (0, -1), 8),
        ("LINEBEFORE",   (0, 0), (0, -1), 2.4, _GOLD),
    ]))
    # KeepTogether on the full quote block would push a long custom statement
    # onto a new page, leaving a blank gap. Append it as a plain flowable so
    # ReportLab can paginate within it if necessary.
    story.append(quote_cell)

    if authorship_line:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(authorship_line, ParagraphStyle(
            "auth", parent=styles["Normal"],
            fontSize=10, textColor=_NAVY, leading=13, fontName=uf_bold,
        )))

    # ── Provenance stamp ──────────────────────────────────────────────────────
    story.append(Spacer(1, 6 * mm))
    stamp = Table(
        [[Paragraph(
            f"<b>Project ID</b>  {project.project_id}<br/>"
            f"<b>Watermark</b>  {watermark_id}<br/>"
            f"<b>Exported</b>  {exported_at}  \u00b7  Project revision {project.version}",
            ParagraphStyle("stamp", parent=muted, leading=12, fontSize=7.5,
                            textColor=_SUBTLE, fontName="Helvetica"),
        )]],
        colWidths=[frame_w],
    )
    stamp.setStyle(TableStyle([
        ("BOX",          (0, 0), (-1, -1), 0.6, _BORDER),
        ("BACKGROUND",   (0, 0), (-1, -1), _ROW_ALT),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(stamp)

    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
