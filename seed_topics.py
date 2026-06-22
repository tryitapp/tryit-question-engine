"""
TryIT Question Engine — Topic Seeder
========================================
Populates the (currently empty) `topics` table using your real 42
subjects and real exam section data as the grounding signal for
crowded/medium/niche tiering — not guesswork.

Tier classification logic (grounded in exam_marking_schemes.section_config):
  Reasoning, Quant/Maths, English, GK sections appear across nearly every
  general competitive exam (SSC, Banking, Railways, State PSC, Defence
  written tests) -> CROWDED
  Physics/Chemistry/Biology/Computer/standalone History/Geography/Polity/
  Economy appear for specific but still large exam clusters (NEET, JEE,
  UPSC Mains, IT-sector exams) -> MEDIUM
  Accountancy, Management, Law, Agriculture, Engineering-subject, Hindi,
  Regional Languages serve specific professional streams only -> NICHE

Only LEAF subjects get topics (maths/english/reasoning/general_knowledge
are umbrella parents for display grouping — their children hold the
actual content).

is_visual is only set True for topics whose diagram type is ALREADY
supported by diagrams.py / geometry_engine.py (geometry_svg, chart_data,
nonverbal_mirror_svg, paper_fold, embedded_figure). Marking a topic
visual without a working validator would silently produce unverified
diagrams — same principle we used for maps/embedded-figures earlier.
Expanding this list later means building the matching validator first.
"""

import os
import requests

REQUEST_TIMEOUT = 30

# ──────────────────────────────────────────────────────────
# TIER -> per-topic question_target floor
# ──────────────────────────────────────────────────────────
TIER_TARGETS = {"crowded": 25000, "crowded_headline": 30000, "medium": 15000, "niche": 8000}

