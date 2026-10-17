# SKILL: ATS Scorer + RAG Verification

Two functions in one skill:
1. Score how well a generated CV would perform in ATS keyword-matching
2. Verify every claim in the CV against the knowledge base (anti-hallucination)

This skill runs AFTER cv-writer generates the data module and BEFORE the PDF is rendered. If it fails, the CV goes back to cv-writer for correction.

---

## Part 1: ATS Scoring

### 5 Dimensions (each 1-10)

**1. Keyword Match (weight: 30%)**
Compare the generated CV text against the JD's required skills, tools, and technologies.
- Count exact keyword matches
- Count semantic matches (synonyms the ATS might recognize)
- List every JD keyword and whether it appears in the CV
- Score purely on the real percentage of JD keywords found — independent of
  what cv-writer was targeting at generation time:
  - 10 = 90%+ keywords found
  - 8-9 = 75-89%
  - 6-7 = 60-74%
  - 4-5 = 40-59%
  - 1-3 = below 40%
- Do not cap this score because cv-writer's own generation instructions
  target 75-80% (that target exists to avoid keyword-stuffing during
  writing, not to define this dimension's ceiling). A CV that naturally
  achieves 90%+ genuine, naturally-worded overlap scores 10, full stop.

**2. Title Alignment (weight: 20%)**
Does the candidate's most recent title and experience level match the JD's seniority?
- Exact title match = 10
- Adjacent title (Data Scientist → ML Engineer) = 7-8
- Different function (CDO → Data Scientist) = 5-6 — flag co-founder repositioning
- Score reflects how an ATS title-matching algorithm would evaluate

**3. Experience Relevance (weight: 20%)**
Do the bullet points directly address the JD's stated responsibilities?
- For each JD responsibility, is there at least one bullet that demonstrates it?
- Are the most relevant bullets in the first position under each role?

**4. Formatting Safety (weight: 15%)**
Is the CV free of elements that break ATS parsers?
- [ ] Standard section headers (not spaced out with non-breaking spaces)
- [ ] All text in paragraph stream (not drawString absolute positioning)
- [ ] No multi-column layouts in content area
- [ ] Dates in MM/YYYY format
- [ ] No images containing text
- [ ] Single-column footer (not two-column)
- Note: resume_design_base.py with ATS fixes should pass all of these

**5. Quantification Density (weight: 15%)**
What percentage of bullet points include specific numbers, percentages, or metrics?
- Score purely on the real percentage of bullets quantified — independent of
  what cv-writer was targeting at generation time:
  - 10 = 90%+ of bullets have a metric
  - 8-9 = 75-89%
  - 6-7 = 60-74%
  - below that, score proportionally lower
- Do not cap this score because cv-writer's own generation instructions
  target 80%+ (that target exists as generation guidance, not to define this
  dimension's ceiling). A CV that naturally quantifies 90%+ of its bullets
  scores 10, it is not capped at 7 for "exceeding the target."

### Overall Score

Weighted sum → normalize to /50

| Range | Label | Action |
|-------|-------|--------|
| 40-50 | Strong ATS match | Proceed to PDF |
| 35-39 | Good match | Proceed, note improvements |
| 30-34 | Moderate match | Review suggested additions before PDF |
| Below 30 | Weak match | Send back to cv-writer with specific corrections |

---

## Part 2: RAG Verification (Anti-Hallucination Check)

This is the critical safety layer. Adapted from career-ops's cv-sync-check pattern.

### What to Check

RAG verification applies ONLY to hard factual claims — not to targeting language, skills keywords, or aspirational framing.

**MUST verify (these cause FAIL if unverified):**
- Every number/metric: percentages, counts, currency amounts, time metrics, team sizes
- Company names (must match employment-master.md exactly)
- Employment dates (must match employment-master.md exactly)
- Job titles in EXPERIENCE section (must match employment-master.md exactly)
- Named organizations, hospitals, awards, scholarships in EXPERIENCE/EDUCATION
- Named technologies explicitly claimed as experience (not just listed in SKILLS)

**DO NOT fail for these (they are acceptable without source IDs):**
- SUMMARY targeting language — e.g., "Targeting Growth PM roles", "seeking to apply X in Y", positioning claims like "7+ years across X and Y environments" are aspirational framing, not factual assertions requiring source verification
- SKILLS section keywords — skill labels are permissible if they can reasonably be inferred from the candidate's actual work; skills-master is a guide, not an exhaustive whitelist
- Interpretive framing in bullets — e.g., "improving user activation" derived from verified multilingual expansion work is acceptable inference, not fabrication
- "Growth Product Manager, Product Growth Lead profile" in SUMMARY — this is a targeting statement, not a claim of prior title
- "acquisition", "retention", "engagement" in SUMMARY — these are keyword-aligned framing of verified user metrics (verified recurring use can support an engagement narrative); acceptable inference
- Minor wording differences — e.g., "product data visibility" vs "model drift monitoring dashboard" in Northwind Health context; same work, different frame
- Rounded number presentation at any magnitude (e.g., "10M+" for a verified 10,050,066 metric,
  "34K+" for a verified 34,328 metric, "~350" for a verified 362 metric) — this is CV-writer
  formatting per its number-formatting rule, not fabrication. The rounded form must still trace
  to the same source ID as the exact figure.

**Verified examples that should always PASS:**
- "Forecasting evaluation" — verified, Acme Analytics AA-01
- "18 validation checks" — verified, NH-01
- Awards, scholarships in education-master.md

### Verification Output

```
## RAG VERIFICATION REPORT

### Metrics Traced
| CV Text | Source ID | Status |
|---------|----------|--------|
| "12% lower MAE" | AA-01 | ✅ Exact match |
| "18 validation checks" | NH-01 | ✅ Exact match |
| ... | ... | ... |

### Unverified Claims
| CV Text | Issue | Action Required |
|---------|-------|-----------------|
| [any text not traceable to source] | Not found in knowledge base | REMOVE or VERIFY with candidate |

### Verdict: PASS / FAIL

FAIL only if a HARD FACTUAL CLAIM is unverified:
- A fabricated number (metric, date, count, currency amount, percentage)
- A company name, title, or date that does not match employment-master.md
- A named award, organization, or credential not found in any knowledge base file
- Return to cv-writer with specific corrections and the exact lines to change

PASS if:
- All hard metrics trace to source IDs
- Any FAIL issues are summary targeting language, skills keyword framing, or minor bullet inference (these do not prevent PASS)
```

---

## Part 3: Gap Report

After scoring and verification, output gaps for the candidate's awareness:

```
### Skills/Experience Gaps
| JD Requirement | Gap | Suggested Framing (for interview prep) |
|----------------|-----|----------------------------------------|
| "{requirement}" | No direct experience | "{adjacent experience}: {specific from employment-master.md}" |

### Missing Keywords
| JD Keyword | Status | Suggestion |
|-----------|--------|-----------|
| "{keyword}" | Not in CV | Add to Skills section / Reword bullet X |
```

---

## Decision Gate

```
ATS Score: XX/50
RAG Verification: PASS/FAIL
Unverified Claims: X

IF score >= 35 AND verification == PASS:
  → Render PDF via resume_design_base.py
  → Save as JaneDoe_{Company}_{Role}.pdf

IF score < 35 OR verification == FAIL:
  → Return to cv-writer with:
    - Missing keywords to incorporate
    - Unverified claims to remove
    - Specific bullet rewrites suggested
  → Re-run this scorer on the corrected version
  → Maximum 2 correction cycles before human review
```

## Required Output Footer

Always end your response with exactly these two lines (replace XX with the actual number):

```
SCORE: XX/50
VERDICT: PASS
```

or

```
SCORE: XX/50
VERDICT: FAIL
```

No other text after this block. The pipeline parses these lines programmatically.
