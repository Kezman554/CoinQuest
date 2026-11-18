# Every input, and what it does at the wall (Session AS)

The wall is the kitchen panel: 1280×800, touch, Chromium in kiosk mode on the
hub Pi, no physical keyboard and no on-screen keyboard. Decisions (18 Nov 2026):

- **PINs and amounts** get CoinQuest's own numeric keypad at the wall.
- **Text** stays a laptop or phone job. At the wall the field keeps its place,
  disabled, with a one-line reason.
- No system-wide on-screen keyboard (a separate, open question for the wall).

And for the inputs that did not fit those cleanly, decided when asked:

- **The child's "Add money you got another way"** works at the wall: the amount
  by keypad, and where it came from tapped from a list instead of typed. The
  label tapped is stored as the note, exactly as if typed. Laptops and phones
  keep the free-text field. The list lives in one place,
  `MONEY_SOURCES` in `frontend/src/wall.ts`: **Birthday, Christmas, Gift from
  family, Sold something, Other.**
- **Record a reward, Record a deposit, Log a withdrawal** need words the server
  requires, so they are laptop or phone only at the wall: the amount *and* the
  words are disabled, with the one reason "Use the laptop or a phone.", so
  nobody keys in an amount the screen cannot then send.
- **Times a week** takes the keypad in whole numbers (no point). Editing a
  chore at the wall works: its name stays as it is, disabled, and the numbers
  change by keypad. **A new chore** needs a typed name, so at the wall its
  whole form is disabled with "Use the laptop or a phone."
- **Void the week and Reopen a closed week** need a written reason: laptop or
  phone only at the wall. **The two waiver reasons** are optional: disabled at
  the wall, and the waiver still goes through without one.

"Required" means the server refuses the act without it (`Field(min_length=1)`).

| # | Screen / section | File | Field | Kind | Required | At the wall |
|---|---|---|---|---|---|---|
| 1 | Any PIN dialog (every parent act) | `components/parent/PinDialog.tsx` | PIN | PIN | yes | keypad, beside the field |
| 2 | Child — Savings: "Add money you got another way" | `SavingsView.tsx` | Amount | amount | yes | keypad |
| 3 | Child — Savings: same | `SavingsView.tsx` | Where it came from | text | yes | tapped from `MONEY_SOURCES` |
| 4 | Parent — Chores tab: Record a reward | `components/parent/Money.tsx` | Amount | amount | yes | disabled, "Use the laptop or a phone." |
| 5 | Parent — Chores tab: Record a reward | `components/parent/Money.tsx` | What it is for | text | yes | disabled, same reason |
| 6 | Parent — This week: Mark paid | `components/parent/Money.tsx` | Banked | amount | no | keypad |
| 7 | Parent — Savings: Record a deposit | `components/parent/Money.tsx` | Amount | amount | yes | disabled, "Use the laptop or a phone." |
| 8 | Parent — Savings: Record a deposit | `components/parent/Money.tsx` | Where it came from | text | yes | disabled, same reason |
| 9 | Parent — Savings: Log a withdrawal | `components/parent/Money.tsx` | Amount | amount | yes | disabled, "Use the laptop or a phone." |
| 10 | Parent — Savings: Log a withdrawal | `components/parent/Money.tsx` | What it went on | text | yes | disabled, same reason |
| 11 | Parent — Savings: Reconcile | `components/parent/Money.tsx` | What the account holds | amount | yes | keypad |
| 12 | Parent — Savings: Settle the match | `components/parent/SavingsMatch.tsx` | Bank balance after | amount | no | keypad |
| 13 | Parent — Chores: Weekly basic pay | `components/parent/Chores.tsx` | Amount | amount | yes | keypad |
| 14 | Parent — Chores: add / edit a chore | `components/parent/Chores.tsx` | Name | text | yes | edit: disabled, unchanged, "Use the laptop or a phone to type here."; add: whole form disabled, "Use the laptop or a phone." |
| 15 | Parent — Chores: add / edit a chore | `components/parent/Chores.tsx` | Times a week | other number | for "N times a week" | keypad, whole numbers (add: disabled) |
| 16 | Parent — Chores: add / edit a chore | `components/parent/Chores.tsx` | Amount | amount | for bonus chores | keypad (add: disabled) |
| 17 | Parent — This week: Waive a day | `components/parent/ThisWeek.tsx` | Why | text | no | disabled, "Use the laptop or a phone to type here."; waiving still works |
| 18 | Parent — This week: Waive a chore | `components/parent/ThisWeek.tsx` | Why | text | no | as 17 |
| 19 | Parent — This week: Void the week | `components/parent/ThisWeek.tsx` | Why this week is void | text | yes | disabled; Void disabled, "Use the laptop or a phone." |
| 20 | Parent — closed weeks: Reopen | `components/parent/ClosedWeeks.tsx` | Why it is reopened | text | yes | as 19 |
| — | Chores form: category, cadence, weekdays, "marks directly" | `Chores.tsx` | select / checkbox | — | — | by touch (add: disabled) |
| — | Mark missed: chore; Waive: day, chore | `ThisWeek.tsx` | select | — | — | by touch, unchanged |
| — | Mark paid: which weeks | `Money.tsx` | checkbox | — | — | by touch, unchanged |

Amounts are typed today as free text parsed by `parsePence` (`api.ts`): `£2`,
`2.50`, `.5`, `50p`. The keypad enters the same thing as pounds with up to two
decimal places for the pence (`2.50`, `0.50`): one point, two decimals at most.

## The keypad only fills the field

`KeypadField` (`components/Keypad.tsx`) holds no copy of what is typed: each
key reads the field's value and hands the next one to the field's own
`onChange`. The PIN lives where it always did, in the PIN dialog's state,
cleared before the request is awaited; it is checked on the server, never
stored or logged. Away from the wall `KeypadField` is the plain input it was.

## How the wall is recognised

**The wall is CoinQuest framed by a page on the loopback address.** The kiosk
shows the hub dashboard at `http://localhost:8500`, and the dashboard shows
CoinQuest in an iframe. Only a browser running on the hub itself can have a
`localhost` parent: a phone or the laptop reaches the dashboard by the hub's
LAN address, and opening CoinQuest directly is not framed at all. The check
reads the parent's origin from `location.ancestorOrigins` (Chromium), falling
back to `document.referrer`, once when the page loads (`frontend/src/wall.ts`).

Considered and turned down:

- **Touch media queries** (`pointer: coarse`, `hover: none`). Phones match too,
  and the wall's touch controller also registers as a mouse (the Pi lists
  "ILITEK ILITEK-TP Mouse" among its input devices), so Chromium may report a
  fine pointer at the wall.
- **The user agent.** The wall's Linux Chromium looks like any other.
- **Screen size.** 1280×800 is also a laptop window.

`?wall=on` or `?wall=off` overrides the check on one device and is remembered
there (browser storage); `?wall=auto` forgets it. That covers a kiosk ever
opened some other way, and trying the wall's controls on the laptop.

What it costs: if the kiosk ever opens CoinQuest at the top level rather than
in the dashboard's frame, the keypad will not show until `?wall=on` is added.

**Never both keyboards.** At the wall every keypad field has
`inputMode="none"`, so no system keyboard is ever asked for; away from the
wall the keypad is not rendered, so a phone shows only its own. A physical
keyboard types into any field everywhere, the wall included.
