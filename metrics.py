"""SHARP evaluation metrics — reads classifications from SQLite and reports
the figures cited in Section 4.4 of the paper.

Metrics:
  Critical retention rate    Planted ESCALATE risks correctly placed in FLAG
                             or ESCALATE (i.e. not wrongly sent to MONITOR).
                             This is the most important metric: the paper
                             argues the only dangerous error is a critical
                             risk silently classified as MONITOR.
  Volume reduction           Share of risks classified as MONITOR. Measures
                             how much PM cognitive load is offloaded to the
                             AI. Paper target: 65-70%.
  Initial false negative     Planted criticals wrongly in MONITOR on the
  rate                       first classification pass (= 1 - retention).
  Tier-level recall          Per-tier sensitivity vs planted ground truth.
  Confusion matrix           Full breakdown of classifications by tier.
  Mean confidence by tier    Diagnostic for whether the model's confidence
                             tracks ambiguity (FLAG should be lowest).
"""

import sqlite3
from collections import Counter, defaultdict


def compute_metrics(db_path: str = "sharp.db") -> dict:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """SELECT r.risk_id, r.ground_truth_tier, c.tier, c.confidence
           FROM risks r
           JOIN classifications c ON r.risk_id = c.risk_id
           WHERE r.ground_truth_tier IS NOT NULL
           ORDER BY r.risk_id"""
    ).fetchall()

    if not rows:
        raise RuntimeError("No labeled classifications found in DB.")

    n = len(rows)
    ai_dist = Counter(r[2] for r in rows)
    gt_dist = Counter(r[1] for r in rows)

    # Critical retention rate
    critical_rows = [r for r in rows if r[1] == "ESCALATE"]
    retained = sum(1 for r in critical_rows if r[2] in ("FLAG", "ESCALATE"))
    critical_retention = retained / len(critical_rows) if critical_rows else None
    leaked_to_monitor = [r for r in critical_rows if r[2] == "MONITOR"]

    # Volume reduction
    volume_monitor = ai_dist["MONITOR"] / n

    # Per-tier recall (correctly placed at exact tier)
    per_tier_recall = {}
    for tier in ("MONITOR", "FLAG", "ESCALATE"):
        gt_rows = [r for r in rows if r[1] == tier]
        if gt_rows:
            correct = sum(1 for r in gt_rows if r[2] == tier)
            per_tier_recall[tier] = (correct, len(gt_rows), correct / len(gt_rows))

    # Confusion matrix
    confusion = defaultdict(lambda: defaultdict(int))
    for _, gt, ai, _ in rows:
        confusion[gt][ai] += 1

    # Mean confidence by AI tier
    conf_by_tier = defaultdict(list)
    for _, _, ai, conf in rows:
        conf_by_tier[ai].append(conf)
    mean_conf = {t: sum(c) / len(c) for t, c in conf_by_tier.items()}

    return {
        "n": n,
        "ai_distribution": dict(ai_dist),
        "gt_distribution": dict(gt_dist),
        "critical_retention_rate": critical_retention,
        "n_critical_planted": len(critical_rows),
        "n_critical_leaked_to_monitor": len(leaked_to_monitor),
        "leaked_critical_ids": [r[0] for r in leaked_to_monitor],
        "volume_reduction_to_monitor": volume_monitor,
        "per_tier_recall": per_tier_recall,
        "confusion_matrix": {gt: dict(row) for gt, row in confusion.items()},
        "mean_confidence_by_ai_tier": mean_conf,
    }


def print_report(m: dict) -> None:
    print("=" * 60)
    print("SHARP MINIMAL PIPELINE — EVALUATION REPORT")
    print("=" * 60)
    print(f"\nTotal risks evaluated: {m['n']}")

    print(f"\n--- HEADLINE METRICS ---")
    print(f"Critical retention rate: "
          f"{m['critical_retention_rate']:.1%} "
          f"({m['n_critical_planted'] - m['n_critical_leaked_to_monitor']}"
          f"/{m['n_critical_planted']} planted criticals retained)")
    print(f"Initial false-negative rate (criticals -> MONITOR): "
          f"{m['n_critical_leaked_to_monitor']}/{m['n_critical_planted']} "
          f"= {m['n_critical_leaked_to_monitor']/m['n_critical_planted']:.1%}")
    if m["leaked_critical_ids"]:
        print(f"  Leaked critical IDs: {m['leaked_critical_ids']}")
    print(f"Volume reduction (share in MONITOR): "
          f"{m['volume_reduction_to_monitor']:.1%} "
          f"({m['ai_distribution'].get('MONITOR', 0)}/{m['n']})")

    print(f"\n--- DISTRIBUTION ---")
    print(f"Ground truth: {m['gt_distribution']}")
    print(f"AI classification: {m['ai_distribution']}")

    print(f"\n--- PER-TIER RECALL (exact match) ---")
    for tier, (correct, total, rate) in m["per_tier_recall"].items():
        print(f"  {tier:>9}: {correct}/{total} = {rate:.1%}")

    print(f"\n--- CONFUSION MATRIX (rows = ground truth, cols = AI) ---")
    tiers = ["MONITOR", "FLAG", "ESCALATE"]
    header_label = "GT vs AI"
    print(f"  {header_label:>10} " + " ".join(f"{t:>9}" for t in tiers))
    for gt in tiers:
        row = m["confusion_matrix"].get(gt, {})
        print(f"  {gt:>10} " + " ".join(f"{row.get(t, 0):>9}" for t in tiers))

    print(f"\n--- MEAN AI CONFIDENCE BY ASSIGNED TIER ---")
    for tier in tiers:
        c = m["mean_confidence_by_ai_tier"].get(tier)
        if c is not None:
            print(f"  {tier:>9}: {c:.2f}")

    print()


if __name__ == "__main__":
    m = compute_metrics()
    print_report(m)
