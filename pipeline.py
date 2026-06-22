"""
TryIT Question Engine — Main Pipeline
========================================
Run this file. It pulls today's job list from quota_tracker (highest
coverage_score first, sourced from real Supabase data), and for each
job: generates -> parses -> decency-checks -> dedup-checks -> verifies
with two independent models -> writes a local JSON batch file -> pushes
the verified rows to Supabase, matching your REAL questions table schema.

Usage:
    python pipeline.py                  # run the full priority-ordered queue
    python pipeline.py --max-jobs 5     # just a handful, for testing
    python pipeline.py --report         # print quota progress and exit
    python pipeline.py --dry-run        # generate+verify but don't push to Supabase

NOTE on exam_tags: this still writes an empty list for exam_tags on every
record. Wiring real exam_topic_weightage data in is a separate next step
(needs to confirm that table actually has data first) — not faked here.
"""

import os
import json
import time
import uuid
import argparse
from datetime import datetime, timezone

import requests

from config import (
    LEVELS, PROVIDER_MODELS, QUALITY_SCORE_THRESHOLD, JSON_BATCH_SIZE,
    DIAGRAM_KIND_BY_TOPIC_ID, DEFAULT_ACCESS_TIER, DEFAULT_PATTERN_TYPE,
    difficulty_label_for_level,
)
from content_rules import (
    COPYRIGHT_INSTRUCTION, build_explanation_prompt_block, DECENCY_RULES,
    PROFANITY_TRIPWIRE_EN,
)
from diagrams import diagram_instruction_for, validate_diagram
import geometry_engine
from providers import (
    call_with_failover, GENERATION_CHAIN, VERIFICATION_CHAIN_1,
    VERIFICATION_CHAIN_2,
)
from dedup import filter_duplicates
from quota_tracker import build_today_jobs, progress_report
from supabase_data import fetch_topic_by_id, fetch_subjects

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
PENDING_REVIEW_PATH = os.path.join(OUTPUT_DIR, "pending_review.jsonl")


def _topic_and_subject(topic_id: str):
    """Fetches real topic + subject metadata once per job. Raises a
    clear error if the topic_id doesn't actually exist in Supabase,
    rather than silently generating against nothing."""
    topic = fetch_topic_by_id(topic_id)
    if not topic:
        raise ValueError(f"topic_id '{topic_id}' not found in Supabase topics table")
    subjects = fetch_subjects()
    subject = subjects.get(topic["subject_id"], {})
    return topic, subject


# ──────────────────────────────────────────────────────────
# STAGE A — GENERATION
# ──────────────────────────────────────────────────────────
def build_generation_prompt(topic_id: str, level: int, count: int) -> str:
    topic, subject = _topic_and_subject(topic_id)
    level_desc = LEVELS.get(level, "competitive level")
    diagram_kind = DIAGRAM_KIND_BY_TOPIC_ID.get(topic_id)

    diagram_block = ""
    if topic.get("is_visual") and diagram_kind:
        diagram_block = "\n" + diagram_instruction_for(diagram_kind) + "\n"

    return f"""You are an expert Indian competitive exam question writer.

SUBJECT: {subject.get('subject_name', topic['subject_id'])} | TOPIC: {topic['topic_name']}
DIFFICULTY LEVEL: {level} ({level_desc})
NUMBER OF QUESTIONS: {count}

{COPYRIGHT_INSTRUCTION}

{DECENCY_RULES}

FORMAT: Standard MCQ with exactly 4 options (A, B, C, D), only one correct.

{build_explanation_prompt_block()}
{diagram_block}
Return ONLY a JSON array, no markdown fences, no commentary. Each item:
{{
  "question": "...",
  "options": ["A text", "B text", "C text", "D text"],
  "correct_answer": 0,
  "why_correct": "...",
  "why_wrong_option_b": "...",
  "why_wrong_option_c": "...",
  "why_wrong_option_d": "...",
  "story_explanation": "...",
  "shortcut_tips": "...",
  "cross_exam_intelligence": "..."
}}
{"Also include the diagram fields described above in EVERY item — a question in this topic without its diagram is incomplete and will be rejected." if diagram_block else ""}
"""


def generate_batch(topic_id: str, level: int, count: int):
    prompt = build_generation_prompt(topic_id, level, count)
    text, provider = call_with_failover(prompt, GENERATION_CHAIN, label=f"generate:{topic_id}:L{level}")
    return text, provider


