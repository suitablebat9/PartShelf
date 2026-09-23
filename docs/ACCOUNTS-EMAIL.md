# PCB Studios accounts, email and public access

Existing users keep their passwords and data. This update replaces the old username-only cookie with revocable server-validated sessions, so everyone must sign in once again. Passwords are never stored in cookies. Optional **Remember me for 30 days** has a fixed 30-day expiry; normal sign-ins use a browser-session cookie with a maximum server lifetime of 12 hours. Account → Sign out all other devices revokes other sessions. Password resets revoke all sessions.

## Configure the server

Run as root inside the LXC after updating:

```bash
python3 /opt/partshelf/current/scripts/setup_integrations.py --public-url https://inventory.pcb-studios.com
```

This sets secure HTTPS cookies and the WebAuthn origin, installs a five-minute low-stock timer, and restarts Partshelf. Use the HTTPS hostname afterward, including on your home network. Passkeys belong to this exact hostname. Changing it requires enrolling passkeys again. These settings live in `/etc/partshelf.env`, outside Git. Back up that root-only file separately from `/var/lib/partshelf`.

## Google sign-in

1. In [Google Auth Platform](https://console.cloud.google.com/auth/overview), create/select a project and configure its branding. Use Partshelf by PCB Studios and your business support address. An Internal audience limits Google sign-in to your Workspace; choose External only if you intend to link external Google accounts.
2. Create an OAuth **Web application** client. Register exactly this redirect URI:
   `https://inventory.pcb-studios.com/auth/google/callback`
3. Enter the client ID and secret using the private setup prompts below. The app requests only `openid email`; it does not request Gmail or Drive access.
4. Google sign-in automatically links an existing verified email account when Google hosts that address (Gmail or Workspace), then applies the account’s configured MFA. Unverified, ambiguous, non-Google-hosted, or already differently linked accounts require signing in and explicitly linking Google in Account & security. New Google identities automatically receive a private workspace while public registration is open. Google-only accounts can confirm security changes with Google and set a backup password using Forgot password; Google cannot be unlinked until a password is set. Stable Google subject IDs remain the identifier for subsequent sign-ins.

Google validates the redirect URI; the OAuth library validates state, nonce and signed ID tokens. [Google’s OpenID Connect setup](https://developers.google.com/identity/openid-connect/openid-connect).

## Google Workspace email from the no-reply alias

The SMTP login is the **primary mailbox that owns** `no-reply@pcb-studios.com`, not the alias. Confirm the alias is allowed under Gmail’s **Send mail as** settings. Enable two-step verification on that mailbox and create an app password if your Workspace admin permits it. Use the app password, never the normal Google account password. If your organization disables app passwords, ask your Workspace admin about an authenticated SMTP relay; this app supports TLS SMTP with username/password, including an administrator-configured relay, but not Gmail API OAuth mail delivery.

```bash
python3 /opt/partshelf/current/scripts/setup_integrations.py --credentials
```

Secrets are entered with hidden prompts. Blank fields keep existing values. The helper configures `smtp.gmail.com:587` using STARTTLS. It writes `/etc/partshelf.env` with mode 0600 and restarts the service. Google client credentials and SMTP credentials are separate; you may configure either first.

Default sender: `no-reply@pcb-studios.com`. Reply-To: `support@pcb-studios.com`. Google must authorize the alias, and your domain’s SPF/DKIM/DMARC must support Workspace delivery. Do not create a second SPF record. See [Workspace SMTP setup](https://support.google.com/a/answer/176600?hl=en) and [Gmail alias sending](https://support.google.com/mail/answer/22370?hl=en).

The service supports these environment keys: `PUBLIC_URL`, `COOKIE_SECURE`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_FROM`. Port 465 uses implicit TLS; other configured ports require STARTTLS with certificate validation. No credentials go into browser code or GitHub.

## Passkeys, two-step verification and email notifications

- Sign in, then open **Account & security**. Security changes require a sign-in within the last 10 minutes. Use **Confirm identity again** if needed.
- **Add a passkey**: complete your browser/device prompt yourself. Enrollment requires user verification and a discoverable credential. Private keys stay with your device/password manager. Password sign-in remains available.
- **Authenticator**: scan the enrollment QR in an authenticator app and enter its code. Save the ten one-use recovery codes. The secret is encrypted in the database; keep `secret.key` in data backups. Reused codes are rejected.
- **Email codes**: first send a verification code to your email and confirm it; then choose **Use email codes**. Email verification and sign-in codes expire after 10 minutes and allow at most five attempts. You can use recovery codes if email delivery is unavailable. Enabling either method replaces the old method and recovery codes.
- Optional two-step verification applies to password, Google and passkey sign-ins. Remembered sessions do not request it again until a new sign-in is needed.
- **Low-stock alerts**: verify your email, opt in, then enter a low-stock threshold on each component. Blank disables that component. Stock at or below the threshold triggers one email per recipient per low-stock episode. Restocking above the threshold resets the alert; failures retry after 15 minutes. Delivery is checked every five minutes, not continuously. As with SMTP generally, a process interruption immediately after delivery can cause a duplicate retry.

Verify the timer without sending a test message:

```bash
systemctl status partshelf-alerts.timer --no-pager
```

Run a real check only after opting in; it sends applicable alerts:

```bash
systemctl start partshelf-alerts.service
journalctl -u partshelf-alerts.service -n 20 --no-pager
```

## Recovery

Lost second factor and all recovery codes: the server owner can run `python3 /opt/partshelf/current/scripts/reset_mfa.py` as root inside the LXC. This disables that account’s second factor and revokes every session, but still requires its password. Reset passwords using the existing `scripts/manage_user.py` procedure in the Proxmox guide.

## Brave and the Cloudflare tunnel

`ERR_NAME_NOT_RESOLVED` is a DNS failure before a request reaches Partshelf. The application does not limit access to your LAN. Public Google and Cloudflare DNS both resolved `inventory.pcb-studios.com` to Cloudflare addresses during this update; the Mac’s system resolver did too. No tunnel/DNS settings were changed.

For access without a browser-specific DNS override, the normal resolver must return the same public record. In Cloudflare, ensure the hostname has a proxied tunnel CNAME to your tunnel’s `<id>.cfargotunnel.com` and no conflicting A/AAAA records. Check any home router/AdGuard/local DNS overrides and stale negative caches, and verify the same hostname from a second network. A filtering resolver can block a hostname even while other tunnels work. If it fails again, record the exact browser error and the resolver’s answer before changing anything. [Cloudflare tunnel DNS guide](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/).


## Google error 403: org_internal

This is Google's OAuth audience restriction. External Google accounts cannot authorize a project configured as Internal. For public clients use a dedicated Google Cloud project/app called **Partshelf by PCB Studios** with **External** audience. If the consent screen is named **Cloudflare**, check whether it is shared with Cloudflare Access before changing its audience; a separate Partshelf project avoids changing that integration.

Create a Web application client with this Authorized redirect URI:

`https://inventory.pcb-studios.com/auth/google/callback`

In Testing, add intended test accounts (for example the owner's personal Gmail) as test users; publish to Production for the public rollout and complete any verification Google requires. Enter the new client ID and secret through `setup_integrations.py --credentials`. Secrets stay on the server. New customers should use **Create a workspace → Sign up with Google**.

[Google's audience documentation](https://support.google.com/cloud/answer/15549945?hl=en).

## Sender displays the primary Workspace mailbox

Partshelf sets both the email From header and SMTP envelope sender to `MAIL_FROM` (normally `no-reply@pcb-studios.com`), with the display name **PCB Studios · Partshelf**. SMTP authentication still uses the primary mailbox that owns the alias.

In Gmail, while signed into that primary mailbox, open **Settings → See all settings → Accounts → Send mail as**. Add/verify `no-reply@pcb-studios.com` there if absent. An alias that receives messages in Workspace is not, by itself, evidence the SMTP account is authorized to send as it. If Google still rewrites the From address, inspect a delivered message's original headers and the alias's send-as status; the application cannot force Google to honor an unapproved sender.

Do not change the primary mailbox's default sender unless you also want its ordinary mail to use no-reply. [Gmail send-as instructions](https://support.google.com/mail/answer/22370?hl=en).
