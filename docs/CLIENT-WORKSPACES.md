# Client workspaces and administration

Partshelf supports public registration at `/register`. Each new client receives an independent workspace with its own inventory database and upload folder. Staff in that workspace share components, categories, tags, suppliers, storage, projects, labels and stock history. One account belongs to one workspace; joining another workspace currently requires a different email/account.

## Existing installation

The first upgrade keeps the original inventory and all existing logins in workspace 1, named **PCB Studios**. The earliest existing user becomes its owner and the platform administrator. Other existing users retain inventory editing as members. Existing passwords, passkeys, Google links, MFA settings and inventory identifiers remain intact. The migration is transactional and safe across restarts.

For a fresh installation, complete the installer's first-user prompt before opening registration. The first account created by `flask --app wsgi create-user` becomes the platform administrator. Public signup never grants platform administration.

## Public onboarding

1. Configure the public HTTPS origin and Google Workspace SMTP using [Accounts and email](ACCOUNTS-EMAIL.md).
2. Open **Client management** and leave **Allow verified self-service registration** enabled.
3. Share `https://inventory.pcb-studios.com/register`.
4. The client chooses a workspace name, username and password, then verifies a six-digit email code in the same browser. No inventory or account is created before verification.
5. The client signs in and opens **Team management** to invite staff.

Registration can be paused at any time. It also stays unavailable while HTTPS or mail configuration is missing. Codes expire after 10 minutes, allow five attempts and are browser-bound. Signup and email sends are throttled. Password reset is available from the login page for verified account emails; it revokes old sessions and retains MFA.

Both sign-in and registration support Google. A new verified Google identity automatically gets a private workspace, an available username and an owner account. The owner can rename the workspace in Team management and set a backup password through Forgot password. Matching verified Gmail/Workspace email accounts link automatically; ambiguous, unverified, non-hosted or differently linked accounts still require an explicit signed-in link. Existing MFA applies. Passkeys can be enrolled after signup. Password login accepts a username or email, case-insensitively; ambiguous legacy username/email collisions fail closed.

## Roles and invitations

| Role | Access |
|---|---|
| Owner | Edit inventory, manage all staff roles/access, invite other owners/admins, rename and export the workspace |
| Admin | Edit inventory, manage member/viewer accounts, rename and export the workspace |
| Member | Edit inventory, storage and projects; print labels |
| Viewer | Read inventory, storage and projects; print labels |
| Platform administrator | Manage client workspaces, registration and staff access; no inventory workspace switching or impersonation |

Invitations are single-use, expire in 48 hours and can be revoked. Choose **Send invitation by email**, or generate a private link to share yourself. Anyone with a link can claim its invitation, so send it only to its intended recipient. Invited users verify their email separately under Account & security before email MFA, stock notifications or email password recovery are available.

Changes to member role/access revoke their sessions, pending authentication challenges and invitations they created. Suspension blocks all workspace logins, revokes sessions/invitations and stops low-stock alerts. Reactivation does not restore old sessions. The UI prevents editing your own role/access, removing the last active owner, or suspending the platform administrator's own workspace. Platform administrators can delete users and workspaces by typing the exact name in the deletion form. Deletion moves the record to Trash and revokes access. Inventory, files, account identity and MFA/passkeys remain stored for restoration; username/email values stay reserved. Restore controls are available in Client management and workspace settings. There is no permanent purge. Suspended workspace logins show a dedicated support page after credential validation.

Management changes require a sign-in within the last 10 minutes and are recorded in the management activity log. Inventory edits continue using component movement history. Password resets never disable MFA.

## Isolation and exports

The server determines the workspace from the authenticated user's registry record, never a browser-supplied workspace ID. New clients use `/var/lib/partshelf/workspaces/<id>/inventory.db` and `uploads/`; workspace 1 preserves the original paths. Account credentials, sessions and challenges remain in the central registry. Inventory endpoints cannot switch workspace through route/query/form IDs.

Workspace owners/admins can download a ZIP containing JSON inventory tables and their uploads. It excludes all passwords, session tokens, MFA secrets, other client records and server settings. This is an export, not an automatic import/restore feature.

