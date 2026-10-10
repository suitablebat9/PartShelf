# Admin review implementation

October 9, 2026

## Correctness
- Barcode preview failures use a small error response instead of the full application page. Code 128 validation lists affected parts, a Use QR action preserves settings, and empty/invalid batches disable Download. Stored identifiers are unchanged.
- Build-count changes recalculate full, shortage and whole-pack costs and carry the count into shopping lists and back. BOM quantities are labeled per build.
- Storage parenting excludes descendants by ID ancestry; server cycle validation remains authoritative.
- Site section saves preserve unrelated settings, record previous changed values, and reject stale versioned edits. Restoring a revision creates another recoverable revision.
- Roadmap moves are transactional, check revisions and preserve publication state.
- Private feedback notes have independent revisions and never notify subscribers.

## Navigation and editing
- Workspace links and platform administration have separate sidebar groups, with explicit client scope and a label for the administrator's own inventory.
- Workspaces lead client management; settings, Trash and readable/localized activity are separate views. Creation is collapsed, lists searchable, membership wording corrected, and empty deletion sections hidden.
- Account title precedes email, sign-in methods and two-step verification. Linked Google accounts no longer show Link again. Sessions show a live count and explain the revoke scope.
- Analytics has Overview, Workspaces and Users views, search/status filters, expandable mobile rows, effective access counts, tracking definitions and the first recorded demo date. User searching is explicitly scoped to the current 100-user page.
- Site settings are split into About, Support, Policies and Integrations, with per-section publishing, plain-text draft preview, unsaved change summaries and revision history.
- Roadmap forms identify draft/public state, have preview/cancel and explicit publish labels, and support accessible move controls.
- Feedback actions show recipient counts and preview the status/note text. Private notes are separately labeled and saved without email.

## Inventory and storage
- Searchable location dialogs retain full paths, keyboard operation and recently used paths; existing native selectors remain usable.
- Drawer search reports results, scrolls to a unique match, and opens contents on selection. Assignment uses searchable checkboxes and removable selection chips.
- Physical controller settings stay behind a setup disclosure; calibration has its own advanced disclosure. No device communication behavior changed.
- Organizer creation shows a live grid and total drawer count.
- Single-part stock review avoids bulk wording and accepts an optional reason.
- Duplicate inventory/label identifiers are suppressed, small unit prices retain up to six decimals, empty specification groups are hidden, scanner idle state shows guidance, and bug feedback has optional prompts.
- Donation copy is less repetitive; policy text has headings without changing wording; dark-mode product imagery is framed and slightly smaller.

## Validation and limitations
169 automated tests, including new preview/batch, stale-publication/restore, private-note, reorder and storage-cycle cases. Browser checks cover administrator pages at 390 and 1440 pixels in light/dark, label recovery/empty selection, the review's 141-resistor/$4.03 two-build example, P8 drawer search, assignment selections, draft preview and cancel. Disposable data only: no live emails sent, account changes submitted, or physical devices actuated. Real device operation, external Google identity changes and physical printing were not exercised.
