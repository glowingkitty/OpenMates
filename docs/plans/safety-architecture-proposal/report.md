# OpenMates safety processing: research and proposal

Status: proposal for the owner's review. Research only: nothing here is built,
and production is unchanged. Version 2, 2026-11-15. It adds: judging answers
(§6), the strike policy (§7), the cybersecurity line (§8) and uploaded videos
(§9).

## In short

- **Hard-block only the narrow illegal set,** everywhere. That is:
  - sexual content involving minors;
  - non-consensual intimate images;
  - sexual deepfakes of real people;
  - clear help toward weapons of mass harm.

  Only a clear *request* for these can count as a strike.
- **Everything else is judged by purpose in the chat context.**
  - Weapons, wounds, war and medical images are allowed as such.
  - We decline propaganda, promotion of violence or military action, sensational or tabloid-style material and misleading content. The decline gives a short reason and a safe alternative, and no strike.
- **Jev can be the single deciding model** for text, answers, generated images, slides and uploads.
  - In our benchmark it was as accurate or better, about 3× faster and 3–20× cheaper.
  - The condition: purpose categories, explicit content and multi-turn context are not benchmarked yet. We benchmark them before switching.
- **Answers are checked too.** The check runs in the postprocessing call that already exists, so it adds no user-visible latency. Risky chats also get rolling checks while the answer streams. A hit replaces the answer with a localized notice and never gives the user a strike.
- **Strikes become rare and humane:** warning first, decay after 90 days, an appeal, and never automatic account deletion.
- **Urgent:** production still deletes accounts automatically after repeated upload rejections. Suggestive-only photos stopped counting on 2026-11-15 (hotfix). The automatic deletion itself should go next (§7.1).
- **Cybersecurity:** allow by default, including learning, CTFs, pentesting your own or authorized systems, malware analysis and defensive work. Decline only the operational part when a real third-party target meets deployable attack tooling. Never strike for asking (§8).
- **Uploaded videos:** video upload isn't supported yet, so the privacy policy's promise to moderate every uploaded video should be corrected now. When video upload ships, it gets only security checks plus a Tier 0 check at upload: local hash matching plus Jev on keyframes, about $0.01 per minute. There are no nudity, gore or weapon thresholds. Share links get a report button and 1-hour takedown (§9).
- **New wellbeing layer.** Risk signals are computed per turn. Above thresholds the assistant gently steers back and shows local helplines. It never blocks and never gives a strike, and no signal is stored server-side.

## 1. What we have today: the gaps that matter

| Area | Today | Problem |
|---|---|---|
| Uploads | Image screening rejects at weapon > 0.5, gore > 0.3 and suggestive > 0.6, and each rejection is a strike. | Overblocks news and medical images, the opposite of the direction we want. Gore and weapon scores never fired before a parser fix on dev (2026-11-15), so enforcing them now would be a new policy. |
| Uploads | Screening does not fail closed when the provider is unavailable. | Must fail closed for the illegal tier (details in the Task). |
| Uploads | Video upload is not supported at all. | The privacy policy promises moderation for every uploaded image and video. The wording is wrong (§9). |
| Strikes | One shared 24 h counter for generation, edits, video and uploads ends in automatic account deletion. Production deletes on the 4th upload rejection within 24 h. | Ordinary users can lose their account over borderline photos (§7.1). |
| Chat text | The preprocessing model gives a harm score. Jev (then a fallback model) confirms a block only with exact quotes. No strikes. | Works, but each message is judged alone, with no conversation-level view. |
| Answers | Postprocessing scores the finished answer as `harmful_response` 0–10. | The score has one effect: it hides the follow-up suggestion. No block, log or notice (§6). |
| Provider filters | When an AI provider's own filter stops an answer, the user sees an English notice. | Localized fix is in progress (parked). |
| Self-harm / suicide | No detection and no helpline offer. Self-harm is excluded from the harm score. A crisis-support focus mode exists, but the user has to pick it. | The biggest gap compared with the leading providers. |
| Audit log | `safety_audit_log` holds a prompt hash, scores, reasoning and category. It is written on image and video blocks only. | "1 year" exists only in a code comment, and no deletion job exists. The privacy policy mentions neither the log nor strikes. |

## 2. What leading platforms and research do

- **Context over keywords.**
  - YouTube allows or age-restricts graphic content that has educational, documentary, scientific or artistic context visible in the content itself.
  - The Meta Oversight Board kept graphic footage documenting abuses up behind a warning screen (Sudan case, 2022).

  The pattern: allow with context, use a warning or age gate in between, and remove only a narrow set.
- **Refusals cost more than they look.**
  - On OR-Bench (80k harmless prompts that sound harmful), safer models mostly also refuse more harmless prompts (rank correlation ≈ 0.88).
  - Multi-turn benchmarks show the same.
  - OpenAI moved from hard refusals to "safe completions", which judge the harm of the answer rather than guessing intent.
