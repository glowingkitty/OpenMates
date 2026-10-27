---
status: automated-adjudication
created: 2026-10-21
scope: retained 2026-10-20 corrected-30-second public-feed findings only
---

# Daily Inspiration v6 rubric alignment

This is a re-review of yesterday’s **19 material-flagged cards plus four uncertain cards**, using their retained exact source/card pairs. It is automated and is **not human or native-speaker approval**. The 19 original material cards contain 20 material findings because the Thai volcano-model card has two. No new inference calls, application/runtime edits, deployment or full-feed rescore were performed for this document. No provider-key access was needed; no provider attribution or comparative quality conclusion is made here.

The aligned rubric allows faithful translations/paraphrases, proper names, context-resolvable ellipsis and open questions about actual source concepts even when the answer is absent. It rejects an extra factual claim, scenario or question premise unsupported by the actual supplied source, even if true from background knowledge. Entity/subtype scope, qualifiers, temporal status and causal roles must remain intact. Cosmetic grammar and recoverable terminology are separate.

The previous broad permission for “basic explanatory inferences” is not used to manufacture support. **Off-source is not synonymous with factually false.** A known chemical reaction, a software capability or a historical event can be true and still unsupported by this frozen snippet. Conversely, a strange translated word is not automatically a material invented phenomenon when the full card resolves it.

## Outcome

Among these 23 selected cards: **18 reject for material source/language failures; four allow with minor wording advisories; one remains unresolved**. These are scoped review labels, not fresh model decisions or a benchmark-wide error rate. The retained rejects contain 19 distinct material findings; the two volcano-model findings count once at card level. One former material card (Swedish solar-eclipse terminology) is downgraded to minor. Three former uncertain cards receive minor advisory labels; the Vietnamese causal-agent ambiguity remains unresolved.

Evidence root: `/home/superdev/projects/.openmates-runtime/product-stack/test-results/d115-multilingual-30s-final-20261020/blind-review`. The original snapshot date, not today’s date, governs temporal comparisons.

## Per-card adjudication
### card-2bd6e6548764 (nl)

Exact source/card snapshot: `final-group-3.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `phrase`.

Card: “Hoe ontwerp je een tandwiel in 3D?”

Source contrast: “This video focuses on making simple gears.”

Making gears and the named software are explicit; a 3D design scenario is not. Inferring software capabilities from outside familiarity would be precisely the broad explanatory permission excluded by v6.

Evidence files: `adjudication-final-3.json`.

### card-488912680f00 (fr)

Exact source/card snapshot: `final-group-1.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `assistant_response`.

Card: “ces impressionnantes structures naturelles visibles depuis l'espace”

Source contrast: “La plus grande de ces formations, la Grande Barrière de corail ... est visible depuis l'espace.”

The plural attaches space-visibility to the structures generally; the source supplies it only for the named largest formation. The immediately preceding phrase mentions the largest but the response separately broadens the subject. This is an unsupported scope extension, not proof that other reefs are invisible.

Evidence files: `adjudication-final-1.json`.

### card-49c44dda776f (cs)

Exact source/card snapshot: `final-group-4.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `phrase`.

Card: “pyl ze samčích buněk”

Source contrast: “samčí rostlinné buňky (pyl) přenášejí na samičí orgány květu (blizna)”

Source identifies the transferred cells as pollen. The phrase makes those cells the origin from which pollen is transferred. The response is better, but does not turn the phrase’s explicit origin relation into a faithful paraphrase.

Evidence files: `adjudication-final-4.json`.

### card-4d557a74cab1 (tr)

Exact source/card snapshot: `final-group-3.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `phrase; assistant_response`.

Card: “Bu resifler sert kolonileri nasıl oluşturuyor?”

Source contrast: “bu kolonilerin bir araya gelmesiyle de mercan kayalığı meydana geliyor”

Source says organisms build hard colonies and colonies combine into a reef. The phrase/response make reefs form the hard colonies. Open-question permission does not permit reversing this construction order.

Evidence files: `adjudication-final-3.json`.

### card-685a499fe03e (pl)

Exact source/card snapshot: `final-group-3.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `assistant_response`.

Card: “Jak pyłek dociera do woreczka zalążkowego?”

Source contrast: “łagiewka pyłkowa przenosząca komórki plemnikowe do woreczka zalążkowego”

The source specifies a pollen tube transporting sperm cells to the embryo sac. The question assigns that destination to pollen itself. This changes the transported entity, rather than merely leaving the mechanism unanswered.

Evidence files: `adjudication-final-3.json`.

### card-6bc707660ed2 (de)

Exact source/card snapshot: `final-group-1.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `follow_up_suggestions[1]`.

