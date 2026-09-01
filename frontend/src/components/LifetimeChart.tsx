/**
 * Two balance trajectories on one chart: what actually happened, and what
 * would have happened if no withdrawal ever had.
 *
 * Plain inline SVG, not a charting library — this app depends on nothing
 * but react and react-dom, and two lines are not worth a new dependency.
 * Colour comes from CSS custom properties via className, the same as every
 * other themed element on these screens, so the chart follows light and
 * dark mode without any logic of its own.
 */

import type { BalancePoint } from '../api'

const WIDTH = 720
const HEIGHT = 240
const PAD_X = 6
const PAD_TOP = 14
const PAD_BOTTOM = 6

function toTimestamp(occurredOn: string): number {
  return new Date(`${occurredOn}T12:00:00`).getTime()
}

type Scale = (value: number) => number

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
}: {
  real: BalancePoint[]
  counterfactual: BalancePoint[]
}) {
  const all = [...real, ...counterfactual]
  if (all.length === 0) return null

  const times = all.map((point) => toTimestamp(point.occurred_on))
  const minTime = Math.min(...times)
  const maxTime = Math.max(...times)
  const maxValue = Math.max(...all.map((point) => point.balance_pence), 1)

  const xScale: Scale = (time) =>
    maxTime === minTime
      ? WIDTH / 2
      : PAD_X + ((time - minTime) / (maxTime - minTime)) * (WIDTH - 2 * PAD_X)
  const yScale: Scale = (value) =>
    HEIGHT - PAD_BOTTOM - (value / maxValue) * (HEIGHT - PAD_TOP - PAD_BOTTOM)

  return (
    <div className="lifetime-chart">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label="The real savings balance against what it would be if nothing had ever been withdrawn"
      >
        <line
          x1={PAD_X}
          y1={HEIGHT - PAD_BOTTOM}
          x2={WIDTH - PAD_X}
          y2={HEIGHT - PAD_BOTTOM}
          className="lifetime-chart-axis"
        />
        <Series points={counterfactual} xScale={xScale} yScale={yScale} kind="counterfactual" />
        <Series points={real} xScale={xScale} yScale={yScale} kind="real" />
      </svg>

      <ul className="lifetime-legend">
        <li className="lifetime-legend-real">Real</li>
        <li className="lifetime-legend-counterfactual">If nothing had ever been withdrawn</li>
      </ul>
    </div>
  )
}

/** A line for two or more points; a single point still has to show up as
 * something, so it gets a dot instead of an invisible zero-length path. */
function Series({
  points,
  xScale,
  yScale,
  kind,
}: {
  points: BalancePoint[]
  xScale: Scale
  yScale: Scale
  kind: 'real' | 'counterfactual'
}) {
  if (points.length === 0) return null

  if (points.length === 1) {
    return (
      <circle
        cx={xScale(toTimestamp(points[0].occurred_on))}
        cy={yScale(points[0].balance_pence)}
        r={5}
        className={`lifetime-line lifetime-line-${kind}`}
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
