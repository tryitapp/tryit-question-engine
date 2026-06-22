"""
TryIT Question Engine — Supabase Data Layer
==============================================
Reads real subjects/topics from your actual database instead of a
hand-typed config.py tree. This module is READ-ONLY for topics/subjects
— per your confirmation, topic_question_targets and the topics
quota fields are auto-maintained by the database, so the pipeline never
writes to them directly, only to `questions`.

Results are cached in-memory for the lifetime of one pipeline run (these
don't change mid-run), so a single `python pipeline.py` invocation only
fetches each table once no matter how many jobs it processes.
"""

import os
import requests

REQUEST_TIMEOUT = 30
_cache = {}


def _supabase_conf():
    return os.environ.get("SUPABASE_URL", "").strip(), os.environ.get("SUPABASE_KEY", "").strip()


def _get_all_rows(table, select="*", order=None):
    url, key = _supabase_conf()
    if not url or not key:
        raise RuntimeError(f"SUPABASE_URL/SUPABASE_KEY not set — cannot read {table}")

    rows, offset, page_size = [], 0, 1000
    while True:
        params = {"select": select, "limit": page_size, "offset": offset}
        if order:
            params["order"] = order
        r = requests.get(
            f"{url}/rest/v1/{table}",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            params=params, timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Failed to read {table}: {r.status_code} {r.text[:200]}")
        page = r.json()
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return rows


def fetch_subjects(force_refresh=False):
    """Returns {subject_id: {subject_name, parent_id, stream}}"""
    if not force_refresh and "subjects" in _cache:
        return _cache["subjects"]
    rows = _get_all_rows("subjects")
    result = {r["subject_id"]: r for r in rows}
    _cache["subjects"] = result
    return result


def fetch_topics(force_refresh=False):
    """Returns list of topic dicts, ordered by coverage_score descending
    (the real-world equivalent of our old 'crowded tier first' ordering —
    coverage_score was set by seed_topics.py based on real exam-section
    frequency, not a guess)."""
    if not force_refresh and "topics" in _cache:
        return _cache["topics"]
    rows = _get_all_rows("topics", order="coverage_score.desc")
    _cache["topics"] = rows
    return rows


def fetch_topic_by_id(topic_id):
    for t in fetch_topics():
        if t["topic_id"] == topic_id:
            return t
    return None


def clear_cache():
    _cache.clear()