# ──────────────────────────────────────────────────────────
# GEOMETRY-FIRST PATH — paper folding & embedded figures
# ──────────────────────────────────────────────────────────
GEOMETRY_GENERATORS = {
    "paper_fold": geometry_engine.generate_paper_fold_geometry,
    "embedded_figure": geometry_engine.generate_embedded_figure_geometry,
}


def build_geometry_first_prompt(topic_id: str, level: int, scenarios: list) -> str:
    topic, subject = _topic_and_subject(topic_id)
    level_desc = LEVELS.get(level, "competitive level")
    items_desc = "\n".join(
        f"{i + 1}. {s['scenario_text']} The correct option is option "
        f"{s['correct_letter']} — this is FIXED, do not contradict it or "
        f"invent different reasoning."
        for i, s in enumerate(scenarios)
    )

    return f"""You are an expert Indian competitive exam question writer.

SUBJECT: {subject.get('subject_name', topic['subject_id'])} | TOPIC: {topic['topic_name']}
DIFFICULTY LEVEL: {level} ({level_desc})

{COPYRIGHT_INSTRUCTION}

{DECENCY_RULES}

The diagrams for these questions are ALREADY BUILT and already correct —
your only job is the question stem and explanation text. Do not describe,
redraw, or second-guess the geometry; just write around it.

{build_explanation_prompt_block()}

SCENARIOS:
{items_desc}

Return ONLY a JSON array of {len(scenarios)} objects, in the same order,
each with exactly these fields (no "options" or "correct_answer" — those
are already fixed):
{{
  "question": "...",
  "why_correct": "...",
  "why_wrong_option_b": "...",
  "why_wrong_option_c": "...",
  "why_wrong_option_d": "...",
  "story_explanation": "...",
  "shortcut_tips": "...",
  "cross_exam_intelligence": "..."
}}
"""


def generate_geometry_first_batch(topic_id: str, level: int, count: int):
    diagram_kind = DIAGRAM_KIND_BY_TOPIC_ID[topic_id]
    generator_fn = GEOMETRY_GENERATORS[diagram_kind]

    geometries = [generator_fn() for _ in range(count)]
    scenarios = [
        {"scenario_text": g["scenario_text"], "correct_letter": "ABCD"[g["correct_answer"]]}
        for g in geometries
    ]

    prompt = build_geometry_first_prompt(topic_id, level, scenarios)
    text, provider = call_with_failover(prompt, GENERATION_CHAIN, label=f"geo-generate:{topic_id}:L{level}")
    if not text:
        return [], None

    text_items = parse_questions(text)
    if len(text_items) != len(geometries):
        n = min(len(text_items), len(geometries))
        text_items, geometries = text_items[:n], geometries[:n]

    merged = []
    for text_fields, geom in zip(text_items, geometries):
        q = dict(text_fields)
        q["options"] = ["Option A", "Option B", "Option C", "Option D"]
        q["correct_answer"] = geom["correct_answer"]
        q["diagram_svg"] = geom["diagram_svg"]
        q["option_svgs"] = geom["option_svgs"]
        q["diagram_meta"] = geom["diagram_meta"]
        merged.append(q)
    return merged, provider


def parse_questions(raw_text: str):
    if not raw_text:
        return []
    text = raw_text.strip()
    text = text.replace("```json", "").replace("```", "")
    start = text.find("[")
    end = text.rfind("]") + 1
    if start == -1 or end <= start:
        if start != -1:
            print(f"   [parse] found '[' but no closing ']' at all in {len(text)} chars — "
                  f"almost certainly TRUNCATED mid-output (hit the token limit). "
                  f"Last 150 chars: {text[-150:]!r}")
        else:
            print(f"   [parse] no JSON array found anywhere — response started with: {text[:150]!r}")
        return []
    try:
        result = json.loads(text[start:end])
        return result if isinstance(result, list) else []
    except json.JSONDecodeError as e:
        tail = text[max(0, end - 200):end]
        print(f"   [parse] JSON error: {e}")
        print(f"   [parse] response length {len(text)} chars — last 200 chars before the closing ']': {tail!r}")
        if not tail.rstrip().endswith("}"):
            print("   [parse] looks TRUNCATED (doesn't end cleanly on a closing brace) — "
                  "likely hit the model's output token limit for this batch size")
        return []


def decency_tripwire(question: dict) -> bool:
    blob = json.dumps(question).lower()
    return not any(bad in blob for bad in PROFANITY_TRIPWIRE_EN)