Card: “Warum bilden Zahnräder die größte Gruppe der Getriebe?”

Source contrast: “Zahnradgetriebe bilden unter den Getrieben die größte Gruppe.”

Replaces a transmission subtype (Zahnradgetriebe) with individual components (Zahnräder) as the category member. This is not the context-resolvable shortening Getriebe for Zahnradgetriebe; it changes the entity/category.

Evidence files: `adjudication-final-1.json`.

### card-7e3a34a64363 (id)

Exact source/card snapshot: `final-group-3.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `assistant_response`.

Card: “dibentuk oleh koral pembangun karang dan alga zooxanthellae”

Source contrast: “Koral sendiri adalah hewan karang yang bersimbiosis dengan sejenis tumbuhan alga yang disebut zooxanthellae.”

Source establishes reef-building corals and a symbiotic algae relationship, not algae as co-builders. Adding a construction role exceeds that relationship. Reject as unsupported causal role, not a claim that algae make no ecological contribution.

Evidence files: `adjudication-final-3.json`.

### card-84ad3dd2abc6 (th)

Exact source/card snapshot: `final-group-4.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `phrase`.

Card: “Fear of Success - by Dr. Leon Tec. What is this psychological paradox?”

Source contrast: “Requested language: th; source topic is Fear of Success - by Dr. Leon Tec.”

The entire generated phrase is English, including its explanatory question. Retaining Dr. Leon Tec is allowed; retaining the full English reader-facing sentence is substantial language failure.

Evidence files: `adjudication-final-4.json`.

### card-a46a2c71be72 (nl)

Exact source/card snapshot: `final-group-3.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `phrase; assistant_response`.

Card: “Pollination is the movement of pollen from the anther to the stigma.”

Source contrast: “Requested candidate language: nl; source explains pollination in English.”

A full explanatory sentence is English in both generated fields and several follow-ups retain English vocabulary. This is substantial untranslated prose, beyond preserving the source’s proper title.

Evidence files: `adjudication-final-3.json`.

### card-a489d9928f1c (es)

Exact source/card snapshot: `final-group-1.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `follow_up_suggestions[1]`.

Card: “¿Por qué prefieren aguas con pocos nutrientes?”

Source contrast: “generalmente viven en aguas marinas que contienen pocos nutrientes”

A question may explore an explicit habitat, but prefieren adds a preference premise beyond generally living there. The source’s separate grow-best conditions do not establish nutrient preference. Reject the unsupported premise, without asserting a biological falsehood.

Evidence files: `adjudication-final-1.json`.

### card-be1183b9b61c (zh)

Exact source/card snapshot: `final-group-1-extra.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `assistant_response`.

Card: “這個序列歷經了一千多年才結束”

Source contrast: “終於2459年5月3日 ... 歷經1280.14年”

The response says the sequence already ended after over a thousand years, while the source end date is 2459-05-03, future relative to the frozen 2026-10-20 run. Preserve temporal status; a retrospective completed ending is not supported.

Evidence files: `adjudication-final-1-extra.json`.

### card-bf6017073c52 (th)

Exact source/card snapshot: `final-group-4.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `phrase`.

Card: “หลายคนกลัวความล้มเหลว”

Source contrast: “Fear of Success - by Dr. Leon Tec - An Introduction to a Psychological Paradox”

Adds fear of failure and a many-people prevalence statement, neither present in the sparse source. It is off-source even if plausible or true. The remaining fear-of-success copy is not thereby declared false.

Evidence files: `adjudication-final-4.json`.

### card-c368bca8fa09 (ar)

Exact source/card snapshot: `final-group-4.json`.

Previous: **uncertain**. Aligned label: **allow_minor**. Field: `assistant_response`.

Card: “يحاكون حياكة شعاب مرجانية”

Source contrast: “Source title says Tausende Menschen häkeln riesiges Korallenriff: thousands actually crochet the reef, rather than imitate crocheting.”

يحاكون literally suggests imitation, but the phrase explicitly describes actual participation in crocheting, and title/follow-ups refer to that same art project. A one-word typo or awkward construction is a plausible contextual resolution. Record minor action-word ambiguity rather than assert a material simulation scenario. Native Arabic wording review remains useful, but is not claimed.

Evidence files: `adjudication-final-4.json`.

### card-c7d6efa69f2d (th)

