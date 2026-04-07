---
status: active
last_verified: 2026-04-07
---

# Server Hardening Guide

A step-by-step guide to harden a fresh Linux server (Ubuntu/Debian) before exposing it to the public internet for an OpenMates self-hosted deployment. Six layers of defense covering SSH brute-force, stolen credentials, missing security patches, and accidental service exposure.

Tested on Ubuntu 24.04 LTS with OpenSSH 9.6. Commands assume you are logged in as a non-root user with `sudo` privileges (e.g. `superdev`). Replace `superdev` with your own administrative username throughout.

## Critical Safety Rules

Before you start — read these or risk locking yourself out:

1. **Keep your current SSH session open the entire time.** Never log out of your existing connection until a new login in a separate terminal succeeds.
2. **Test every change in a second SSH session** before considering it done.
3. **Bookmark your VPS provider's web/rescue console.** This is your only fallback if SSH breaks.
4. **Save your TOTP scratch codes** (Layer C) in a password manager, separate from the device running the authenticator app.
5. **One change at a time.** Don't batch multiple risky changes — verify each layer before moving on.

## Layer A — Non-Root User with Sudo

### Why

Logging in as root removes the safety net of an explicit privilege boundary. A dedicated administrative user requires `sudo` for privileged operations, leaves an audit trail, and lets you disable root SSH access entirely.

### Already configured?

Run this — if all three lines pass, **skip this layer**:

```bash
id "$USER" | grep -q sudo && echo "✓ user in sudo group" || echo "✗ NOT in sudo"
sudo -n true 2>/dev/null && echo "✓ sudo works (cached)" || echo "? run 'sudo -v' to test password"
sudo sshd -T | grep -qi '^permitrootlogin no' && echo "✓ root SSH disabled" || echo "✗ root SSH NOT disabled"
```

### Steps

Create the user (skip if already exists):

```bash
sudo adduser superdev
sudo usermod -aG sudo superdev
```

Set a strong password (it will be required by `sudo` and as a factor in Layer C). Store it in a password manager.

Disable root SSH login by editing `/etc/ssh/sshd_config`:

```bash
sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sshd -t && sudo systemctl reload ssh
```

### Verify

```bash
id superdev | grep -o sudo                       # → sudo
sudo -v                                          # → succeeds with password
sudo sshd -T | grep -i permitrootlogin           # → permitrootlogin no
```

## Layer B — SSH Key-Only Authentication

### Why

Passwords over SSH can be brute-forced. Public-key authentication replaces the password challenge with a cryptographic proof — the private key never leaves your workstation, and brute-forcing a 256-bit Ed25519 key is computationally infeasible.

### Already configured?

Run on the server — if both pass, **skip this layer**:

```bash
sudo sshd -T | grep -qi '^passwordauthentication no' && echo "✓ password auth disabled" || echo "✗ password auth still enabled"
[ -s ~/.ssh/authorized_keys ] && echo "✓ authorized_keys has entries" || echo "✗ no authorized_keys"
```

### Steps

On your **local workstation** (not the server), generate a key pair if you don't have one:

```bash
ssh-keygen -t ed25519 -C "your-email@example.com" -f ~/.ssh/openmates_server
```

Set a passphrase when prompted. Copy the public key to the server:

```bash
ssh-copy-id -i ~/.ssh/openmates_server.pub superdev@<your-server>
```

Test that key-based login works (in a new terminal, leave the old session open):

```bash
ssh -i ~/.ssh/openmates_server superdev@<your-server>
```

Once confirmed, disable password authentication on the server:

```bash
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sshd -t && sudo systemctl reload ssh
```

### Verify

```bash
sudo sshd -T | grep -i passwordauthentication   # → passwordauthentication no
ssh -v superdev@<your-server>                   # shows "Server accepts key", no password prompt
```

## Layer C — Three-Factor SSH Authentication (Key + Password + TOTP)

### Why

Even key-based SSH has one point of failure — the private key file. If your laptop is stolen or your key file leaked, an attacker has full access. Adding two more independent factors (something you know + something you have) eliminates this single point of failure.

