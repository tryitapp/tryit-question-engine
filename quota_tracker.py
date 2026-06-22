"""
TryIT Question Engine — Quota Tracker
========================================
Reads real topic quotas straight from Supabase: each topic row already
has question_target (the floor) and questions_available (the live
count, auto-maintained by the database per your confirmation). No more
guessed crowded/medium/niche tiers — topics are processed in
coverage_score order, which seed_topics.py set from real exam-section
frequency data, not a guess.
"""

from config import levels_from_difficulty_range
from supabase_data import fetch_topics


def build_today_jobs(questions_per_job: int = 15, max_jobs: int = None) -> list:
    """Returns a list of (topic_id, level, count_to_generate) tuples,
    highest coverage_score first, skipping any topic+level cell that's
    already met its question_target."""
    jobs = []
    topics = fetch_topics()  # already ordered by coverage_score desc

    for topic in topics:
        topic_id = topic["topic_id"]
        target = topic.get("question_target") or 0
        available = topic.get("questions_available") or 0
        if target <= 0:
            continue

        levels = levels_from_difficulty_range(topic.get("difficulty_range", ""))
        per_level_floor = max(target // len(levels), questions_per_job)

        # questions_available is a topic-level total (not per-level), so
        # split the remaining work evenly across this topic's levels —
        # an approximation, since the database doesn't track progress
        # per-level, only per-topic.
        remaining_total = target - available
        if remaining_total <= 0:
            continue
        remaining_per_level = max(remaining_total // len(levels), 0)

        for level in levels:
            count = min(remaining_per_level, questions_per_job) if remaining_per_level > 0 else 0
            if count <= 0:
                continue
            jobs.append((topic_id, level, count))

    if max_jobs:
        jobs = jobs[:max_jobs]
    return jobs


def progress_report() -> str:
    """Human-readable summary of floor progress, highest-priority topics first."""
    lines = []
    topics = fetch_topics()
    for topic in topics:
        target = topic.get("question_target") or 0
        available = topic.get("questions_available") or 0
        pct = (available / target * 100) if target else 0
        lines.append(f"  {topic['topic_id']:45s} {available:>6}/{target:<6} ({pct:5.1f}%)  coverage={topic.get('coverage_score')}")
    return "\n".join(lines)
