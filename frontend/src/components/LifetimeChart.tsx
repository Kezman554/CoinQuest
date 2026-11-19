/**
 * Three balance trajectories on one chart: what actually happened, what
 * would have happened if no withdrawal ever had, and that again with every
 * week's pay saved whole (Session AT).
 *
 * Plain inline SVG, not a charting library — this app depends on nothing
 * but react and react-dom, and two lines are not worth a new dependency.
 * Every stroke is a token, set by className in App.css, so the chart follows
 * day and night without any logic of its own; each is measured against the
 * panel it is drawn on by check:contrast. The never-withdrawn line is dashed
 * and the saved-everything line dotted, as well as coloured, so no two
 * series are told apart by colour alone (DESIGN.md).
 *
 * Every line has its figure: the key under the chart names each line beside
 * its swatch and gives the line's final balance in the line's own colour and
 * dash, so which number goes with which line never needs working out. The
 * vertical axis is marked in pounds, so any point can be read, not only the
 * last. Nothing is shaded between the lines: the page's caption is how money
 * grows if you leave it alone, and a gap filled in would read as money lost.
 */

import { money } from '../api'
import type { BalancePoint } from '../api'

const WIDTH = 720
const HEIGHT = 240
const PAD_X = 6
const PAD_TOP = 14

type Kind = 'real' | 'counterfactual' | 'saved'

/** The key's words, short enough to read at a glance from the wall: the
 * page's own, unchanged — "Real, today" was the real balance's figure. */
const LABELS: Record<Kind, string> = {
  real: 'Real, today',
  counterfactual: 'If nothing had ever been withdrawn',
  saved: "If every week's pay had been saved",
}
const PAD_BOTTOM = 6

function toTimestamp(occurredOn: string): number {
  return new Date(`${occurredOn}T12:00:00`).getTime()
}

type Scale = (value: number) => number

/** Round pound marks for the vertical axis, about four of them: a step of
 * 1, 2 or 5 times a power of ten (in pence), and a top mark at or above the
 * highest point so every line sits inside the marks. */
function axisMarks(highest: number): number[] {
  const rough = Math.max(highest, 1) / 4
  const scale = 10 ** Math.max(0, Math.floor(Math.log10(rough)))
  const step = [1, 2, 5, 10].map((m) => m * scale).find((s) => s >= rough) ?? 10 * scale
  const top = Math.max(step, Math.ceil(highest / step) * step)
  const marks: number[] = []
  for (let mark = 0; mark <= top; mark += step) marks.push(mark)
  return marks
}

function last(points: BalancePoint[]): number {
  return points[points.length - 1].balance_pence
}

function pathFor(points: BalancePoint[], xScale: Scale, yScale: Scale): string {
  return points
    .map((point, index) => {
      const command = index === 0 ? 'M' : 'L'
      return `${command} ${xScale(toTimestamp(point.occurred_on))} ${yScale(point.balance_pence)}`
    })
    .join(' ')
}

export function LifetimeChart({
  real,
  counterfactual,
  saved,
}: {
  real: BalancePoint[]
  counterfactual: BalancePoint[]
  saved: BalancePoint[]
}) {
  const all = [...real, ...counterfactual, ...saved]
  if (all.length === 0) return null

  const times = all.map((point) => toTimestamp(point.occurred_on))
  const minTime = Math.min(...times)
  const maxTime = Math.max(...times)
  const marks = axisMarks(Math.max(...all.map((point) => point.balance_pence)))
  const top = marks[marks.length - 1]

  const xScale: Scale = (time) =>
    maxTime === minTime
      ? WIDTH / 2
      : PAD_X + ((time - minTime) / (maxTime - minTime)) * (WIDTH - 2 * PAD_X)
  const yScale: Scale = (value) =>
    HEIGHT - PAD_BOTTOM - (value / top) * (HEIGHT - PAD_TOP - PAD_BOTTOM)

  const series: [Kind, BalancePoint[]][] = [
    ['real', real],
    ['counterfactual', counterfactual],
    ['saved', saved],
  ]

  return (
    <div className="lifetime-chart">
      <div className="lifetime-plot">
      {/* The pound marks, in the page's type rather than the drawing's, so
          they stay readable however wide the chart is drawn. Each sits at its
          mark's height as a share of the drawing's. */}
      <ol className="lifetime-axis" aria-label="Pounds">
        {marks.map((mark) => (
          <li key={mark} style={{ top: `${(yScale(mark) / HEIGHT) * 100}%` }}>
            {money(mark)}
          </li>
        ))}
      </ol>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="The real savings balance, what it would be if nothing had ever been withdrawn, and what it would be if every week's pay had been saved"
      >
        <line
          x1={PAD_X}
          y1={HEIGHT - PAD_BOTTOM}
          x2={WIDTH - PAD_X}
          y2={HEIGHT - PAD_BOTTOM}
          className="lifetime-chart-axis"
        />
        {marks.slice(1).map((mark) => (
          <line
            key={mark}
            x1={PAD_X}
            y1={yScale(mark)}
            x2={WIDTH - PAD_X}
            y2={yScale(mark)}
            className="lifetime-chart-mark"
          />
        ))}
        <Series points={saved} xScale={xScale} yScale={yScale} kind="saved" />
        <Series points={counterfactual} xScale={xScale} yScale={yScale} kind="counterfactual" />
        <Series points={real} xScale={xScale} yScale={yScale} kind="real" />
      </svg>
      </div>

      <ul className="lifetime-legend">
        {series
          .filter(([, points]) => points.length > 0)
          .map(([kind, points]) => (
            <li key={kind} className={`lifetime-legend-${kind}`}>
              <span className="lifetime-legend-label">{LABELS[kind]}</span>
              <span className="lifetime-legend-value">{money(last(points))}</span>
            </li>
          ))}
      </ul>
    </div>
  )
}

/** A line for two or more points. A single point still has to show up as
 * something: a zero-length path, drawn as a round dot by its round cap. A
 * circle would not do — the drawing stretches to fit its box and would
 * squash it into an oval; a stroke does not stretch. */
function Series({
  points,
  xScale,
  yScale,
  kind,
}: {
  points: BalancePoint[]
  xScale: Scale
  yScale: Scale
  kind: Kind
}) {
  if (points.length === 0) return null

  if (points.length === 1) {
    return (
      <path
        d={`M ${xScale(toTimestamp(points[0].occurred_on))} ${yScale(points[0].balance_pence)} h 0`}
        fill="none"
        className={`lifetime-line lifetime-dot lifetime-line-${kind}`}
      />
    )
  }

  return (
    <path
      d={pathFor(points, xScale, yScale)}
      fill="none"
      className={`lifetime-line lifetime-line-${kind}`}
    />
  )
}