Exact source/card snapshot: `final-group-4.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `phrase; assistant_response`.

Card: “แค่ขวดพลาสติกกับเบกกิ้งโซดาก็ทำให้มันปะทุได้ / เกิดจากปฏิกิริยาระหว่างเบกกิ้งโซดากับน้ำส้มสายชู”

Source contrast: “Materials Needed ... 6. Plastic bottle ... 10. Baking soda ... 12. Vinegar ... 13. Eno”

Two separate material findings on one card: (1) just bottle plus baking soda is an unsupported sufficiency premise, inconsistent with the response’s additional vinegar; (2) the response specifies a reaction mechanism where the source only lists materials. Familiar chemistry is not supplied evidence. The second is not a finding that the reaction claim is scientifically false.

Evidence files: `adjudication-final-4.json`, `adjudication-final-4.json`.

### card-d1189852804e (vi)

Exact source/card snapshot: `final-group-3.json`.

Previous: **uncertain**. Aligned label: **unresolved**. Field: `assistant_response`.

Card: “Lúc này bóng của Mặt Trăng phủ lên Trái Đất và che khuất hoàn toàn hoặc một phần đĩa Mặt Trời.”

Source contrast: “Mặt Trời bị Mặt Trăng che khuất và bóng của Mặt Trăng phủ lên Trái Đất.”

The coordinated sentence makes bóng của Mặt Trăng (the Moon’s shadow) cover Earth and grammatically obscure the solar disk. The phrase and preceding response instead correctly name the Moon body as the occluder. A recoverable ellipsis versus changed causal agent cannot be distinguished confidently in this automated review. Keep unresolved and exclude from both material-reject and clean-allow totals; no human/native adjudication has occurred.

Evidence files: `adjudication-final-3.json`.

### card-d399e32936fc (ar)

Exact source/card snapshot: `final-group-4.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `phrase`.

Card: “أكثر الطرق فعالية لمنع الأمراض”

Source contrast: “أكثر الطرق فعالية لمنع الأمراض المعدية”

Drops infectious from the superlative prevention claim. The response retains the restriction, but the standalone phrase states the broader superlative. Under explicit qualifier preservation this remains an off-source generalization, without asserting vaccines cannot prevent other conditions.

Evidence files: `adjudication-final-4.json`.

### card-d60db9fceb69 (vi)

Exact source/card snapshot: `final-group-3.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `phrase`.

Card: “giữa các loài thực vật”

Source contrast: “to the stigma of a flower on different plant”

Explicit loài (species) introduces interspecies scope where the source identifies different individual plants. A question about pollination is allowed; this extra species-level scenario is not supplied. Not a finding that interspecies pollination is impossible.

Evidence files: `adjudication-final-3.json`.

### card-e4ee2203f046 (it)

Exact source/card snapshot: `final-group-2.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `phrase`.

Card: “I vulcani possono distruggere città intere.”

Source contrast: “volcanoes can do some major damage”

Entire cities is an additional destruction extent not supplied by major damage or a named historical example. Familiar background history is outside source evidence. Reject as off-source extent, not a claim that volcanoes cannot destroy cities.

Evidence files: `adjudication-final-2.json`.

### card-ec3144f2a351 (sv)

Exact source/card snapshot: `final-group-4.json`.

Previous: **uncertain**. Aligned label: **allow_minor**. Field: `phrase`.

Card: “från antern till märket”

Source contrast: “Source: pollen from the anther to the stigma.”

Antern is a lexical/anglicized rendering of the source anther. The card preserves the pollen-to-stigma relation and uses ståndare in the response. This is terminology quality, not substantial foreign-language replacement or a distinct transported entity. Native Swedish terminology review remains useful, but is not claimed.

Evidence files: `adjudication-final-4.json`.

### card-eeef1d0d6f7d (th)