After this layer, an attacker would need: your private SSH key file **+** your Unix password **+** real-time access to your authenticator device, all simultaneously.

### Already configured?

Run on the server — if **all four** pass, **skip this layer**:

```bash
dpkg -l libpam-google-authenticator 2>/dev/null | grep -q ^ii && echo "✓ TOTP module installed" || echo "✗ TOTP module missing"
[ -f ~/.google_authenticator ] && [ "$(stat -c %a ~/.google_authenticator)" = "400" ] && echo "✓ TOTP enrolled (mode 400)" || echo "✗ TOTP not enrolled"
sudo grep -q '^auth required pam_google_authenticator.so' /etc/pam.d/sshd && ! sudo grep -q 'pam_google_authenticator.so nullok' /etc/pam.d/sshd && echo "✓ PAM enforces TOTP (no nullok)" || echo "✗ PAM not enforcing TOTP"
sudo sshd -T | grep -qi '^authenticationmethods publickey,keyboard-interactive' && echo "✓ sshd requires key + kbd-interactive" || echo "✗ sshd not requiring 3-factor"
```

### Step 1: Install the TOTP PAM module

```bash
sudo apt update && sudo apt install -y libpam-google-authenticator
```

The package name says "google" but it's just an RFC 6238 TOTP implementation — it works with any compatible authenticator app (1Password, Authy, Bitwarden, Google Authenticator, etc.).

### Step 2: Enroll TOTP for your user

Run this **as your administrative user**, not with sudo (the config must land in your home directory):

```bash
google-authenticator -t -d -f -r 3 -R 30 -W
```

Flag explanations:
- `-t` time-based tokens (TOTP)
- `-d` disallow reuse of the same token (prevents replay)
- `-f` write config to file without asking
- `-r 3 -R 30` rate-limit to 3 attempts per 30 seconds
- `-W` permit only matching time-window (tighter security)

What happens:
1. A large QR code prints in your terminal — scan it with your authenticator app.
2. A secret key, current verification code, and **5 emergency scratch codes** are printed.
3. **Save the 5 scratch codes in your password manager NOW.** These are your only recovery path if you lose your phone.

Verify the secret file landed correctly:

```bash
ls -la ~/.google_authenticator
# → -r-------- 1 superdev superdev 135 ... /home/superdev/.google_authenticator
```

The `-r--------` permissions (mode 400, owner read-only) are required.

### Step 3: Configure PAM to require TOTP

Back up the file and add the TOTP line above `@include common-auth`:

```bash
sudo cp /etc/pam.d/sshd /etc/pam.d/sshd.bak-$(date +%Y%m%d)
sudo sed -i '/^@include common-auth/i auth required pam_google_authenticator.so nullok' /etc/pam.d/sshd
```

Why `nullok`: temporarily allows users without an enrolled `~/.google_authenticator` file to still log in. This is a safety net during initial rollout — we'll remove it in Step 6 once we've verified our own login works.

Verify:

```bash
sudo grep -n -B1 -A1 'common-auth\|google_authenticator' /etc/pam.d/sshd
# Expected:
# 3-# Standard Un*x authentication.
# 4:auth required pam_google_authenticator.so nullok
# 5:@include common-auth
```

### Step 4: Configure sshd for 3-factor auth

Drop a clean override file in `/etc/ssh/sshd_config.d/` (rather than editing the main `sshd_config`) so it's easy to revert:

```bash
sudo tee /etc/ssh/sshd_config.d/99-mfa.conf > /dev/null <<EOF
KbdInteractiveAuthentication yes
AuthenticationMethods publickey,keyboard-interactive
EOF
```

The **comma** in `publickey,keyboard-interactive` is critical — it means "both required". A space would mean "either one".

> **Heredoc gotcha:** the closing `EOF` must be at the start of a line with **no leading whitespace**. If your terminal indents pasted content, use this single-line alternative instead:
> ```bash
> printf 'KbdInteractiveAuthentication yes\nAuthenticationMethods publickey,keyboard-interactive\n' | sudo tee /etc/ssh/sshd_config.d/99-mfa.conf
> ```

