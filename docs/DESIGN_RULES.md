# Design Rules

These rules keep application materials accurate, useful, and under the user's control.

1. **Do not invent qualifications or metrics.** Use source-backed career facts and preserve their source IDs so a claim can be checked.
2. **Respect hidden-role rules.** Do not reveal a confidential employer or recruiter-hidden detail in generated materials.
3. **Keep each job's files together.** Separate output folders make it easier to review and retrieve the right application.
4. **Reject fabrication, not imperfect fit.** ATS checks should fail on unsupported claims. Give the writer up to three attempts to fix quality problems.
5. **Respect user-controlled region order.** Detection order can affect names and contact details in a CV, so the user controls the regions and their priority.
6. **Treat profile photos as optional.** If a user supplies a photo, use it consistently where the selected CV design supports it.
7. **Keep follow-ups in the agreed sequence.** Use the Day 0, Day 5, and Day 12 email schedule, with a LinkedIn message after acceptance.
8. **Do not put agency names in a hiring-company summary.** The agency is not the employer and may obscure a confidential role.
9. **Keep Gmail drafts-only.** A person must review and send every email.
10. **Do not use Proxycurl.** Contact and profile workflows must use supported, authorized sources.
11. **Do not mention visa status unless the user supplied it and asked to include it.** Unprompted visa claims can be inaccurate or harmful.
12. **Use the supported contact types only.** This keeps contact filtering and follow-up behavior predictable.
13. **Attach the CV to the first email only.** Later follow-ups should not resend it automatically.
14. **Company research must never block outreach.** Missing profile data is an optional gap, not a pipeline failure.
15. **Track each draft separately.** A saved draft is not evidence that a message was sent.
16. **Salary estimation should fail safely.** Missing or invalid research must not cause an API error or present a made-up value.
17. **Do not profile recruitment agencies as employers.** Researching a confidential client as if it were the agency can mislead the user.
18. **Do not treat “Confidential” as a company name.** Leave unknown employers unknown rather than inventing a profile.
19. **Allow a person to correct agency detection.** Automated classification can be wrong; preserve a manual override.
20. **Round money and scores consistently.** Clear precision is easier to compare and less likely to imply false accuracy.
21. **Do not cap a valid ATS score merely to make it look familiar.** Keep the score within the defined scoring range and explain it.
22. **Use one quality gate for generated claims.** CV, cover letter, and outreach must follow the same evidence rules.
23. **Deduplicate jobs by stable job ID.** URL tracking parameters should not create duplicate applications.
24. **Limit discovery to the job's context.** Contacts should be plausibly relevant to the role and company.
25. **Use only the supported contact categories and fields.** Invalid or incomplete candidates should be skipped safely.
26. **Do not equate an entry-point or self-check with a working service.** Verify the actual API and dashboard behavior.
27. **Keep tests isolated.** Use a copied fictional fixture and fake provider so tests cannot read or change a user's live data.
28. **Treat AgentMail as the default email option, with a human send step.** Convenience does not remove user review.
29. **Keep web research within its safeguards.** Use logged-out public pages, observe the configured budget limit, and require a human to approve sourced jobs.
