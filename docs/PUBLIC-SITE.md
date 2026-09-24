# Public site, feedback, and project purchasing

Platform administrators can open **Public site settings** from the gear icon → Settings to edit the About name, biography, AI section heading and text, no-paywall promise, Terms of Service, privacy information, and optional Stripe Payment Link. These settings are stored on the server and survive code updates.

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

## Visitor analytics

The platform-only Analytics page includes live website and demo browser counts, plus demo visits today, over 30 days, and since tracking began. Live counts use visible-page heartbeats every 30 seconds with a two-minute activity window. Demo is a subset of the website total. A demo visit includes viewing the demo landing page or exploring the demo; it counts once until the browser has been away from demo activity for 30 minutes. Multiple tabs sharing a session are deduplicated. Counts start when this version is installed, not retroactively.

These are approximate sessions, not unique identified people: separate browsers, devices, cleared cookies, and sign-in transitions can create separate sessions. Background tabs stop reporting, so abandoned pages age out. JavaScript blockers and browser privacy settings may reduce counts. Platform administrators, Do Not Track, and Global Privacy Control are excluded. An anonymous random identifier is kept in the existing signed session cookie; visitor records contain no account, email, or raw IP. Activity rows older than a day are pruned during subsequent pulses; daily aggregate demo totals are retained. The admin cards refresh every 15 seconds while visible.

## Page customization

The HTML and app template editors have been removed. Legacy overrides remain in the database for recovery but are no longer applied. Edit supported public text in Settings → Public site settings; application layout changes use the Git repository and Python updater.

## Stripe buy button and thank-you page

The supplied Stripe Buy Button is embedded on both `/welcome` and `/support`. Manage its button ID and **publishable** key in Public site settings. Never enter a secret key. Clear both fields to disable the widget. Stripe JavaScript and frames are permitted on the public pages that embed it; authenticated application pages retain their existing script policy. The Buy Button opens Stripe-hosted checkout; it is not an embedded credit-card entry form. A full embedded Checkout integration is a different Stripe integration requiring server-side credentials.

Set the Payment Link's **After payment → Redirect** URL in Stripe to:

`https://partshelf.pcb-studios.com/donation/thank-you`

The thank-you page is public and excluded from search indexing. It never treats URL parameters or a visit as payment verification. Payment records and receipts remain in Stripe. No payment is submitted during development checks.

## Personal appearance and navigation

The gear icon opens Settings. Each account can choose Partshelf blue (default), Forest green, Violet, Warm amber, or Slate; every palette works in light and dark mode. Sidebar items can be reordered with the arrow buttons, hidden, or restored. The Donate button is optional and appears below navigation. These preferences are stored per user on the server. Light/dark mode remains a browser preference. Sign out is in Settings.

## Feedback management and email

The feedback inbox can move requests to Trash and restore them. A roadmap action lets the administrator review a public title, description and status before publishing; private feedback text and email addresses are not automatically copied. It links the request to the roadmap item and sends the update to confirmed, subscribed submitters, using the existing retry control if delivery fails. Duplicate submissions are rejected.

Business email includes a branded HTML version and a plain-text alternative. Feedback and low-stock emails use signed unsubscribe links that immediately disable their respective subscriptions when opened, then show a confirmation page. A mail client or scanner that opens links can therefore trigger unsubscribing; no further confirmation is required. Unsubscribe links expire after one year. Changing an account email requires recent authentication and verification of the new address; the original address remains until verification succeeds.
