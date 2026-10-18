<!-- skill: profile-builder -->
Build a factual career profile from the supplied CV and optional LinkedIn evidence.
Return ONLY JSON, without prose or fences, using this exact schema:
{"career":{"headline_variants":[{"label":"","text":""}],"narrative":"","why_looking":"","target_roles":[],"notice_period":"","target_compensation":"","work_authorization":""},"roles":[{"company":"","title":"","location":"","start":"YYYY-MM","end":"YYYY-MM or present","hidden":false,"description":"","owned":"","achievements":[{"text":"","metric":"","context":"","needs_metric":true}],"technologies":[],"keywords":[]}],"education":[{"degree":"","school":"","dates":"","detail":""}],"projects":[{"name":"","context":"","text":""}],"skills":{"category":["skill"]},"certifications":[]}

NEVER invent numbers. All numbers must come from input evidence. When no metric is
available, use metric "" and needs_metric true. Keep one achievement per
accomplishment. Use 2–3 headline variant families grounded only in supplied facts.
Unknown text fields are ""; unknown lists are []; unknown skills are {}. Keep roles
most recent first. Hidden role flags are profile data: never invent them.
For a fresh draft, never output id or unverified: the server owns those fields.
When existing profile context is supplied, preserve its IDs and user edits.

For MODE: apply_gaps, rewrite ONLY the answered achievements' text and metric with
the user's supplied facts and numbers. Keep all existing IDs, set needs_metric
false for answered achievements, and change NOTHING else. Return the full JSON
profile while preserving unanswered achievements and all unrelated data.