The standard backup and updater include the entire data directory and all workspace files. They stop the web service and notification worker during snapshots. Restore the complete backup and keep `/etc/partshelf.env` separately protected, as documented in the Proxmox guide.

## Capacity and operations

Default limits can be adjusted in the root-only `/etc/partshelf.env`, followed by restarting Partshelf:

- `MAX_WORKSPACES=1000`
- `MAX_WORKSPACE_MEMBERS=100`
- `MAX_WORKSPACE_COMPONENTS=100000`
- `WORKSPACE_UPLOAD_LIMIT_MB=1024`
- `WORKSPACE_DATABASE_LIMIT_MB=256`

Inventory text submissions are limited to 64 KB; total upload request size remains 12 MB. These application limits are admission checks, not filesystem reservations. Monitor actual server storage and keep off-server backups. With many clients, also monitor SMTP quotas and notification timer duration.

Application throttling uses the direct request source plus per-account/email limits. Behind the default local reverse proxy the source limit is shared, deliberately conservative. Do not trust arbitrary forwarded headers; configure a verified proxy chain before increasing public traffic. Production scale, billing/subscriptions, custom domains, workspace switching, legal terms/privacy policy and a marketing site are separate from this initial client portal.

## Public demo

`/demo` provides prefilled credentials and a shared, editable sample inventory. Visitors can create/edit parts, upload sample files, adjust stock, build projects, and print labels. Changes are visible to other visitors, so the UI asks visitors to use sample information only. Demo accounts cannot access account settings, administration, analytics or exports. It creates no registry users or workspaces and never accesses a client's inventory.

The separate demo database and uploads reset after 48 hours. A cross-process lock serializes demo operations and resets; expired data resets before the next request is served. Stale forms are rejected after a reset. The hourly `partshelf-demo-reset.timer` also resets expired data when there is no traffic. The UI shows the next reset time in UTC. Limits: 500 component types, 100 projects/storage areas, 20 MB database, 25 MB uploads, and 120 writes per request source per hour (shared behind the default local proxy).

For existing installs run `python3 /opt/partshelf/current/scripts/setup_integrations.py` after updating to install the timer. Fresh installations install it automatically. `flask --app inventory:create_app reset-demo` checks expiry without forcing an early reset.

## Self-service deletion

Non-platform users can delete their own account from Account & security after recent authentication and typing their exact username. The last active owner must first assign another owner or delete the workspace. Owners can delete their own workspace from Team management by typing its exact name. Members/admins cannot delete a workspace, and the platform administration workspace is protected. All affected sessions/challenges/invitations are revoked.

These operations use the existing recoverable Trash system: access is removed immediately, while records and inventory remain available for platform-admin restoration. They do not promise permanent erasure. No scheduled purge is performed.

## Private analytics

Only platform administrators can open `/management/analytics`. It shows workspace creation dates, member/component-type/project counts, user creation and last-sign-in times, signup methods, first-touch referral/campaign sources, and approximate signup country. The demo is excluded. User rows paginate in groups of 100; unavailable inventory counts are marked rather than silently reported as zero.

Historical user signup dates and attribution that were never recorded remain **Not recorded**. New signup attribution captures only external referral hostname (not paths/query strings), bounded `utm_source`, `utm_medium`, `utm_campaign`, and optional country. It never sends this information to a third-party analytics service or stores raw IP addresses for analytics. Attribution is descriptive, not an access-control signal.

Country capture is opt-in: only use `python3 /opt/partshelf/current/scripts/setup_integrations.py --cloudflare-country` on an origin protected by Cloudflare. This sets `TRUST_CLOUDFLARE_COUNTRY=1` and accepts the approximate `CF-IPCountry` header. Enable Cloudflare Network → IP Geolocation if the header is absent. Restrict direct origin access or strip client-supplied country headers on non-Cloudflare ingress; the application cannot authenticate arbitrary headers. Without the setting/header, country stays unrecorded. See [Cloudflare IP Geolocation](https://developers.cloudflare.com/network/ip-geolocation/).
