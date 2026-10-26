# Unsent Desert Ant licensing/privacy inquiry

To: licensing@desertant.com

Subject: Redact local inference: SDK telemetry privacy terms and fully offline licensing

We are evaluating Redact for OpenMates, a privacy-focused application. Our current
development-only browser experiment uses SDK 4.1.0 and model v0.4.0. Text inference
runs locally, but the browser directly calls your licence and activation endpoints.

Before considering production, we need clarification on these points:

1. Where is the privacy notice specifically covering SDK licensing telemetry?
   Please identify the collected fields, handling of IP addresses/Origin/User-Agent,
   retention and deletion periods, hosting locations, subprocessors/recipients,
   international transfers, legal basis and end-user rights process. The public
   website policy appears to cover demos, contact forms and hiring.
2. Your licence identifies Desert Ant as controller of the telemetry. What
   arrangement and disclosures do you expect from an integrating application?
   Can a user exercise access/deletion rights if its worker-scoped identifier
   has already been lost?
3. Is a written commercial licence available for entirely offline use, with
   no end-user licensing requests or persistent third-party identifiers?
   Does any paid tier include this, or would it require separate terms?
4. If that is unavailable, would you permit a first-party relay or aggregate
   usage reporting that avoids disclosing users' IP addresses directly to you?
   Please specify an approved protocol and accounting terms; we will not silently
   alter the existing reporting or substitute a shared identifier.
5. The SDK's default metadata store in a Web Worker is in memory. Is that the
   intended supported identity lifetime, and how does it affect monthly-active
   device accounting across tabs, reloads and worker resets?
6. If we run the published model with our own Rust inference integration, which
   reporting and redistribution obligations apply? We need explicit terms
   allowing fully local inference and first-party model hosting rather than
   assuming a different runtime removes the model licence's requirements.
7. Please provide the applicable commercial pricing/device-count definitions
   and distribution terms for our open-source application before any production
   adoption decision.

We have not enabled the model in production and are preserving the SDK's current
licensing behavior during engineering evaluation. We are seeking written terms
and a clear privacy assessment, rather than a telemetry bypass.
