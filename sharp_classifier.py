"""SHARP tier classifier — minimal pipeline.

Reads risks from SQLite, classifies each into MONITOR/FLAG/ESCALATE using
Claude Sonnet 4.6 with prompt caching on the system prompt and structured
JSON output. Writes results back to the classifications table.

Design notes
------------
- Model: claude-sonnet-4-6. Adaptive thinking is disabled because tier
  classification is a structured-output task that does not need deep
  reasoning; effort is set to low for cost and determinism.
- Prompt caching: the system prompt encodes the PM's semantic rules and
  tier definitions and is identical across batches, so cache_control
  ephemeral on the system block lets batches 2..N read from cache at
  ~0.1x cost.
- Structured output: messages.create with output_config.format.json_schema
  binding the response to a Pydantic schema. The first content block of the
  response is a JSON string that parses cleanly into ClassificationBatch.
- Confidence: self-reported by the model on a 0-1 scale. The PM-policy rule
  "If AI confidence is low, FLAG (never MONITOR)" is encoded directly in
  the system prompt so the model applies it during classification.
"""

import json
import os
import sqlite3
from typing import List

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional
from typing_extensions import Literal

from db import init_db, list_risks_for_classification, record_classification


MODEL = "claude-sonnet-4-6"
BATCH_SIZE = 20
LOW_CONFIDENCE_THRESHOLD = 0.60  # documented in system prompt for traceability


SYSTEM_PROMPT = """You are SHARP, a Semantic Human-AI Risk Prioritization classifier. \
Your job is to assign every project risk you receive to exactly one of three \
collaboration tiers: MONITOR, FLAG, or ESCALATE. You apply project-manager \
policy rules to the semantic content of each risk; you do not compute \
probability-impact scores.

# Tier definitions

MONITOR (AI decides, PM only sees aggregates)
- Low impact on project objectives (scope, time, cost, quality)
- No connection to the critical path within the next 4 weeks
- High reversibility if the risk materializes
- No match with any PM escalation rule below
- AI confidence in the assessment is high

FLAG (AI proposes a response, PM decides)
- Moderate impact OR high uncertainty about impact
- Match with a PM escalation rule (see below)
- Membership in a risk cluster (multiple risks sharing root cause or vendor)
- AI confidence in the assessment is low (below {low_conf}); when in doubt, FLAG

ESCALATE (AI prepares a dossier, PM acts with team and stakeholders)
- High impact on project objectives (scope, time, cost, quality)
- Low reversibility: if it materializes, damage cannot be undone in-cycle
- Systemic threat: combines multiple connected risks or affects multiple teams
- Triggered by a direct PM ESCALATE rule (see below)

# PM semantic escalation rules for this project

1. Anything affecting the critical path within 4 weeks -> minimum FLAG.
2. Any risk affecting client relationship, anchor customer, or commercial \
contract -> ESCALATE.
3. Any risk affecting regulatory compliance (GDPR, SOC2, financial) -> ESCALATE.
4. Any risk affecting safety, security, or production data integrity -> ESCALATE.
5. Single point of failure on people (key person dependency) with no documented \
knowledge transfer -> ESCALATE.
6. Direct financial penalty triggers above 10% of project budget -> ESCALATE.
7. Two or more risks linked to the same supplier or vendor -> FLAG (cluster).
8. If the AI has low confidence in its assessment -> FLAG, never MONITOR.

# How to read each risk

Each risk arrives as a structured record with Risk ID, Type, Root Cause, \
Incident, Impact, Response Strategy, and Response Action. Treat the entry as \
a narrative within the broader project context. Vague entries with imprecise \
language ("Things go wrong", "Bad outcome for the team", "Customer may \
complain") carry low semantic signal and should generally be classified \
MONITOR unless an explicit field reveals a critical concern. Specific, \
well-defined entries that match an escalation rule above should follow the \
rule.

# Output format

Return a JSON object with a single field `classifications` containing one \
object per risk in the batch, with these fields:
- risk_id (integer, must match the input Risk ID)
- tier (string, exactly one of MONITOR, FLAG, ESCALATE)
- confidence (number, 0 to 1, your self-assessed confidence)
- justification (string, one sentence explaining the tier choice in terms of \
the rule or criterion that drove it)

Process every risk in the batch. Do not group, summarize, or omit any risk. \
The order of classifications must follow the order of input risks.
""".format(low_conf=LOW_CONFIDENCE_THRESHOLD)


