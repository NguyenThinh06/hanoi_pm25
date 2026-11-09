import { useState } from 'react'
import { dayNum, fmt, fmtDate } from './lib.js'

const W = 360
const H = 190
const LEFT = 30
const RIGHT = 8
const TOP = 10
const BOTTOM = 22

export default function HistoryChart({ series, date }) {
  const [hover, setHover] = useState(null)
  if (!series.length) return <p className="text-sm text-gray-500">Không có dữ liệu lịch sử.</p>

  const d0 = dayNum(series[0].date)
  const days = dayNum(series.at(-1).date) - d0
  const peak = series.reduce((a, b) => (b.pm25_pred > a.pm25_pred ? b : a))
  const yMax = Math.max(50, Math.ceil(peak.pm25_pred / 50) * 50)
  const step = yMax <= 100 ? 25 : yMax <= 200 ? 50 : 100
  const yTicks = Array.from({ length: yMax / step + 1 }, (_, i) => i * step)
  const x = (iso) => LEFT + ((dayNum(iso) - d0) / Math.max(days, 1)) * (W - LEFT - RIGHT)
  const y = (v) => H - BOTTOM - (v / yMax) * (H - TOP - BOTTOM)

  // Ngày thiếu thì đứt nét, không nội suy qua khoảng trống.
  const path = series
    .map((p, i) => {
      const joined = i > 0 && dayNum(p.date) - dayNum(series[i - 1].date) === 1
      return `${joined ? 'L' : 'M'}${x(p.date).toFixed(1)} ${y(p.pm25_pred).toFixed(1)}`
    })
    .join('')

  const xTicks =
    days > 62
      ? series.filter((p) => p.date.endsWith('-01') && (days < 200 || +p.date.slice(5, 7) % 2 === 1))
      : series.filter((_, i) => i % 7 === 0)
  const xLabel = (iso) => (days > 62 ? `T${+iso.slice(5, 7)}` : `${iso.slice(8)}/${iso.slice(5, 7)}`)

  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - r.left) / r.width) * W
    setHover(series.reduce((a, b) => (Math.abs(x(b.date) - px) < Math.abs(x(a.date) - px) ? b : a)))
  }
  const selected = series.find((p) => p.date === date)
  const hoverLeft = hover ? (x(hover.date) / W) * 100 : 0

  return (
    <div>
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="block w-full"
          role="img"
          aria-label={`Chuỗi PM2.5 ước tính từ ${fmtDate(series[0].date)} đến ${fmtDate(series.at(-1).date)}, cao nhất ${fmt(peak.pm25_pred)} µg/m³`}
          onPointerMove={onMove}
          onPointerLeave={() => setHover(null)}
        >
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={LEFT} x2={W - RIGHT} y1={y(t)} y2={y(t)} stroke="#e5e7eb" />
              <text x={LEFT - 4} y={y(t) + 3} textAnchor="end" fontSize="9" fill="#6b7280">
                {t}
              </text>
            </g>
          ))}
          {xTicks.map((p) => (
            <text key={p.date} x={x(p.date)} y={H - 8} textAnchor="middle" fontSize="9" fill="#6b7280">
              {xLabel(p.date)}
            </text>
          ))}
          <path d={path} fill="none" stroke="#2563eb" strokeWidth="2" strokeLinejoin="round" />
          {selected && (
            <g>
              <line x1={x(date)} x2={x(date)} y1={TOP} y2={H - BOTTOM} stroke="#111827" strokeDasharray="3 3" />
              <circle cx={x(date)} cy={y(selected.pm25_pred)} r="4" fill="#111827" stroke="#fff" strokeWidth="2" />
            </g>
          )}
          {hover && (
            <g pointerEvents="none">
              <line x1={x(hover.date)} x2={x(hover.date)} y1={TOP} y2={H - BOTTOM} stroke="#9ca3af" />
              <circle cx={x(hover.date)} cy={y(hover.pm25_pred)} r="4" fill="#2563eb" stroke="#fff" strokeWidth="2" />
            </g>
          )}
        </svg>
        {hover && (
          <div
            className="pointer-events-none absolute top-0 rounded bg-gray-900 px-2 py-1 text-xs whitespace-nowrap text-white"
            style={{
              left: `${hoverLeft}%`,
              transform: hoverLeft > 50 ? 'translateX(calc(-100% - 8px))' : 'translateX(8px)',
            }}
          >
            {fmtDate(hover.date)}: {fmt(hover.pm25_pred)} µg/m³
          </div>
        )}
      </div>
      <p className="mt-1 text-xs text-gray-600">
        Cao nhất {fmt(peak.pm25_pred)} µg/m³ ngày {fmtDate(peak.date)}. Nét đứt: ngày đang chọn.
      </p>
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer text-gray-600">Xem bảng số liệu</summary>
        <div className="mt-1 max-h-48 overflow-y-auto">
          <table className="w-full">
            <thead>
              <tr className="text-left text-gray-500">
                <th className="font-medium">Ngày</th>
                <th className="text-right font-medium">Ước tính (µg/m³)</th>
              </tr>
            </thead>
            <tbody>
              {series.map((p) => (
                <tr key={p.date}>
                  <td>{fmtDate(p.date)}</td>
                  <td className="text-right tabular-nums">{p.pm25_pred}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}