def build_verification_prompt(question: dict) -> str:
    return f"""Check this exam question for correctness and quality.

QUESTION: {question.get('question')}
OPTIONS: {question.get('options')}
MARKED CORRECT ANSWER (0-indexed): {question.get('correct_answer')}

Respond with ONLY a JSON object, no commentary:
{{
  "answer_is_correct": true or false,
  "factual_error_found": true or false,
  "quality_score": 1-10,
  "reason": "one short sentence"
}}

Score 1-10 based on: clarity (2pts), plausibility of wrong options (2pts),
explanation quality (2pts), cultural relevance (2pts), uniqueness (2pts).
"""


def verify_question(question: dict):
    prompt = build_verification_prompt(question)

    text1, _ = call_with_failover(prompt, VERIFICATION_CHAIN_1,
                                   model_override=PROVIDER_MODELS["groq_strong"],
                                   label="verify1")
    text2, _ = call_with_failover(prompt, VERIFICATION_CHAIN_2, label="verify2")

    result1 = _parse_verification(text1)
    result2 = _parse_verification(text2)

    votes_correct = sum(1 for r in (result1, result2) if r and r.get("answer_is_correct"))
    any_factual_error = any(r and r.get("factual_error_found") for r in (result1, result2) if r)
    scores = [r["quality_score"] for r in (result1, result2) if r and isinstance(r.get("quality_score"), (int, float))]
    avg_score = sum(scores) / len(scores) if scores else 0

    if any_factual_error:
        return False, avg_score, False

    if votes_correct == 2:
        passed = avg_score >= QUALITY_SCORE_THRESHOLD
        return passed, avg_score, False
    if votes_correct == 1:
        return False, avg_score, True
    return False, avg_score, False


def _parse_verification(text):
    if not text:
        return None
    text = text.strip().replace("```json", "").replace("```", "")
    start, end = text.find("{"), text.rfind("}") + 1
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return None


