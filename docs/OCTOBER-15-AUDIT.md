# Usability audit implementation — October 15, 2026

Implemented the supplied PartShelf usability audit, including:

- Stable label presets in both unit systems and readable square-label identifiers.
- Mobile component actions, full storage paths, and readable tablet inventory rows.
- Inline stock and signup errors that retain the user's context.
- Quick stock adjustments with guarded, single-use undo; bulk changes retain previews.
- Separate out-of-stock and low-stock counts, consistent currency, and relevant before/after bulk comparisons.
- Signup code resend and email correction without restarting workspace setup. Initial and resent emails include the code in the subject, for example `123456 — Partshelf account creation code`.
- Optional onboarding, clearer storage creation, account sections, and public-page navigation.

Validation: 193 automated tests; browser checks at 320–1024 pixels in both themes; all six label presets in inches and millimeters; downloaded PDF dimensions; QR decoding from a one-inch label; stock save/undo and signup recovery regressions.

No workshop photo was fabricated. Tests use local sample inventory and mocked email delivery. Physical printing, motor hardware, external identity-provider enrollment, and payment processing were not exercised by this audit.
