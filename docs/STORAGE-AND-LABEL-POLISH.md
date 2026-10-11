# Storage, labels, and navigation update

- Product links suggest a supplier by hostname; choosing a supplier manually stops automatic changes.
- Storage views preselect the location for new components and preserve the return page. Existing components can be selected and moved through the existing reviewed bulk workflow.
- Drawer inventory links return to the selected drawer. Organizers and individual drawers support validated image uploads using workspace upload limits.
- Workspace totals form a compact top bar on inventory, hidden when viewing storage. Component details stay visible. Filters contain sorting, tags and specifications; internal drawer locations are omitted except the drawer currently being viewed. The trigger stays in place and opens with a short, reduced-motion-aware animation.
- Restocking includes zero stock and parts at/below a configured threshold. The zero-stock filter remains separate.
- Label Custom selection is explicit and reveals its editor without opening advanced layout. Batch selection, new projects and storage creation are directly visible.
- Print actions for inventory, project BOMs and drawer maps omit editing controls. Maps include all component names and quantities, including sections outside the on-screen scrolling area.
- Theme initialization runs before paint. Versioned assets are cached across visits; authenticated documents remain uncached. Inventory refreshes its results without reloading the page. Organizer contents use one batched component query instead of a query for every drawer.

Validation: full Python suite, focused supplier/return-path/photo/move tests, desktop/mobile browser workflows, dark theme and print previews. No external provider credentials or controller commands changed.
