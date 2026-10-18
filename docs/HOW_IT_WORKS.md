# How it works

Job Hunt Copilot keeps its application data on your computer. You add a job, review the details, and the app prepares materials using your profile and career knowledge. You decide what to edit, save, and send.

## A job's path through the app

1. **Job description:** add a job description or public job link. The app collects the available details.
2. **Agency and region:** it checks whether the listing appears to come from a recruiter and identifies likely work regions. Your configured region order guides selection.
3. **Career knowledge:** it loads the facts you reviewed during setup. Generated claims should be traceable to those facts; missing facts are not invented.
4. **CV draft and checks:** the CV writer creates a tailored draft. The ATS checker reviews it against the job description, and a shared quality gate checks for unsupported claims. The system can make up to three attempts.
5. **PDF:** the approved CV draft is rendered to a PDF in that job's output folder.
6. **Cover letter and outreach:** the app prepares a cover letter and contact-specific outreach drafts where those features are available.
7. **Human review:** you review generated content. Email integrations create drafts; a person chooses whether to send them. LinkedIn actions are not automated.

## Outreach schedule

When you start outreach, the suggested sequence is:

| Day | Touchpoint |
| --- | --- |
| 0 | Email draft and LinkedIn connection suggestion |
| After connection acceptance | LinkedIn message draft |
| 5 | Second email draft |
| 12 | Third email draft |

The CV is attached to the first email only. The app tracks draft and send status so it does not treat every prepared draft as sent.

## Local data

The `data/` folder contains settings and secrets, your profile, uploaded CVs, reviewed knowledge files, the application database, scheduler state, and generated output. Typical folders include:

```text
data/
  settings.json
  profile.json
  pipeline.db
  knowledge/
  uploads/
  output/
  gmail/
```

Back up this folder to preserve your work. Do not commit it or put it in a shared location without protecting it.

## Background schedule

The scheduler uses the timezone in your profile. Jobs run only when the required integration is connected.

| Background job | When it runs | Connection needed |
| --- | --- | --- |
| Gmail sent-mail check | At the configured polling interval | Gmail |
| Gmail inbox scan | At the configured local time | Gmail |
| AgentMail inbox scan | Five minutes after the configured inbox scan time | AgentMail |
| Job sourcing | At the configured local time | Apify and sourcing settings |
| Saved-job queue | 3:00 a.m. local time | Saved-jobs webhook secret |

You can view and change schedule settings in the dashboard. Disabled integrations do not block the rest of the application.
