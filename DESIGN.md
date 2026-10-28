# DESIGN — CoinQuest

The child's week is a chore chart on a kitchen wall, read by a nine-year-old from across the room and tapped standing up. Its look is **Coin block**: a bright platform game, where chores turn into gold coins. The child chose it from four directions on 27 Oct 2026.

**This document doesn't settle the palette.** Every value below came from the design canvas and passed a contrast script. The values stay provisional until they've been judged on the kitchen panel (10", 1280×800), which hasn't been bought yet. Until then, judge on the laptop at 1280×800.

## Conditions of use

- **Primary surface:** the kitchen touch panel, 1280×800, landscape, shown full screen. A phone (390 wide) and 1920×1080 must keep working, but they are secondary.
- **Distance and attention:** glanced at from across the room, and tapped at arm's length for a few seconds at a time. Nothing should be read twice to be understood.
- **The element looked at most** is the "On track for" figure. Next come the gold "I've done it" buttons.
- **Day and night:** the wall is on all evening, so both modes are first-class (see Modes).

## The look, as rules

- **Typefaces:** Lilita One for display text (the title, day names, money figures, section headings). Nunito 600/700/800 for everything else. Bundle both with `@fontsource`; never fetch from a URL.
- **Geometry:** every card and control has a solid outline in the `outline` role, 3px on cards and buttons and 2px on small tags. Corner radius is 14px on cards, 12px on buttons and 8–10px on tags.
- **Shadows are hard and offset:** `0 4px 0` on buttons and `0 5px 0` on cards, in the `shadow` role. Never a blurred or soft shadow.
- **Gold means money and action.** The money card and the coin are `gold`; every "I've done it" / "Have another go" button, and the child's own "Add it" on Savings, is `action`. A finished chore shows a small gold coin with a tick. Nothing else is gold.
- **Every screen wears it.** Savings, Lifetime, the parent view and the PIN dialog use the same outlines, hard shadows, radii and typefaces as the week, with the brick strip under them.
- **A parent's buttons are never gold.** A confirming act (confirm, settle, pay, record) is `raised` with a `control-edge` outline. A destructive or money-removing one (refuse, void, reopen, mark missed, a withdrawal, retire) is `raised` with a `danger-edge` outline and `danger` words, and so is its PIN dialog's button. A caution ("This cannot be undone") is `waiting`'s, never `danger`'s.
- **A forbidden control stays and says why.** It keeps its place in the `disabled` roles, with the reason in a line beside it that the button names (`aria-describedby`). It is never hidden for being unusable.
- **The ground is the sky**, with a brick strip 24px tall along the bottom edge (`brick`, with `mortar` joints). The strip is decoration and carries nothing.
- **Past weeks lose the shine.** On a settled or voided week paged back to, the money card is `settled`, the coin is muted, and nothing has a shadow, so nothing looks tappable.
- **State is never colour alone.** Every state has its word ("Done", "Waiting to be checked", "Missed", "Not accepted last time"). Done adds the coin tick, waiting uses a dashed edge, and the last-day notice adds an alarm-clock icon.

## Prohibitions

- No gradient washes. The current purple-to-coral gradient on the money card goes.
- No `system-ui`, no stock indigo, and no Vite favicon.
- No translucent fills behind coloured text. Every tint in this document is opaque.
- **No Nintendo artwork, sprites, logos or typefaces.** The repo is public. The coin, the star and the bricks are our own drawings in the spirit of a platform game.
- No hex, `rgb()`, font name or px radius outside the token block (see Enforcement).

## Token roles

The values are provisional (see the top of this document). Day is light and night is dark.

| Role | Day | Night | Used for |
|---|---|---|---|
| `ground` | `#8CCFFA` | `#18203F` | page background (sky) |
| `brick` / `mortar` | `#C2602A` / `#8A3E14` | `#7A3A1A` / `#4A220C` | bottom strip, decoration only |
| `panel` | `#FFFFFF` | `#242D57` | day tiles, owed card, any-time card |
| `panel-today` | `#FFF6D6` | `#2F2F5E` | today's tile |
| `raised` | `#FFFFFF` | `#2A3463` | neutral buttons (week arrows, Savings, Lifetime, Parent, sun/moon) |
| `ink` | `#1E1B3A` | `#F2F4FF` | text |
| `ink-soft` | `#4A4766` | `#C9D2FF` | dates and secondary text |
| `outline` | `#1E1B3A` | `#0A0D1C` | outlines on gold and action fills |
| `panel-edge` | `#1E1B3A` | `#6674BC` | outline of panels |
| `control-edge` | `#1E1B3A` | `#8E9BE0` | outline of neutral buttons |
| `shadow` | `#1E1B3A` | `#0A0D1C` | hard offset shadows |
| `gold` / `on-gold` | `#FFC93C` / `#1E1B3A` | same | money card, coin, bonus tag |
| `coin-light` / `coin-dark` | `#FFE27A` / `#C98A00` | same | coin face and inner ring (decoration) |
| `action` / `on-action` | `#FFD54A` / `#1E1B3A` | same | "I've done it", "Have another go" |
| `on-gold-chip` / `on-gold-chip-ink` / `on-gold-chip-ink-soft` / `on-gold-chip-edge` | `#FFFFFF` / `#1E1B3A` / `#4A4766` / `#1E1B3A` | same | chips, the make-good box and the notice frame on the money card, and the coin's outline: the gold card keeps its day look at night, so what is on it does too |
| `on-gold-done` / `on-gold-done-bg` / `on-gold-done-edge` | `#1B6B2F` / `#DFF5E1` / `#23803A` | same | the Chores chip once won, a put-right notice, on the money card |
| `on-gold-danger` / `on-gold-danger-bg` / `on-gold-danger-edge` | `#A61B1B` / `#FFE3E1` / `#C62828` | same | the Chores chip at risk, the missed-chore notice, on the money card |
| `done` / `done-bg` / `done-edge` | `#1B6B2F` / `#DFF5E1` / `#23803A` | `#7EE59A` / `#1E3A33` / `#5BD27A` | finished chore, "All paid up", Put right |
| `waiting` / `waiting-bg` / `waiting-edge` | `#7E5100` / `#FFF1C7` / `#9A6300` | `#FFD66B` / `#2E2E45` / `#FFC93C` | claimed, waiting to be checked (dashed edge) |
| `danger` / `danger-bg` / `danger-edge` | `#A61B1B` / `#FFE3E1` / `#C62828` | `#FF9B93` / `#3A2338` / `#FF7A70` | missed, refusal tag, chores at risk, last-day notice |
| `today` / `on-today` | `#B8161A` / `#FFFFFF` | `#FF5A52` / `#1E1B3A` | the TODAY tag |
| `today-edge` | `#B8161A` | `#FF5A52` | today's tile outline |
| `disabled` / `disabled-bg` / `disabled-edge` | `#2E4A63` / `#B9E2FC` / `#3B6688` | `#9AA4D6` / `#1F2849` / `#6370AC` | "This is the latest", and any control the state forbids |
| `settled` | `#E8E4D4` | `#343A55` | money card on a past week |

**Three tiers for warnings:** `danger` for missed chores, refused claims, chore money at risk and the last day; `waiting` for a claim nobody has checked yet; `gold`/`action` for offers. A caution never borrows `danger`.

## Contrast floors

Text needs 4.725:1 and non-text 3.15:1: 5% above the 4.5 and 3.0 floors. `npm run check:contrast` measures exactly the 57 pairings below, in both modes, and every one passes. The tightest are `today-edge` on `ground` by day (3.92), `panel-edge` on `ground` at night (3.64), `disabled-edge` on `ground` (3.61 by day, 3.37 at night) `today` on `panel-today` at night (4.05) and the won Chores chip's edge on `gold` (3.24, both modes). Check `waiting-edge` against `waiting-bg` by day (4.49) whenever either value moves.

A component is measured against the surface it sits on, and its fill or its outline may carry the boundary (WCAG 1.4.11): the gold card is told apart from the sky by its outline, not its gold. An outline is never measured against its own fill, because that isn't what makes a shape visible.

**Text (4.725:1), words on their fill:**
- `ink` on `ground`, `panel`, `panel-today`, `raised` and `settled`
- `ink-soft` on `ground`, `panel`, `panel-today` and `raised`
- `on-gold` on `gold`, `on-action` on `action`, `on-today` on `today`
- `done` on `done-bg`, and on `panel` ("All paid up")
- `waiting` on `waiting-bg`, `danger` on `danger-bg`, `disabled` on `disabled-bg`
- on the money card, fixed in both modes: `on-gold-chip-ink` and `on-gold-chip-ink-soft` on `on-gold-chip`, `on-gold-done` on `on-gold-done-bg`, `on-gold-danger` on `on-gold-danger-bg`
- on the other screens: `danger` on `raised` (a destructive button) and on `panel` (an error, the reopen heading), `waiting` on `panel` (a reconciliation that disagrees), `ink-soft` on `settled` (a retired chore)

**Named non-text pairings (3.15:1), measured exactly as named:**
- `today` on `panel-today` (the TODAY pill)
- `today-edge` on `ground`, `panel-edge` on `ground`, `disabled-edge` on `ground`
- `waiting-edge` on `waiting-bg` (the dashed edge)
- the lifetime chart, on its `panel`: `ink` (the real balance), `done` (if nothing had been withdrawn, dashed as well), `ink-soft` (the baseline)

**Boundaries (3.15:1), a component on its surface, by the better of fill and edge:**
- on `ground`: a panel (`panel`/`panel-edge`), today's tile (`panel-today`/`today-edge`), the money card (`gold`/`outline`), a neutral button (`raised`/`control-edge`), a disabled control (`disabled-bg`/`disabled-edge`)
- on `panel`: the savings match amount on the owed card (`gold`/`outline`), a neutral button (`raised`/`control-edge`), "I've done it" (`action`/`outline`), a done chore (`done-bg`/`done-edge`), a waiting chore (`waiting-bg`/`waiting-edge`), a missed chore (`danger-bg`/`danger-edge`), the savings bar (`done-edge`)
- on `panel-today`: "I've done it" (`action`/`outline`)
- on `danger-bg`: "Not missed after all" (`raised`/`danger-edge`), inside a missed chore
- on the other screens: a destructive button on `panel` (`raised`/`danger-edge`); Yes and No on a ruled queue row (`raised`/`control-edge` and `raised`/`danger-edge` on `done-bg`, `raised`/`control-edge` on `danger-bg`), a chosen Yes (`raised`/`done-edge` on `done-bg`); the waiting count on a tab (`waiting-bg`/`waiting-edge` on `raised`); chore money at risk as a figure (`danger-bg`/`danger-edge` on `panel`)
- on `gold`: a chip or the make-good box (`on-gold-chip`/`on-gold-chip-edge`), the won Chores chip (`on-gold-done-bg`/`on-gold-done-edge`), the at-risk chip and the notice (`on-gold-danger-bg`/`on-gold-danger-edge`)

**Decoration, not measured:** `brick` and `mortar` (the bottom strip), `coin-light` and `coin-dark` (the coin's face and ring), and `shadow` (a depth cue under shapes whose boundaries are measured). Any other colour token that is neither measured nor listed here fails the check.

## Modes

- **The clock decides, and a sun/moon button overrides.** Night runs from 19:00 to 07:00, Europe/London (provisional times, kept in one constant). The sun/moon button sits in the title row. Pressing it flips the mode until the next scheduled switch, when the clock takes over again.
- **The override lives in the browser** (`localStorage`). It touches no database, so the restyle can be rolled back without a migration.
- The device's own `prefers-color-scheme` no longer decides; the clock does, on every surface.
- Apply the mode before first paint, so the wall never flashes the wrong one.

## Layout

The 1280×800 wall layout from `91d155f` stays: the title row with its buttons, the money strip, seven day columns, the any-time row, and only the days region scrolling. The makeover changes only these:

- **The missed-chore notice moves inside the money card**, beside the make-good line, instead of taking a full-width row above it. On the last day it gains the alarm-clock icon and the `danger` edge.
- **The days region gets a soft fade at its bottom edge** whenever it can scroll, so the wall shows there's more.
- **The sun/moon button joins the title row**: 46px square, a `raised` fill and a `control-edge` outline.
- **Size budget:** the 1280×800 fit test with three chores, the at-risk note, a make-good line and two owed weeks must still pass. The chore button keeps a minimum height of 60px. **Set `html { font-size: 16px }`** so 1rem means what it says, and express sizes as tokens.

**Type sizes** (provisional, judged at 1280): title 40px, day names 22px, money figure 52px, owed figure 40px, chore names 15px/700, button labels 16px/800, dates 14px/700. If chore names read too small from across the kitchen, raise them before anything else.

## Icon

The favicon is a gold coin with a raised star that has two eyes, our own drawing. Keep **three SVG sources** in one folder: `coin.svg` (the full coin with rim, inner ring, star and eyes, for 48px and up), `coin-32.svg` (no rim, with the eyes, for 32px and the SVG favicon) and `coin-small.svg` (no rim and no eyes, for 16px, where eyes would be a single grey pixel). Generate every PNG and the touch icon from them by script, and give the touch icon a `ground` background. One mid-tone works on light and dark browser tabs, so there's no per-mode icon. **Outlines are thin**: about 2 units on a 64-unit grid for the coin and 1.5 for the star.

## Enforcement

- **A literal check, run as an npm script:** no hex, `rgb(`, quoted font name or px radius outside the token block. It must cover CSS, TSX inline styles and SVG `rx`/`ry`. Prove it both ways by planting one literal of each kind.
- **A contrast script, run as an npm script**, that measures every pairing above in both modes against the floors, and fails on any colour token it doesn't measure or list as decoration.
- Both checks are success criteria on the first card, not rules.
