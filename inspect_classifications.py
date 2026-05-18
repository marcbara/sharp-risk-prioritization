"""Quick read-only inspector for sharp.db classifications."""
import sqlite3
from collections import Counter

conn = sqlite3.connect("sharp.db")
rows = conn.execute(
    """SELECT r.risk_id, r.ground_truth_tier, c.tier, c.confidence, c.justification
       FROM risks r JOIN classifications c ON r.risk_id = c.risk_id
       ORDER BY r.risk_id"""
).fetchall()

print(f"{'ID':>3} {'GT':>9} {'AI':>9} {'conf':>5}  match  justification")
for risk_id, gt, ai, conf, just in rows:
    match = "  ok" if gt == ai else "MISS"
    print(f"{risk_id:>3} {gt:>9} {ai:>9} {conf:>5.2f}  {match}   {just[:80]}")

print()
ai_dist = Counter(r[2] for r in rows)
gt_dist = Counter(r[1] for r in rows)
print(f"AI distribution: {dict(ai_dist)}")
print(f"GT distribution (this subset): {dict(gt_dist)}")
matches = sum(1 for r in rows if r[1] == r[2])
print(f"Exact-match accuracy: {matches}/{len(rows)} = {matches/len(rows):.1%}")

# Critical-retention check: any planted ESCALATE risk wrongly placed in MONITOR
escalate_risks = [r for r in rows if r[1] == "ESCALATE"]
if escalate_risks:
    leaked = [r for r in escalate_risks if r[2] == "MONITOR"]
    print(f"Planted ESCALATE wrongly in MONITOR: {len(leaked)}/{len(escalate_risks)}")
