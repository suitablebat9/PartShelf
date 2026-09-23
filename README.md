# Partshelf — self-hosted component inventory

A small, server-backed inventory system for a workshop, electronics bench, or parts collection. Runs directly in a Debian 13 Proxmox LXC using Python, Flask, SQLite, Gunicorn, and Nginx. No Docker, hosted database, CDN, external fonts, or cloud account is needed to use the app. GitHub is used only to distribute source and updates.

**[Install in a Proxmox LXC →](docs/PROXMOX.md)**

## Features

- Shared inventory across computers and phones; inventory/search pages refresh every 20 seconds when idle. All records are read from the server; forms are not refreshed while you edit them. Edits detect stale versions instead of overwriting newer changes.
- Separate HTML templates for inventory, search, component creation/editing, component details, storage, projects, and labels.
- Light/dark themes, responsive layout, locally served CSS and JavaScript.
- Component name, stock, Name_ID (defaults to name), description, category, stock unit, supplier and product URL, datasheet, image, specifications, and barcode/QR identifier.
- Add multiple tags to each component: Enter adds a tag chip and clears the input, and chips can be removed before saving. Enter in other single-line component fields keeps the form open. Suppliers and categories use visible dropdowns with an Add new option. Category names are case insensitive; the app does not guess classifications from a part name.
- Parametric-style search across name, description, Name_ID, specifications and scan identifiers, with category, storage, supplier, stock, tag, size/package, resistance, capacitance, voltage and tolerance filters. Specification filters list saved values in searchable columns with counts. Select multiple values per column (OR); selections across columns combine with AND. Counts reflect the other active filters. Enter units consistently (no automatic conversion between, for example, nF and µF). Sort by name, stock, price, or newest. This searches your inventory; there is no Digi-Key/Mouser catalog import or live pricing integration.
- Nested storage: room → closet/cabinet → drawer/shelf/bin. Each component has one storage assignment. Create and assign a new storage area directly in the component form.
- Per-project folders/pages with bills of materials, required quantity per part, shortages, full build cost and estimated missing-parts cost. “Build once” deducts the entire list atomically or makes no changes if any part is short. Planning lists do not reserve stock between projects.
- Stock adjustments and movement history. Fractional units supported. Use one currency throughout; prices use decimal arithmetic and six decimal places per unit.
- Enter either unit price or total purchase price; the other updates automatically using the saved original purchase quantity. This quantity starts from initial stock but can be changed independently. Using stock never changes historical purchase pricing. Default numeric zeros are selected on focus so typing replaces them.
- PDF datasheets and PNG/JPEG/WebP/GIF images upload to local server storage. External links are optional and remain links; no automatic remote downloading.
- Printable labels: custom width/height (0.5–12 inches), common presets including 3.5 × 1.5, QR / Code 128 / no code, editable or hidden text, three font families, adjustable text size, automatic shrinking, and up to 100 copies per component. Preview one layout, select multiple components (or select all), and download one PDF with up to 1,000 labels. Use placeholders such as `{name_id}`, `{resistance}` or `{tags}` for per-component text. The preview updates automatically as you edit and is rendered from the same PDF. Top, bottom, left, and right margins are individually adjustable in inches. One label per print page; set your printer stock to the same dimensions.
- USB/Bluetooth scanners that type into a field work in the search box and identifier field. No phone-camera scanner is included; enter/paste a decoded code or use a keyboard-mode scanner. New barcode/QR identifiers default to Name_ID and can be customized. Existing identifiers stay unchanged during updates so printed labels remain valid. Code 128 requires printable ASCII; use QR for Unicode identifiers.
- Login, password hashing, CSRF protection, authenticated uploads, and Nginx login rate limiting.
- Python updater with independent release environments, preflight tests, data backup, health check and automatic rollback. Inventory files and credentials never go to GitHub.

## Local development (Python 3.10–3.14)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/flask --app wsgi create-user
.venv/bin/flask --app wsgi run --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and sign in. Local data goes into `data/`, excluded from Git. Set `INVENTORY_DATA` to change that directory. The development server is for local use; the LXC installation uses Gunicorn behind Nginx.

```bash
.venv/bin/python -m pytest -q
```

Tests cover login and CSRF, validation, category creation, price conversion, filtering, stale edits, stock protection, project totals and atomic deductions, local attachments, generated labels, shared server state, atomic release activation, and preflight update failure. CI repeats them on Linux with Python 3.10–3.14. The updater safely extracts regular files without requiring newer tarfile extraction-filter APIs.

## Update the LXC

After changes have been committed to `main` in your repository:

```bash
python3 /opt/partshelf/current/scripts/update.py
```

Run as root **inside the LXC**. The updater fetches `origin/main` into a new release, installs pinned dependencies, runs tests, stops the service briefly, copies data into a protected backup, switches releases, starts the app and checks `/login`. A failed startup restores the old release and data. Previous releases/backups remain in `/opt/partshelf`; periodically archive/remove old ones after verifying a separate backup. Failed preflight releases can also be removed manually.

The updater deploys changes you have made and pushed to GitHub; it does not invent code changes. Server configuration changes to systemd/Nginx need explicit application as described in the setup guide. It intentionally does not overwrite system configuration during routine app updates.

Existing installations migrate automatically on startup. Original purchase quantity is left unknown for older components because remaining stock cannot establish the original purchase amount; enter it when editing those components. Existing stock, prices, history, and identifiers are preserved.

## Files

```text
inventory/__init__.py       Application routes, validation and database schema
inventory/migrations.py    Additive database migrations
inventory/label_pdf.py     Shared PDF renderer and image preview
inventory/templates/       Separate HTML pages and shared search partial
inventory/static/          CSS and browser behavior (served locally)
wsgi.py                    Production/development application entry
scripts/create_lxc.sh      Proxmox host container creation helper
scripts/install.sh         Debian LXC installer
scripts/update.py          Versioned-release updater and rollback
scripts/backup.py          Consistent server-data backup
scripts/manage_user.py     Create/reset login credentials interactively
scripts/patch_code.py      Apply a reviewed unified code patch via Python
scripts/publish.py         Publish local code with Git
docs/PROXMOX.md             Complete installation and operating guide
deploy/                    systemd and Nginx configuration
tests/                     Functional tests
```

## Operating boundaries

Designed for a personal/small-team LAN or VPN deployment with one shared inventory and individual logins. All users have the same editing permissions. Put HTTPS in front before use outside a trusted LAN, then set `COOKIE_SECURE=1`. Internet exposure is not configured automatically. No offline editing, accounting/tax engine, per-location stock splits, currency conversion, reservations, or automatic supplier imports.

Use server-side backups for recovery. GitHub stores source only, not inventory data. See the setup guide for backup, restore, adding users, and troubleshooting.
