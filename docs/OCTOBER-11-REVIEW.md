# October 11 usability review follow-up

Implemented from `partshelf-review-2026-10-11.md` in the supplied review folder.

## Correctness and navigation

- Fixed `/projects/<id>?builds=2`: Jinja was given an undefined `int` callable when parsing a present query value. Shared backend parsing now validates counts from 1 to 10,000 for both project and shopping pages.
- Project costs, readiness, shortage rows and shopping links retain the selected count, including the return trip. BOM editing quantities remain per build.
- Added an in-app server-error page with inventory, projects and support recovery links.
- Quick-stock previews carry a validated inventory/search return URL through Cancel and successful application; search, filters, sorting and browser scroll position are retained.
- Missing component prices display “Price not set,” separately from deliberately recorded zero prices. Incomplete estimates identify known subtotals and unpriced counts. CSV exports leave unknown prices blank.
- Renamed shopping list “Exact unit cost” to “Exact shortage cost,” with price × quantity when known.

## Interface

- Mobile inventory starts with its title and Add component. Metrics fit in a compact grid; Print is in More actions and setup reminders follow the inventory. Empty category/supplier/price placeholders are suppressed on phones; useful details remain visible to respect the earlier request for always-visible details.
- Settings starts with account/workspace destinations, followed by expandable Appearance and Sidebar sections.
- New organizers default to 4 × 4 × 1. The live grid is larger and updates its total before creation. Existing organizers are unchanged.
- Label design begins with a live selected-parts summary linking directly to batch selection. Repeated identical identifiers are omitted there.
- Bug reports display explicit optional reproduction prompts and an appropriate field label; existing user-entered text is preserved.
- About prose is limited to 70 characters per line. Updated desktop/mobile sample screenshots reflect the current interface and load eagerly.

No real workshop photograph was available in the review files; no substitute or invented personal image was added.

## Validation

185 Python tests pass, including regression coverage for count parsing, the project/shopping round trip, stock-preview returns, unknown versus zero prices, and server-error recovery. Browser checks cover desktop and 390px phone layouts, filter retention, Settings ordering, bug prompts, organizer preview updates and label selection navigation. Public product screenshots use only a local sample inventory.
