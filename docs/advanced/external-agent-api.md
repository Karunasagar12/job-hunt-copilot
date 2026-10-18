# External research and saved-jobs API

This guide is for an optional external agent that you operate. It describes webhook endpoints exposed by the local Job Hunt Copilot API. The app does not include or run the external agent.

The API listens on `127.0.0.1` by default. An external process must be able to reach that local address, or you must provide a private, secure network path. Do not expose the app to the public internet: it has no login. Send `X-Webhook-Secret` on every request. Use HTTPS if traffic leaves your computer or trusted private network.

## Configure secrets

Set separate, long random values in **Settings → Webhooks**, or provide them as environment variables:

```text
WEBHOOK_SECRET=<random secret for company research>
SAVED_JOBS_WEBHOOK_SECRET=<different random secret for saved jobs and contacts>
```

The values can also be stored under `webhooks.secret` and `webhooks.saved_jobs_secret` in `data/settings.json`. Keep secrets private. The API compares the header against the configured value; missing or incorrect secrets receive `401 Unauthorized`.

## Company research

The app may queue a company name for optional enrichment. This data does not block CV generation, outreach, or dashboard use.

### List pending company names

```http
GET /api/company-profiles/pending
X-Webhook-Secret: <WEBHOOK_SECRET>
```

Response:

```json
{"companies": ["Example Company"]}
```

An empty list means there is no work waiting.

### Deliver a company profile

Use the exact company string from the pending response. Send any known subset of these fields:

```http
POST /api/company-profiles/<URL-encoded-company-name>
X-Webhook-Secret: <WEBHOOK_SECRET>
Content-Type: application/json
```

```json
{
  "sector": "Example industry",
  "company_size": "51-200",
  "funding_stage": "Series B",
  "tech_stack": "Python, PostgreSQL",
  "geography": "Head office and relevant locations",
  "recent_news": "A short, sourced summary",
  "competitors": "Relevant competitors",
  "hiring_for": "Teams or roles visibly hiring",
  "mission_values_culture": "Publicly stated mission and attributed culture signals",
  "employer_rating": "Rating, review count, and source"
}
```

Unrecognized keys are silently ignored. If the request contains only unknown keys, the API still accepts it and may mark the company profile complete without saving useful profile fields. Send at least one recognized field, preferably a complete profile in one request; another request updates the stored values. Omit information that cannot be verified rather than guessing.

## Saved job intake

An external tool can add a public LinkedIn job URL for later processing:

```http
POST /api/saved-jobs/ingest
X-Webhook-Secret: <SAVED_JOBS_WEBHOOK_SECRET>
Content-Type: application/json
```

```json
{"url": "https://www.linkedin.com/jobs/view/1234567890/", "source_type": "company"}
```

`source_type` must be `company` or `recruiter`. The URL must contain `/jobs/view/<numeric-id>`. A newly queued job returns `202` and `{"status":"queued"}`. A duplicate returns `200` and `{"status":"duplicate"}`. Invalid input returns `400`.

## Contact discovery

### List jobs awaiting contacts

```http
GET /api/saved-jobs/needs-contacts
X-Webhook-Secret: <SAVED_JOBS_WEBHOOK_SECRET>
```

The response contains a `jobs` array with job ID, company, role, job URL, and company size when known. An empty array is normal.

### Check a candidate before delivery

```http
GET /api/saved-jobs/contact-lookup?linkedin_url=<URL-encoded-public-profile-url>
X-Webhook-Secret: <SAVED_JOBS_WEBHOOK_SECRET>
```

Response:

```json
{"already_exists": false, "email": null}
```

When `already_exists` is true, discard that candidate. `email` is present only when the configured enrichment provider returns an email considered verified. A missing email alone is not a reason to discard a relevant candidate.

### Deliver candidates

```http
POST /api/jobs/<job-id>/discovered-contacts
X-Webhook-Secret: <SAVED_JOBS_WEBHOOK_SECRET>
Content-Type: application/json
```

```json
{"candidates": [
  {
    "name": "Candidate Name",
    "title": "Product Director",
    "contact_type": "hiring_manager",
    "linkedin_url": "https://www.linkedin.com/in/example-person/",
    "email": null
  }
]}
```

There is no enforced candidate-count limit in the endpoint. Send only relevant candidates, and keep each delivery concise; an empty list is accepted. `contact_type` must be one of `hiring_manager`, `recruiter`, `agency`, `executive`, or `peer`. A public LinkedIn profile URL is required. `email` is optional; if omitted, the app may look it up using its configured provider. Duplicate LinkedIn URLs or email addresses are skipped across the whole database. Other candidate properties such as `why_relevant` are not persisted. The response reports `added` and `skipped` counts.

Use public information, do not invent contact details, and do not access authenticated social media pages or automate actions on those services. Delivered contacts appear in the dashboard for the user to review.