- **Policy-as-prompt classifiers are standard.** OpenAI's open-weight safeguard model (with ROOST, Oct 2025) and Llama Guard take a written policy plus the content. The recommended layering is a fast check first, with deeper reasoning only for unclear cases. Jev already fits this pattern.
- **Output classifiers can run while the answer streams.** Anthropic's Constitutional Classifiers (2025) score the output as it is generated and stop the stream when it crosses the line. This is the model for §6.
- **Wellbeing is per conversation, not per message.**
  - OpenAI (Oct 2025): about 0.15% of weekly users show explicit signs of suicidal planning, and safeguards weaken in long chats.
  - Anthropic (Dec 2025): a small classifier across the conversation triggers a crisis-resource banner through ThroughLine. It does not block.
  - RAND (2025): both failing to respond and over-cautious refusals do harm.
- **Privacy-preserving moderation.** Apple dropped on-device photo scanning in 2022, citing attack risks, misuse and false positives. Our server already decrypts content while it handles a request. The privacy-friendly option is to screen in that moment, keep only the verdict and store nothing else.

## 3. Proposed architecture

**Three tiers, one decider (Jev), one place per stage.**

| Tier | What | Action | Strike? |
|---|---|---|---|
| 0: illegal | Sexual content involving minors; non-consensual intimate images; sexual deepfakes of real people; clear help toward weapons of mass harm | Block everywhere, input and output | Only for a clear request (§7) |
| 1: purpose | Propaganda; glorifying or promoting violence or military action; sensational or tabloid gore; clickbait or misleading fakes (e.g. a realistic fake news photo of a real person); photoreal minors; real public figures in generated images; operational attacks on third-party systems (§8) | Decline with a category reason and a safe alternative, in the user's language | No |
| 2: allowed | News, documentary, medical, educational, historical and artistic use of weapons, wounds or war; fiction; stylized minors; security learning and defensive work | Allow. Optionally, generated graphic images get a blurred preview with "show anyway" | No |

**Where and when it runs:**

| Stage | Check | Added latency | Cost per item |
|---|---|---|---|
| Upload (upload server) | **Tier 0 only:** Jev image labels plus a sexual/minor rule. ClamAV stays. If Jev is down, hold the file and retry; never let it through. | ~0.35 s | ≈ $0.0006 (today: $0.009–0.017) |
| Message sent (text plus attached images) | Jev with the **last few turns as context**: Tier 0, Tier 1 and the wellbeing signals in one call, in parallel with preprocessing. | ~0 s (hidden behind preprocessing) | ≈ $0.0002–0.0004 |
| Generation request (image, slide, video) | Jev prompt verdict with chat context | ~0.2 s before 5–15 s of generation | ≈ $0.00013 |
| Generated output | Jev image labels plus purpose. Tier 0 outputs are discarded before billing. | ~0.35 s per image | ≈ $0.0006 |
| Answer (§6) | Request plus answer together, in the existing postprocessing call; rolling checks only for risky chats | 0 s visible | ≈ $0 extra (same call); ≈ $0.001 per rolling-checked answer |
| AI provider's own filter | Localized category reply, no retry for child-safety blocks | 0 | 0 |

- The current image-safety provider stays only to detect AI-generated media, with one operation instead of six.
- The vision model and the safeguard model drop out of the main path once Jev passes the missing benchmarks.

**Jev as single decider: trade-offs.**
- For:
  - It led every category we measured, with 0 critical misses on the prompt sets.
  - It is the fastest and cheapest option we tested.
  - Its policy is editable text.
  - It is already used for chat-request safety, PDFs and prompt injection.
- Against:
  - Single-vendor risk.
  - Not yet measured on explicit adult content, Tier 1 purpose categories or conversation context.
- Recommendation: Jev decides.
  - On a Jev error, Tier 0 falls back to a second, independent model, and Tier 1 lets the request through.
  - First, run a benchmark covering Tier 1, explicit content, multi-turn context and the cyber set (§8). The owner sees the numbers before any switch.

## 4. False positives and appeals

- **Confidence bands:** a clear yes blocks, a clear no allows, and the band in between gets a second opinion. Over-refusal is tracked monthly on a harmless set (OR-Bench-style plus our own tricky-benign prompts, multi-turn and cyber included).
- **Every decline explains itself:** the category, why the rule exists and a safe alternative. It never reveals the exact trigger.
- **Appeals:**
  - A "this was wrong" button opens the appeal.
  - The user consents to share only the flagged request, decrypted.
  - A human decides within a set time. A wrong strike is removed, and a suspension is lifted.
  - An upheld false positive goes into the benchmark set.

## 5. Wellbeing layer

- **Signals,** scored 0–1 by the same Jev call on every message:
  - suicidal thoughts;
  - interest in methods or means;
  - plan, intent or timeline;
  - self-harm;
  - hopelessness or isolation;
  - eating-disorder risk;
  - danger from others (abuse).
