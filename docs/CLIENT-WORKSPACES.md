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

The registration page also offers **Sign up with Google**. Google must return a verified email; the new client then chooses a workspace name, username and backup password. Existing accounts are never merged by matching email: sign in with a password first and link Google. Passkeys can be enrolled after signup. Password login accepts a username or email, case-insensitively; ambiguous legacy username/email collisions fail closed.

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
