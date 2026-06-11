---
status: active
doc_type: guide
audience:
  - users
last_verified: 2026-06-10
claims:
  - id: user-guide-billing-pricing-source
    type: unit
    claim: Pricing guidance is grounded in credit billing utilities, payment routes, and charge behavior.
    file: scripts/tests/test_user_guide_billing_docs_claims.py
    assertion: user-guide-billing-pricing-source
---

# Pricing

## Summary

Cloud OpenMates uses a credits system for paid usage. You buy credits and spend them as you send messages or use paid app skills.

## What It Does

Instead of monthly subscriptions, OpenMates uses **credits**. You buy credits and spend them as you send messages and use app skills. Different actions cost different amounts depending on the model and tools used.

## How Credits Work

- **Buy credits** in Settings > Billing.
- **Minimum charge** is 1 credit per request.
- **Prices vary** by model and skill. More powerful models cost more credits per message.

## What Gets Charged

- **Messages**: Every message you send uses credits based on the length of the conversation and the model selected.
- **App skills**: Tools like web search, image generation, and code execution have their own prices. Some charge per use, per token, or per unit, like per image or per minute of audio.
- **Prices are listed** in the Apps section for each skill.

## Cost Transparency

- **Prices are listed** in the Apps section for each skill, so you know the cost before using them.
- In your billing section, you can see a detailed breakdown of credits used per chat.
- You can **export any chat** to see the full billing details and token counts.

## Running Out of Credits

- OpenMates allows a small overdraft so multi-step requests can finish cleanly.
- If your balance reaches the hard overdraft limit, paid calls are refused with an insufficient-credits error until you buy or redeem more credits.

## Tips

- Check your credit balance in Settings > Usage at any time.
- Enable **auto top-up** in Settings > Billing to automatically purchase credits when your balance gets low.
- Gift cards can also be redeemed for credits. See [Gift Cards](gift-cards.md).

## Related

- [Usage & Billing](usage.md) -- Viewing your usage history
- [Gift Cards](gift-cards.md) -- Redeeming gift cards for credits
