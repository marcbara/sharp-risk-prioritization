# SHARP — Semantic Human-AI Risk Prioritization

Reference implementation accompanying the paper:

> **Operationalizing Human-AI Collaboration for High-Volume Project Risk Management.**
> Marc Bara. *4th Decision Science Alliance International Summer Conference (DSA ISC 2026)*, Madrid, June 2026. Springer LNCS (forthcoming).

SHARP operationalizes a three-tier semantic triage system (MONITOR / FLAG / ESCALATE) for AI-augmented project risk management. A project manager defines escalation rules in natural language; a large language model applies them at volume, returning a tier, a self-reported confidence score, and a justification for every risk. The system is designed to **fail safely**: the only error the architecture asymmetrically prevents is a critical risk being silently routed to MONITOR.

This repository contains the dataset, code, and paper source needed to reproduce the empirical results in Section 4.4 of the paper end-to-end.

---

## What the experiment shows

Running the pipeline once on the bundled 80-risk synthetic project produces:

| Metric | Result |
| --- | --- |
| Critical retention rate | **12 / 12 = 100%** |
| Initial false-negative rate (critical → MONITOR) | **0 / 12 = 0%** |
| Volume reduction (share classified MONITOR) | **53 / 80 = 66.2%** |
| Exact-match accuracy vs ground truth | 73 / 80 = 91.2% |
| Mean confidence: ESCALATE / MONITOR / FLAG | 0.95 / 0.79 / 0.75 |
| Approximate API cost per full run | ~US$0.07 |

The confidence ordering (ESCALATE highest, FLAG lowest) is the expected diagnostic signature: the model is most certain where escalation rules fire unambiguously, and least certain in the genuinely ambiguous middle tier.

---

## Repository layout

```
sharp-risk-prioritization/
├── README.md                       # this file
├── LICENSE                         # MIT
├── requirements.txt                # Python dependencies
├── .env.example                    # template for ANTHROPIC_API_KEY
├── .gitignore
│
├── sharp_dataset.csv               # 80 risks with planted ground-truth tier
│
├── db.py                           # SQLite schema (risks, classifications, events)
├── sharp_classifier.py             # Anthropic SDK pipeline (Sonnet 4.6 + caching)
├── metrics.py                      # critical retention / volume reduction / etc.
├── inspect_classifications.py      # per-risk audit table (read-only)
├── check_paper.py                  # static check: cites / refs / labels in the .tex
│
└── paper/
    ├── SHARP_paper_DSA26.tex       # paper source (LNCS class)
    └── SHARP_paper_DSA26.pdf       # compiled paper (11 pages)
```

Generated at runtime (gitignored): `sharp.db`, `.env`, PDF build artifacts.

---

## Reproducing the paper results

### 1. Prerequisites

- Python ≥ 3.9
- An Anthropic API key with access to `claude-sonnet-4-6`
- (Optional, for compiling the paper) a LaTeX distribution that ships `llncs.cls`: MiKTeX, TeX Live, or MacTeX

### 2. Install dependencies

```bash
git clone https://github.com/marcbara/sharp-risk-prioritization
cd sharp-risk-prioritization
pip install -r requirements.txt
```

### 3. Configure your API key

```bash
cp .env.example .env
# Edit .env and replace the placeholder with your real key
```

Cost expectation: a full classification of the bundled 80-risk dataset uses ~7,400 input tokens (with prompt caching on batches 2–4) and ~4,300 output tokens, costing roughly **US$0.07** at Claude Sonnet 4.6 list prices. No data is retained on Anthropic infrastructure beyond the request itself.

### 4. Run the pipeline

```bash
# (a) Initialize the SQLite database from the CSV
python db.py

# (b) Classify all 80 risks in four batches of 20
python sharp_classifier.py

# (c) Compute the headline metrics reported in Section 4.4
python metrics.py
```

Optional sanity checks:

```bash
# Per-risk audit table: ground truth vs AI, with justifications
python inspect_classifications.py

# Quick classification of just the first batch (20 risks), for debugging
python sharp_classifier.py 1
```

### 5. Compile the paper

```bash
cd paper
pdflatex SHARP_paper_DSA26.tex
pdflatex SHARP_paper_DSA26.tex    # second pass resolves \cite and \ref
```

The paper uses the Springer `llncs` class, which is bundled with both MiKTeX and TeX Live. No external `.bib` file is needed — the bibliography is embedded in the source.

---

## What this minimal implementation does *not* yet do

The paper's architecture also describes dynamic reclassification, clustering, weak-signal scanning of communications, and a Streamlit dashboard for human review. The pipeline shipped here exercises only the **static initial classification pass** plus the four-layer safety architecture, which is the core triage mechanism evaluated quantitatively in Section 4.4. The multi-event simulation is planned follow-on work.

---

## Design notes worth knowing if you adapt this

- **Model selection.** `claude-sonnet-4-6` is the right cost/quality point for high-volume structured classification. Opus would be overkill (5× cost, no measurable lift on this task); Haiku may suffice for the volume tier but was not evaluated.
- **Thinking disabled, effort low.** For a structured-output task driven by explicit rules, deep reasoning is wasted tokens. The prompt is the lever, not the reasoning depth.
- **Prompt caching is essential.** The system prompt is identical across batches; caching it brings batches 2–N to ~10% of base input price. Verify with `usage.cache_read_input_tokens > 0` in the classifier output.
- **JSON schema must be Anthropic-compatible.** Pydantic's default `model_json_schema()` emits `minimum` / `maximum` constraints that the structured-output endpoint rejects, and omits `additionalProperties: false` which it requires. `sharp_classifier.py:_strict_schema` post-processes the schema to fix both.
- **Append-only classifications table.** Every new tier assignment is a new row, not an update. This preserves the full reclassification history of each risk for longitudinal analysis once dynamic reclassification is added.

---

## Related work

This implementation builds on two prior pieces, neither of which is included in this repository:

- **The Catania conceptual framework** ([Bara & Lostumbo, 2025](https://decisionsciencesummit.com/)) — the cross-domain transfer matrix and three-tier proposal that SHARP operationalizes. See the citation in the paper bibliography.
- **The LLM-based risk register enhancement pipeline** ([github.com/marcbara/risk-register-llm](https://github.com/marcbara/risk-register-llm)) — the prior single-task pipeline whose seven-field risk schema, batch processing, and structured-output approach SHARP inherits. Used in this paper as the qualitative baseline (an LLM without triage architecture).

---

## Citation

If you use SHARP in your research, please cite:

```bibtex
@inproceedings{bara2026sharp,
  author    = {Bara, Marc},
  title     = {Operationalizing Human-AI Collaboration for High-Volume Project Risk Management},
  booktitle = {Proceedings of the 4th Decision Science Alliance International Summer Conference (DSA ISC 2026)},
  publisher = {Springer},
  series    = {Lecture Notes in Computer Science},
  year      = {2026},
  address   = {Madrid, Spain}
}
```

---

## License

[MIT](LICENSE). Risk text in `sharp_dataset.csv` is synthetic and contains no real project, person, or organization.

## Contact

Marc Bara — `marcoantonio.bara@esade.edu`