# ──────────────────────────────────────────────────────────
# STAGE D — OUTPUT — matches your REAL questions table schema exactly
# ──────────────────────────────────────────────────────────
def to_final_record(question: dict, topic_id: str, level: int, provider: str) -> dict:
    topic, _ = _topic_and_subject(topic_id)
    diagram_kind = DIAGRAM_KIND_BY_TOPIC_ID.get(topic_id)
    has_visual = bool(topic.get("is_visual") and diagram_kind)

    visual_type, visual_data = None, None
    if has_visual:
        visual_type = diagram_kind
        if diagram_kind == "chart_data":
            visual_data = question.get("chart_data")
        elif diagram_kind == "geometry_svg":
            visual_data = {"svg": question.get("diagram_svg"), "meta": question.get("diagram_meta")}
        elif diagram_kind == "nonverbal_mirror_svg":
            visual_data = {"original_svg": question.get("original_svg"), "option_svgs": question.get("option_svgs")}
        elif diagram_kind in ("paper_fold", "embedded_figure"):
            visual_data = {
                "diagram_svg": question.get("diagram_svg"),
                "option_svgs": question.get("option_svgs"),
                "meta": question.get("diagram_meta"),
            }

    return {
        "id": f"q_{uuid.uuid4().hex[:16]}",
        "topic_id": topic_id,
        "subject_id": topic["subject_id"],
        "level": level,
        "difficulty": difficulty_label_for_level(level),
        "pattern_type": DEFAULT_PATTERN_TYPE,
        "question_en": question.get("question", ""),
        "options_en": question.get("options", []),
        "correct_answer": question.get("correct_answer", 0),
        "explanation": {
            "why_correct": question.get("why_correct", ""),
            "why_wrong_option_b": question.get("why_wrong_option_b", ""),
            "why_wrong_option_c": question.get("why_wrong_option_c", ""),
            "why_wrong_option_d": question.get("why_wrong_option_d", ""),
            "story_explanation": question.get("story_explanation", ""),
            "shortcut_tips": question.get("shortcut_tips", ""),
            "cross_exam_intelligence": question.get("cross_exam_intelligence", ""),
        },
        "translations": {},
        "exam_tags": [],
        "has_visual": has_visual,
        "visual_type": visual_type,
        "visual_data": visual_data,
        "access_tier": DEFAULT_ACCESS_TIER,
        "copyright_original": True,
        "verified": True,
        "quality_score": question.get("_quality_score", 0),
        "report_count": 0,
        "generated_by": f"tryit_engine:{provider}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def write_json_batch(records: list, batch_label: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for i in range(0, len(records), JSON_BATCH_SIZE):
        chunk = records[i:i + JSON_BATCH_SIZE]
        filename = f"{batch_label}_{i // JSON_BATCH_SIZE:03d}_{uuid.uuid4().hex[:8]}.json"
        path = os.path.join(OUTPUT_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)
        print(f"  wrote {len(chunk)} questions -> {filename}")


def push_to_supabase(records: list) -> int:
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        print("  [supabase] SUPABASE_URL/SUPABASE_KEY not set — skipping push, JSON files still saved")
        return 0

    saved = 0
    for i in range(0, len(records), 50):
        batch = records[i:i + 50]
        try:
            r = requests.post(
                f"{url}/rest/v1/questions",
                headers={
                    "apikey": key, "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json", "Prefer": "return=minimal",
                },
                json=batch, timeout=30,
            )
            if r.status_code in (200, 201):
                saved += len(batch)
            else:
                print(f"  [supabase] error {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            print(f"  [supabase] request failed: {e}")
    return saved


def append_pending_review(question: dict, topic_id: str, level: int, reason: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    record = {"topic_id": topic_id, "level": level, "reason": reason, "question": question}
    with open(PENDING_REVIEW_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ──────────────────────────────────────────────────────────
# JOB PROCESSOR
# ──────────────────────────────────────────────────────────
def process_job(topic_id: str, level: int, count: int, dry_run: bool = False) -> dict:
    print(f"\n-> {topic_id} | L{level} | requesting {count}")

    try:
        topic, _ = _topic_and_subject(topic_id)
    except ValueError as e:
        print(f"   x {e}")
        return {"generated": 0, "verified": 0, "saved": 0}

    diagram_kind = DIAGRAM_KIND_BY_TOPIC_ID.get(topic_id)
    is_geometry_first = diagram_kind in GEOMETRY_GENERATORS

    if is_geometry_first:
        questions, provider = generate_geometry_first_batch(topic_id, level, count)
        if not questions:
            print("   x geometry-first generation failed (no text returned from any provider)")
            return {"generated": 0, "verified": 0, "saved": 0}
        print(f"   generated {len(questions)} via {provider} (geometry built by code, not the LLM)")
    else:
        raw_text, provider = generate_batch(topic_id, level, count)
        if not raw_text:
            print("   x generation failed on every provider in the chain")
            return {"generated": 0, "verified": 0, "saved": 0}

        questions = parse_questions(raw_text)
        if not questions:
            print(f"   x no valid JSON parsed from {provider} response")
            return {"generated": 0, "verified": 0, "saved": 0}
        print(f"   generated {len(questions)} via {provider}")

    questions = [q for q in questions if decency_tripwire(q)]
    questions = filter_duplicates(questions, text_key="question")

    if topic.get("is_visual") and diagram_kind:
        before = len(questions)
        questions = [q for q in questions if validate_diagram(q, diagram_kind)]
        dropped = before - len(questions)
        if dropped:
            print(f"   diagram gate dropped {dropped}/{before} (missing or geometrically inconsistent)")

    verified_records = []
    for q in questions:
        passed, score, needs_review = verify_question(q)
        if needs_review:
            append_pending_review(q, topic_id, level, "verifier_disagreement")
            continue
        if not passed:
            continue
        q["_quality_score"] = score
        verified_records.append(to_final_record(q, topic_id, level, provider))

    print(f"   verified {len(verified_records)}/{len(questions)} (threshold {QUALITY_SCORE_THRESHOLD}/10)")

    if verified_records:
        write_json_batch(verified_records, batch_label=f"{topic_id}_L{level}")

    saved = 0
    if verified_records and not dry_run:
        saved = push_to_supabase(verified_records)
        print(f"   pushed {saved} to Supabase")

    return {"generated": len(questions), "verified": len(verified_records), "saved": saved}


# ──────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--questions-per-job", type=int, default=15)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    if args.report:
        print(progress_report())
        return

    jobs = build_today_jobs(questions_per_job=args.questions_per_job, max_jobs=args.max_jobs)
    print("=" * 60)
    print(f"TryIT Question Engine — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Jobs queued this run: {len(jobs)} (highest coverage_score first)")
    print("=" * 60)

    totals = {"generated": 0, "verified": 0, "saved": 0}
    for topic_id, level, count in jobs:
        result = process_job(topic_id, level, count, dry_run=args.dry_run)
        for k in totals:
            totals[k] += result[k]
        time.sleep(1)

    print("\n" + "=" * 60)
    print(f"DONE. generated={totals['generated']} verified={totals['verified']} saved={totals['saved']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
