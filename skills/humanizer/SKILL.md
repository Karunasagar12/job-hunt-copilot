# SKILL: Humanizer — AI Writing Pattern Remover

You receive a job outreach document and return the same document with all AI writing
patterns removed. The structure (section headers, separator lines, subject lines,
Day labels) must remain identical. Only the prose changes.

## Two-Pass Process

### Pass 1: Rewrite
Go through every sentence of prose and eliminate the patterns listed below.
Replace with direct, specific, concrete language. Write like a sharp person
dashing off a thoughtful note — not like a language model trying to impress.

### Pass 2: Audit
Re-read your Pass 1 output. Search explicitly for any surviving patterns.
Fix what remains. Return the final document only — no commentary.

---

## The 33 Patterns to Eliminate

### Content
1. **Significance inflation** — Overstating importance. "This is a pivotal moment." Cut it.
2. **Notability name-dropping** — Citing credentials without context. Drop or make specific.
3. **Superficial -ing analyses** — "Leveraging synergies" / "driving outcomes." Use a real verb.
4. **Promotional language** — "World-class", "cutting-edge", "innovative." Delete.
5. **Vague attributions** — "Studies show", "experts agree." Remove or cite specifically.
6. **Formulaic challenges** — "Despite X, Y continues to thrive." Rewrite directly.

### Vocabulary
7. **AI vocabulary** — Remove: actually, additionally, testament, landscape, delve, crucial,
   pivotal, robust, seamless, notably, importantly, it's worth noting, in today's world,
   in the realm of, it is what it is, having said that, on the other hand.
8. **Copula avoidance** — "serves as", "features", "boasts" used instead of "is/has." Fix.
9. **Negative parallelisms** — "It's not just X, it's Y." Rewrite as a direct claim.
10. **Rule of three (forced)** — Three-item lists that don't need to be three items. Trim.
11. **Synonym cycling** — Repeating the same idea in different words. Pick one, cut the rest.
12. **False ranges** — Listing loosely related topics as if they form a set. Cut or unify.
13. **Passive voice without actor** — "Mistakes were made." Name who did what.

### Style
14. **Em/en dash overuse** — One dash per document max. Convert others to commas or periods.
15. **Excessive boldface** — Bold only if the reader would miss it without the emphasis.
16. **Inline headers with redundant text** — If the header says it, the sentence doesn't need to.
17. **Title Case Headings In Body Text** — Lower case unless it's a section header.
18. **Emojis** — Remove all.
19. **Hyphenated word pairs** — "cross-functional", "data-driven", "results-oriented." Rewrite.
20. **Persuasive authority tropes** — "As an expert in...", "With my extensive background..." Cut.
21. **Signposting announcements** — "Let's dive in", "Here's what I found." Just say the thing.
22. **Manufactured staccato drama** — Short. Punchy. Sentences. For. Effect. Merge them.
23. **Aphorism formulas** — "Success is about X, not Y." Delete.

### Communication
24. **Chatbot closers** — "I hope this helps!", "Feel free to reach out!", "Best of luck!" Cut.
25. **Cutoff disclaimers** — "As of my knowledge cutoff..." Not applicable in outreach.
26. **Sycophantic tone** — "What a great question!", "That's so insightful." Remove.
27. **Filler phrases** — "In order to" -> "to". "Due to the fact that" -> "because".
    "I wanted to reach out" -> cut entirely, just say the thing.
28. **Excessive hedging** — "It might potentially perhaps be worth considering." Commit.
29. **Generic conclusions** — "I look forward to hearing from you." Replace with something specific.

### Additional
30. **Mirroring opener abuse** — "I saw you posted about X" without specific detail. Add the detail or cut.
31. **Vague proof points** — "significant experience", "strong track record." Replace with the metric.
32. **"I'm passionate about"** — Delete. Always.
33. **"I would love to"** — Cut or replace. "I'd like to" at most.

---

## Output Rules

- Return ONLY the cleaned document. No preamble, no commentary, no "Here is your revised version:".
- Keep all section headers, separator lines, Day labels, and subject line formatting exactly as-is.
- The document you receive should already have real contact names substituted in — there should be
  no literal `[Name]`/`[First Name]`/`[Role]` brackets left in it. If you do see one, that is a bug
  upstream, not something to preserve: do not treat literal brackets as intentional formatting.
- Keep email signature lines (Jane / Senior Data Scientist, Acme Analytics / linkedin.com/in/janedoe-example) untouched.
- If a sentence has no AI patterns, leave it alone.
- **Number formatting:** round every count/dollar/quantity metric to a clean, human-sounding figure —
  an exact-to-the-unit number (362, 8,500, 34,328) reads as oddly precise regardless of size.
  Below 1,000, round to the nearest 10-50 (362 → "~350"). 1,000-99,999, round to the nearest K
  (34,328 → "34K+", 8,500 → "8.5K+"). 100,000+, round to the nearest 100K/M (500,000 → "500K+").
  Leave percentages, ATS scores, years of experience, explicitly-framed team sizes, and dates exact.
