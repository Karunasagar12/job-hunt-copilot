# SKILL: Outreach Drafter — Precision Job Outreach Engine

Draft targeted outreach for each contact. Auto-detect contact type from title and context —
never ask the user. Every email follows the same skeleton; only the ask changes by type.
Every email must be impossible to reuse for a different company or role.

## Sources of Truth
- `employment-master.md` — proof points and exact metrics (never invent numbers)
- `career-master.md` — positioning, narrative, "why looking now"

---

## Contact Type Detection

Infer type from title and company context. Never ask.

| Type | Signals |
|------|---------|
| **Hiring Manager** | Team Lead, Engineering Manager, VP, Director, CTO, Founder, Head of X — at the hiring company, direct authority over the role |
| **Recruiter** | "Talent Acquisition", "Recruiter", "HR", "People Partner" — at the hiring company |
| **Agency** | Any title at a known recruitment agency (La Fosse, Robert Walters, Hays, Michael Page, Korn Ferry, etc.) — not at the hiring company itself |
| **Executive** | CEO, VP, C-suite, senior leader at the hiring company who does NOT have direct hiring authority over this specific role |
| **Peer** | Currently holds the same or similar title to the role being applied for, at the target company |

---

## The Flow (universal across all 5 types)

```
Day 0   EMAIL 1      Cold email — sent first
Day 0   LI REQUEST   LinkedIn connection note — sent same day
Day 1+  LI DM        After they accept — references the email, nothing more
Day 5   EMAIL 2      Restates the ask with a timely nudge — never a new pitch
Day 12  EMAIL 3      Graceful close. Then stop.
```

Email is the primary channel. LinkedIn is the cross-channel reference that increases
warm recognition and visibility. Do not treat LinkedIn as the pitch channel.

---

## Universal Skeleton (all 5 types, Email 1)

Every Email 1 — regardless of contact type — is built from the same pieces. Only the
ask (see below) changes by type.

1. **Personal connection opener, when findable.** If the candidate and recipient share
   something real — same university, same city, same former employer, mutual LinkedIn
   connections — open with one line referencing it, **only for Peer contacts.** For
   Hiring Manager, Recruiter, Agency, and Executive, skip straight to the credential
   line — shared background reads as camaraderie, which undersells you to someone
   evaluating or gatekeeping the role rather than a lateral colleague. This is an
   enhancement for Peer only, never a requirement — do not invent a connection that
   doesn't exist.
2. **One credential line matched to the JD.** Not a summary, not three bullets. Pick the
   single strongest overlap between the candidate's background (employment-master.md)
   and what this JD is asking for. One line only.
3. **"I've already applied online" blocker.** State plainly that a formal application
   has already been submitted. This preempts "just apply on our website" and signals
   the candidate followed process AND is reaching out on top of it.
4. **Resume attached instruction.** Tell the recipient the tailored CV for this exact
   role is attached.
5. **The ask** — see the per-type table below. Exactly one ask. Never stack multiple
   asks in one email.

**Target range: 60-80 words for Email 1.** Not "aim for brevity" — count the words. Below
60 starts dropping required elements; above 80 stops rendering as one screen on mobile,
where most of these get read. The recipient decides read-or-delete in seconds.

---

## The Ask (per type — this is the ONLY thing that varies)

| Type | The Ask |
|------|---------|
| **Hiring Manager** | For their time: "Would welcome 15 minutes to discuss how my experience fits." They evaluate and decide — an audition is exactly what they expect from a strong candidate. |
| **Recruiter** | For visibility: "Could you help ensure my application gets fair visibility?" They route applications — this asks them to do their job, low-effort and aligned with their role. |
| **Agency** | For a conversation: "I'd welcome a conversation about roles matching this profile." Agencies are paid on placement — offer yourself as inventory across their book, not one role. |
| **Executive** | For routing: "I'd appreciate any steer on who's leading the hiring for this." They have no evaluation authority over this specific role and won't champion an application — asking them to meet, evaluate, or advocate misreads the relationship. Routing is the only ask that respects their position. |
| **Peer** | For perspective: "Curious what the reality of this role looks like day-to-day — happy to trade notes." "Happy to trade notes" signals reciprocity, not extraction. Never ask a peer for a referral in Email 1 — that only belongs in a Day 5+ follow-up, and only after they've actually replied. |

**NEVER swap asks between types.** Asking a Peer for 15 minutes, or an Executive to evaluate your CV, misreads what that person can actually do for you.

---

## Email 2 — Day 5 (all types)

Restates the same ask in a slightly different frame. **No new credentials, no new
pitch, no escalation of the ask.** The only new element is one lightweight reason to
reply now: "I'm in final stages with another opportunity" or "noticed your team just
posted a second role in this area." Not a bigger or smaller version of Email 1 — same
ask, same 60-80 word range, one nudge added.

NEVER: "just following up", "circling back", "bumping this", "checking in"

---

## Email 3 — Day 12 (all types)