- **Over time:** an exponential moving average over the turns. One dark joke changes nothing, but a gradual drift does. This also counters the "long-chat decay" OpenAI reported.
- **Levels:**
  1. **Elevated:** the model gets a safe-messaging instruction. It stays warm and engaged, does not lecture, gives no method details and opens the topic gently.
  2. **High:** a calm card with local helplines (ThroughLine API, by country and language) and an offer to switch to the crisis-support focus.
  3. **Imminent (plan plus timeline):** the helpline card is prominent, and the assistant encourages contacting someone now.

  The chat is never blocked or refused, and no strike is given.
- **Storage:**
  - The state lives in the chat's client-encrypted metadata and is read only during the request.
  - Nothing is stored per user, logged or shown to admins.
  - Only an anonymous daily count is kept ("support card shown N times").
- **Legal:**
  - These signals are health data (GDPR Art. 9), so a DPIA and a stated legal basis are needed.
  - DSA Art. 18 (all hosting providers) is about suspected crimes threatening life, which points at threats to others. Counsel should confirm the boundary.

## 6. Judging the answer, not only the request

### 6.1 What `harmful_response` does today

- **Where:** postprocessing (`backend/apps/ai/processing/postprocessor.py`, `_postprocessing_decisions_with_jev`).
- **How:**
  - It asks Jev one score question over `{user_message, assistant_response}`: "Rate whether the assistant response itself contains unsafe or materially harmful assistance".
  - The answer is on a 10-step scale from "Safe" to "Extreme harm", scaled to 0–10.
  - If Jev is unavailable, an LLM tool field is used instead.
- **When:** after the whole answer has streamed and is visible. It is sent in `post_processing_completed`.
- **Effect:** the web client skips the follow-up ghost suggestion when the score is not 0. Nothing else reads it: no block, notice, log, metric or strike.

So we pay for the signal, but it does not protect anyone.

### 6.2 Proposal: one joint check of request and answer

The question Jev answers changes from "is this answer harmful?" to the tier policy, with context. The input is the last few turns, the user's message and the answer. There are three questions:

1. **Tier 0 assistance:** does the answer give material help toward Tier 0, or meaningful uplift toward mass-harm weapons?
2. **Wellbeing safety:** given the chat's wellbeing level, does the answer contain method or means details, or does it ignore a risk the user expressed?
3. **Purpose drift:** did the answer produce Tier 1 material, such as propaganda, a deployable attack on a third party (§8) or a misleading fake?

The request side keeps its own check at send time (§3). Judging both together catches the two cases a request-only check misses:
- a harmless-looking request that the model answered badly;
- a multi-turn build-up where each request alone is fine.

### 6.3 Streaming: when the answer is already on screen

