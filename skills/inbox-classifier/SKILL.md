<!-- skill: inbox-classifier -->
# SKILL: Inbox Reply Classifier

Classify a single inbound email reply to a job-outreach message. Output **only**
a JSON object, nothing else — no prose, no markdown fences.

## Output format

```json
{"classification": "ooo" | "rejection" | "bounce" | "genuine_reply" | "other", "extracted_date": "YYYY-MM-DD" | null}
```

## Classification rules

- **ooo** — an out-of-office / automatic reply stating the person is away.
  Extract a return date if the message states or implies one (e.g. "back on
  Monday", "returning July 15th", "out until 6/20"). If no usable date can be
  determined, set `extracted_date` to `null` — never guess.
- **rejection** — the sender states or clearly implies the candidate will not
  be moving forward for this specific role (e.g. "we've decided to move
  forward with other candidates", "not a fit at this time"). `extracted_date`
  is always `null` for this classification.
- **bounce** — an automated mail-delivery-failure notification, not a reply
  from a person at all: "couldn't be delivered", "wasn't found at", "user
  unknown", "mailbox full", "Undeliverable:", non-delivery reports from
  mail servers (Exchange, Gmail's own mailer-daemon, etc.), regardless of
  the specific sender address or subject wording used. `extracted_date` is
  always `null` for this classification.
- **genuine_reply** — any other substantive reply from the person that isn't
  OOO, a rejection, or a bounce — interest, a question, scheduling a call, a
  referral, "let me check and get back to you", etc. `extracted_date` is
  always `null`.
- **other** — anything that isn't a genuine reply from this person about this
  role: forwarded/CC'd threads, mailing-list or newsletter content, another
  auto-reply that isn't OOO or a bounce (e.g. a ticket-system acknowledgment),
  spam. `extracted_date` is always `null`.

## Rules

- Output valid JSON only. No commentary before or after it.
- Never guess a return date you can't support from the message text.
- A short "thanks, got it" or similar acknowledgment with no other content is
  `genuine_reply`, not `other` — it's a real response from a real person.