### Step 5: Validate and reload sshd

```bash
sudo sshd -t && echo "CONFIG OK"
sudo sshd -T 2>/dev/null | grep -iE '^(kbdinteractiveauthentication|passwordauthentication|pubkeyauthentication|authenticationmethods|usepam)'
```

Expected output:
```
pubkeyauthentication yes
passwordauthentication no
kbdinteractiveauthentication yes
usepam yes
authenticationmethods publickey,keyboard-interactive
```

If everything matches, reload sshd. **Existing sessions are not killed by reload** — your current connection stays alive even if the new rules are broken:

```bash
sudo systemctl reload ssh && echo RELOADED
```

### Step 6: Verify in a second session, then remove `nullok`

**Keep your current session open.** From a separate terminal on your workstation:

```bash
ssh -v superdev@<your-server>
```

You should see:
1. SSH key offered and accepted automatically.
2. Prompt for **TOTP verification code** — enter the 6-digit code from your authenticator app.
3. Prompt for **password** — enter your Unix password.
4. Shell appears.

(The order of TOTP vs password depends on PAM module ordering — both are required either way.)

Once verified, make TOTP truly mandatory by removing `nullok`:

```bash
sudo sed -i 's|pam_google_authenticator.so nullok|pam_google_authenticator.so|' /etc/pam.d/sshd
sudo grep google_authenticator /etc/pam.d/sshd
# → auth required pam_google_authenticator.so
```

No reload needed — PAM re-reads on next login. Test once more in a fresh terminal before closing your safety-net session.

### Common gotcha: "Too many authentication failures"

If your SSH agent has multiple keys loaded, OpenSSH offers them in order and exhausts the `MaxAuthTries` budget (Layer D) before reaching the correct key. The fix is on the **client side** — add `IdentitiesOnly yes` to your `~/.ssh/config`:

```
Host openmates-server
    HostName <your-server>
    User superdev
    IdentityFile ~/.ssh/openmates_server
    IdentitiesOnly yes
```

This tells SSH to **only** offer the explicit key, not every key in the agent.

### Verify Layer C

```bash
sudo sshd -T | grep -iE 'kbdinteractive|authmethods|usepam'
sudo grep google_authenticator /etc/pam.d/sshd          # no nullok
ls -la ~/.google_authenticator                          # -r-------- (400)
```

## Layer D — Additional SSH Hardening

### Why

Smaller SSH server settings that reduce attack surface and limit the impact of misconfiguration: restrict who can log in, cap auth attempts per connection, and shorten the connection grace time.

### Already configured?

Run on the server — if all three pass, **skip this layer**:

```bash
sudo sshd -T | grep -qi '^allowusers ' && echo "✓ AllowUsers set" || echo "✗ AllowUsers not set"
sudo sshd -T | grep -qiE '^maxauthtries [123]$' && echo "✓ MaxAuthTries ≤ 3" || echo "✗ MaxAuthTries too high"
sudo sshd -T | grep -qiE '^logingracetime ([0-9]|[1-5][0-9])$' && echo "✓ LoginGraceTime ≤ 59s" || echo "✗ LoginGraceTime too long"
```

### Steps

Append to the same override file from Layer C:

```bash
sudo tee -a /etc/ssh/sshd_config.d/99-mfa.conf > /dev/null <<EOF
AllowUsers superdev
MaxAuthTries 3
LoginGraceTime 30
EOF
sudo sshd -t && sudo systemctl reload ssh
```

What each does:
- `AllowUsers superdev` — only `superdev` can SSH in. Defense-in-depth on top of `PermitRootLogin no`. Add more usernames space-separated if needed.
- `MaxAuthTries 3` — disconnect after 3 failed attempts in a single connection. Reduces brute-force throughput.
- `LoginGraceTime 30` — close the connection if auth isn't complete in 30 seconds (default is 2 minutes, much longer than legitimate logins need).

### Verify

