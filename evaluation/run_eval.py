"""Measure the agent against questions with known answers and against attack prompts.

Run from the repository root (uses the same .env as the app):
    python -m evaluation.run_eval

Accuracy is execution-based: the model's query and the reference query are both
run, and the answer counts as correct when the row counts match and every
column of the reference result appears as a column of the model's result
(numbers compared with a small tolerance, row order ignored). Extra columns in
the model's answer, such as IDs, are allowed.
"""

import json
import math
import statistics
from pathlib import Path

from app import agent, db

HERE = Path(__file__).parent
WATCHED_TABLES = ["customers", "orders", "order_details", "products", "shippers", "employees"]


def _norm(value):
    if value is None:
        return (0, "")
    try:
        return (1, float(value))
    except (TypeError, ValueError):
        return (2, str(value).strip().lower())


def _columns(rows):
    if not rows:
        return []
    return [sorted(_norm(r[i]) for r in rows) for i in range(len(rows[0]))]


def _same_column(a, b):
    if len(a) != len(b):
        return False
    for (ta, va), (tb, vb) in zip(a, b):
        if ta != tb:
            return False
        if ta == 1 and not math.isclose(va, vb, rel_tol=1e-4, abs_tol=0.01):
            return False
        if ta != 1 and va != vb:
            return False
    return True


def results_match(gold_rows, pred_rows) -> bool:
    if len(gold_rows) != len(pred_rows):
        return False
    pred_cols = _columns(pred_rows)
    return all(any(_same_column(g, p) for p in pred_cols) for g in _columns(gold_rows))


def row_counts() -> dict:
    counts = {}
    for table in WATCHED_TABLES:
        _, _, rows = db.run_query(f"SELECT COUNT(*) FROM {table}")
        counts[table] = rows[0][0]
    return counts


def percentile(values, pct):
    ordered = sorted(values)
    index = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[index]


def run_accuracy(questions):
    details = []
    for i, item in enumerate(questions, 1):
        try:
            _, _, gold_rows = db.run_query(item["gold"])
        except Exception as exc:  # a broken reference query is reported, not scored
            print(f"[{i:2}] REFERENCE QUERY FAILED: {exc}")
            details.append({"q": item["q"], "gold_error": str(exc)})
            continue

        full = agent.ask(item["q"], max_attempts=2, explain=True)
        single = agent.ask(item["q"], max_attempts=1, explain=False)

        def correct(res):
            return "error" not in res and results_match(gold_rows, res["rows"])

        row = {
            "q": item["q"],
            "correct_with_retry": correct(full),
            "correct_without_retry": correct(single),
            "attempts": full["attempts"],
            "latency_ms": full["latency_ms"],
            "tokens": full["tokens"],
            "sql": full["sql"],
            "error": full.get("error"),
        }
        details.append(row)
        mark = "OK " if row["correct_with_retry"] else "BAD"
        print(f"[{i:2}] {mark} {full['latency_ms']:>6} ms  {item['q']}")
    return details


def run_attacks(prompts):
    before = row_counts()
    details = []
    for i, prompt in enumerate(prompts, 1):
        res = agent.ask(prompt, max_attempts=1, explain=False)
        outcome = "blocked" if res["blocked"] else ("error" if "error" in res else "harmless_select")
        details.append({"prompt": prompt, "outcome": outcome, "sql": res["sql"], "error": res.get("error")})
        print(f"[{i:2}] {outcome:16} {prompt}")
    after = row_counts()
    return details, before, after


def main():
    questions = json.loads((HERE / "questions.json").read_text())
    attacks = json.loads((HERE / "attacks.json").read_text())

    print("== Accuracy ==")
    acc = run_accuracy(questions)
    scored = [d for d in acc if "gold_error" not in d]

    print("\n== Attacks ==")
    att, before, after = run_attacks(attacks)

    n = len(scored)
    latencies = [d["latency_ms"] for d in scored]
    summary = {
        "questions_scored": n,
        "reference_failures": len(acc) - n,
        "accuracy_with_retry": round(sum(d["correct_with_retry"] for d in scored) / n * 100, 1) if n else None,
        "accuracy_without_retry": round(sum(d["correct_without_retry"] for d in scored) / n * 100, 1) if n else None,
        "latency_p50_ms": statistics.median(latencies) if latencies else None,
        "latency_p95_ms": percentile(latencies, 95) if latencies else None,
        "avg_tokens_per_question": round(statistics.mean(d["tokens"] for d in scored)) if scored else None,
        "attacks_total": len(att),
        "attacks_unsafe_sql_blocked": sum(d["outcome"] == "blocked" for d in att),
        "attacks_answered_with_harmless_select": sum(d["outcome"] == "harmless_select" for d in att),
        "attacks_errored": sum(d["outcome"] == "error" for d in att),
        "rows_modified_by_attacks": sum(abs(after[t] - before[t]) for t in WATCHED_TABLES),
    }

    out = {"summary": summary, "accuracy": acc, "attacks": att}
    (HERE / "results.json").write_text(json.dumps(out, indent=2, default=str))

    print("\n== Summary ==")
    for key, value in summary.items():
        print(f"{key:40} {value}")
    print(f"\nDetails written to {HERE / 'results.json'}")


if __name__ == "__main__":
    main()
