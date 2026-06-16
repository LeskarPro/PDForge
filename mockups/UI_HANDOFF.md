# UI Handoff Prompt — PDForge (ДДД protocol system)

> Paste this whole file into a new chat to continue the work with full context.
> It is written as a brief to you (Claude). Read it, then wait for the user's next instruction.

---

## Your role

You are helping **Kiril** design and build the management interface for **PDForge**, a Django web app that produces and manages **DDD protocols** (ДДД = Дезинфекция / Дезинсекция / Дератизация — disinfection, disinsection, deratization; i.e. pest-control treatment records) for a Bulgarian pest-control business. The UI language is **Bulgarian**.

Right now the app only renders the printable protocol as a PDF. We are designing the surrounding **web management interface** (the app "shell" + its screens) from scratch. We are still at the **visual-design / mockup stage**, not final implementation.

---

## How Kiril wants to work (process rules — important)

1. **One preview per iteration.** Each round, produce exactly **one** HTML preview, then stop and wait for feedback. Do not build multiple variants.
2. **Agree on the main view first.** Lock the app shell (nav + colors + layout) before building anything else.
3. **Every menu's inner content is discussed separately.** Kiril wants full control over what each screen displays. Do not design screen internals until asked.
4. **Do not proceed to the "7b setup"** (a later implementation phase Kiril referred to) until he explicitly confirms he's happy with the interface and style. Always wait for his approval before moving on.
5. Deliver previews as a **standalone HTML file** saved to the workspace (`/Users/leskarpro/PycharmProjects/PDForge/mockups/`) and present it — full browser width is needed to evaluate the dark sidebar + dashboard. Do **not** use the inline chat widget for this (its design system fights the custom brand palette and is too narrow).

---

## The project (codebase facts)

- **Location:** `/Users/leskarpro/PycharmProjects/PDForge` (Django project, app is `core`).
- **Current behavior:** `core/views.py` → `protocol_pdf()` renders `templates/protocol/protocol.html` to PDF via **WeasyPrint**. Templates: `base.html`, `protocol.html`, `_protocol_front.html`, `_protocol_back.html`, `protocol_old.html`. Admin in `core/admin.py`. DB is SQLite (`db.sqlite3`).
- **The protocol itself** is a structured table: numbered rows (1–14) × **three service columns** — Дезинсекция, Дератизация, Дезинфекция. Front + back A5 panels. (Reference images existed as `mf_page-1.png` / `mf_page-2.png`.)

### Domain models (`core/models.py`)
- `Client` (Клиент) — firm, name, EIK, address, phone, notes.
- `Company` (Фирма изпълнител) — the executor company printed in the header; one is default; logo + slogan; text identity is **snapshotted** onto each protocol.
- `Site` (Обект) — building belonging to a Client; area, tags.
- `Product` (Препарат) — biocide; category (disinsection/deratization/disinfection), authorization no., active substances, working solution, safety, bait descriptor, etc.
- `Pest` (Вредител / спектър) — row 1 targets, per category.
- `NonChemicalMean` (Нехимично средство) — traps, lamps (row 5).
- `Tag` (Етикет) — colored labels for sites/protocols.
- `Worker` (Работник) — field operators; defaults for "Подготвил"/"Изпълнил".
- `Protocol` (Протокол) — central record: client, site, company snapshot, date/time, prepared_by/executed_by, long-term-contract flag, **preset machinery** (`is_preset`, `preset_name`), notes, tags. Has `columns` (ProtocolColumn) per service.
- `ProtocolColumn` — one service column; pests, treated area, surface, treatment methods, non-chemical means, products, recommendations, corrections, `is_active`.
- `ProtocolProduct` — product used in a column, with a frozen snapshot of the product's fields.

---

## Agreed design decisions

### Color palette (current, replaces an earlier rejected one)
| Hex | Name | Use |
|-----|------|-----|
| `#fec196` | peach | light highlights, soft fills |
| `#ffa686` | coral | **primary accent** — active nav bar, primary button, key chart color |
| `#d6a184` | clay | secondary chart color |
| `#aa767c` | mauve | secondary accent / chart color |
| `#63474d` | plum (darkest) | **sidebar background** |

Derived shades in use: `#4a343a` (darker band for company-name header), `#74565c` (nav hover), `#83626a` (nav active fill), `#7d5f66` (subtle version text), content bg `#f6efe9`, card bg `#fff`, ink `#3d2b2f`.

### Left sidebar / nav (top → bottom)
1. **Company-name header** — bigger (≈20px bold), in a **darker band** (`#4a343a`) with a logo mark, visually differentiated from the nav items.
2. **Табло (Dashboard)** — at the very top, above all pages. *This is the active/default page.*
3. **Протоколи (Protocols)**
4. **Шаблони (Templates)** — its own nav button placed **directly under Протоколи** (indented to show the relationship). Will hold presets + a search option.
5. **Справки (Reports/Analytics)** — detailed charts with filtering, customization, export.
6. *— separator (labelled "Управление") —*
7. **Справочници (Reference catalogs)** — at the bottom under the separator. **Foldable**, expands to: Клиенти, Обекти, Препарати, Вредители, Нехимични средства, Работници, Фирми изпълнители, Етикети.
8. **База данни (Database management)** — near Настройки/Справочници. **Foldable**: Архивиране сега / Възстановяване / График на архивиране (scheduled backup time) / Експорт-Импорт.
9. **Настройки (Settings)**
10. **Version** pinned at the very bottom — small, low-contrast (`#7d5f66`, barely-there but legible).

### Interactivity / features
- **Foldable lists** in some menus (demonstrated on Справочници + База данни) — part of keeping interactivity moderate.
- **Dashboard (Табло):** general overview with KPI cards + charts (protocols-by-month, services-by-type donut, top clients, recent protocols). Справки will show the same data in more depth with filters/customization/export.
- **"Create new protocol"** should open an editor that **looks close to the actual protocol layout**, where the user selects/fills cells directly (more interactivity). Templates can still drive it; moderate interactivity is acceptable.
- **База данни:** proper backup setup including a configurable scheduled backup time.
- More visualizations are likely in the future — keep that door open.

### Tech-stack decision (agreed direction)
Stay **server-rendered Django templates + HTMX + Alpine.js + a JS chart lib (Chart.js, or ECharts later for richer exports)**. HTMX handles foldables, live filters, inline cell-select/fill, row swaps by swapping server-rendered fragments; Alpine covers tiny client-only toggles. One codebase, one deploy, WeasyPrint PDF pipeline unchanged. If a single screen ever needs heavy client interactivity (e.g. drag-and-drop protocol designer), mount a **React "island"** on just that page — no full SPA rewrite.

---

## Status & what's been built

- **Done:** main-view preview at `/Users/leskarpro/PycharmProjects/PDForge/mockups/main-view-v2.html` — dark plum sidebar, new palette, full nav order above, foldable Справочници/База данни, subtle version, and a Dashboard page (4 KPI cards + 3 live Chart.js charts + recent-protocols table). Awaiting Kiril's feedback.
- **Pending Kiril's approval** of the interface/style before moving to the "7b setup" / implementation.
- **Not yet designed:** internals of each screen (Протоколи list, Шаблони, Справки, Справочници sub-pages, База данни, Настройки) and the interactive protocol editor — all to be done one at a time, on request.

## Suggested next step
Wait for Kiril. He will either request tweaks to the main view (another iteration is expected) or approve it. Only after approval do we discuss individual screens and/or the "7b setup". Keep producing **one preview at a time**.
