# Automated security monitoring

Contract: `specifications/architecture/security-monitoring` (approved).
Plan: `docs/plans/security-monitoring/plan.yml`.

The system watches for security advisories, exploitation signals and vendor
incidents that affect what OpenMates actually runs, judges real impact with a
read-only AI triage, applies guarded fixes to dev only, and tells the operator
what is left to do.

```mermaid
flowchart TD
    subgraph Servers["Hetzner servers: prod (core), upload, preview"]
        R["Host reporter (systemd, no login account)<br/>daily + boot + after apt"]
    end
    R -- "signed + encrypted report<br/>Hetzner private network only" --> C

    subgraph Dev["Dev server (private network address from local config)"]
        C["Collector<br/>verifies signer, rejects replays/extra fields"]
        I["Inventory (daily + after deploy)<br/>lockfiles, images, OS, kernels, vendors,<br/>skill providers, dev tools, CI actions<br/>+ not-used list with reasons"]
        S["Hourly source checks (no AI)<br/>OSV/MAL, GHSA, Dependabot, Ubuntu/Debian/Alpine,<br/>CISA KEV, EPSS, vendor bulletins, news"]
        M{"Match + score + dedupe"}
        X["Suppressed<br/>not used / recorded not-affected"]
        G["Daily digest only"]
        D{"Already triaged for these facts?<br/>triage chat already running?"}
        T["Triage chat (Claude, read-only)<br/>applicability, reachability,<br/>exploitability, blast radius"]
        V{"Verdict"}
        F["Fix chat (separate, structured input only)<br/>allowlisted fix, release-age rules,<br/>isolated CI, deploy to dev"]
        H["Intrusion signals (no AI)<br/>unknown key login, new key, sshd config,<br/>new account/sudoers, modified files"]
        N["Notifier (fixed templates)"]
    end

    C --> I
    C --> H
    I --> M
    S --> M
    M -- "not used / known verdict" --> X
    M -- "weak match, not critical" --> G
    M -- "relevant" --> D
    D -- "yes: carry forward, no new chat" --> G
    D -- "new or material change" --> T
    T --> V
    V -- "not affected (remembered)" --> G
    V -- "low" --> G
    V -- "fix soon" --> N
    V -- "urgent" --> F
    F --> N
    H --> N
    N --> DC["Discord #security"]
    N --> EM["Email"]
    N --> TK["OpenMates Task (fix soon)"]
    DC & EM --> OP(("Operator: prod release,<br/>server patch/reboot,<br/>secret rotation"))
```

## Rules in short

- **No false alarms for things we don't run.** The not-used list carries a
  reason for each entry, and anything installed on a host is never "not used".
- **One chat per change.** An advisory is triaged once per material change
  (new version or environment, severity up, first known exploitation, public
  exploit, advisory changed or withdrawn). Unread or unhandled notifications
  never start another chat. Only one triage chat runs at a time.
- **Read-only triage, separate fix.** Advisory and web text is untrusted. The
  fix chat only sees validated verdict fields and cannot touch agent config, CI
  workflows, deployment templates, secrets or this system's code.
- **Release age.** Routine updates wait 7 days. Security fixes use the oldest
  fixing version. At 72h or older it applies immediately. Younger versions apply
  only for reachable, exposed or exploited issues after integrity checks pass.
  Otherwise the fix chat mitigates first.
- **Dev only.** Production deploys, server patching, reboots and secret rotation
  stay manual and appear as a checklist in each notification.
- **Never silent.** Source failures, triage failures, failed or reverted fixes,
  stale host reports and a stopped watcher alert immediately. The daily digest
  proves liveness.
