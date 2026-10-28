/**
 * The PIN, asked for once per submission and kept nowhere afterwards.
 *
 * The value lives in this component's own state and nowhere else. The
 * component is unmounted the moment the act finishes or is cancelled, which
 * takes the state with it, and `pin` is cleared before the request is even
 * awaited so a slow network cannot leave it sitting in a live component.
 * There is no "remember for 5 minutes", no session, no header set for later:
 * the next act asks again.
 *
 * That matters here more than it usually would. This screen is on a wall in a
 * kitchen the child walks through, and a PIN left authorised is a PIN the
 * child can use. The API refuses these requests server-side without it — this
 * is not what makes the app safe — but an app that stayed unlocked would make
 * the server-side check irrelevant in practice.
 *
 * The dialog states what is about to happen before it asks. Authorising
 * something permanent while looking at a PIN pad and not at the consequence
 * is how a wrong figure gets agreed to.
 */

import { useEffect, useId, useRef, useState } from 'react'
import { Why } from '../Why'

export type PinAct = {
  title: string
  summary?: string
  lines?: string[]
  confirmLabel: string
  run: (pin: string) => Promise<void>
  /** Set for anything permanent, which is styled to be read twice. */
  permanent?: boolean
  /** Set for an act that removes money or undoes something — void, reopen,
   * a withdrawal, declining a deposit, retiring a chore. Its button takes
   * danger's outline; everything else confirms, in the neutral raised look.
   * Neither is gold: gold is money and the child's own do-it actions. */
  danger?: boolean
}

type Props = {
  act: PinAct
  onClose: () => void
  onDone: () => void
}

export function PinDialog({ act, onClose, onDone }: Props) {
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const whyId = useId()
  const why = !busy && pin.length === 0 ? 'Enter the PIN first.' : null

  useEffect(() => {
    input.current?.focus()
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (busy || pin.length === 0) return

    // Read once, then dropped from state immediately: what goes to the server
    // is this local const, and nothing that outlives the call.
    const offered = pin
    setPin('')
    setBusy(true)
    setError(null)

    try {
      await act.run(offered)
      onDone()
    } catch (problem) {
      setError((problem as Error).message)
      setBusy(false)
      input.current?.focus()
    }
  }

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <form className="dialog" onSubmit={submit}>
        <h2>{act.title}</h2>
        {act.summary && <p className="dialog-summary">{act.summary}</p>}
        {act.lines && act.lines.length > 0 && (
          <ul className="dialog-lines">
            {act.lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
        {act.permanent && (
          <p className="dialog-permanent">
            This cannot be undone once it is done.
          </p>
        )}

        <label className="pin-label" htmlFor="pin">
          Parent PIN
        </label>
        <input
          id="pin"
          ref={input}
          className="pin-input"
          type="password"
          inputMode="numeric"
          autoComplete="off"
          value={pin}
          disabled={busy}
          onChange={(event) => setPin(event.target.value)}
        />

        {error && (
          <p className="dialog-error" role="alert">
            {error}
          </p>
        )}

        <div className="dialog-buttons">
          <button
            type="button"
            className="button button-quiet"
            onClick={onClose}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="submit"
            className={act.danger ? 'button button-danger' : 'button button-confirm'}
            disabled={busy || pin.length === 0}
            aria-describedby={why ? whyId : undefined}
          >
            {busy ? 'Working…' : act.confirmLabel}
          </button>
        </div>
        <Why id={whyId} reason={why} className="why why-end" />
      </form>
    </div>
  )
}
