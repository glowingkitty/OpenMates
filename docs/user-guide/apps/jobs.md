---
status: active
doc_type: guide
audience:
  - end-users
last_verified: 2026-10-13
claims:
  - id: user-guide-apps-jobs-source
    type: unit
    claim: The Jobs app guide is grounded in the Jobs app metadata.
    file: scripts/tests/test_user_guide_app_docs_claims.py
    assertion: user-guide-apps-jobs-source
---

# Jobs

> Find job offers and explore your next career move.

## What It Does

**Search** finds job offers by role, countries and location. Germany searches include Bundesagentur für Arbeit and Arbeitnow; Sweden searches include the public employment service's JobTech API. 80,000 Hours and Hard Problems add meaningful and impact-focused jobs for both countries. You can compare several searches in one request and optionally filter by remote work, employment type or posting age.

Results include the employer, workplace, description and original listing link. Open a search result to browse its job cards, then open a card for the full listing and application link. Salary and remote status are shown only when the source supplies them. A hybrid-work mention does not establish that a job is fully remote.

Coverage varies by source, and offers can close after a search. Follow the original link to confirm availability and requirements. A source failure can leave useful results from other sources; OpenMates shows a partial-results notice in that case.

The Jobs app also provides a career insights focus mode that acts as a thoughtful career advisor. It helps you gain clarity on your career direction through an in-depth conversation about who you are, what you want, and what is realistic for you.

**Available focus mode:**

- **Career Insights** -- A guided conversation that helps you figure out your next career move. Your mate asks about your current situation, background, skills, interests, values, and practical constraints. It then suggests 2-4 concrete career directions with explanations of why each fits your profile, what the typical path looks like, and what steps to take next.

## How to Use It

- Find offers: "Find software developer jobs in Berlin posted in the last week"
- Compare places: "Find developer jobs in Stockholm and Malmö, with original listing links"
- Filter working arrangements: "Find fully remote engineering jobs in Germany"
- Start a conversation: "I am feeling stuck in my job and want to explore other options"
- Get guidance: "Help me figure out what career path makes sense for me"
- Explore options: "I have a background in marketing but I am interested in tech -- what should I consider?"

## Automate Job Searches

Add a **Jobs Search** action to a [Workflow](../workflows.md). Set the role keyword, select Germany, Sweden or both, and add any location or other filters. Only providers covering the selected countries are queried, in parallel. Add up to five search requests to compare roles or cities. The remote-work selector offers **Any**, **Fully remote** and **On-site**; Any leaves this filter unset.

Use the action's **Results** in a later **For each** step to inspect individual jobs, or include its result count in a **Send message** step. Each result provides typed fields such as title, company, country, location and listing URL. Configure the Workflow's trigger to repeat the search on your preferred schedule.

## Tips

- The career insights mode asks questions one or two at a time rather than overwhelming you with a long list.
- It takes into account practical constraints like location, finances, and family.
- Suggestions include concrete next steps like specific courses, communities, or job boards to explore.
- The mode is honest about realistic expectations while framing feedback constructively.

## Related

- [Web](./web.md) -- Research specific companies or industries
- [Study](./study.md) -- Track learning goals for skill development
