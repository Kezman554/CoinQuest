/**
 * Managing the chores themselves — create, edit, retire — and the one
 * figure the basic ones share.
 *
 * A definition is the rule; the child's screen and every figure the app
 * computes read it live. Editing here changes what happens from here on and
 * never touches a settled week's own stored figures — a closed week keeps
 * its own frozen copy of everything it paid for, whatever the definition
 * looks like afterwards.
 *
 * Retiring is not deleting, and there is no delete here at all: a chore
 * withdrawn from the scheme is switched off (`is_available: false`), because
 * settled weeks and past instances still point at it. It is the one act this
 * screen offers for a chore nobody wants any more, and — like everything
 * else on this page — it goes through the same PIN dialog as a settle or a
 * void, never a second mechanism of its own.
 *
 * A BASIC chore carries no amount of its own. "Make bed" at £2 and
 * "Lunchbox and cups" at £2 never meant £4 — the rules describe one shared
 * weekly basic pay, and each basic chore only gates whether it is earned.
 * So the amount field is gone from this form for that category, and the
 * one figure that replaces it — the pot itself — has its own control at the
 * top of the section, edited the same PIN-gated way as everything else
 * here. BONUS and REWARD are untouched: they still carry, and still ask
 * for, their own individual amount.
 */

import { useState } from 'react'
import { money, parsePence } from '../../api'
import type {
  Cadence,
  ChoreDefinition,
  ChoreWrite,
  SchemeSettings,
  Weekday,
} from '../../parentApi'
import {
  WEEKDAYS,
  createChore,
  editChore,
  retireChore,
  updateSchemeSettings,
} from '../../parentApi'
import { cadenceLabel, weekdayLabel } from '../../parentWords'
import type { PinAct } from './PinDialog'

type Ask = { ask: (act: PinAct) => void }

const CADENCES: { value: Cadence; label: string }[] = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekdays', label: 'Chosen days of the week' },
  { value: 'weekly_count', label: 'A number of times a week' },
  { value: 'weekly_condition', label: 'All week, judged on Sunday' },
  { value: 'one_off', label: 'One-off' },
  { value: 'event', label: 'Logged by a parent when it happens' },
]

const CATEGORIES: { value: string; label: string }[] = [
  { value: 'basic', label: 'Basic — counts toward the weekly chore pay' },
  { value: 'bonus', label: 'Bonus — a fixed amount, all or nothing' },
  { value: 'reward', label: 'Reward — pays its own amount' },
]

