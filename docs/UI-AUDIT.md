# PEHCHAAN UI audit

Date: 26 Sep 2026 · Method: heuristic review (priority rules §1–§10 and a pre-delivery checklist) applied to `frontend/src` (React 19 + Tailwind 4). Numbers below were measured from the code; contrast ratios are computed with the WCAG 2.2 formula.

Severity: **Critical** = blocks some users or breaks trust · **High** = visible inconsistency on most screens · **Medium** = polish · **Low** = nice to have.

---

## 1. Accessibility (Critical)

| # | Issue | Evidence | Fix |
|---|---|---|---|
| A1 | The most used "muted" grey fails contrast. | `#717785` is used 161 times: 4.49:1 on white, 4.06:1 on the `#f4f3f8` cards, 3.89:1 on the green verdict panel (needs 4.5:1). | Darken to about `#5d6370` (≥ 5.5:1 on all three). |
| A2 | Placeholder and "not read" greys are unreadable. | `#a0a4ad` 2.50:1; `#8a96a3` (photo-box labels) 3.01:1; `#94a3b8` on white 2.56:1. | Use ≥ `#6b7280` for any text meant to be read. |
| A3 | Dark screens use near-invisible secondary text. | `#3e4a5c` on `#141b28` is **1.92:1**; `#5a677d` on `#141b28` 3.02:1; login footer `#6b7a8e` 4.35:1. | Raise to ≥ `#a3aec0` on dark cards. |
| A4 | White text on the amber "REVIEW" bar fails. | `#ffffff` on `#c98a00` 2.95:1. | Use dark text (`#3d2600`) or a darker amber (`#8a5600`). |
| A5 | 87 Material icons are read aloud by screen readers. | 0 of 87 `material-symbols-outlined` spans have `aria-hidden`; a screen reader says "arrow_forward", "shield_lock"… | Add `aria-hidden="true"` to decorative icons (a shared `<Icon>` component does it once). |
| A6 | Icon-only buttons have no accessible name. | Only 8 `aria-label`s in the whole app; e.g. close ✕ buttons in NewScanView, ScreeningReportView and Sidebar, and the mobile menu toggle. | `aria-label` on every icon-only control. |
| A7 | Keyboard focus is removed and never replaced. | 14 `focus:outline-none/hidden`, only 1 `focus:ring`, 0 `focus-visible`. Tabbing through the app shows no focus position. | Global `:focus-visible` ring token; stop removing outlines. |
| A8 | Dialogs are not accessible dialogs. | 4 files use `fixed inset-0` overlays; only 1 has `role="dialog"`/`aria-modal`; **no** Escape handling anywhere; focus is not moved into or trapped in the dialog. | Shared `<Dialog>`: role, `aria-modal`, labelled title, Escape to close, focus trap, return focus. |
| A9 | Motion ignores the reduced-motion setting. | 7 `animate-pulse`, 1 `animate-ping`, 6 `animate-spin`; 0 `motion-reduce` / `prefers-reduced-motion`. The pinging "live" dots never stop. | `motion-reduce:animate-none`, and remove decorative infinite pings. |
| A10 | Colour is the only signal in places. | Sync status dots, "SIGNATURE OK" chips and the status dots on system-health tiles rely on red/green alone in several spots. | Always pair colour with text or an icon shape (most verdict chips already do). |

## 2. Touch & interaction (Critical)

| # | Issue | Evidence | Fix |
|---|---|---|---|
| T1 | Many controls are far below the 44 × 44 px target. | Header language `<select>` (`text-[11px] px-2 py-1`, about 22 px tall); table "View" buttons `px-2.5 py-1`; chips used as buttons on the Overview cards. | Minimum 40–44 px hit area on touch layouts (`min-h-11`), even if visually small. |
| T2 | Clickable table rows and cards are not buttons. | Overview rows use `onClick` on `<tr>` and on stat `<div>`s; they are not focusable or operable by keyboard. | Make the first cell a real `<button>`/link, or add `tabIndex`, a role and Enter handling. |
| T3 | Loading feedback is inconsistent. | New Scan shows staged progress; Audit Trail, Security and System Health show a bare "Loading…" string or nothing; the checkpoint screen used to show plain text. | One `<Spinner>`/skeleton pattern everywhere. |

## 3. Visual consistency (High)