# ──────────────────────────────────────────────────────────
# SUBJECT -> (tier, [topics])
# Each topic: (topic_name, is_visual, diagram_kind_or_None, is_headline)
# is_headline bumps a crowded topic to the higher 30k floor — reserved for
# the 2-3 topics within a subject that show up in literally every exam.
# ──────────────────────────────────────────────────────────
SUBJECT_TOPICS = {
    "maths_arithmetic": ("crowded", [
        ("Number System", False, None, True),
        ("Percentage", False, None, True),
        ("Profit, Loss and Discount", False, None, True),
        ("Ratio and Proportion", False, None, False),
        ("Simple and Compound Interest", False, None, False),
        ("Time, Speed and Distance", False, None, False),
        ("Time and Work", False, None, False),
        ("Average", False, None, False),
        ("Mixture and Alligation", False, None, False),
        ("Partnership", False, None, False),
    ]),
    "maths_algebra": ("crowded", [
        ("Linear Equations", False, None, False),
        ("Quadratic Equations", False, None, False),
        ("Polynomials", False, None, False),
        ("Algebraic Identities", False, None, False),
        ("Progressions (AP/GP)", False, None, False),
    ]),
    "maths_geometry": ("crowded", [
        ("Triangles", True, "geometry_svg", True),
        ("Circles", True, "geometry_svg", False),
        ("Quadrilaterals and Polygons", True, "geometry_svg", False),
        ("Coordinate Geometry", True, "geometry_svg", False),
        ("Mensuration 2D", True, "geometry_svg", False),
        ("Mensuration 3D", True, "geometry_svg", False),
    ]),
    "maths_trigonometry": ("medium", [
        ("Trigonometric Ratios and Identities", True, "geometry_svg", False),
        ("Heights and Distances", True, "geometry_svg", True),
    ]),
    "maths_stats": ("crowded", [
        ("Mean, Median and Mode", False, None, False),
        ("Bar and Line Graph Interpretation", True, "chart_data", True),
        ("Pie Chart Interpretation", True, "chart_data", False),
        ("Tabular Data Interpretation", True, "chart_data", False),
        ("Probability Basics", False, None, False),
    ]),
    "data_interpretation": ("crowded", [
        ("Caselet-Based DI", True, "chart_data", True),
        ("Mixed Graph DI", True, "chart_data", False),
        ("Data Sufficiency", False, None, False),
    ]),
    "maths_calculus": ("medium", [
        ("Limits and Continuity", False, None, False),
        ("Differentiation", False, None, False),
        ("Integration", False, None, False),
    ]),

    "reasoning_verbal": ("crowded", [
        ("Analogy", False, None, True),
        ("Classification (Odd One Out)", False, None, False),
        ("Series Completion", False, None, True),
        ("Coding-Decoding", False, None, False),
        ("Blood Relations", False, None, False),
        ("Syllogism", False, None, False),
        ("Seating Arrangement", False, None, True),
        ("Direction Sense", False, None, False),
        ("Statement and Conclusion", False, None, False),
        ("Puzzle (Linear/Circular)", False, None, False),
    ]),
    "reasoning_nonverbal": ("crowded", [
        ("Mirror Image", True, "nonverbal_mirror_svg", True),
        ("Paper Folding", True, "paper_fold", True),
        ("Embedded Figures", True, "embedded_figure", False),
        ("Figure Series", False, None, False),
        ("Water Image", False, None, False),
    ]),
    "reasoning_critical": ("crowded", [
        ("Statement and Assumption", False, None, False),
        ("Course of Action", False, None, False),
        ("Cause and Effect", False, None, False),
        ("Logical Sequence of Events", False, None, False),
    ]),

    "english_grammar": ("crowded", [
        ("Tenses", False, None, True),
        ("Articles and Determiners", False, None, False),
        ("Prepositions", False, None, False),
        ("Subject-Verb Agreement", False, None, False),
        ("Error Spotting", False, None, True),
        ("Sentence Improvement", False, None, False),
        ("Active and Passive Voice", False, None, False),
        ("Direct and Indirect Speech", False, None, False),
    ]),
    "english_vocab": ("crowded", [
        ("Synonyms and Antonyms", False, None, True),
        ("One Word Substitution", False, None, False),
        ("Idioms and Phrases", False, None, False),
        ("Spelling Correction", False, None, False),
        ("Homophones", False, None, False),
    ]),
    "english_reading": ("crowded", [
        ("Main Idea and Inference", False, None, True),
        ("Vocabulary in Context", False, None, False),
        ("Author's Tone and Attitude", False, None, False),
        ("Para Jumbles", False, None, False),
        ("Cloze Test", False, None, False),
    ]),
    "english_writing": ("medium", [
        ("Essay Writing", False, None, False),
        ("Letter and Application Writing", False, None, False),
        ("Precis Writing", False, None, False),
    ]),

    "gk_history": ("crowded", [
        ("Ancient India", False, None, False),
        ("Medieval India", False, None, False),
        ("Modern India and Freedom Movement", False, None, True),
        ("World History Key Events", False, None, False),
    ]),
    "gk_polity": ("crowded", [
        ("Constitution Basics", False, None, True),
        ("Fundamental Rights and Duties", False, None, False),
        ("Parliament and Legislature", False, None, False),
        ("Judiciary and Constitutional Bodies", False, None, False),
        ("Panchayati Raj", False, None, False),
    ]),
    "gk_geography": ("crowded", [
        ("Indian Physical Geography", False, None, False),
        ("Indian Rivers and Mountains", False, None, False),
        ("World Geography Basics", False, None, False),
        ("Climate and Natural Resources", False, None, False),
    ]),
    "gk_economy": ("crowded", [
        ("Basic Economic Concepts", False, None, False),
        ("Indian Economy Overview", False, None, True),
        ("Government Schemes", False, None, False),
        ("Banking and Financial Institutions", False, None, False),
    ]),
    "gk_science": ("crowded", [
        ("Science and Technology Current Affairs", False, None, False),
        ("Space and Defence Technology", False, None, False),
        ("Inventions and Discoveries", False, None, False),
    ]),
    "gk_sports": ("crowded", [
        ("Major Tournaments and Champions", False, None, False),
        ("Sports Awards and Records", False, None, False),
        ("Olympics and International Games", False, None, False),
    ]),
    "gk_awards": ("crowded", [
        ("National Awards", False, None, False),
        ("International Awards", False, None, False),
        ("Nobel Prize Highlights", False, None, False),
    ]),
    "gk_india": ("crowded", [
        ("States, Capitals and UTs", False, None, True),
        ("National Symbols", False, None, False),
        ("Important Days and Events", False, None, False),
    ]),
    "current_affairs": ("crowded", [
        ("National News and Schemes", False, None, True),
        ("International Affairs", False, None, False),
        ("Appointments and Resignations", False, None, False),
        ("Summits and Conferences", False, None, False),
    ]),

    "physics": ("medium", [
        ("Mechanics", False, None, False),
        ("Electricity and Magnetism", False, None, False),
        ("Optics", False, None, False),
        ("Modern Physics", False, None, False),
        ("Thermodynamics", False, None, False),
    ]),
    "chemistry": ("medium", [
        ("Organic Chemistry Basics", False, None, False),
        ("Inorganic Chemistry Basics", False, None, False),
        ("Physical Chemistry Basics", False, None, False),
        ("Periodic Table and Bonding", False, None, False),
    ]),
    "biology": ("medium", [
        ("Cell Biology and Genetics", False, None, False),
        ("Human Physiology", False, None, False),
        ("Plant Physiology", False, None, False),
        ("Ecology and Environment", False, None, False),
    ]),
    "science_gen": ("medium", [
        ("General Science Facts", False, None, False),
        ("Everyday Science Applications", False, None, False),
        ("Health and Nutrition Basics", False, None, False),
    ]),
    "computer": ("medium", [
        ("Computer Fundamentals", False, None, False),
        ("Internet and Networking Basics", False, None, False),
        ("MS Office Basics", False, None, False),
        ("Cybersecurity Awareness", False, None, False),
    ]),
    "environment": ("medium", [
        ("Ecosystem and Biodiversity", False, None, False),
        ("Climate Change and Pollution", False, None, False),
        ("Environmental Conventions and Policy", False, None, False),
    ]),
    "history": ("medium", [
        ("Indian National Movement (Detailed)", False, None, False),
        ("Post-Independence India", False, None, False),
        ("Ancient and Medieval Dynasties (Detailed)", False, None, False),
    ]),
    "geography": ("medium", [
        ("Physical Geography (Detailed)", False, None, False),
        ("Economic Geography", False, None, False),
        ("Population and Settlement", False, None, False),
    ]),
    "polity": ("medium", [
        ("Constitutional History (Detailed)", False, None, False),
        ("Centre-State Relations", False, None, False),
        ("Amendments and Landmark Judgments", False, None, False),
    ]),
    "economy": ("medium", [
        ("Five Year Plans and NITI Aayog", False, None, False),
        ("Budget and Fiscal Policy", False, None, False),
        ("Monetary Policy and RBI", False, None, False),
    ]),

    "accountancy": ("niche", [
        ("Basic Accounting Principles", False, None, False),
        ("Financial Statements", False, None, False),
        ("Cost Accounting Basics", False, None, False),
        ("Taxation Basics", False, None, False),
    ]),
    "management_sub": ("niche", [
        ("Principles of Management", False, None, False),
        ("Marketing Fundamentals", False, None, False),
        ("HR Management Basics", False, None, False),
    ]),
    "law_sub": ("niche", [
        ("Constitutional Law Basics", False, None, False),
        ("Law of Torts", False, None, False),
        ("Contract Law Basics", False, None, False),
        ("Legal Reasoning", False, None, False),
    ]),
    "agriculture_sub": ("niche", [
        ("Crop Production Basics", False, None, False),
        ("Soil Science Basics", False, None, False),
        ("Agricultural Schemes and Policy", False, None, False),
    ]),
    "engineering_sub": ("niche", [
        ("Basic Engineering Mechanics", False, None, False),
        ("Engineering Mathematics Basics", False, None, False),
        ("Electrical and Electronics Basics", False, None, False),
    ]),
    "hindi": ("niche", [
        ("Hindi Grammar Basics", False, None, False),
        ("Hindi Vocabulary", False, None, False),
        ("Hindi Comprehension", False, None, False),
    ]),
    "regional_lang": ("niche", [
        ("Regional Language Grammar Basics", False, None, False),
        ("Regional Language Vocabulary", False, None, False),
    ]),
}