| Option | How | Visible latency | Extra cost | Harm already shown |
|---|---|---|---|---|
| A. After the answer (today's timing) | Check once, before the final save | 0 | ≈ 0 (folded into the existing postprocessing call) | The whole answer was visible for a few seconds |
| B. Rolling checks while streaming | Check the text so far at ~400 characters, then at about every 1,500 characters or each paragraph, in parallel with the stream | 0 (the stream is never held) | 3–6 checks per long answer, ≈ $0.001 | Up to ~0.5 s of text before the stop |
| C. Hold-back buffer | Show text one window behind the check | +0.3–0.5 s per window | as B | none |

**Recommendation: A for every answer, plus B only for risky chats.** A chat is risky when one of these holds:
- the send-time check landed in the uncertain band;
- the wellbeing level is elevated or higher;
- the topic is a sensitive one (cyber operational, weapons, extremism).

This is the layered "fast first, deeper when unclear" pattern. C is rejected, because it slows every answer to protect against a rare case.

### 6.4 What happens when it fires

| Finding | Action | Strike? | Record |
|---|---|---|---|
| Tier 0 assistance | Stop the stream. Replace the answer with a localized notice ("This answer was stopped because it went into …; here is what I can help with instead"). The answer is never saved. | No (the model wrote it). A strike is possible only if the *request* was itself a clear Tier 0 request (§7). | Audit entry: hash, category, model; no text |
| Wellbeing: method details to a user at risk | Replace the answer with a supportive reply plus the helpline card | Never | Anonymous count only |
| Purpose drift (Tier 1) | No retraction. A short note is added to the next turn's instructions so the assistant steers back. | No | Anonymous count per model |
| Score low | Nothing | — | — |

- **Client side:**
  - A new `answer_withdrawn` event (category, notice key) replaces the visible bubble before the client encrypts and saves the final message.
  - The logic lives in the shared Rust client core, so web, Apple and CLI behave the same.
  - The provider-filter notice path reuses the same event.
- **Metrics:** the rate of withdrawn answers per model and category, with no content. A model with a high rate is a routing problem, not the user's.

## 7. Strike policy

### 7.1 Today

- **Dev (with the open safety hotfix PR):**
  - A technical error never counts, and there is one strike per violation, with severity weights.
  - 4 weighted points within 24 h trigger logout and account deletion.
  - Upload rejections count separately: the 4th within 24 h deletes the account immediately.
- **Production:**
  - The same upload rule is live.
  - The suggestive > 0.6 rejection counts toward it, so four swimwear or beach photos in a day can delete an account.
  - Image generation is off on production until the hotfix is merged, but uploads are on.
- **Deletion:** account deletion is final, without review or appeal.

**Done on 2026-11-15 (owner-approved production hotfix):** suggestive-only upload rejections no longer count as strikes and never delete an account. Explicit sexual rejections still count. The same change is on the open hotfix PR and on dev.

**Still recommended (needs the owner's go for production):**
- Replace the remaining automatic deletion with suspension plus an admin alert.
- Stop counting the other non-Tier-0 upload rejections.
- Stop rejecting suggestive uploads at all (decision 8).

### 7.2 Proposed policy

- **What gives a strike:** only a clear request for Tier 0 content, judged at high confidence on the user's own input (prompt or upload).
- **What never gives a strike:**
  - borderline or uncertain-band scores;
  - purpose declines (Tier 1);
  - outputs the model produced;
  - technical errors;
  - provider-filter blocks;
  - adult nudity uploads;
  - wellbeing signals;
  - cyber questions (§8).
- **Ladder:**
  1. **1st strike:** a warning in the user's language, with the reason, the policy link and the appeal button. Only the request is blocked.
  2. **2nd strike within 90 days:** a 7-day suspension of generation and uploads, plus an admin alert.
  3. **3rd strike within 12 months:** the account is suspended pending human review.
     - Deletion only after that review, never automatically.
     - Invoices, the compliance log and audit logs are kept as legally required.
- **Exception:** a high-confidence child-safety hit on an upload suspends the account at once and alerts an admin. It does not delete it. Whether to report, and to whom, is the owner's decision (DSA/CSAM legal review).
- **Decay:** each strike expires after 90 days without a new one. The counter holds only the category, time, severity and appeal state, with no content.
- **Credits:** blocked requests are refunded.
- **Appeal:** as in §4. A successful appeal removes the strike and lifts the suspension.

## 8. Cybersecurity: where the line is

### 8.1 What others do

- **Anthropic's Usage Policy:**
  - It prohibits compromising systems *without authorization*: exploiting vulnerabilities without the owner's permission, unauthorized access, persistent remote-access tools, automated mass compromise, malware and ransomware, DoS and botnets.
  - It explicitly allows research and testing on systems you own or operate, with the owner's authorization, or within a bug bounty or disclosure program.
  - The line is authorization plus scale, not "dangerous topic".
- **Identity-gated tiers for defenders:** Anthropic's Cyber Verification Program and OpenAI's Trusted Access for Cyber give verified defenders fewer classifier refusals, which is an admission that default classifiers over-block malware analysis and exploit validation. Real-time blocks stay for mass-disruption actions such as deploying ransomware. A small platform cannot run identity tiers, so the default policy itself must be generous.
- **Threat reports** (Anthropic Nov 2025; Google GTIG Jan and Nov 2025; Microsoft with OpenAI, Feb 2024):
  - Attackers mostly use AI as a productivity aid.
  - The evasion pattern is a pretext ("I'm doing a CTF", "I'm a student", "we're a pentest firm") plus splitting the attack into innocent-looking steps.
  - So persona claims are weak signals either way. The artefact and the target matter.
- **Law and norms:**
  - EU Directive 2013/40/EU: offences require acting "without right", meaning without the owner's or the law's authorization. Tools are an offence only with intent that they be used for offences.
  - German §202c StGB: the Federal Constitutional Court (2009) clarified that dual-use tools are not covered merely because they are suitable for offences. Intent is what counts.
  - US DOJ (2022): it does not charge good-faith security research.
  - Pentest practice requires written permission and an agreed scope.
  - Coordinated disclosure norms: CERT/CC's default is 45 days; ISO/IEC 29147.
- **Over-refusal is measured:** CyberSecEval 2 introduced a false-refusal rate on borderline-benign cyber prompts, and over-refusal there is a real, measured cost.
- **OWASP LLM Top 10 (2025):** prompt injection (LLM01) and excessive agency (LLM06) matter most to us. They concern our own tools, such as code execution and remote machines, more than user requests.

### 8.2 Proposed policy (principle: when in doubt, allow a bit too much)

- **Allowed by default:**
  - learning and explaining attacks, vulnerabilities and CVEs;
  - CTF practice and write-ups;
  - pentest methodology and reports;
  - hardening and configuration;
  - detection rules;
  - log and malware analysis;
  - reverse engineering;
  - exploit concepts and proofs of concept against your own systems, a lab or clearly synthetic targets;
  - security tooling on your own systems.

  Naming a tool (nmap, Metasploit, Burp) is never a signal.
- **Decline only the operational part, and only when several of these signals combine:**
  - a named real third-party target with no ownership or authorization;
  - a ready-to-deploy artefact (e.g. a complete ransomware encryptor with spreading, a phishing kit for a named brand);
  - mass or automated targeting;
  - stealth, persistence or anti-detection aimed at real victims;
  - harvesting real people's credentials;
  - extortion intent;
  - multi-turn steps that add up to the above.
- **How to respond:**
  - Help partially: the concept, detection and mitigation, a lab setup, or a sanitized proof of concept against a local test target.
  - When the target is a real third party and the scope is unclear, ask one question about authorization. Accept a plausible answer, and never demand documents.
  - Decline briefly, without lecturing.
- **Never a strike:** cyber requests are Tier 1 at most. Account-level action is only for repeated, clear targeting of third parties with deployable malware, through human review.
- **Benchmark:** add a cyber set to the Jev benchmark, with benign-but-scary prompts (CTF, malware analysis, own-server pentest) and clearly operational third-party attacks. We measure false refusals first.

## 9. Uploaded videos

### 9.1 What exists today

- **Video upload is not supported anywhere:**
  - The upload service accepts only images, PDFs and audio (`ALLOWED_MIMES` in `backend/upload/routes/upload_route.py`) and rejects `video/*`.
  - The web file picker leaves out video, camera video capture is disabled, and no other client uploads video.
  - So no uploaded video goes unchecked, because there is none. The privacy policy still says "every image and video you upload is scanned" (`shared/docs/privacy_policy.yml`, `legal/privacy.yml`), which describes a feature that does not exist.
- **Encryption model for files:**
  - The upload server sees the plaintext once, encrypts it with a per-file key and wraps that key with Vault.
  - So a check *at upload time* fits our model: screen, keep only the verdict, forget.
  - After upload, shared content is protected by a key in the share-link fragment, so our servers cannot read it later. Upload time is the only point where we can check.
- **Video in the product today:**
  - The assistant analyses YouTube videos through their URLs.
  - Slides can embed `embed:` refs or YouTube/Vimeo links.
  - Public plaintext video exists only in the internally reviewed examples bucket.
- **Generated videos:**
  - Composed videos have their first, middle and last frames checked.
  - Short generative clips get only the prompt check. Their output checks should match the composed path (details in the Task).

### 9.2 Misuse and attack scenarios (once video upload exists)

| # | Scenario | Likelihood | Harm | Does checking help? |
|---|---|---|---|---|
| 1 | **CSAM:** upload, then distribution through share links | Low–medium. File hosts with share links are a documented distribution pattern (IWF: image hosts and cyberlockers carry a large share; Ofcom treats file storage and sharing as high risk). | Extreme | **Yes, at upload only.** Hash matching finds known material with almost no false positives. A classifier on keyframes finds some new material. Later we are blind (fragment key). |
| 2 | **Non-consensual intimate video / sexual deepfakes** of real people, shared by link | Low | Severe | **Partly.** StopNCII hashes catch reported victims' material. No classifier can see consent, so reports and fast takedown matter most. |
| 3 | **Free hosting / CDN abuse** (piracy, malware, mass distribution) | Low: links need our app, files are ≤ 100 MB and storage beyond 1 GiB is billed. | Moderate (legal notices, cost) | **No.** Content checks don't help. Size, rate and share-view limits plus notice-and-action do. |
| 4 | **Extremist propaganda** spread through public share links | Low | High. The EU TCO Regulation applies to content disseminated to the public, with 1-hour removal orders. | **Little.** Purpose classifiers are weak, and GIFCT hashes need membership. What matters is a process that disables a link and its files within 1 hour of an order or report. |
| 5 | **Private analysis of disturbing but legal footage** (news, war, bodycam, own security camera, medical, sports injuries) | **High: a main use case** | None | **Checking hurts.** Any nudity, gore or weapon threshold would block these. They must pass. |
| 6 | **Adult pornography** in private storage | Medium | None if adult and consensual | No block or strike. Purpose rules apply only to generation and to answers. |
| 7 | **Prompt injection inside a video** (on-screen text or spoken instructions aimed at the assistant) | Medium, once analysis exists | Moderate (tool misuse) | **Yes, in-request:** treat transcripts and on-screen text as untrusted input, with the same Jev injection check used for PDFs. |
| 8 | **Malformed files** attacking decoders (crafted containers targeting ffmpeg) | Low–medium | High (server compromise) | **Yes, but this is security, not moderation:** ClamAV, strict container validation, and a sandboxed transcode with time and memory limits. |
| 9 | **Resource abuse** (huge or long videos to burn analysis credits or storage) | Medium | Moderate (cost) | Duration and size limits, rate limits, credits. |
| 10 | **Harassment or doxxing video** of a private person, shared | Low | Moderate–high | Reports, plus takedown of the share link. |

### 9.3 Options compared

| Option | Finds | Cost per minute of video | Latency | Privacy | Over-blocking risk |
|---|---|---|---|---|---|
| Image-safety provider's video API (frame sampling, 0.5–2 fps) | Nudity, gore, weapons by class score | ≈ $0.06/min *per model* at 1 frame per 2 s ($0.002/op). The exact ops-per-video rule is unpublished, so this is an estimate. Several models: ≈ $0.18–0.36/min. | Sync only < 60 s; async beyond | Decrypted video goes to an EU processor | **High:** class thresholds hit news, war, medical and art (published art false-positive rates of 7–48% for NSFW classifiers) |
| Cloud video APIs (AWS Rekognition, Google Video Intelligence) | Explicit content and violence | $0.10/min (Google: first 1,000 min/month free) | Async, minutes | Video copied to the cloud vendor; check EU regions | High (same class approach) |
| Hive | Many classes | ≈ $0.80/min via a reseller; direct price is quote-only | Async | Third-party processor | High |
| **Hash matching** (PDQ / TMK+PDQF locally, matched against lists we qualify for) | **Known** CSAM / NCII / terror material only | ≈ $0 compute | Milliseconds per keyframe | Best: only hashes are compared, and the content never leaves | **≈ none** |
| – list access | PhotoDNA Cloud (free for qualified orgs; images, so used on keyframes); Google CSAI Match (video, free for approved partners); StopNCII (open invitation to upload platforms); IWF (≥ £5k/yr, needs > 12 months trading and > 2 staff); Thorn Safer (≈ $30k+/yr) | — | Application lead time of weeks | — | — |
| Check only shared or public videos | Whatever the check is, only where distribution happens | Lowest | At share time | Private use untouched | Low. But the client must send the file key at share time, which a modified client can skip. Upload-time checking is more robust. |
| **Jev on sampled keyframes** (1 per 5 s plus scene changes, max ~60 frames) | Tier 0 only (sexual/minor rule), including **new** material | ≈ $0.007–0.01/min ($0.0006/frame) | ~0.35 s per frame, in parallel; a few seconds per minute of video | Same as image uploads today | **Low**, if used for Tier 0 only |

### 9.4 Recommendation

- **Now (video upload doesn't exist):**
  - **Correct the privacy-policy wording.** It should say that uploaded images are checked, that we don't accept video uploads yet, and that generated videos are checked. This is a factual correction, not a policy change. Changing only the wording is right *for now*.
  - Bring the output check of generated short clips in line with composed videos.
  - **Apply for hash-list access** (PhotoDNA, Google CSAI Match, StopNCII). It is free and slow, so start early. IWF later, once eligible.
- **When video upload ships, launch with this minimum and nothing heavier:**
  1. **Security:** container validation, ClamAV, a sandboxed transcode, size and duration limits (e.g. 100 MB / 10 min), rate limits.
  2. **Tier 0 at upload:** local keyframe hashing against the lists we have, plus Jev Tier 0 on sampled keyframes. Fail closed (hold and retry). No strike except the high-confidence child-safety exception (§7.2).
  3. **No nudity, gore or weapon thresholds.** Legal private footage is never blocked.
  4. **Purpose** (propaganda, misleading material) is judged only when the video is used in a chat, at message time (§3), never at upload.
  5. **Share links:** a report button on shared pages; disabling a link and its files within 1 hour (TCO); an admin alert when a file share reaches unusual view counts. That last one is a distribution signal that needs no content.
- **Cost:** about $0.01 per minute of video, against $0.06–0.36 (image-safety provider) or $0.10 (cloud APIs), with lower over-blocking and better privacy.
- **Why not wording alone, long term:** file storage with share links is the documented pattern for CSAM distribution. Upload time is our only chance to see the content, and the minimal Tier 0 check is cheap and does not overblock.

## 10. What is stored, where, how long

| Data | Where | Content | Retention |
|---|---|---|---|
| Allow decisions | nowhere | — | — |
| Tier 1 declines | inside the encrypted chat (the reply itself); aggregate counter | no extra record | as the chat |
| Withdrawn answers (§6) | audit log (Tier 0 only); counters | hash, category, model | 1 year (Tier 0); counters aggregate |
| Tier 0 blocks | `safety_audit_log` | prompt hash, category, scores, model, short reasoning; no prompt text, no image | **1 year, enforced by a new deletion job** |
| Strikes / suspension | Redis plus the user record | category, time, severity, appeal state | 90 days after the last strike |
| Rejected uploads and outputs | nowhere (discarded) | — | — |
| Appeal | appeal record | only the flagged request, decrypted with consent, plus the decision | until decided + 6 months |
| Wellbeing signals | client-encrypted chat metadata | 7 numbers per chat | as the chat |
| Operational logs | OpenObserve | category, decision, latency; no text | 14 days |
| Account deletions | compliance log | reason, type | 2 years (legal) |

The privacy policy needs to cover strikes, the audit log, appeals and the wellbeing layer, and it must state accurately what happens with uploaded videos (§9).

## 11. Decisions for the owner

**Decided so far (2026-11-17):**
- **Decision 1: yes, adapted.** A strike that today deletes the account suspends it instead. A suspended account cannot be used until an admin review, which ends in deletion or restoring the account. Nothing is deleted automatically. Approved for the alert, review page and appeal flow:
  - **Admin alert:** Discord plus email, linking to a "Safety reviews" page. It shows the category, the check, its scores and threshold, the purpose verdict, account age, plan, and earlier strikes and appeals. The request text appears only with the user's consent in an appeal. It never shows an image.
  - **Review actions:** Restore (one click: lifts the suspension, clears the strike, sends an apology email), Delete (with a confirmation: standard deletion with a full refund, deletion email and compliance record) and Ask the user. A reminder goes out after 48 hours.
  - **Suspended user:** sees, in their language, the category-level reason and two buttons, Appeal and Download my data. There are no charges while suspended.
  - **Appeal form:** an explanation of up to 1,000 characters, plus consent to share only the flagged requests, which the user's own device decrypts. The photo may be attached again for upload categories that don't involve minors; the admin opens it with a click (no blur, per decision 3), and it is deleted at the decision.
  - **Deadlines:** 14 days to appeal; a decision within 7 days of an appeal. **An unclear case with no appeal after 14 days is restored.**
  - **Retention:** the strike and suspension record is kept 90 days after the case closes; the appeal record until 6 months after the decision; after a deletion, the compliance record (2 years) and the invoices.
- **Decision 2: changed.** Requests with a harmful purpose (propaganda, hate content, disinformation and misleading content, manipulative tabloid content) are declined and count as a strike right away, like the four illegal categories. They are judged by the content, not by who asks.
- **Decision 3: no blur feature for now, anywhere.** Graphic but legitimate images (wounds, medical, war reporting) are shown normally; images with a harmful purpose are still declined. Re-evaluating blur for shared or public views is a low-priority Task due 8 Dec 2026.
- **Decision 4: waiting** for the re-run benchmark of Gemini against Jev.
- **Decision 5: approved as recommended.** Every finished answer is checked together with its request (Jev). Live checks during the answer run only in risky chats. An answer is withdrawn only for illegal content or a wellbeing risk, and a withdrawn answer never gives the user a strike.
- **Decision 6: approved.** 1st strike: a warning. 2nd strike: a 7-day suspension. 3rd strike: suspension until an admin review (decision 1). Strikes expire after 90 days, and an account is never deleted automatically. Strikes apply to the four illegal categories and to the harmful-purpose categories (decision 2).
- **Decision 7: approved, with this setup.**
  - **Allowed by default:** knowledge and code (explaining attacks, reviewing the user's own code, test or load scripts the user runs themselves, CTFs, learning).
  - **When OpenMates itself acts on a live site** (web browse, skills): only normal single-user actions at human speed. No mass or abusive actions against any live domain for now (mass comments, mass sign-ups, password guessing, flooding, large-scale scraping), whatever ownership the user claims.
  - **How it declines:** politely, assuming good faith. It says the user probably does own the site, but for safety reasons such tests currently run only against localhost or a local dev environment (or a staging copy run locally), and offers to help set that up.
  - **Strikes:** none for a plausible ownership claim; a strike only for clear signs, such as repeated attempts against several sites that obviously aren't the user's.
  - **Domain ownership verification** (DNS TXT record or a file on the domain), which would later unlock unrestricted testing of verified domains, is not built now. It is a separate Task due in about two weeks.
- **Decision 8 (uploaded images): approved in this form.** The check runs at upload, independent of the chat (chats, Projects and profile images alike).
  1. **Sightengine stays the primary upload check** (already paid; to verify: does the included volume cover expected uploads). Thresholds follow the agreed lines: refuse the four illegal categories with a strike; refuse explicit sexual content and extreme gore without context, without a strike. Allowed: news and war images (e.g. a tank in a destroyed city), weapons, medical images, and ordinary nudity in art or medicine.
  2. **Jev only for borderline scores** near a threshold, as a second opinion.
  3. **Jev as the fallback** when Sightengine is down. Strict: if Jev isn't clearly sure the image is harmless, the upload is refused.
  4. **If both fail,** the upload is refused, never with a strike.
  5. **No Gemini at upload.** Harmful purpose is judged later, when the image is used in a chat.
- **Decision 9 (uploaded videos):** handled together with the video upload work (Sightengine plus a Jev fallback).
- **Decision 10 (wellbeing support): approved; build now.** Jev scores a few risk questions in the same preprocessing call (no extra call). The scores are kept in the client-encrypted chat metadata; the client sends the recent scores with each message, and the server computes a rolling level without keeping them. Past level 1 the answer gets a short, gentle check-in instruction; past level 2, or at once for acute risk, local helplines are shown as a card and support comes before the task. Never lecture, block or strike. The answer check of decision 5 runs in postprocessing. The server keeps only an anonymous daily count, and nothing goes into memories automatically. Measured on a labelled synthetic multi-turn test set with many hard negatives, thresholds tuned on a held-out split; the added cost per 1,000 messages is reported and kept negligible.
- **Decision 11 (legal review):** not now. Duties for a small business are researched from official sources first; reporting to authorities is not built until that research is done.
- **Decision 12 (order of work):** set by the implementer, with the deletion-to-suspension change (decision 1) first.
- **Decision 4** still waits for the re-run benchmark of Gemini against Jev.

1. **Urgent, production: stop automatic account deletion.** Suggestive-only strikes were switched off on 2026-11-15. What remains: replace the automatic deletion with suspension plus an admin alert, and stop counting the other non-Tier-0 upload rejections (§7.1). *Recommendation: yes, as a small hotfix before everything else.*
2. **Tier 0 list.** Exactly: sexual content involving minors, non-consensual intimate images, sexual deepfakes of real people, and clear help toward mass-harm weapons? *Recommendation: yes.*
3. **Tier 1 list and generated graphic images.** Plain decline, or a blurred preview with "show anyway"? *Recommendation: decline only for the purpose categories; blurred preview for graphic but legitimate outputs.*
4. **Jev as single decider** after a new benchmark (Tier 1, explicit content, multi-turn, cyber), with a second model only as a Tier 0 fallback? *Recommendation: yes.*
5. **Answer checks (§6):** a joint check on every answer, rolling checks only for risky chats, and retraction only for Tier 0 and wellbeing. *Recommendation: yes.*
6. **Strike policy (§7.2):** strikes only for clear Tier 0 requests; ladder of warning, then a 7-day suspension, then human review; 90-day decay; never automatic deletion. *Recommendation: yes; it replaces next week's strike rework scope.*
7. **Cyber line (§8.2):** allow by default; decline only the operational third-party part; never a strike. *Recommendation: yes.*
8. **Uploads: Tier 0 only, fail closed.** Purpose is judged when the message is sent. *Recommendation: yes.*
9. **Uploaded videos (§9.4):**
   - Now: correct the privacy-policy wording, align the output check of generated short clips, and apply for free hash-list access.
   - When video upload ships: security checks plus Tier 0 only at upload (local hashing plus Jev on keyframes, fail closed); no class thresholds; share-link reports and 1-hour takedown.

   *Recommendation: yes; no video-moderation API.*
10. **Wellbeing layer:** signals, thresholds, ThroughLine API, no server-side storage. *Recommendation: yes.*
11. **Legal review by counsel:**
    - DSA scope (Art. 16 notices, Art. 18 duty);
    - GDPR Art. 9 basis and a DPIA for wellbeing signals;
    - AI Act Art. 50 labelling (from 2 Aug / 2 Dec 2026);
    - CSAM and terrorist-content reporting.
12. **Order of work.** *Recommendation:*
    - (a) the production hotfix from decision 1;
    - (b) quick fixes: upload fail-closed for Tier 0, the audit-log deletion job, privacy-policy accuracy, finishing the localized provider-filter notices;
    - (c) the benchmark;
    - (d) purpose check with context, plus the joint answer check;
    - (e) the strike ladder and appeals;
    - (f) the wellbeing layer;
    - (g) video: the policy wording now, inside (b); the hash-list applications now; the upload checks together with the video-upload feature.

## Limits of this report

- Platform and provider claims come from company publications and were not independently checked. Some cyber details are from secondary press, and OpenAI's policy pages could not be read this session.
- Video API prices come from vendor pages and search snippets. The image-safety provider's ops-per-video rule, Hive's and Azure's video prices, and eligibility details for hash lists (CSAI Match, StopNCII, GIFCT) were not confirmed. The TCO scope for share links needs legal review.
- Latency and cost figures come from our benchmark of 2026-11-15. Conversation context will change them.
- This is not legal advice.

## Sources

- Platforms and research: support.google.com/youtube/answer/2802008 · oversightboard.com (2022-002-FB-MR) · arxiv.org/abs/2405.20947 (OR-Bench) · arxiv.org/abs/2510.08158 · openai.com/index/gpt-5-safe-completions · openai.com/index/strengthening-chatgpt-responses-in-sensitive-conversations · anthropic.com/research/constitutional-classifiers
- Wellbeing: anthropic.com/news/protecting-well-being-of-users · rand.org/pubs/external_publications/EP71040.html · developer.throughlinecare.com
- Legal: bka.de (DSA Art. 18 FAQ) · data.consilium.europa.eu ST-10499-2026
- Video: sightengine.com/pricing · sightengine.com/docs/moderate-stored-video · aws.amazon.com/rekognition/pricing · cloud.google.com/video-intelligence/pricing · microsoft.com/en-us/photodna · protectingchildren.google/tools-for-partners · iwf.org.uk/membership · github.com/facebook/ThreatExchange (PDQ, TMK+PDQF) · stopncii.org · gifct.org · ofcom.org.uk (file-sharing and file-storage guidance) · iwf.org.uk/annual-data-insights-report-2025 · arxiv.org/abs/2409.17156 (NSFW classifiers on art) · eur-lex.europa.eu (Regulation 2021/784, TCO)
- Cyber: anthropic.com/legal/aup · anthropic.com/news/disrupting-AI-espionage · anthropic.com/news/cyber-verification-program · cloud.google.com/blog/topics/threat-intelligence/threat-actor-usage-of-ai-tools · cloud.google.com/blog/topics/threat-intelligence/adversarial-misuse-generative-ai · microsoft.com/en-us/security/blog/2024/02/14/staying-ahead-of-threat-actors-in-the-age-of-ai · arxiv.org/abs/2404.13161 (CyberSecEval 2) · bundesverfassungsgericht.de (2 BvR 2233/07) · certcc.github.io/certcc_disclosure_policy · eur-lex.europa.eu (Directive 2013/40/EU)