| # | Issue | Evidence | Fix |
|---|---|---|---|
| V1 | **Two unrelated visual systems in one app.** | Shell, login, header, sidebar, bottom nav and 404 are dark navy (`#0c1017`/`#141b28`, Tailwind slate colours); every content screen is light lavender-grey (`#faf8fe`/`#f4f3f8`, Material-3 colours). The seams are visible at every page edge. | Pick one: a light app with a dark header only, or a full dark theme. Tokens for both. |
| V2 | **The theme tokens exist but are never used.** | `index.css` defines ~40 `@theme` colours (`--color-primary`, `--color-surface-*`…): **0 usages**. Components hard-code **157 distinct hex values**. | Replace hex literals with tokens (`bg-surface`, `text-on-surface-variant`, …). This fixes V1, V3 and A1 at the source. |
| V3 | The same meaning has different colours on different screens. | "Clear/green" appears as `#006a26`, `#008633`, `#00531d`, `#047857`, `#10b981`, `#22c55e`; "review/amber" as `#9e6200`, `#b45309`, `#8a5600`, `#c98a00`, `#7c4d00`. | Three semantic tokens per state (fg / bg / border) used by every verdict chip, bar and panel. |
| V4 | Two different blues for "primary". | Light screens use `#0059b5`; dark shell uses Tailwind blue `#2563eb`/`#60a5fa`; the login button is `#2563eb` while every in-app primary button is `#0059b5`. | One primary token. |
| V5 | Type scale is ad hoc. | 16 different arbitrary pixel sizes (`text-[10px]` ×94, `[11px]` ×99, `[10.5px]` ×12, `[7.5px]`, `[8px]`…) alongside 9 named sizes. Body text at 10–11 px is below the 12 px minimum. | A 5-step scale (12 / 14 / 16 / 20 / 24) and no body text under 12 px. |
| V6 | Page containers have different widths and gutters. | `max-w-[1400px]` (5 screens), `[1500px]` (Audit Trail), `[1720px]` (4 older screens), `[1920px]` (1); padding `p-6` vs `p-4 sm:p-6`. Content jumps sideways when switching pages. | One page container component. |
| V7 | Heading styles differ per screen. | Page titles are `text-xl` on new screens, `text-2xl` on Overview/Report, and uppercase tracked micro-headings on others; section titles mix UPPERCASE, Title Case and sentence case. | One title and one section-title style, in sentence case. |
| V8 | Stale or decorative status badges. | Header shows fixed "Face: OpenCV+ORB" and "Forensics: ELA/ORB" pills with pulsing dots. The face matcher is now SFace, and the pills are not connected to real status. | Remove them, or drive them from `/api/engine/health`. |
| V9 | Mixed card treatments. | Some cards use `shadow-2xs` + border, others border only, others filled `#f4f3f8`; radii `rounded-lg`/`xl`/`2xl` mixed on the same screen. | Card = border + `rounded-xl`, one elevation reserved for dialogs. |

## 4. Navigation (High)

| # | Issue | Evidence | Fix |
|---|---|---|---|
| N1 | Mobile bottom nav and sidebar disagree. | Sidebar labels are translated; bottom nav labels are hard-coded English ("Overview", "New Scan"…) and show a different set of items. | Build both from one nav config with `t()` labels. |
| N2 | No deep links or back button. | Screens are React state only; a refresh always returns to Overview and the browser back button leaves the app. A report cannot be linked or bookmarked. | Hash or router URLs (`#/report/SCN-…`). |
| N3 | Overlapping admin destinations. | "Admin Portal", "Officer Status", "System Health", "System Logs" and "Security & trust" overlap (users, logs and health appear in more than one). | Merge into Admin → Users / Activity / System / Security. |
| N4 | Report without a record. | "Screening Report" is always in the menu, but opens blank if no record is selected. | Hide it until a record is selected, or show the latest. |

## 5. Language (i18n) (High)

| # | Issue | Evidence | Fix |
|---|---|---|---|
| L1 | Hindi/Nepali stop at the navigation. | 14 of 23 components call `t()` zero times, including New Scan, Report, Audit Trail, Security, System Health, Officer Status and Admin Portal. Switching to हिन्दी changes the menu but not the working screens. | Move screen strings into the dictionary; English fallback per key. |
| L2 | Mixed-language labels. | Some screens show bilingual labels ("नाम / Name") and others English only, on the same page. | One rule: UI in the selected language; document field names follow the document. |

## 6. Forms & feedback (Medium)

| # | Issue | Evidence | Fix |
|---|---|---|---|
| F1 | Placeholder-only labels. | Audit search, the Security "Add a user" fields and the checkpoint form use placeholders as labels (screen-reader labels exist but are visually hidden). | Visible labels above inputs. |
| F2 | Errors appear far from the field. | Login and setup errors show at the top of the card; Security form errors show at the top of the tab. | Inline error under the field plus a summary. |
| F3 | Destructive actions without confirmation. | "Deactivate" and "Reset password" act immediately. | Confirm step with the consequence stated. |
| F4 | Success messages vanish or never appear. | Report decisions show a banner that stays forever; account actions show nothing. | Toast with a consistent 5 s timeout plus a persistent log entry. |

## 7. Content honesty (High, for a security product)

| # | Issue | Evidence | Fix |
|---|---|---|---|
| C1 | Old screens still present invented facts. | Admin Portal shows "All engines active" without checking; Remote Location Sync Bar shows signal and bandwidth pills that are not measured. | Show only measured values, or remove. |
| C2 | Legal pages. | Privacy/Terms are generic text not tied to DPDP Act practice (retention period, purpose, contact). | Update when retention and consent are final. |

## 8. Charts & data (Low)

| # | Issue | Evidence | Fix |
|---|---|---|---|
| D1 | Chart axis and legend text is 11 px grey. | Recharts ticks use `fill: #5b606b` at 11 px. | 12 px minimum, token colour. |
| D2 | No text alternative for charts. | The Analytics tab has charts only. | A small data table or summary sentence under each chart. |

---

## Done while auditing

- The **checkpoint selection screen is removed**. After sign-in the app reads the device location and picks the nearest checkpoint **among those assigned to the user** (the server decides; the browser's location cannot unlock other checkpoints). Every detection is written to the system log with its distance.
- **Fallbacks:** one assigned checkpoint → used automatically; location denied → assigned checkpoint; admin away from any checkpoint → global scope; no assignment → clear error.
- The header shows the checkpoint and how it was chosen, with **Re-detect** and a manual choice limited to the user's own checkpoints. It is also visible on phones now.
- Admins can store latitude, longitude and radius for each checkpoint (Security & trust → Users & checkpoints, including "Use my current location").
- `Permissions-Policy` now allows geolocation for the app's own origin; it was blocked before.
