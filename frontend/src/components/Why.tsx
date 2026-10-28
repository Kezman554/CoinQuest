/**
 * Why a control is disabled, said beside it (DESIGN.md: any control the
 * state forbids keeps its place, in the disabled roles, and says why).
 *
 * A control that vanishes when it cannot be used teaches nobody that it
 * exists; one that sits greyed with no reason leaves a parent guessing which
 * field is wrong. The button names this note with aria-describedby, so a
 * screen reader hears the reason with the button.
 *
 *   const whyId = useId()
 *   const why = ready ? null : 'Needs an amount first.'
 *   <button disabled={why !== null} aria-describedby={why ? whyId : undefined}>
 *   <Why id={whyId} reason={why} />
 */

export function Why({
  id,
  reason,
  className = 'why',
}: {
  id: string
  reason: string | null
  className?: string
}) {
  if (!reason) return null
  return (
    <p className={className} id={id}>
      {reason}
    </p>
  )
}