Exact source/card snapshot: `final-group-4.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `assistant_response`.

Card: “ซากสิ่งมีชีวิตที่ตายไปจะทับถมพอกพูนกลายเป็นหินปูนแสนแข็งแกร่ง”

Source contrast: “เมื่อตายไปแล้วจะยังคงเหลือซากหินปูนทับถมพอกพูน”

The source describes already-limestone remains accumulating after organisms die. The response describes dead remains accumulating and becoming limestone. This changes the material-transformation sequence; it is more than a shorter description of accumulation.

Evidence files: `adjudication-final-4.json`.

### card-f431a11cb6b3 (sv)

Exact source/card snapshot: `final-group-4.json`.

Previous: **material**. Aligned label: **allow_minor**. Field: `phrase`.

Card: “en total solföljd”

Source contrast: “Source asks: Have you ever seen a total solar eclipse? It discusses solar and lunar eclipses, not a solar sequence.”

The central word solföljd is malformed/mistranslated, but the title and repeated sol- och måneklipser plus Earth/Moon/Sun context make the intended eclipse subject recoverable. Under the explicit context-resolvable wording rule, record a lexical defect rather than claim that the full card teaches a different solar-sequence phenomenon. This is a downgrade from yesterday’s material terminology label, not native approval.

Evidence files: `adjudication-final-4.json`.

### card-f639b90d64a2 (th)

Exact source/card snapshot: `final-group-4.json`.

Previous: **uncertain**. Aligned label: **allow_minor**. Field: `assistant_response; follow_up_suggestions[1]`.

Card: “ซึ่งเกี่ยวข้องกับพืชชนิดต่างๆ”

Source contrast: “Source defines self-pollination by the same plant and cross-pollination by separate plants; insect- and wind-pollinated flowers have different adaptations. It does not introduce a species comparison.”

พืชชนิดต่างๆ can denote different plant kinds/types in loose language, not necessarily an assertion of interspecies pollination. The phrase explicitly says พืชแต่ละต้น (individual plants), and the source names insect-/wind-pollinated flowers with different adaptations. The follow-up about plant types stays on explicit concepts. Treat this as recoverable scope ambiguity; do not equate it with the explicit Vietnamese species word loài.

Evidence files: `adjudication-final-4.json`.

### card-fe2a22dcaa0a (cs)

Exact source/card snapshot: `final-group-4.json`.

Previous: **material**. Aligned label: **reject_material**. Field: `phrase`.

Card: “Mnozí lidé se obávají neúspěchu.”

Source contrast: “Fear of Success - by Dr. Leon Tec - An Introduction to a Psychological Paradox”

Adds fear of failure and its prevalence, absent from the actual source. The issue is source support, not whether many people actually fear failure.

Evidence files: `adjudication-final-4.json`.

## Disputed boundaries and limits

- **Swedish `solföljd`:** yesterday treated a core mistranslated term as material. The full eclipse context resolves the referent; the aligned policy instead treats it as a lexical advisory. This is a deliberate documented rubric change, not a new native-language judgment.
- **Thai plant “types” versus Vietnamese “species”:** the Thai wording can refer to types already in the pollination source; the Vietnamese explicit `loài` creates a species-level scenario. Do not mechanically give both the same entity-scope label.
- **Vietnamese shadow versus Moon:** the local coordinated subject suggests the shadow as the solar occluder; the immediately preceding context correctly identifies the Moon. The boundary between recoverable ellipsis and causal-agent replacement remains unresolved. Exclude it from clean approvals and material counts pending qualified language review.
- **Arabic `يحاكون` and Swedish `antern`:** context resolves the intended activity/relation. These remain language-quality advisories, not substantial wrong-language failures. The actual Dutch and Thai full-English sentences remain material language failures.
- **Infectious-disease qualifier and space-visible reefs:** full-card context matters but does not authorize broadening a standalone superlative or a plural property. These are unsupported scope changes under the explicit qualifier/entity rule. They are potentially rubric-sensitive cases and should remain separately inspectable.
- **Preference and mechanism premises:** asking “why” is allowed for an actual source-mentioned relationship. It is not permission to replace residence with preference, imply 3D from a product name, or derive a chemical mechanism from a shopping list. Such rejects state an evidence mismatch, not scientific impossibility.

## Synthetic v6 controls

`backend/scripts/fixtures/daily_inspiration_editorial_v6.json` contains **120 cases / 60 matched pairs / 20 feed locales**, with three allow/reject pairs per locale. Families are bounded-trial scope versus universal generalization, target-language explanation versus two full foreign-language sentences, and explicit water-wheel follow-up versus an absent Mars/battery-charging premise.

There are **three source mini-passages and three semantic contrast templates translated into 20 locales**, not 120 independent educational concepts. Source passages are original synthetic text. Each pair differs in exactly one generated field; expected labels remain outside candidate text. English-source mini-passages are retained across locales. The telescope name Mira is deliberately allowed as a proper name; positive Japanese prose has no artificial spaces.

Labels and translations are automated, not native-speaker gold. These easy boundary controls do not independently cover every causal-role, temporal, subtype or subtle-premise ambiguity. Repeated translations are correlated observations; do not turn 120 cases into a claim of 120 independent topics or human-validated multilingual qualification. No live editorial decisions were run in this subtask.
