PDForge — Changelog

v1.0.0 — May 10, 2026 — Initial release
Core application structure, protocols, reference data, OneDrive sync, Mac packaging, rich-text notes, Firm/SiteFirm model, site popup, client list redesign.

v1.1.0 — May 15, 2026 — Reference data pages
Full CRUD pages: Products, Non-chemical means, Workers, Pests, Services, Tags. Template system — creating, saving, using protocol templates; folder structure.

v1.1.1 — May 17, 2026 — Bug fixes
Template search wasn't working — fixed. Saved templates weren't visible in the main template folder — fixed.

v1.2.0 — May 22, 2026 — Search, filtering and protocol UX
Case-insensitive search on the protocol page and client search bar in the protocol form. Arrow + Enter navigation for selecting from the client/site dropdown results; dropdown no longer closes on click before typing. Protocol preview opens on click on the protocol. Download popup shown on the download button, instead of rendering a full page with no back button. The second date on the protocol is empty by default; shown in the protocol list when set. Site tags are auto-applied when the site is selected in the protocol editor.

v1.3.0 — May 28, 2026 — Settings page + Mac packaging + OneDrive sync
Settings page (company info / personal data). Standalone PyInstaller .app build for Mac (no Homebrew dependency). OneDrive backup sync with a conflict warning when the remote database has changes not present in the local database.

v1.3.1 — June 2, 2026 — Fixes after first packaging of the app
Fixed issues with the seed database and separate databases created by packaging. run_app.py runs migrations on startup (automatic migration on launch).

v1.4.0 — June 10, 2026 — Major client & site UI overhaul
Copy/paste enabled throughout the app. Currency BGN → € across all price fields, list cards and the protocol editor. Redesigned print-selection page: format tabs (A5 / A5-landscape / A4) in a frozen top bar, print and back buttons repositioned, duplicate back button removed. Client dropdown in the protocol editor shows pseudonym instead of internal name. Phone removed from the client→protocol link; contact name field added instead. Redesigned client list: pseudonym as the primary line, company name as secondary, EIK repositioned, phone number row removed, first contact shown in the info grid. Inline "add new tag" from the protocol editor, site form, one-time treatments, and template forms. Sticky action bar in the protocol preview popup (buttons frozen at the top next to the back button, pseudonym shown instead of "New protocol").

v1.4.1 — June 15, 2026 — Contacts model
Unified contact model (client FK + sites M2M), replacing the originally planned ClientContact/SiteContact split. Full add/edit/delete/reorder UI for client-level and site-level contacts. Contacts UI in the protocol editor: staged rows in the new-client modal, checklist in the new-site modal. Same model extended to the standalone Client and Site creation forms.

v1.4.2 — June 17, 2026 — Protocol editor modal completion
Added tags and notes to the "New site" modal in the protocol editor (previously missing compared to the standalone site form). Fixed a modal height bug: the modal card now scrolls on short windows instead of overflowing off-screen.

v1.4.3 — June 18, 2026 — Rich-text notes: Clients and Sites
Shared rich-text widget with Cmd+B/I/U shortcuts, preserved line breaks, safe HTML storage. Applied to all client and site note fields, with formatted preview in list cards and tooltips. Data migration: existing plain-text notes converted to the new format.

v1.4.4 — June 19, 2026 — Rich-text notes: Products and non-chemical means
Same rich-text widget applied to the notes fields for products and non-chemical means. Data migration for existing records.

v1.4.5 — June 20, 2026 — Firm model and site-first protocol editor (major rework)
Standalone Firm model (reusable across multiple sites) + SiteFirm link with is_active / start_date / end_date per site. Site gets its own active/inactive toggle plus start/end dates (month+year only). Client active status derived from "has at least one active site". Protocol editor reworked to be site-first: pick a site, then the firm auto-fills from the site's active firm link. Month/year dropdowns replace the native month input on all date fields (fixes a silent form-reset bug in the Mac WebKit web view). Data migration linking existing records to the new structure.

v1.4.6 — June 21, 2026 — "Firms" page + Site popup
New top-level "Firms" nav page: flat list of all firm records with a linked-sites column. Site popup: status bar, full firm-link history per site, active/inactive toggle switch, delete per row, inline "+ Link firm" with tabs for searching existing firms or creating a new one. Nav entry renamed: old "Reference data → Firms" became "Personal data"; new "Firms" nav item added for client companies.

v1.4.7 — June 21, 2026 — Client form and site form improvements
Client popup removed; contacts and firm summary moved into the linear client edit form. Create/edit site form gained an optional section to pick or create a firm. Site editing switched to a full form (the client can now be reassigned when editing a site).

v1.4.8 — June 22, 2026 — Client list live update
Extracted each client's card into a reusable partial. Site and contact save/edit/delete responses now include an out-of-band swap of the client card — the client list reflects changes immediately, no manual page reload needed.

