export const privacyPolicyLinks = {
  // Group A — Always active
  vercel: "https://vercel.com/legal/privacy-policy",
  hetzner: "https://www.hetzner.com/legal/privacy-policy",
  brevo: "https://www.brevo.com/legal/privacypolicy",
  ipApi: "https://members.ip-api.com/privacy-policy",
  sightengine: "https://sightengine.com/policies/privacy",
  apiVideo: "https://api.video/privacy-policy/", // verified 2026-04-14

  // Group B — Payments
  stripe: "https://stripe.com/privacy",
  revolutBusiness: "https://www.revolut.com/en-LT/legal/privacy/", // Revolut Bank UAB (Lithuania) — verified 2026-04-14

  // Group C — AI models
  inception: "https://www.inceptionlabs.ai/docs/privacy-policy", // verified 2026-10-20
  inceptionTerms: "https://www.inceptionlabs.ai/docs/terms-of-use", // verified 2026-10-20
  mistral: "https://legal.mistral.ai/terms/privacy-policy/", // verified 2026-09-23
  aws: "https://aws.amazon.com/privacy/",
  anthropic: "https://www.anthropic.com/legal/privacy",
  openai: "https://openai.com/policies/privacy-policy",
  openrouter: "https://openrouter.ai/privacy",
  typesafe: "https://typesafe.ai/legal/privacy-policy", // verified 2026-10-19
  typesafeDataProcessing: "https://typesafe.ai/legal/data-processing", // verified 2026-10-19
  typesafeLegal: "https://docs.typesafe.ai/legal", // verified 2026-10-19
  cerebras: "https://www.cerebras.ai/privacy-policy",
  google: "https://policies.google.com/privacy",
  googleGemini: "https://ai.google.dev/gemini-api/terms",
  googleVertexMaas: "https://cloud.google.com/terms/cloud-privacy-notice",
  googleVertexAi: "https://cloud.google.com/terms/cloud-privacy-notice", // verified 2026-05-21
  together: "https://www.together.ai/privacy",
  groq: "https://groq.com/privacy-policy",
  alibaba:
    "https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-privacy-policy",
  deepseek:
    "https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html",
  moonshot: "https://platform.kimi.ai/docs/agreement/userprivacy",
  zai: "https://docs.z.ai/legal-agreement/privacy-policy",

  // Group D — Image generation
  fal: "https://fal.ai/legal/privacy-policy", // verified 2026-04-14
  recraft: "https://www.recraft.ai/privacy", // verified 2026-04-14
  bfl: "https://blackforestlabs.ai/privacy-policy/",

  // Group D2 — Audio generation and text-to-speech
  elevenLabs: "https://elevenlabs.io/privacy-policy", // verified 2026-08-09

  // Group E — 3D model generation
  hi3d: "https://docs.hi3d.ai/en/api/resources/privacy-policy", // verified 2026-07-11

  // Group F — Code and developer tools
  github:
    "https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement",
  context7: "https://upstash.com/trust/privacy.pdf", // Context7 is an Upstash project; verified 2026-05-24
  e2b: "https://e2b.dev/privacy", // verified 2026-05-19

  // Group F — Web, search, content retrieval
  brave: "https://brave.com/privacy/",
  iconify: "https://iconify.design/privacy/", // verified 2026-07-18
  googleMaps: "https://privacy.google.com/",
  geoapify: "https://www.geoapify.com/privacy-policy/", // verified 2026-07-30
  wikimedia: "https://foundation.wikimedia.org/wiki/Policy:Privacy_policy", // verified 2026-08-28
  youtube: "https://www.youtube.com/howyoutubeworks/privacy/",
  mediaCCC: "https://media.ccc.de/about.html#privacy", // verified 2026-10-21

  // Group G — Travel
  flightradar24: "https://www.flightradar24.com/terms-and-conditions",

  // Group H — Events

  // Group I — Health

  // Group I2 — Fitness

  // Group J — Shopping

  // Group J2 — Connected services
  googleCalendar: "https://policies.google.com/privacy",

  // Group J3 — Public company data
  secEdgar: "https://www.sec.gov/about/privacy-information",

  // Group J4 — Weather
  openMeteo: "https://open-meteo.com/en/terms",
  brightSky: "https://brightsky.dev/docs/",

  // Group K — Nutrition
  edamam: "https://www.edamam.com/privacy/", // verified 2026-06-13

  // Group L — Electronics

  // Group M — Mail
  protonmail: "https://proton.me/legal/privacy", // verified 2026-07-15

  // Group N — Home and housing

  // Group N2 — Jobs; provider notices verified 2026-10-13
  jobtech: "https://arbetsformedlingen.se/om-webbplatsen/juridisk-information/sa-behandlar-vi-dina-personuppgifter",

  // Group O — Community
  discord: "https://discord.com/privacy",

  // Group P — Social media
  bluesky: "https://bsky.social/about/support/privacy-policy",
  mastodon: "https://joinmastodon.org/privacy-policy",
} as const;