export function Chores({
  ask,
  chores,
  schemeSettings,
}: Ask & { chores: ChoreDefinition[]; schemeSettings: SchemeSettings }) {
  const active = chores.filter((chore) => chore.is_available)
  const retired = chores.filter((chore) => !chore.is_available)
  const [creating, setCreating] = useState(false)

  return (
    <section className="panel">
      <h2>Chores</h2>
      <p className="act-note">
        Editing changes what happens from here on. A week already settled
        keeps its own figures whatever a chore is renamed, repriced or
        retired to afterwards — nothing here ever recomputes one.
      </p>

      <WeeklyBasicPay settings={schemeSettings} ask={ask} />

      {active.length === 0 && (
        <p className="nothing">No chores yet.</p>
      )}

      <ul className="chore-defs">
        {active.map((chore) => (
          <ChoreDefRow key={chore.id} chore={chore} ask={ask} />
        ))}
      </ul>

      {creating ? (
        <ChoreForm
          ask={ask}
          submitLabel="Add chore"
          initial={null}
          onDone={() => setCreating(false)}
          onCancel={() => setCreating(false)}
        />
      ) : (
        <button
          type="button"
          className="button"
          onClick={() => setCreating(true)}
        >
          Add a chore
        </button>
      )}

      {retired.length > 0 && (
        <>
          <h3>Retired</h3>
          <ul className="chore-defs">
            {retired.map((chore) => (
              <li key={chore.id} className="chore-def chore-def-retired">
                <span className="chore-def-name">{chore.name}</span>
                <span className="tag tag-retired">Retired</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

/**
 * The one figure every basic chore gates rather than earns its own slice
 * of. Shown once, at the top of the section, so "how much are the basics
 * worth" has one answer on the screen rather than one per chore.
 */
function WeeklyBasicPay({ settings, ask }: Ask & { settings: SchemeSettings }) {
  const [editing, setEditing] = useState(false)
  const [amount, setAmount] = useState(money(settings.weekly_basic_pay_pence))

  const pence = parsePence(amount)
  const ready = pence !== null && pence >= 0

  if (!editing) {
    return (
      <div className="act chore-basic-pay">
        <h3>Weekly basic pay</h3>
        <p className="act-note">
          What the basic chores are collectively worth for the week, all or
          nothing — not a total of their own amounts, which they no longer
          carry.
        </p>
        <div className="act-row">
          <span className="chore-basic-pay-amount">
            {settings.weekly_basic_pay}
          </span>
          <button
            type="button"
            className="button button-quiet"
            onClick={() => {
              setAmount(money(settings.weekly_basic_pay_pence))
              setEditing(true)
            }}
          >
            Edit
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="act chore-basic-pay">
      <h3>Weekly basic pay</h3>
      <div className="act-row">
        <input
          type="text"
          inputMode="decimal"
          placeholder="Amount, e.g. £2"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
        />
        <button
          type="button"
          className="button button-quiet"
          onClick={() => setEditing(false)}
        >
          Cancel
        </button>
        <button
          type="button"
          className="button button-do"
          disabled={!ready}
          onClick={() => {
            if (!ready || pence === null) return
            ask({
              title: 'Change the weekly basic pay',
              summary: `${settings.weekly_basic_pay} → ${money(pence)}`,
              lines: [
                'Every basic chore gates this one figure — none of them carry an amount of their own.',
                'A week already settled keeps its own figures; this only changes what happens from here on.',
              ],
              confirmLabel: 'Save',
              run: (pin) =>
                updateSchemeSettings(pin, {
                  weekly_basic_pay_pence: pence,
                  savings_match_start_rate_percent: settings.savings_match_start_rate_percent,
                  savings_match_ceiling_rate_percent: settings.savings_match_ceiling_rate_percent,
                  savings_match_cap_pence: settings.savings_match_cap_pence,
                }).then(() => {
                  setEditing(false)
                }),
            })
          }}
        >
          Save
        </button>
      </div>
      {amount !== '' && pence === null && (
        <p className="dialog-error">
          That is not an amount that can be paid in coins.
        </p>
      )}
    </div>
  )
}

function ChoreDefRow({ chore, ask }: Ask & { chore: ChoreDefinition }) {
  const [editing, setEditing] = useState(false)

  if (editing) {
    return (
      <li>
        <ChoreForm
          ask={ask}
          submitLabel="Save changes"
          initial={chore}
          onDone={() => setEditing(false)}
          onCancel={() => setEditing(false)}
        />
      </li>
    )
  }

  return (
    <li className="chore-def">
      <span className="chore-def-name">{chore.name}</span>
      <span className={`tag tag-${chore.category}`}>{chore.category}</span>
      <span className="chore-def-cadence">
        {cadenceLabel(chore.cadence, chore.times_per_week, chore.weekdays)}
      </span>
      {chore.is_administered && (
        <span className="chore-def-admin">Marked by a parent, not claimed</span>
      )}
      {chore.category === 'basic' ? (
        <span className="chore-def-amount chore-def-amount-shared">
          shares the weekly basic pay
        </span>
      ) : (
        <span className="chore-def-amount">{money(chore.amount_pence)}</span>
      )}
      <span className="chore-def-actions">
        <button
          type="button"
          className="button button-quiet"
          onClick={() => setEditing(true)}
        >
          Edit
        </button>
        <button
          type="button"
          className="button button-danger"
          onClick={() =>
            ask({
              title: `Retire ${chore.name}`,
              summary:
                'Switched off, not deleted — any settled week that already paid for it is untouched.',
              confirmLabel: 'Retire',
              permanent: true,
              run: (pin) => retireChore(pin, chore.id).then(() => undefined),
            })
          }
        >
          Retire
        </button>
      </span>
    </li>
  )
}

function ChoreForm({
  ask,
  submitLabel,
  initial,
  onDone,
  onCancel,
}: Ask & {
  submitLabel: string
  initial: ChoreDefinition | null
  onDone: () => void
  onCancel: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [category, setCategory] = useState<string>(initial?.category ?? 'basic')
  const [cadence, setCadence] = useState<Cadence>(initial?.cadence ?? 'daily')
  const [timesPerWeek, setTimesPerWeek] = useState(
    initial?.times_per_week ? String(initial.times_per_week) : '',
  )
  const [weekdays, setWeekdays] = useState<Weekday[]>(initial?.weekdays ?? [])
  const [amount, setAmount] = useState(
    initial && initial.category !== 'basic' ? money(initial.amount_pence) : '',
  )
  const [administered, setAdministered] = useState(initial?.is_administered ?? false)

  const isBasic = category === 'basic'
  const pence = parsePence(amount)
  const needsCount = cadence === 'weekly_count'
  const needsWeekdays = cadence === 'weekdays'
  const count = needsCount ? Number(timesPerWeek) : null
  const ready =
    name.trim().length > 0 &&
    (isBasic || (pence !== null && pence >= 0)) &&
    (!needsCount || (count !== null && count > 0)) &&
    (!needsWeekdays || weekdays.length > 0)

  const toggleWeekday = (day: Weekday) => {
    setWeekdays((current) =>
      current.includes(day)
        ? current.filter((each) => each !== day)
        : [...current, day],
    )
  }

  const submit = () => {
    if (!ready) return
    const chore: ChoreWrite = {
      name: name.trim(),
      category,
      cadence,
      times_per_week: needsCount ? count : null,
      weekdays: needsWeekdays ? weekdays : null,
      // A basic chore has no amount of its own — see the module note.
      amount_pence: isBasic ? null : pence,
      is_administered: administered,
    }
    const shape = cadenceLabel(cadence, chore.times_per_week, needsWeekdays ? weekdays : null)
    ask({
      title: initial ? `Save changes to ${initial.name}` : `Add ${chore.name}`,
      summary: isBasic ? shape : `${shape} — ${money(pence as number)}`,
      confirmLabel: submitLabel,
      run: (pin) =>
        (initial
          ? editChore(pin, initial.id, chore)
          : createChore(pin, chore)
        ).then(() => {
          onDone()
        }),
    })
  }

  return (
    <div className="act chore-form">
      <div className="act-row">
        <input
          type="text"
          placeholder="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <select
          value={category}
          onChange={(event) => setCategory(event.target.value)}
        >
          {CATEGORIES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="act-row">
        <select
          value={cadence}
          onChange={(event) => setCadence(event.target.value as Cadence)}
        >
          {CADENCES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {needsCount && (
          <input
            type="number"
            inputMode="numeric"
            min={1}
            placeholder="Times a week"
            value={timesPerWeek}
            onChange={(event) => setTimesPerWeek(event.target.value)}
          />
        )}
        {!isBasic && (
          <input
            type="text"
            inputMode="decimal"
            placeholder="Amount, e.g. £0.50"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        )}
      </div>

      {isBasic && (
        <p className="act-note">
          No amount of its own — it gates the shared weekly basic pay, set
          once at the top of this section.
        </p>
      )}

      {needsWeekdays && (
        <div className="chore-form-weekdays" role="group" aria-label="Which days">
          {WEEKDAYS.map((day) => (
            <label key={day} className="chore-form-weekday">
              <input
                type="checkbox"
                checked={weekdays.includes(day)}
                onChange={() => toggleWeekday(day)}
              />
              {weekdayLabel(day)}
            </label>
          ))}
        </div>
      )}

      <label className="chore-form-administered">
        <input
          type="checkbox"
          checked={administered}
          onChange={(event) => setAdministered(event.target.checked)}
        />
        Nick marks this one directly — the child does not claim it
      </label>

      {!isBasic && amount !== '' && pence === null && (
        <p className="dialog-error">
          That is not an amount that can be paid in coins.
        </p>
      )}

      <div className="act-row">
        <button
          type="button"
          className="button button-quiet"
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          className="button button-do"
          disabled={!ready}
          onClick={submit}
        >
          {submitLabel}
        </button>
      </div>
    </div>
  )
}
