# SKILL: Cover Letter Writer

You generate tailored cover letters. Every letter is unique to the specific JD and company.

## Sources of Truth
- employment-master.md — ONLY source for achievements and metrics
- career-master.md — narrative, positioning, "why looking now"
- education-master.md — capstone projects, immersions for relevant references
- identity.md — contact details (geo-matched)

---

## Pipeline (adapted from career-ops cover.md — 4-prompt gate MANDATORY)

### Step 1: Parse JD
Extract role title, company, location, top 3-4 required competencies, mission/vision language, domain, start date signals.

### Step 2: Company Research
If web search available, search:
1. "{company}" product strategy OR roadmap {year}
2. "{company}" challenges OR problems {year}
3. "{company}" news OR funding {year}

Synthesize into 2-3 sentences about what the company is working on and what challenges they face.

### Step 3: Keyword Extraction
Extract top 8-10 exact phrases. Split into:
- **ATS-critical:** tool names, methodology names, role-specific terms
- **Human trust signals:** action verbs, product nouns, outcome language the company uses

### Step 4: Gap Detection
Check for domain mismatch, visa/sponsorship needs, language requirements, title mismatch. Flag each with options:
a) Address it directly in the letter
b) Don't mention it
c) Custom angle

### Step 5: Four Prompts (MANDATORY — adapted from career-ops)

**A. Why this role / company?** Pick from angles visible in JD: scale signal, tech ambition, domain/mission, growth stage, strategic learning.

**B. What problem would you solve?** Based on company research.

**C. How would you approach it?** Opening move on day one. Most differentiated part.

**D. Tone?** Formal / Direct / Conversational / Mirror JD.

### Step 6: Achievement Selection
Select 4-5 achievement bullets from employment-master.md:
1. Score each against JD's top requirements
2. Pick highest-scoring with at least one metric each
3. Use the wording from source, but round every count/dollar/quantity metric to a clean,
   human-sounding figure — an exact-to-the-unit number (362, 8,500, 34,328) reads as oddly
   precise regardless of size. Below 1,000, round to the nearest 10-50 (362 → "~350").
   1,000-99,999, round to the nearest K (34,328 → "34K+", 8,500 → "8.5K+"). 100,000+, round to
   the nearest 100K/M (500,000 → "500K+"). Leave percentages, ATS scores, years of experience,
   and explicitly-framed team sizes exact. The underlying metric must still trace to the source
   ID — only the presentation is rounded.
4. Apply keyword mirroring vocabulary only

Format: `**Bold lead phrase,** one sentence of impact with metric.`

### Step 7: Draft

```
[Name]
[Location] | [Email] | [Phone] | [LinkedIn]

Cover Letter: [Role Title]
[Company], [City]   [Date]

[Opening — 2 sentences]
Why applying + functional summary. From Angle A. Uses JD mirror vocabulary.

[Profile introduction — 1 paragraph]
Years of experience, current role, domain. From career-master.md identity version matching archetype.

[Achievements — 4-5 bullets]
• **Lead phrase,** impact sentence with metric.

[Problems I will solve — 2-3 sentences]
From company research + Angle B + Angle C. Specific to this company.

[Closing — 1-2 sentences]
Availability + any gap acknowledgments.
```

**350-420 words total.**

### Language Rules (from career-ops)
1. Active voice only
2. No buzzwords: leverage, synergy, seamless, holistic, robust, cutting-edge, spearheaded, championed, orchestrated, passionate, excited, stakeholder alignment, data-driven, actionable insights, perfect fit, strong track record
3. No filler openers: "I am pleased to", "I am writing to express", "I am excited to"
4. Concrete over abstract: every claim needs a number, system name, or specific outcome
5. Self-check: could this sentence appear in any cover letter for any company? If yes, rewrite.

---

## Output
Output the letter text only — no filename, no metadata, no headers beyond the letter structure above.
