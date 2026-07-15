# ---------------------------------------------------------------------------
# Song Genre Presets & Vibe Modifiers
#
# Used by pages/create_project.py to pre-fill the Song Vibe field so
# creators can start from a strong template rather than a blank canvas.
#
# Design principle: presets FILL, not LOCK.  The user always edits the
# text freely after clicking — they remain the author.
# ---------------------------------------------------------------------------

GENRE_PRESETS: dict[str, dict] = {
    "🎸 Indie Folk": {
        "genre": "Indie Folk",
        "vibe": (
            "Acoustic guitar-driven, intimate storytelling. "
            "Warm, melancholic mood with a sense of quiet hope. "
            "Tempo: slow to mid. Instruments: fingerpicked guitar, cello, "
            "brushed drums, sparse piano. Emotional register: vulnerable, honest."
        ),
    },
    "🌙 Dark R&B": {
        "genre": "Dark R&B",
        "vibe": (
            "Moody, sensual atmosphere. Late-night feel with reverb-heavy vocals. "
            "Minor key, synth pads, 808 bass, sparse snare. "
            "Tempo: slow. Emotional register: longing, introspection."
        ),
    },
    "⚡ Alt-Pop Anthem": {
        "genre": "Alt-Pop",
        "vibe": (
            "Explosive chorus energy with a cinematic build. "
            "Layered synths, punchy drums, anthemic hook. "
            "Tempo: mid-fast. Emotional register: empowerment, catharsis."
        ),
    },
    "🎹 Neo-Soul Ballad": {
        "genre": "Neo-Soul",
        "vibe": (
            "Rich chord progressions, jazz-influenced harmony. "
            "Warm Rhodes, smooth bass, light percussion. "
            "Tempo: slow to mid. Emotional register: soulful, romantic."
        ),
    },
    "🌊 Chillwave / Lo-fi": {
        "genre": "Chillwave",
        "vibe": (
            "Hazy, nostalgic texture. Tape-saturated drums, detuned synths, "
            "relaxed groove. Tempo: slow. "
            "Emotional register: dreamy, introspective, comfortable."
        ),
    },
    "🔥 Trap Soul": {
        "genre": "Trap Soul",
        "vibe": (
            "Minimalist trap beat with soulful vocal melody. "
            "Hi-hat rolls, 808s, pitched harmonies. "
            "Tempo: slow trap. Emotional register: vulnerability, confidence."
        ),
    },
    "✨ Ethereal Pop": {
        "genre": "Ethereal Pop",
        "vibe": (
            "Lush, otherworldly soundscape. Reverb-soaked vocals, shimmering "
            "arpeggios, ambient pads. Tempo: floating. "
            "Emotional register: wonder, escapism."
        ),
    },
    "🎺 Jazz Noir": {
        "genre": "Jazz / Noir",
        "vibe": (
            "Smoky, cinematic, late-night. Muted trumpet, upright bass, brushed "
            "snare, sparse piano comping. "
            "Tempo: mid-slow swing. Emotional register: mysterious, melancholic."
        ),
    },
    "🎻 Cinematic Orchestral": {
        "genre": "Cinematic / Orchestral",
        "vibe": (
            "Sweeping strings, brass swells, deep percussion. "
            "Epic emotional arc with a quiet intimate opening and a soaring climax. "
            "Tempo: slow build to dramatic. Emotional register: heroic, bittersweet."
        ),
    },
    "🌴 Afrobeats": {
        "genre": "Afrobeats",
        "vibe": (
            "Infectious groove with layered percussion, talking drum, and bass-heavy "
            "production. Bright, celebratory energy. "
            "Tempo: mid-fast. Emotional register: joyful, vibrant, communal."
        ),
    },
}

# ---------------------------------------------------------------------------
# Vibe Modifiers — short descriptors that append to (not replace) the
# preset vibe, letting users mix-and-match texture on top of a genre base.
# ---------------------------------------------------------------------------
VIBE_MODIFIERS: list[dict] = [
    {"label": "🌧️ Rain / Storm",       "text": "Ambient rain and distant thunder in the sonic background."},
    {"label": "🌅 Golden Hour",         "text": "Warm, sun-drenched tonal quality — like late afternoon light."},
    {"label": "🌃 City at Night",       "text": "Urban nighttime energy: distant sirens, neon glow, restless streets."},
    {"label": "💔 Heartbreak",          "text": "Underlying emotional weight of loss and longing."},
    {"label": "🎉 Euphoric / Uplifting","text": "Celebratory lift — chorus should feel like a release of joy."},
    {"label": "🤫 Intimate / Whispered","text": "Close-mic intimacy, hushed delivery, minimal space."},
    {"label": "⚡ High Energy",         "text": "Urgent, driving tempo — listener should feel propelled forward."},
    {"label": "🕯️ Stripped Back",       "text": "Candlelit acoustic simplicity — no production excess."},
    {"label": "🌌 Cosmic / Spacey",     "text": "Wide reverbs, alien textures, sense of infinite space."},
    {"label": "🏙️ Nostalgic / Retro",   "text": "Vintage production feel — tape warmth, analog character."},
]
