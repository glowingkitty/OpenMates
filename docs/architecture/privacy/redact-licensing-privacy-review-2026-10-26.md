# Redact licensing and privacy review

Reviewed 2026-10-26 for TASK-6119, session 678f. Production activation is disabled.
The user requested reassessment of direct client licensing traffic, then preferred
retaining the enabled development trial with a settings switch back to regex.
Production still awaits sufficient SDK privacy terms and a lawful-basis assessment.

## Decision

Do not approve the current integration for production. Local text inference and
third-party telemetry are separate properties. The observed browser calls did
not contain our typed synthetic markers, but the integration automatically
creates direct third-party connections. We cannot describe it as sending no
personal data off the device.

Preserve the working browser engine and regex fallback while resolving the
commercial/privacy terms. Do not disable SDK reporting, replace identifiers with
a shared value, or assume that a proxy/custom Rust runtime removes the model's
licensing obligations. A telemetry-free arrangement or altered reporting scheme
needs written permission. No provider has been contacted.

## Observed browser data flow

Pinned SDK: `@desert-ant-labs/redact` and core 4.1.0, source
`86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb`; model `redact@v0.4.0`.

| Destination | Request and information | Current evidence |
| --- | --- | --- |
| `events.desertant.com/api/v1/license` | POST with `installId`, `model`, `modelVersion`, `sdk.name`, `sdk.version`, `platform`, `app.id`; an optional vendor key is not configured | Pinned source plus actual isolated browser request audit |
| `events.desertant.com/api/v1/activate` | POST returning the signed licence token supplied by the vendor | Pinned source plus actual isolated browser request audit |
| Hugging Face model repository/download hosts | Public model catalog/files and their ordinary request metadata | Actual model download requests |
| OpenMates origin | Self-hosted runtime/WASM assets | Deployed response hashes and browser request audit |

For the browser, `platform` is `web`, `app.id` is the worker's hostname, and the
SDK identifies itself as `desert-ant-core` version `4.1.0`. These are direct
browser requests, without an OpenMates relay. The receiving service necessarily
sees the connection IP address and timing, plus transmitted browser headers
such as Origin and User-Agent. Whether these network fields are retained, and
for how long, is not established by the available policy.
The browser can also send CORS preflight OPTIONS requests. Their connection
metadata is exposed even if a later licence POST fails. An IP may be a VPN or
privacy-relay exit address; the application cannot assume that protection.

The current worker has no localStorage/custom SDK identity store. Its default
identity/token state is in memory and can reset with worker recreation. Do not
promise one request per browser per month: reloads, new tabs, resets and retries
can cause further requests. The implications for device counting also need
clarification before production; adding a persistent identifier is not a routine
performance fix.

No inspected grant/activation request field accepts message text, transcripts,
detected values or placeholder maps. The audit searched actual outgoing URL,
body and header values for typed synthetic markers and found none. Fresh text
was also classified after networking was disabled. This is bounded evidence for
the pinned trial, not an independent rebuild of the browser binary or proof
against arbitrary encoded covert channels or future SDK changes.

Sources: [wire fields](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Usage/Wire.swift),
[licensing implementation](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Usage/Licensing.swift),
[storage](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/86b9b55fe8c61ec1c27c5b6383f545c6df1d6ceb/Sources/Usage/Storage.swift),
and [browser evidence](redact-browser-dev-trial.md).

## Licence terms

The [source-available licence v1.0](https://license.desertant.com/1.0), especially
sections 3, 6, 7 and 9, permits free use below 100,000 monthly active devices per
model/platform, then requires a commercial licence. Attribution must be
discoverable and linked where links are supported. Reporting must remain intact.
The vendor says the telemetry excludes content and identifies itself as its
controller rather than OpenMates' processor. It places relevant disclosure duties
on the integrating application. Competitor-training and standalone-redistribution
restrictions also apply. Paying does not by itself establish a telemetry waiver.

## Privacy-policy gap

The [published privacy page](https://desertant.com/privacy/), dated 2026-10-05,
describes the website, demos, contact forms and hiring. It does not identify SDK
licensing identifiers/endpoints or state their retention, legal basis, hosting
locations, recipients or specific rights-handling process. Its hiring retention
periods do not answer SDK retention. Its demo-download explanation acknowledges
IP visibility. Website service-provider disclosures cannot be assumed to cover
the SDK licensing service. This is a documentation gap, not evidence that the
vendor sells data or uploads message content.

The European Commission lists IP addresses among examples of personal data and
explains that re-identifiable pseudonymised information remains personal data.
A random identifier therefore does not establish anonymity. The appropriate
basis, transparency and device-storage assessment require the actual processing
details; this review does not infer a consent exemption or lawful basis from
the vendor's general GDPR statement. [Commission guidance](https://commission.europa.eu/law/law-topic/data-protection/data-protection-explained_en).

## Information needed before production

- A specific SDK telemetry notice: fields, IP/header handling, retention,
  processors/recipients, locations/transfers, security and deletion/access process.
- The legal basis and allocation of responsibilities for the direct disclosure.
- Written terms for telemetry-free/self-hosted use or a permitted relay/reporting
  arrangement, if available; do not assume the ordinary commercial tier includes it.
- Confirmation that worker-scoped identity storage satisfies device-counting terms.
- A licence compatibility review for the application's distribution and notices.

Self-hosting public model files would remove their Hugging Face download
connection, but would not remove SDK licensing traffic. A relay would expose the
relay's IP instead of the browser's to that endpoint, but would still transmit
licensing metadata and would need an approved design and terms. Running the
same SDK from Rust still performs licensing; on a server it exposes the server
connection, and in an installed CLI it exposes that user's connection.

## Native benchmark clarification

The earlier Node benchmark called `Redact.load` and `flushTelemetry` before its
network seal. Source inspection now shows that the JS wrapper can defer actual
session creation when model files already exist. That historical flush is not
proof of a successful licensing HTTP exchange. Its content-offline measurements
remain retained unchanged.

The new Rust harness explicitly calls the native `dal_download` to initialize
the session, flushes normal SDK licensing, and records successful real ES256
licence verification before disconnecting idle sockets and sealing networking.
Only then does it read the synthetic inputs. It does not remove telemetry or
alter licensing fields. Performance is measured separately from that startup.
