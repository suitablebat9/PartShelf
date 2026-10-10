# Imports, bulk actions, shopping lists and scanning

## Where to find them

- **Inventory → Import CSV:** download a template, upload UTF-8 CSV, review and confirm new components. At most 1,000 rows / 2 MB per file. Existing identifiers are rejected, never overwritten. Existing storage paths are matched exactly; categories and tags are created on confirmation.
- **Inventory row checkboxes:** move, add/remove tags, or adjust stock for up to 500 visible selected components. **± stock** selects a single component for a quick adjustment. Search/filter changes clear selection. Quantities apply to each selected part in its own unit.
- **Project → Import BOM:** match existing internal part numbers with required quantities. Duplicate CSV rows are summed. Merge sets listed quantities and keeps unlisted parts. Replace removes unlisted project entries. Neither changes stock.
- **Project → Shopping list & CSV:** shortages grouped by supplier, with exact-unit and rounded-pack costs and supplier links. Choose a build count. Exported text cells are protected against spreadsheet formula interpretation. Estimates use recorded USD prices, not live supplier quotes.
- **Project → Duplicate project:** copies details and BOM, without changing stock or copying build history.
- **Search → Scan:** QR and Code 128 camera/photo scanning, with manual input fallback. ZXing is vendored and served locally. Images stay in the browser. Cameras require HTTPS and browser permission; camera lifecycle is stopped on successful reads, explicit Stop, hidden pages and navigation. Decoded URLs are searched as text, not automatically opened.
- **Sidebar ? → Help:** guides for setup, imports, projects, bulk changes, scanning and labels. Setup progress tracks storage, parts, a label PDF download and a project; editors can hide the checklist for the workspace.

## Validation and permissions

Imports and batch actions are staged in the current workspace database. Previews expire after 30 minutes, are tied to the creator's signed-in browser, and can be applied once. The full plan is revalidated inside the same write transaction as application. New duplicates, changed quantities, missing records, stock shortages and changed bulk-record versions block the batch. User data is escaped in previews. Viewer roles cannot stage/apply changes or duplicate projects. The shared demo uses its own database and retains its existing caps and rate limits.

No credentials, client data or staged uploads are committed to GitHub. Preview records are excluded from workspace exports. Expired previews are cleaned when staging another action. The updater's full backup includes them as part of the database snapshot.

## Roadmap publication

After deploying, run inside the LXC:

```sh
python3 /opt/partshelf/current/scripts/publish_workflows_roadmap.py
```

This publishes six Released entries once, without altering existing roadmap items or republishing over later administrator edits. It sends no emails. Edit the published items through Settings → Edit roadmap (or its sidebar entry). Empty roadmap columns are hidden instead of implying unannounced plans.

## Verification

Automated tests cover CSV validity, duplicates, quantities, atomic application, replay/expiry, stale previews, bulk limits, workspace/browser isolation, viewer permissions, BOM replacement, stock preservation, duplication, whole-pack math, spreadsheet exports and roadmap idempotency. Browser tests use actual QR/Code 128 images and a simulated camera; physical phone camera focus and hardware behavior still depend on the device.
