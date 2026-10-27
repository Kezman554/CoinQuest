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
- **Gold means money and action.** The money card and the coin are `gold`; every "I've done it" / "Have another go" button is `action`. A finished chore shows a small gold coin with a tick. Nothing else is gold.
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
| `done` / `done-bg` / `done-edge` | `#1B6B2F` / `#DFF5E1` / `#23803A` | `#7EE59A` / `#1E3A33` / `#5BD27A` | finished chore, "All paid up", Put right |
| `waiting` / `waiting-bg` / `waiting-edge` | `#7E5100` / `#FFF1C7` / `#9A6300` | `#FFD66B` / `#2E2E45` / `#FFC93C` | claimed, waiting to be checked (dashed edge) |
| `danger` / `danger-bg` / `danger-edge` | `#A61B1B` / `#FFE3E1` / `#C62828` | `#FF9B93` / `#3A2338` / `#FF7A70` | missed, refusal tag, chores at risk, last-day notice |
| `today` / `on-today` | `#B8161A` / `#FFFFFF` | `#B8161A` / `#FFFFFF` | the TODAY tag |
| `today-edge` | `#B8161A` | `#FF5A52` | today's tile outline |
| `disabled` / `disabled-bg` / `disabled-edge` | `#2E4A63` / `#B9E2FC` / `#3B6688` | `#9AA4D6` / `#1F2849` / `#6370AC` | "This is the latest", and any control the state forbids |
| `settled` | `#E8E4D4` | `#343A55` | money card on a past week |

**Three tiers for warnings:** `danger` for missed chores, refused claims, chore money at risk and the last day; `waiting` for a claim nobody has checked yet; `gold`/`action` for offers. A caution never borrows `danger`.

## Contrast floors

Text needs 4.725:1 and non-text 3.15:1: 5% above the 4.5 and 3.0 floors. All 48 pairings drawn on the canvas pass in both modes. The tightest are `today-edge` on `ground` by day (3.92), `panel-edge` on `ground` at night (3.64) and `disabled-edge` on `ground` (3.61 by day, 3.37 at night). Check `waiting-edge` against `waiting-bg` by day (4.49) whenever either value moves.

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

The favicon is a gold coin with a raised star that has two eyes, our own drawing. Keep **two SVG sources** in one folder: `coin.svg` (the full coin with rim, inner ring, star and eyes, for 48px and up) and `coin-small.svg` (no rim; at 16px it also drops the eyes). Generate every PNG and the touch icon from them by script, and give the touch icon a `ground` background. One mid-tone works on light and dark browser tabs, so there's no per-mode icon. **Outlines are thin**: about 2 units on a 64-unit grid for the coin and 1.5 for the star.

## Enforcement

- **A literal check, run as an npm script:** no hex, `rgb(`, quoted font name or px radius outside the token block. It must cover CSS, TSX inline styles and SVG `rx`/`ry`. Prove it both ways by planting one literal of each kind.
- **A contrast script, run as an npm script**, that measures every pairing above in both modes against the floors, and fails on any colour token it doesn't measure or list as decoration.
- Both checks are success criteria on the first card, not rules.