v1.4.9 — June 22, 2026 — "Firms" page: edit, delete, search
Edit and delete buttons added to the "Firms" page (previously view-only). Name + EIK search field, case-insensitive. Soft delete: deleted firms disappear from lists and search pickers, but don't break existing links to sites or printed protocols (which snapshot the firm's data at creation time).

v1.4.10 — June 23, 2026 — Rich-text notes: Protocols and one-time treatments
Rich-text widget applied to the protocol editor's notes field and One-time Treatments notes. Preview-mode lock in the protocol editor extended to cover the new rich-text field. Data migration for existing protocol and one-time-treatment notes.

v1.4.11 — June 24, 2026 — Template comment cleanup
Removed all Django template comments across the whole app (visual clutter in the code).

v1.4.12 — June 25, 2026 — Minor polish
Minor layout and spacing improvements on several pages.

v1.4.13 — June 27, 2026 — Bug fixes
Client edit — "Save" button wasn't working; also, adding a second contact to a client overwrote its name — fixed. One-time treatments — price field showed empty when reopening an existing treatment for editing — now restores correctly. Save as template — creating a new protocol, saving it as a template, then saving it as a protocol silently deleted the template — both are now saved as separate records. Back to editor from preview — "← Back to editing" opened an empty editor; now returns with all data intact.

v1.4.14 — June 29, 2026 — Bug fixes
One-time treatments — decimal comma in the price field prevented saving changes to existing treatments — fixed. Firm deletion — deleting a firm now unlinks it from all associated sites and no longer blocks creating a new firm with an identical EIK.

v1.4.15 — July 6, 2026 — Protocol column width fix
Fixed a rendering mismatch where table columns in the protocol preview (especially the empty Disinfection column) could stretch wider than they appear in the actual printed/exported PDF. Column widths are now fixed to match the actual printed protocol exactly, so what's shown in the preview now matches what gets printed.

v1.5.0 — July 11, 2026 — VAT pricing, template folder picker, date/UX fixes

VAT pricing
- Added an optional "price with VAT" field next to the existing net price, with a toggle — editing either price recalculates the other automatically.
- The VAT percentage is a configurable setting (Settings page); the rate used is frozen onto each protocol/treatment at the time it's set, so later changes to the setting don't retroactively change already-saved prices.
- Available on both protocols and one-time treatments.

Tag styling
- One-time treatment tags now show their real assigned color when unselected, instead of being dimmed to near-illegibility.
- Protocol editor tags match the same styling.
- The tags section on the one-time treatment form was widened to span the full form.

Bug fixes
- Fixed the protocol preview rendering blank when opening an existing protocol (a locale-formatting bug was breaking the page's JavaScript).
- Fixed empty price fields showing the literal word "None" instead of being blank.

Protocol data integrity
- Protocol company/executor and firm data is no longer silently overwritten every time a protocol is re-saved — it's frozen at creation now, with an explicit "⟳ Обнови данни за фирма" button to refresh it on purpose.

Save as template
- Added folder search — shows the folder hierarchy above nested matches, with matches highlighted.
- Added the ability to create new folders directly from the save dialog.
- Unified the two separate versions of this dialog (opened from an already-saved protocol vs. from the create/edit flow) into one.

Folder creation
- New folders — from the Templates page or the save-as-template dialog — now default to the folder you're currently browsing, instead of always to the root.

Dates
- Site start/end dates and firm start dates now accept any typed year, instead of being limited to a small fixed dropdown range.

v1.5.1 — July 12, 2026 — Customer feedback: pest filters, client search, site-creation client picker, preview/print reference

Pest filtering
- Added filterable "other pest" chips to protocols and one-time treatments — free-typed pest text is split into individual, capitalized filter chips.
- Protocol PDFs still render the raw typed text unchanged; the split only affects filtering and display.
- Filter menus auto-refresh on create/edit/delete, no manual reload needed.

Client search
- Cleaned up legacy client search code (stale placeholder, dead JS reference).
- One-time treatment search is now case-insensitive for Cyrillic, matching search elsewhere in the app.

Site-creation client picker
- Replaced the plain client dropdown on site creation with the same type-to-filter search used in the protocol editor.
- Applied in both the protocol editor's "+ Site" modal and the standalone site form.
- Both now support creating a new client inline — with notes and staged contacts — without leaving the flow.

Preview/print reference (Settings)
- Added a new Settings section documenting every preview/print button's exact behavior.
- Calls out effects not obvious from the button name: delete is a soft-delete (record stays in the database, not recoverable from the app); "save as template" saves only to templates, not to protocols, so the protocol itself still needs a separate save; printing from the in-editor preview on the packaged Mac app silently saves the draft first, same as "Save protocol".
