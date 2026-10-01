# Hosting Search domains — proposed embed layouts

Accepted layout direction, 2026-10-01, with the user's availability and
requirements changes incorporated. This defines a parent search embed and independent
domain child embeds. Prices below come from the dated Gandi sample, including
19% German VAT; they are not guaranteed checkout prices.

The reference is the implemented Shopping search/result family:
`ShoppingSearchEmbedPreview`, `ShoppingSearchEmbedFullscreen`,
`ShoppingResultEmbedPreview`, `ShoppingResultEmbedFullscreen`, and
`SearchResultsTemplate`. Reuse `UnifiedEmbedPreview` and its BasicInfosBar,
and `UnifiedEmbedFullscreen` with the shared gradient header/CTA. Existing
Hosting tokens supply the server icon and red/orange gradient. No image,
favicon, or screenshot is needed for an unregistered domain.

## Parent: chat preview

Keep it a search summary, matching existing search cards. The card opens the
results fullscreen. It does not contain a new carousel or nested action buttons.

```text
+-------------------------------------+
| cedarcomet                          | <- submitted query
| via Gandi                           |
|                                     |
| 4 available · 1 unavailable          | <- only checked counts
| From EUR 9.51 for the first year     | <- comparable 1-year offers
+-------------------------------------+
| [Hosting icon]  Search domains       | <- shared BasicInfosBar
|                 5 results           |
+-------------------------------------+
```

Omit "From" when offers are not comparable or no price is known. For mixed
minimum terms use the count/status summary rather than an unexplained minimum.
Processing, cancelled, error, empty, and partial use the canonical embed states.
Mobile retains the same hierarchy in the shared narrow stacked card.

## Parent: results fullscreen

Use the existing responsive child-card grid and its click-to-detail navigation.
The header shows the query and quote context. Optional local view controls
filter/sort the fetched results; they do not issue background provider requests.

```text
+------------------------------------------------------------------+
| [Close]                    HOSTING                    [Chat]      |
|                       Search domains                             |
|                         cedarcomet                               |
|                   via Gandi · EUR · Germany                       |
+------------------------------------------------------------------+
| 5 checked · 4 available · checked 13:09                            |
| [Show in-use: on*]          [Sort: provider order v]              |
|                                                                  |
| +----------------------------+ +----------------------------+    |
| | Available                  | | Available                  |    |
| | EUR 14.27 first year        | | EUR 9.51 first year         |    |
| | Renews EUR 47.60 / year     | | Renews EUR 38.06 / year     |    |
| | First-year offer           | | First-year offer           |    |
| +----------------------------+ +----------------------------+    |
| | cedarcomet.net · Gandi      | | cedarcomet.org · Gandi      |    |
| +----------------------------+ +----------------------------+    |
|                                                                  |
| +----------------------------+ +----------------------------+    |
| | Unavailable                | | Could not check            |    |
| | No registration price      | | Price unavailable          |    |
| +----------------------------+ +----------------------------+    |
| | cedarcomet.com · Gandi      | | another-domain.et · Gandi   |    |
| +----------------------------+ +----------------------------+    |
|                                                                  |
| Prices include 19% VAT for Germany. Availability may change.       |
+------------------------------------------------------------------+
```

The unchecked card illustrates a supported error state, not an assertion that
that specific domain was queried. Wide screens use two/three cards as space
allows; narrow fullscreen containers use one column, following the template.
The initial grid follows the selected backend results and stays within the
requested count. Show only available domains when those fill the count. If
matching in-use domains fill a shortfall, include those and turn on Show in-use
(`*` illustrates that fallback). An explicit available-only request keeps in-use
domains out of the selected view. The local filter uses encrypted checked children
and makes no provider request; an additional In-use view can isolate those children.
Unknown checks stay distinct diagnostics. Show a compact partial-results notice
when some checks failed, and preserve an exact in-use query under the default policy.
Do not show the provider's raw 911 suggestion count as 911 available domains.

## Child: individual domain preview

This is the same card used inside the fullscreen grid and when the assistant
references a particular domain in a chat message. The entire card opens details.

```text
+-------------------------------------+
| Available            [Premium]*     |
|                                     |
| EUR 14.27                           | <- registration headline
| for the first year                  |
| Renews EUR 47.60 / year              | <- always when supplied
| [First-year offer]                   |
+-------------------------------------+
| [Hosting icon]  cedarcomet.net        |
|                 via Gandi            |
+-------------------------------------+
```

`*` Premium is conditional and absent for the `.net` example. Other conditional
labels: "Minimum 2 years", "Registration restrictions", and "Price unavailable".
For an unknown/error answer use "Could not check", never "Unavailable".
Keep the domain as the primary BasicInfosBar title, with IDN Unicode text and
the ASCII form available in details. Long names wrap/clamp without losing the
suffix; full text is available in selectable fullscreen content.

## Child: domain fullscreen

Keep the standard gradient header and external provider CTA, with sibling
navigation and return to results. One readable information column suits a
domain without a product image; there is no empty media column.

```text
+------------------------------------------------------------------+
| [Back to results]       HOSTING        [< Previous] [Next >] [X]   |
|                       cedarcomet.net                             |
|                      Available · via Gandi                        |
|                       [Open on Gandi ->]                         |
+------------------------------------------------------------------+
| Registration                                                     |
|   EUR 14.27 for 1 year                                            |
|   First-year offer · normal registration EUR 20.54 / year         |
|                                                                  |
| Renewal                                                          |
|   EUR 47.60 / year                                               |
|                                                                  |
| Quote details                                                    |
|   Currency / tax country       EUR / Germany                     |
|   Tax                          Includes 19% VAT                  |
|   Minimum registration term    1 year                            |
|   Premium domain               No                                |
|   Checked                      1 Oct 2026, 13:09                 |
|                                                                  |
| Registration requirements                                        |
|   [Only requirements explicitly returned by Gandi]               |
|                                                                  |
| [Optional: other term prices v]                                  |
| Availability and prices may change before checkout.               |
+------------------------------------------------------------------+
```

Use "Open on Gandi", not an in-app purchase action: the skill only searches.
Normal registration is shown only for a supplied discounted registration tier;
it must never be presented as the renewal rate. Unknown taxes get a neutral
label, not "tax-free". Two-year minimums are explicit. Hide absent requirement
sections; a missing restriction field does not prove no registration rules.
Use copyable domain text in fullscreen and existing top-bar copy facilities
where available. On mobile the header/CTA and detail sections stack in one
scrollable column; sibling controls use the existing template.

## Fields proposed for review

Always show domain, availability, provider, and known registration price with
currency/term. Show renewal beside registration whenever available, including
in the preview. Add premium, offer, or minimum-term badges only when relevant.
Fullscreen adds tax context, checked time, supplied restrictions and tier details.
Keep proxy mode, request IDs, raw JSON, pagination URLs, and retry counts out of
the product UI. Successful fallback does not change the visual layout.

The initial view follows the selected backend results and requested result limit.
Available domains appear first; matching in-use domains fill only a shortfall,
unless available-only was explicit. Local availability controls can reveal the
already checked in-use children without another provider request. Preserve the
selected order and show prices including known taxes. Price sorting is optional
and must separate incomparable terms and unknown prices.

Open design decisions: whether to include the local filter/sort controls in the
first release, whether the first-year offer badge is useful in compact cards,
and whether other term tiers should be expandable or shown as a short table.