class RiskClassification(BaseModel):
    risk_id: int
    tier: Literal["MONITOR", "FLAG", "ESCALATE"]
    confidence: float  # API rejects numerical constraints; clamp client-side
    justification: str


class ClassificationBatch(BaseModel):
    classifications: List[RiskClassification]


def _strict_schema(model: type) -> dict:
    """Pydantic schema, post-processed for Anthropic structured outputs:
    add additionalProperties:false to every object, strip unsupported
    numerical/string constraints, drop pydantic-only metadata."""
    schema = model.model_json_schema()

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
            for k in ("minimum", "maximum", "exclusiveMinimum",
                      "exclusiveMaximum", "multipleOf", "minLength",
                      "maxLength", "minItems", "maxItems", "title"):
                node.pop(k, None)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema


def _format_batch(risks: List[dict]) -> str:
    """Format a batch of risks as a markdown table the model can read."""
    header = (
        "| Risk ID | Type | Root Cause | Incident | Impact | "
        "Response Strategy | Response Action |\n"
        "|---|---|---|---|---|---|---|"
    )
    rows = []
    for r in risks:
        rows.append(
            f"| {r['risk_id']} | {r['type']} | {r['root_cause']} | "
            f"{r['incident']} | {r['impact']} | {r['response_strategy']} | "
            f"{r['response_action'] or ''} |"
        )
    return header + "\n" + "\n".join(rows)


def classify_batch(client: anthropic.Anthropic, risks: List[dict]) -> ClassificationBatch:
    """Send one batch through the Messages API and parse the result."""
    user_content = (
        "Classify each risk in the following batch. Return one classification "
        "per risk in JSON.\n\n"
        + _format_batch(risks)
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "disabled"},
        output_config={
            "effort": "low",
            "format": {
                "type": "json_schema",
                "schema": _strict_schema(ClassificationBatch),
            },
        },
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    # Cache telemetry (printed per call for transparency / reproducibility)
    usage = response.usage
    print(
        f"  usage: input={usage.input_tokens} "
        f"cache_write={getattr(usage, 'cache_creation_input_tokens', 0)} "
        f"cache_read={getattr(usage, 'cache_read_input_tokens', 0)} "
        f"output={usage.output_tokens}"
    )

    # The first text block is guaranteed JSON because of output_config.format
    text_block = next(b for b in response.content if b.type == "text")
    return ClassificationBatch.model_validate(json.loads(text_block.text))


def run(db_path: str = "sharp.db", csv_path: str = "sharp_dataset.csv",
        max_batches: Optional[int] = None) -> None:
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not found in environment or .env")

    client = anthropic.Anthropic()
    conn = init_db(db_path, csv_path)
    risks = list_risks_for_classification(conn)
    print(f"Loaded {len(risks)} risks. Classifying in batches of {BATCH_SIZE}.",
          flush=True)

    classified_ids = set()
    n_batches = (len(risks) + BATCH_SIZE - 1) // BATCH_SIZE
    if max_batches is not None:
        n_batches = min(n_batches, max_batches)
    for i in range(0, n_batches * BATCH_SIZE, BATCH_SIZE):
        batch = risks[i : i + BATCH_SIZE]
        print(f"Batch {i // BATCH_SIZE + 1}: risks "
              f"{batch[0]['risk_id']}-{batch[-1]['risk_id']}", flush=True)
        try:
            result = classify_batch(client, batch)
        except Exception as e:
            print(f"  ERROR on batch: {type(e).__name__}: {e}", flush=True)
            raise
        for c in result.classifications:
            if c.risk_id in classified_ids:
                print(f"  warn: duplicate classification for risk {c.risk_id}, skipping",
                      flush=True)
                continue
            # Clamp confidence client-side (API schema can't enforce 0-1)
            conf = max(0.0, min(1.0, c.confidence))
            record_classification(
                conn,
                risk_id=c.risk_id,
                tier=c.tier,
                confidence=conf,
                justification=c.justification,
                model=MODEL,
            )
            classified_ids.add(c.risk_id)

    total = conn.execute("SELECT COUNT(*) FROM classifications").fetchone()[0]
    print(f"\nDone. {total} classifications recorded in {db_path}.", flush=True)


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(max_batches=n)
