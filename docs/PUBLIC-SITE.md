# Public site, feedback, and project purchasing

Platform administrators can open **Public site settings** from the sidebar to edit the About name, biography, AI section heading and text, Terms of Service, privacy information, and optional Stripe Payment Link. These settings are stored on the server and survive code updates.

## Voluntary donations

Create a Payment Link in your own Stripe account and paste its public `https://buy.stripe.com/...` or `https://donate.stripe.com/...` URL into Public site settings. No Stripe API key is needed. Until a link is saved, the donation page explains that online contributions are not enabled. The no-paywall promise remains visible regardless of whether contributions are enabled. Stripe handles checkout; Partshelf does not store card information or track individual payments.

## Feedback

The public `/feedback` form accepts feature requests, feedback, and bug reports. Email is optional. People who request updates must confirm their email within 48 hours. The administrator's **Feedback inbox** supports New, Reviewing, Planned, In progress, Released, and Not planned statuses, with an optional update message. Saving a changed status/message sends an update to confirmed subscribers using the existing business SMTP configuration. Failed delivery offers a retry. Each update links to unsubscribe. Feedback and contact addresses are never listed publicly.

## Public pages and Google

`/welcome`, `/about`, `/support`, `/feedback`, `/terms`, and `/privacy` are public. The sitemap is at `/sitemap.xml`; robots instructions are at `/robots.txt`. Public canonical URLs use `PUBLIC_URL`, so configure it as the primary HTTPS domain. Private inventory, account, management, and demo pages are marked noindex. The public landing page includes structured data and sharing metadata.

Submit the sitemap URL in Google Search Console using a verified property covering the primary domain. An optional HTML verification token can be saved in Public site settings if needed. Google decides whether and when to index pages and how to rank them; these settings do not guarantee a search position.

The initial Terms and privacy text are editable drafts for PCBStudios in Minnesota. Review them against your actual business practices and obtain legal review before relying on them as final legal documents. Update the effective date and communicate material changes when editing terms.

## Project pack costs

Each component has a **Purchase pack size** independent of original purchase quantity and current stock. Set it to the supplier's required purchase increment (for example, 100 resistors). Existing components default to one unit until edited.

Projects show the cost of exact missing units and the cost after rounding each shortage up to whole packs. At $0.02 per resistor, a shortage of 32 costs $0.64 in exact units, but a 100-piece pack costs $2.00. Estimates use the saved unit price and exclude shipping, tax, supplier discounts, and changing prices.

Click an existing needed quantity to edit it; zero removes it. Use inventory-style filters below the bill of materials to find and set quantities. A component's detail page can also add it to a project, increasing an existing quantity if already present. Planning does not reserve inventory.

## Editable roadmap

Open **Public site settings → Edit roadmap** (or the sidebar link). Add a title, description, status, display order, and publication checkbox. Status columns are Planned, In progress, and Released. Lower display-order numbers appear first. Uncheck publication to remove an item from the public page while keeping it available for later editing. The public `/roadmap` page is linked in the footer and included in the sitemap. No future features are promised or seeded automatically.

## Public HTML editor

Open **Public site settings → Edit public page HTML**. The editor supports Welcome, About, Donations, Terms, and Privacy main content. It starts with the current default HTML, supports preview before publication, and provides Restore default content. Scripts, forms, inline styles, embedded pages, image tags, event handlers, and template execution are excluded. Headings, paragraphs, links, lists, tables, and existing site CSS classes are supported. The header, footer, and authenticated app workflows are not replaced.

Custom HTML takes precedence over the corresponding plain-text settings. For example, after customizing About HTML, edits to the biography or AI text settings will not affect that page until default content is restored. Similarly, a custom Donations page must have its Stripe link updated in the HTML. Updates preserve overrides in the database; restoring defaults uses the latest shipped layout and current settings.

## Visitor analytics

The platform-only Analytics page includes live website and demo browser counts, plus demo visits today, over 30 days, and since tracking began. Live counts use visible-page heartbeats every 30 seconds with a two-minute activity window. Demo is a subset of the website total. A demo visit includes viewing the demo landing page or exploring the demo; it counts once until the browser has been away from demo activity for 30 minutes. Multiple tabs sharing a session are deduplicated. Counts start when this version is installed, not retroactively.

These are approximate sessions, not unique identified people: separate browsers, devices, cleared cookies, and sign-in transitions can create separate sessions. Background tabs stop reporting, so abandoned pages age out. JavaScript blockers and browser privacy settings may reduce counts. Platform administrators, Do Not Track, and Global Privacy Control are excluded. An anonymous random identifier is kept in the existing signed session cookie; visitor records contain no account, email, or raw IP. Activity rows older than a day are pruned during subsequent pulses; daily aggregate demo totals are retained. The admin cards refresh every 15 seconds while visible.
