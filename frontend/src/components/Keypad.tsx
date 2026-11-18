/**
 * CoinQuest's own numeric keypad, for PINs and amounts at the wall (Session
 * AS; docs/wall-inputs.md).
 *
 * The wall has no keyboard of any kind, so a field that needs digits brings
 * its own keys. Everywhere else `KeypadField` is the plain input it always
 * was: the laptop types, and a phone shows its own keyboard.
 *
 * The keypad only fills the field. It holds no copy of what is typed: every
 * key reads the field's current value from its props and hands the next one
 * to the field's own onChange. A PIN therefore lives exactly where it did
 * before — in the PIN dialog's state, cleared before the request is awaited —
 * and nowhere in here. Checking it stays on the server.
 *
 * The keys open under the field, in the page's flow rather than floating
 * over it, so they never cover the next thing to tap (the child's "where it
 * came from" sits right below the amount). They close on Done, or once a tap
 * elsewhere has finished — not on blur, which fires as a finger lands and
 * would move the page under it before the tap completes.
 *
 * At the wall the input keeps `inputMode="none"`: no system keyboard is ever
 * asked for, so a device can never show its own keyboard and this one at
 * once. The input stays editable, so a physical keyboard plugged into the
 * wall still types.
 *
 * Amounts are entered the way they are typed today: pounds, with up to two
 * decimal places for the pence (`2.50`, `0.50`), parsed by `parsePence`.
 */

import { useEffect, useRef, useState } from 'react'
import type { InputHTMLAttributes, Ref } from 'react'
import { useWall } from '../wall'

export type KeypadKind = 'pin' | 'amount' | 'count'

type Key = { label: string; press: string; name?: string }

const DIGITS: Key[] = ['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((digit) => ({
  label: digit,
  press: digit,
}))

const BACK: Key = { label: 'Delete', press: 'back', name: 'Delete the last digit' }
const CLEAR: Key = { label: 'Clear', press: 'clear' }
const POINT: Key = { label: '.', press: '.', name: 'Point' }

/** Four rows of three. An amount has the point left of 0, and Clear in a
 * row below; a PIN or a count has no point, so Clear takes its place and
 * the PIN dialog's keys stay four rows tall, short enough for the panel. */
function keysFor(kind: KeypadKind): Key[] {
  return [...DIGITS, kind === 'amount' ? POINT : CLEAR, { label: '0', press: '0' }, BACK]
}

/** Longest each kind may grow: a PIN is short, a count is a week's worth. */
const LIMIT: Record<KeypadKind, number> = { pin: 12, amount: 8, count: 2 }

/** The field's next value after one key — the only arithmetic in here. */
function nextValue(kind: KeypadKind, value: string, press: string): string {
  if (press === 'clear') return ''
  if (press === 'back') return value.slice(0, -1)
  if (value.length >= LIMIT[kind]) return value
  if (press === '.') {
    if (kind !== 'amount' || value.includes('.')) return value
    return (value === '' || value === '£' ? `${value}0` : value) + '.'
  }
  if (kind === 'amount') {
    const decimals = value.split('.')[1]
    if (decimals !== undefined && decimals.length >= 2) return value
  }
  return value + press
}

type FieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> & {
  kind: KeypadKind
  value: string
  onChange: (value: string) => void
  /** The keypad always shows under the field (the PIN dialog), rather than
   * opening under it when the field is tapped. */
  inline?: boolean
  inputRef?: Ref<HTMLInputElement>
}

export function KeypadField({ kind, value, onChange, inline = false, inputRef, ...input }: FieldProps) {
  const wall = useWall()
  const [open, setOpen] = useState(false)
  const pad = useRef<HTMLDivElement>(null)
  const field = useRef<HTMLSpanElement>(null)
  const own = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!open || inline) return
    pad.current?.scrollIntoView({ block: 'nearest' })
    // A click anywhere else closes the keys, after that click is handled.
    const elsewhere = (event: MouseEvent) => {
      if (!field.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('click', elsewhere)
    return () => document.removeEventListener('click', elsewhere)
  }, [open, inline])

  if (!wall) {
    return <input {...input} ref={inputRef} value={value} onChange={(event) => onChange(event.target.value)} />
  }

  const setRef = (element: HTMLInputElement | null) => {
    own.current = element
    if (typeof inputRef === 'function') inputRef(element)
    else if (inputRef) (inputRef as { current: HTMLInputElement | null }).current = element
  }

  const showing = inline || (open && !input.disabled)

  return (
    <span ref={field} className={`keypad-field${inline ? ' keypad-field-inline' : ''}`}>
      <input
        {...input}
        ref={setRef}
        inputMode="none"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onFocus={(event) => {
          setOpen(true)
          input.onFocus?.(event)
        }}
        onClick={(event) => {
          setOpen(true)
          input.onClick?.(event)
        }}
      />
      {showing && (
        <div
          ref={pad}
          className={`keypad${inline ? '' : ' keypad-pop'}`}
          role="group"
          aria-label="Keypad"
          // A key pressed must not take the focus from the field.
          onPointerDown={(event) => event.preventDefault()}
          onMouseDown={(event) => event.preventDefault()}
        >
          {keysFor(kind).map((key) => (
            <button
              key={key.press}
              type="button"
              className="button keypad-key"
              aria-label={key.name}
              disabled={input.disabled}
              onClick={() => onChange(nextValue(kind, value, key.press))}
            >
              {key.label}
            </button>
          ))}
          {kind === 'amount' && (
            <button
              type="button"
              className="button keypad-key keypad-wide"
              disabled={input.disabled}
              onClick={() => onChange(nextValue(kind, value, 'clear'))}
            >
              Clear
            </button>
          )}
          {!inline && (
            <button
              type="button"
              className={`button keypad-key${kind === 'amount' ? '' : ' keypad-full'}`}
              onClick={() => {
                setOpen(false)
                own.current?.blur()
              }}
            >
              Done
            </button>
          )}
        </div>
      )}
    </span>
  )
}