DIFFICULTY_RANGE_BY_TIER = {
    "crowded": "2-7",  # broadly testable from upper-school through mid-competitive level
    "medium": "4-8",   # stream-specific (NEET/JEE/UPSC Mains depth)
    "niche": "6-9",    # professional/graduate-level only
}


def build_topic_rows():
    rows = []
    for subject_id, (tier, topics) in SUBJECT_TOPICS.items():
        for display_order, (topic_name, is_visual, diagram_kind, is_headline) in enumerate(topics, start=1):
            slug = (
                topic_name.lower()
                .replace(",", "")
                .replace("(", "").replace(")", "")
                .replace("/", "_").replace("-", "_").replace(" ", "_")
            )
            topic_id = f"{subject_id}_{slug}"
            target_key = "crowded_headline" if (tier == "crowded" and is_headline) else tier
            rows.append({
                "topic_id": topic_id,
                "subject_id": subject_id,
                "topic_name": topic_name,
                "topic_name_hi": None,  # left for a dedicated, native-reviewed translation pass
                "topic_name_ta": None,
                "parent_topic_id": None,
                "difficulty_range": DIFFICULTY_RANGE_BY_TIER[tier],  # still an assumption — confirm against your actual convention
                "is_visual": is_visual,
                "coverage_score": {"crowded": 90, "medium": 60, "niche": 30}[tier],
                "question_target": TIER_TARGETS[target_key],
                "questions_available": 0,
                "display_order": display_order,
                "_diagram_kind": diagram_kind,  # not a real column, used by config.py sync below
            })
    return rows


def push_topics(rows, batch_size=50):
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        print("SUPABASE_URL/SUPABASE_KEY not set — nothing pushed")
        return 0

    saved = 0
    for i in range(0, len(rows), batch_size):
        batch = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows[i:i + batch_size]]
        r = requests.post(
            f"{url}/rest/v1/topics",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"},
            json=batch, timeout=REQUEST_TIMEOUT,
        )
        if r.status_code in (200, 201):
            saved += len(batch)
        else:
            print(f"  error {r.status_code}: {r.text[:200]}")
    return saved


if __name__ == "__main__":
    rows = build_topic_rows()
    print(f"Built {len(rows)} topics across {len(SUBJECT_TOPICS)} subjects")
    tier_counts = {}
    for subject_id, (tier, topics) in SUBJECT_TOPICS.items():
        tier_counts[tier] = tier_counts.get(tier, 0) + len(topics)
    for tier, count in tier_counts.items():
        print(f"  {tier}: {count} topics")

    saved = push_topics(rows)
    print(f"Pushed {saved}/{len(rows)} to Supabase")