```bash
sudo sshd -T 2>/dev/null | grep -iE '^(allowusers|maxauthtries|logingracetime)'
# Expected:
# logingracetime 30
# maxauthtries 3
# allowusers superdev
```

## Layer E — Host Firewall (UFW)

### Why

A default-deny firewall blocks every port you didn't explicitly allow, protecting against accidentally exposed services (debug binds, dev tools, misconfigured Docker port mappings) and reducing attack surface to exactly what you intended.

### Already configured?

Run on the server — if all four pass, **skip this layer**:

```bash
sudo ufw status | grep -q '^Status: active' && echo "✓ ufw active" || echo "✗ ufw not active"
sudo ufw status verbose | grep -q 'deny (incoming)' && echo "✓ default deny incoming" || echo "✗ default not deny"
sudo ufw status | grep -qE '22/tcp +ALLOW' && echo "✓ SSH allowed" || echo "✗ SSH not allowed"
sudo ufw status | grep -qE '443(/tcp)? +ALLOW' && echo "✓ HTTPS allowed" || echo "✗ HTTPS not allowed"
```

### Steps

Install UFW (usually pre-installed on Ubuntu):

```bash
sudo apt install -y ufw
```

**Allow SSH first** before enabling — otherwise you lock yourself out:

```bash
sudo ufw allow 22/tcp comment 'SSH'
```

Allow OpenMates HTTP and HTTPS:

```bash
sudo ufw allow 80/tcp comment 'HTTP (Caddy redirect)'
sudo ufw allow 443/tcp comment 'HTTPS (OpenMates)'
```

Optional — if you administer the server over ZeroTier or another mesh VPN:

```bash
sudo ufw allow 9993/udp comment 'ZeroTier'
sudo ufw allow from 10.147.19.0/24 comment 'ZeroTier trusted subnet'
```

