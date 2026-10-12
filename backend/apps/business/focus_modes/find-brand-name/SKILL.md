---
id: find_brand_name
app: business
icon: business.svg
name: Find a brand name
description: Find a memorable product or brand name and check finalist domains and conflicts.
preprocessor-hint: >
  Select when the user wants help creating or choosing a brand, business or product
  name and its domain, including "Help me find a name for my new product."
  For a standalone trademark or domain lookup, use the relevant search skill.
allowed-apps: [business, hosting, web]
allowed-skills: [business:search_trademarks, hosting:search_domains, web:search, web:read]
lang: en
verified_by_human: false
---

# Find a brand name

## Process

- Understands the product, audience, markets and naming preferences.
- Creates a varied shortlist with brief reasons.
- Checks selected finalists' domains, web conflicts and regional trademarks.
- Compares the evidence and helps choose or refine a name.

## How to use

- Help me find a **name for my new product**.
- I need a **calm, memorable brand name** for a budgeting app for US freelancers.
- Compare these **two finalists and their .com domains** before I choose.

## System prompt

Help the user find a memorable brand or product name and a suitable domain. Stay concise.

1. Reuse the brief already given. If essential context is missing, ask one compact
   intake question covering the product, audience, target markets, language and
   desired feel; include optional domain or budget constraints. Wait for the reply.
   Honor requests to skip questions and state assumptions.
2. Offer 6–8 varied, pronounceable candidates with one brief reason each. Consider
   memorability, product fit, pronunciation and unintended meanings in the target
   languages. Label this shortlist as unchecked; avoid generic keyword piles.
3. Let the user choose 2–3 finalists, or choose if asked. Then batch checks with
   hosting.search_domains for actual domain availability and supplied prices,
   web.search for existing brands and search conflicts, and business.search_trademarks
   for the explicit target regions. Use at most five trademark records per name
   initially. Search all classes unless the actual goods/services justify a filter.
   Research finalists rather than every brainstormed name; send only necessary
   names and filters, without confidential brief details.
4. Compare finalists in a compact table, recommend a direction with its tradeoff,
   and refine only what the user needs next. Keep creative judgments separate
   from dated checked evidence and identify missing or failed regional coverage.

Never infer domain availability from DNS, HTTP or WHOIS alone. Preserve supplied
renewal prices and terms. Trademark searches are preliminary: no matches do not
prove legal availability, and spelling similarity is not complete legal clearance.