Final touch. Graceful close: "understand if the timing isn't right, wanted to make one
last attempt before moving on." This gives permission to not reply while being the
email that sometimes gets a response because it signals the candidate is about to
disappear. Same ask, same 60-80 word range. No new pitch, no artifact dump, no
escalation. Then stop — no Email 4.

---

## LinkedIn Cross-Channel

### CONNECTION REQUEST — Day 0 (same day as Email 1)

Max 200 characters (LinkedIn free-plan note limit) — count before you finish. Do NOT pitch. Do NOT re-state your qualifications.
Reference that you emailed. Mention one specific thing about their work, background,
or the role that made you reach out — this is what gets accepted.

### DM — After acceptance only (Day 1+)

Send ONLY after they accept. Under 40 words.
Reference the email so they have context. Confirm the same ask from Email 1. Never
re-pitch or introduce a new ask.

---

## Send Timing (advisory)

Best sent Tuesday–Thursday morning. This is a recommendation surfaced in the UI when
the candidate is about to send or create a Gmail draft — never enforced. The system
never blocks, delays, or refuses to draft based on day of week.

---

## Company Intelligence (enhancement, not a dependency)

When a structured company profile exists in the system (built by a separate research
agent — see the Company tab in the dashboard), use it to sharpen the credential line or
reference one specific company detail in Email 1. When no profile exists yet, draft the
email exactly as normal — the credential line and the ask carry the email regardless. A
missing profile is never a reason to delay, skip, or degrade an email.

---

## MVP-for-Meeting Offer — NEVER AUTOMATED

Offering to build a free MVP or proof-of-concept in exchange for a meeting is a manual,
human-judgment tactic the candidate deploys by hand, after a real person has replied
with genuine interest. **Never generate, suggest, or template this in any output for
any contact type, at any touchpoint.** It lives entirely outside this pipeline.

---

## Universal Rules

### NEVER
- Fabricate metrics — use only numbers from employment-master.md
- Mention visa status, work authorisation, immigration details, or right to work — in
  any email, LinkedIn note, or DM, for any contact type, at any touchpoint
- "I hope this finds you well" / "just following up" / "circling back" / "bumping this" /
  "would love the opportunity" / "at your convenience" / "I wanted to reach out" /
  "leveraging" / "spearheading" / "passionate about"
- Repeat Email 1's exact wording in Email 2 or Email 3 — same ask, different frame
- Write an email that could be sent to a different company without changing a word
- Stack more than one ask in a single email
- Offer an MVP, proof-of-concept, or free work in any automated template
- Use em dashes (—) in body prose — use commas or periods
- Use third person

### ALWAYS
- Auto-detect contact type from title and context — never ask the user
- Start every email with "Hi " followed by the contact's actual first name, on its own line — no exceptions.
  Every bracketed placeholder shown in the Output Format below (`[First Name]`, `[Full Name]`,
  `[Title]`, `[Company]`, `[subject line]`, `[body]`, etc.) marks WHERE real content goes — it is
  never literal output. If you do not know the contact's first name, use their full name instead.
  A literal square bracket appearing anywhere in a finished email or LinkedIn message is always a
  mistake — there is no case where outputting "[First Name]" or "[Name]" literally is correct.
- Mirror vocabulary from the JD and contact's LinkedIn/title exactly
- Keep Email 1, 2, and 3 each within 60-80 words — count before finalizing
- Use exactly one ask per email, matched to contact type
- Reference the email in the LinkedIn DM (cross-channel hook)
- Include full signature block at the end of every email

---

## Signature

```
Jane
Senior Data Scientist, Acme Analytics
linkedin.com/in/janedoe-example
```

---

## Output Format

For EACH named contact, produce exactly this structure. Use the exact separators shown.
Three emails only — no EMAIL 4.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTACT: [Full Name] — [Title] @ [Company]
Email: [email or Unknown]
LinkedIn: [url or Unknown]
Type: [Hiring Manager / Recruiter / Agency / Executive / Peer]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── EMAIL 1 (Day 0 — send first) ──
Subject: [subject line]

Hi [First Name],

[body]

Jane
Senior Data Scientist, Acme Analytics
linkedin.com/in/janedoe-example

── LINKEDIN CONNECTION REQUEST (Day 0 — send same day) ──
[max 200 chars]

── LINKEDIN DM (send after they accept) ──
[max 40 words]

── EMAIL 2 (Day 5) ──
Subject: Re: [same subject]

Hi [First Name],

[body]

Jane
Senior Data Scientist, Acme Analytics
linkedin.com/in/janedoe-example

── EMAIL 3 (Day 12) ──
Subject: Re: [same subject]

Hi [First Name],

[body]

Jane
Senior Data Scientist, Acme Analytics
linkedin.com/in/janedoe-example
```

For the General Template (no specific contact known), use this header instead:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GENERAL TEMPLATE — No Specific Contact
Use for: cold outreach to unknown hiring manager or recruiter
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Then produce TWO sub-sections: "-- FOR HIRING MANAGER --" and "-- FOR RECRUITER --".
Each follows the full EMAIL 1 → LI REQUEST → LI DM → EMAIL 2 → EMAIL 3 structure.
Use [Name] as placeholder.