Set default policies and enable:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw default deny routed
sudo ufw enable
```

`ufw enable` will warn that it may disrupt existing SSH connections — it won't, because we already added the SSH rule above, but the warning is good to acknowledge.

### Verify

```bash
sudo ufw status verbose
```

Expected:
```
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), deny (routed)

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
80/tcp                     ALLOW IN    Anywhere
443/tcp                    ALLOW IN    Anywhere
22/tcp (v6)                ALLOW IN    Anywhere (v6)
80/tcp (v6)                ALLOW IN    Anywhere (v6)
443/tcp (v6)               ALLOW IN    Anywhere (v6)
```

UFW automatically applies rules to both IPv4 and IPv6 — no extra config needed.

## Layer F — Automatic Security Updates

### Why

Most Linux server compromises start with a known unpatched vulnerability. Automating security updates closes the patch window without requiring constant operator attention. The risk of an automatic update breaking something is far smaller than leaving security holes open for days.

### Already configured?

Run on the server — if all three pass, **skip this layer**:

```bash
dpkg -l unattended-upgrades 2>/dev/null | grep -q ^ii && echo "✓ unattended-upgrades installed" || echo "✗ not installed"
systemctl is-active unattended-upgrades >/dev/null && echo "✓ service active" || echo "✗ service inactive"
grep -q 'Unattended-Upgrade "1"' /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null && echo "✓ daily upgrades enabled" || echo "✗ daily upgrades disabled"
```

### Steps

Install `unattended-upgrades` (often pre-installed on Ubuntu):

```bash
sudo apt install -y unattended-upgrades
```

Enable it via the interactive prompt, or directly:

```bash
sudo dpkg-reconfigure -plow unattended-upgrades
```

Verify the daily timer is enabled:

```bash
cat /etc/apt/apt.conf.d/20auto-upgrades
# Expected:
# APT::Periodic::Update-Package-Lists "1";
# APT::Periodic::Unattended-Upgrade "1";
```

If either line is missing or set to `"0"`, create the file with both directives:

```bash
sudo tee /etc/apt/apt.conf.d/20auto-upgrades > /dev/null <<EOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
```

Verify the allowed origins include the security pocket:

```bash
grep -A5 'Allowed-Origins' /etc/apt/apt.conf.d/50unattended-upgrades
```

Expected (Ubuntu defaults — only security updates auto-install):
```
Unattended-Upgrade::Allowed-Origins {
        "${distro_id}:${distro_codename}";
        "${distro_id}:${distro_codename}-security";
        "${distro_id}ESMApps:${distro_codename}-apps-security";
        "${distro_id}ESM:${distro_codename}-infra-security";
};
```

### Optional: Automatic reboot after kernel updates

By default, security updates that require a reboot (kernel, glibc) install but don't activate until you manually reboot. To enable scheduled automatic reboots at a low-traffic hour:

```bash
sudo sed -i 's|//Unattended-Upgrade::Automatic-Reboot "false";|Unattended-Upgrade::Automatic-Reboot "true";|' /etc/apt/apt.conf.d/50unattended-upgrades
sudo sed -i 's|//Unattended-Upgrade::Automatic-Reboot-Time "02:00";|Unattended-Upgrade::Automatic-Reboot-Time "04:00";|' /etc/apt/apt.conf.d/50unattended-upgrades
```

Trade-off: security patches activate immediately (good), but unexpected reboots can interrupt running Docker containers and long-running tasks (bad). For a dev server with an attentive operator, manual reboots are fine. For unattended production, scheduled auto-reboot is usually safer.

### Verify

```bash
systemctl is-enabled unattended-upgrades             # → enabled
systemctl is-active unattended-upgrades              # → active
sudo unattended-upgrade --dry-run --debug 2>&1 | tail -20  # → shows what would be installed
journalctl -u unattended-upgrades --since "7 days ago" | tail
```

## Disaster Recovery

Two recovery paths must exist before applying any layer above:

**1. Hosting provider's rescue/web console.** Every reputable VPS provider (Hetzner, DigitalOcean, AWS, OVH, Linode) offers an out-of-band console that bypasses SSH entirely. Locate it in your provider's control panel, log in once to verify it works, and bookmark it before starting any hardening work. From this console you can edit any file on disk, restart services, and unlock yourself from any misconfiguration.

**2. TOTP scratch codes.** The 5 codes printed during Layer C enrollment are the only way to authenticate when your authenticator device is lost. Store them in a password manager **and** print/write them somewhere physical, kept separate from the device running the authenticator app.

### Emergency rollback commands

If you lock yourself out of SSH but still have a working session, or you're using the rescue console:

**Roll back Layer C/D (3-factor auth + hardening):**
```bash
sudo rm /etc/ssh/sshd_config.d/99-mfa.conf
sudo systemctl reload ssh
```

**Roll back Layer C PAM change:**
```bash
sudo cp /etc/pam.d/sshd.bak-* /etc/pam.d/sshd
```

**Roll back Layer E (firewall):**
```bash
sudo ufw disable
```

## Verification Checklist

After all six layers are in place, run this checklist. Every line should pass.

```bash
# Layer A — Non-root user + root disabled
id <username> | grep -o sudo                                    # → sudo
sudo sshd -T | grep -i permitrootlogin                          # → permitrootlogin no

# Layer B — Key-only auth
sudo sshd -T | grep -i passwordauthentication                   # → passwordauthentication no

# Layer C — 3-factor auth
sudo sshd -T | grep -i authenticationmethods                    # → authenticationmethods publickey,keyboard-interactive
sudo grep google_authenticator /etc/pam.d/sshd                  # → no nullok
ls -la ~/.google_authenticator                                  # → -r-------- (400)

# Layer D — SSH hardening
sudo sshd -T | grep -iE '^(allowusers|maxauthtries|logingracetime)'

# Layer E — Firewall
sudo ufw status verbose | grep -E 'Status|Default|22/tcp|80/tcp|443'

# Layer F — Auto updates
systemctl is-active unattended-upgrades                         # → active
cat /etc/apt/apt.conf.d/20auto-upgrades                         # → both lines = "1"
```

Plus the most important manual test: open a brand-new terminal on your workstation and SSH in. Confirm key + TOTP + password are all required, and you land in a shell. If that works, your server has all six baseline protections in place and is ready to be exposed to the public internet running OpenMates.
