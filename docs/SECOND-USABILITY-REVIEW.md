# Second usability review implementation

October 9, 2026

- Compact mobile navigation with a Menu disclosure, labeled Help/Settings and Escape support. Application footers are in document flow.
- Inventory search precedes collapsed workspace totals and setup. Filters are grouped with an active count and removable chips; storage scope appears only for a chosen location. Import lives under More.
- Phone inventory rows keep name, stock and storage together. Additional desktop columns are optional. BOMs emphasize Needed, Available and Missing.
- Label presets and starter templates match current values. Advanced layout contains dimensions/units, margins, fonts and raw templates. Preview and download precede optional batch selection; selecting a preview component also selects it for printing until the user deliberately changes the batch.
- Projects lead with build readiness. Cost details are expandable; missing prices are flagged on projects and shopping lists.
- Component stock controls precede metadata. Delete remains under More actions and on the edit page. Basic forms put category/storage first and keep Save reachable.
- Storage/project creation forms are collapsed. Copy, singular quantities and encoded-value display are corrected. Quick stock has an independent dialog and Cancel.

Price presence is stored separately from the numeric value. Existing nonzero prices are recorded; historical zero prices are treated as unrecorded because prior versions did not distinguish blank from free. Saving an explicit zero marks a part as free. CSV import preserves this distinction.

Validation: full Python suite; local browser checks at 390, 1000 and 1440 pixels, including first-screen stock, navigation, filters, quick-stock cancellation, label preset/template changes, measurement conversion and PDF download. No physical printer testing.
