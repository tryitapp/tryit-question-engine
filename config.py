"""
TryIT Question Engine — Configuration
=======================================
Topics and subjects now live in your real Supabase tables (seeded by
seed_topics.py) — this file no longer hand-types them. What's left here:
the difficulty level scale, provider model defaults, and a small
topic_id -> diagram_kind lookup for the visual topics (since "which kind
of diagram" isn't a real column in the topics table — only is_visual is;
the specific kind comes from the same source seed_topics.py used).
"""

from seed_topics import SUBJECT_TOPICS

# ──────────────────────────────────────────────────────────
# DIFFICULTY LEVELS — unchanged from before, still the right scale
# ──────────────────────────────────────────────────────────
LEVELS = {
    1:  "LKG-UKG, picture-based, very simple",
    2:  "Class 1-4, basic operations",
    3:  "Class 5-7 (includes 6th standard), foundation concepts",
    4:  "Class 8-10, intermediate school",
    5:  "Class 11-12, advanced school",
    6:  "Graduate / foundation competitive level",
    7:  "SSC, Banking, Railways, TNPSC, State PSC — core competitive level",
    8:  "Professional: GATE, CAT, CLAT, NEET, JEE Advanced",
    9:  "UPSC Prelims / State PSC Mains / PG entrance",
    10: "UPSC Mains advanced, PhD entrance, research level",
}


def difficulty_label_for_level(level: int) -> str:
    """Maps the integer level scale to the text `difficulty` column your
    real questions table expects. Assumption — confirm this matches your
    actual convention if you have one already in use elsewhere."""
    if level <= 3:
        return "Easy"
    if level <= 6:
        return "Medium"
    if level <= 8:
        return "Hard"
    return "Expert"


def levels_from_difficulty_range(difficulty_range: str) -> list:
    """Parses a topics.difficulty_range string like '2-7' into [2,3,4,5,6,7].
    Falls back to a safe single mid-level if the format is unexpected,
    rather than crashing a whole job on one malformed row."""
    try:
        lo, hi = difficulty_range.split("-")
        lo, hi = int(lo), int(hi)
        return list(range(lo, hi + 1))
    except (ValueError, AttributeError):
        return [6]


# ──────────────────────────────────────────────────────────
# DIAGRAM KIND LOOKUP — derived from seed_topics.py, the same source that
# set is_visual on the real topics rows, so the two can't drift apart.
# ──────────────────────────────────────────────────────────
def _build_diagram_kind_lookup():
    lookup = {}
    for subject_id, (tier, topics) in SUBJECT_TOPICS.items():
        for topic_name, is_visual, diagram_kind, is_headline in topics:
            if not is_visual:
                continue
            slug = (
                topic_name.lower()
                .replace(",", "").replace("(", "").replace(")", "")
                .replace("/", "_").replace("-", "_").replace(" ", "_")
            )
            topic_id = f"{subject_id}_{slug}"
            lookup[topic_id] = diagram_kind
    return lookup


DIAGRAM_KIND_BY_TOPIC_ID = _build_diagram_kind_lookup()

# ──────────────────────────────────────────────────────────
# PROVIDER MODEL DEFAULTS
# ──────────────────────────────────────────────────────────
PROVIDER_MODELS = {
    "cerebras":   "llama-3.3-70b",
    "groq_fast":  "llama-3.1-8b-instant",
    "groq_strong":"llama-3.3-70b-versatile",
    "gemini":     "gemini-2.5-flash",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "mistral":    "mistral-small-latest",
}

QUALITY_SCORE_THRESHOLD = 7  # out of 10
JSON_BATCH_SIZE = 300        # questions per output JSON file
DEFAULT_ACCESS_TIER = "free"        # assumption — adjust if you already have a tiering convention
DEFAULT_PATTERN_TYPE = "standalone_mcq4"  # assumption — adjust per topic/exam pattern as needed
