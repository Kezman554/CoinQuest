/**
 * Managing the chores themselves — create, edit, retire.
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
 */

import { useState } from 'react'
import { money, parsePence } from '../../api'
import type { Cadence, ChoreDefinition, ChoreWrite, Weekday } from '../../parentApi'
import { WEEKDAYS, createChore, editChore, retireChore } from '../../parentApi'
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

export function Chores({ ask, chores }: Ask & { chores: ChoreDefinition[] }) {
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
      <span className="chore-def-amount">{money(chore.amount_pence)}</span>
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
  const [amount, setAmount] = useState(initial ? money(initial.amount_pence) : '')
  const [administered, setAdministered] = useState(initial?.is_administered ?? false)

  const pence = parsePence(amount)
  const needsCount = cadence === 'weekly_count'
  const needsWeekdays = cadence === 'weekdays'
  const count = needsCount ? Number(timesPerWeek) : null
  const ready =
    name.trim().length > 0 &&
    pence !== null &&
    pence >= 0 &&
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
    if (!ready || pence === null) return
    const chore: ChoreWrite = {
      name: name.trim(),
      category,
      cadence,
      times_per_week: needsCount ? count : null,
      weekdays: needsWeekdays ? weekdays : null,
      amount_pence: pence,
      is_administered: administered,
    }
    ask({
      title: initial ? `Save changes to ${initial.name}` : `Add ${chore.name}`,
      summary: `${cadenceLabel(cadence, chore.times_per_week, needsWeekdays ? weekdays : null)} — ${money(pence)}`,
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
        <input
          type="text"
          inputMode="decimal"
          placeholder="Amount, e.g. £0.50"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
        />
      </div>

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

      {amount !== '' && pence === null && (
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
