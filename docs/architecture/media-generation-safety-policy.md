# Media Generation Safety Policy

**Status:** Initial implementation
**Applies to:** `images-generate`, `images-generate_draft`, `videos-generate`, `music-generate`

OpenMates supports useful generative media work: product mockups, design drafts,
education, accessibility, personal creative work, documentation, storyboards,
and other legitimate projects. It must not help users create spam, scams,
deceptive synthetic media, or public-figure impersonation.

## Always Block

1. Fraud or scams: phishing assets, fake login pages, fake documents, fake
   testimonials, counterfeit material, credential-harvesting, wallet-draining,
   get-rich-quick or guaranteed-return campaigns.
2. Spam or AI slop: mass content-farm generation, large batches of ads/posts,
   moderation evasion, watermark removal, or requests to hide AI origin.
3. Public figure voice/persona/likeness imitation: narration, singing, visual
   likeness, persona, endorsement, testimonial, or cadence that imitates a real
   public person. This includes science educators, documentary narrators,
   politicians, artists, musicians, CEOs, influencers, journalists, and other
   recognizable people.
4. Deceptive synthetic media: fake realistic footage, leaked audio/video,
   official announcements, confession videos, fake news clips, or any generated
   media intended to be mistaken for real evidence.

## Safer Alternatives

Offer original, non-deceptive substitutes:

- “an original warm science narrator voice” instead of a named educator
- “documentary-style pacing” instead of a named documentary narrator
- “upbeat original pop vocals” instead of a living singer's voice
- “clearly fictional product mockup” instead of fake endorsement material

## Batch Limits

- Images: max 5 requests per skill call
- Videos: max 1 request per skill call
- Music: max 5 requests per skill call

These limits reduce accidental bulk-spam generation while preserving useful
iteration workflows.
