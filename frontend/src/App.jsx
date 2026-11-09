import { useMemo, useState } from 'react'
import { url, useGet } from './api.js'
import { BINS, NO_DATA, binLabel, fmt, fmtDate, nearestDate, yearWindow } from './lib.js'
import MapView from './MapView.jsx'
import HistoryChart from './HistoryChart.jsx'

const control = 'rounded border border-gray-300 bg-white px-2 py-1 text-sm disabled:opacity-40'

function Legend({ showStations }) {
  return (
    <div className="absolute bottom-6 left-2 z-10 rounded bg-white/95 p-2 text-xs shadow">
      <p className="mb-1 font-medium">PM2.5 trung bình ngày (µg/m³)</p>
      {BINS.map((b, i) => (
        <div key={b.color} className="flex items-center gap-2">
          <span className="h-3 w-5" style={{ background: b.color }} />
          {binLabel(i)}
        </div>
      ))}
      <div className="flex items-center gap-2">
        <span className="h-3 w-5" style={{ background: NO_DATA }} />
        Không có dữ liệu
      </div>
      {showStations && (
        <div className="mt-2 border-t border-gray-200 pt-1">
          <p className="mb-1 font-medium">Trạm (số đo thực)</p>
          <div className="flex items-center gap-2">
            <span className="ml-1 h-3 w-3 rounded-full border-2 border-gray-900 bg-orange-300" />
            Đạt chuẩn ngày
          </div>
          <div className="flex items-center gap-2">
            <span className="ml-1 h-3 w-3 rounded-full border-2 border-dashed border-gray-900 bg-orange-300" />
            ⚠ Dưới 18 giờ hợp lệ
          </div>
          <div className="flex items-center gap-2">
            <span className="ml-1 h-3 w-3 rounded-full border border-gray-600 bg-white" />
            Không có số đo
          </div>
        </div>
      )}
    </div>
  )
}

function CellPanel({ feature, model, date, range, value, loading, stations, onClose }) {
  const { grid_id, centroid_lon, centroid_lat } = feature.properties
  const [start, end] = yearWindow(date, range.min, range.max)
  const history = useGet(
    url(`/api/grids/${encodeURIComponent(grid_id)}/history`, { model_id: model.model_id, start, end }),
  )

  return (
    <aside className="w-full shrink-0 border-t border-gray-200 bg-white p-4 md:w-96 md:overflow-y-auto md:border-t-0 md:border-l">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="font-semibold break-all">{grid_id}</h2>
          <p className="text-xs text-gray-600">
            {centroid_lat.toFixed(4)}, {centroid_lon.toFixed(4)}
          </p>
        </div>
        <button className="px-2 text-lg text-gray-500" onClick={onClose} aria-label="Đóng">
          ×
        </button>
      </div>

      <section className="mt-3">
        <p className="text-xs text-gray-600">
          Ước tính mô hình cho ô 1 km · {fmtDate(date)} · {model.label}
        </p>
        <p className="text-2xl font-semibold tabular-nums">
          {loading ? '…' : `${fmt(value)} µg/m³`}
        </p>
        {!loading && value != null && (
          <p className="text-xs text-gray-500 tabular-nums">Giá trị API: {value}</p>
        )}
      </section>

      {stations.length > 0 && (
        <section className="mt-3 rounded border border-gray-200 p-2">
          <p className="text-xs font-medium">Quan trắc tại trạm trong ô (số đo thực)</p>
          {stations.map((s) => (
            <p key={s.station_id} className="mt-1 text-sm">
              {s.station_name}:{' '}
              {s.has_observation ? <b>{fmt(s.pm25_observed)} µg/m³</b> : 'không có số đo'}
              {s.has_observation && !s.is_valid_day && (
                <span className="block text-xs text-amber-700">
                  ⚠ Dưới 18 giờ hợp lệ, không đạt chuẩn thống kê ngày
                </span>
              )}
            </p>
          ))}
        </section>
      )}

      <section className="mt-4">
        <h3 className="mb-1 text-sm font-medium">
          PM2.5 ước tính (µg/m³), {fmtDate(start)} – {fmtDate(end)}
        </h3>
        {history.error ? (
          <p className="text-sm text-red-700">
            {history.error}{' '}
            <button className="underline" onClick={history.retry}>
              Thử lại
            </button>
          </p>
        ) : history.data ? (
          <div className={history.loading ? 'opacity-50' : ''}>
            <HistoryChart series={history.data.data} date={date} />
          </div>
        ) : (
          <p className="text-sm text-gray-500">Đang tải…</p>
        )}
      </section>
    </aside>
  )
}

export default function App() {
  const [pickedModel, setPickedModel] = useState(null)
  const [pickedDate, setPickedDate] = useState(null)
  const [showStations, setShowStations] = useState(true)
  const [cell, setCell] = useState(null)

  const models = useGet('/api/models')
  const grids = useGet('/api/grids')
  const modelList = models.data?.data ?? []
  const model =
    modelList.find((m) => m.model_id === pickedModel) ??
    modelList.find((m) => m.is_default) ??
    modelList[0]
  const modelId = model?.model_id

  const dates = useGet(modelId ? url('/api/dates', { model_id: modelId }) : null)
  const dateList = dates.data?.data ?? []
  const date = dateList.length ? nearestDate(dateList, pickedDate ?? dates.data.max_date) : null
  const index = dateList.indexOf(date)

  const map = useGet(date ? url('/api/map', { date, model_id: modelId }) : null)
  const stations = useGet(date && showStations ? url('/api/stations', { date }) : null)

  const values = useMemo(
    () => new Map(map.data?.data?.map((d) => [d.grid_id, d.pm25_pred]) ?? []),
    [map.data],
  )
  const stationList = stations.data?.data

  const requests = [models, grids, dates, map, stations]
  const failed = requests.filter((r) => r.error)
  const busy = requests.some((r) => r.loading)
  const notice =
    models.data?.count === 0
      ? 'Chưa có mô hình nào được nạp dữ liệu.'
      : dates.data?.count === 0
        ? 'Mô hình này chưa có dữ liệu ngày.'
        : map.data?.count === 0
          ? 'Không có dữ liệu cho ngày đã chọn.'
          : null

  return (
    <div className="flex min-h-dvh flex-col bg-white text-gray-900 md:h-dvh">
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-gray-200 px-4 py-2">
        <div className="min-w-64 flex-1">
          <h1 className="font-semibold">PM2.5 Hà Nội, lưới 1 km</h1>
          <p className="text-xs text-gray-600">
            Ước tính hồi cứu trung bình ngày (µg/m³). Không phải dự báo, không phải chỉ số AQI.
          </p>
        </div>

        <label className="flex max-w-full items-center gap-2 text-sm whitespace-nowrap">
          Mô hình
          <select
            className={`${control} min-w-0`}
            value={modelId ?? ''}
            onChange={(e) => setPickedModel(e.target.value)}
          >
            {modelList.map((m) => (
              <option key={m.model_id} value={m.model_id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

        <div className="flex items-center gap-1 text-sm">
          <label htmlFor="date">Ngày</label>
          <button
            className={control}
            disabled={index <= 0}
            onClick={() => setPickedDate(dateList[index - 1])}
            aria-label="Ngày trước"
          >
            ‹
          </button>
          <input
            id="date"
            type="date"
            className={control}
            value={date ?? ''}
            min={dates.data?.min_date ?? undefined}
            max={dates.data?.max_date ?? undefined}
            onChange={(e) => e.target.value && setPickedDate(e.target.value)}
          />
          <button
            className={control}
            disabled={index < 0 || index >= dateList.length - 1}
            onClick={() => setPickedDate(dateList[index + 1])}
            aria-label="Ngày sau"
          >
            ›
          </button>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={showStations} onChange={(e) => setShowStations(e.target.checked)} />
          Lớp trạm quan trắc
        </label>
      </header>

      {failed.length > 0 && (
        <div role="alert" className="flex items-center gap-3 bg-red-50 px-4 py-2 text-sm text-red-800">
          {failed[0].error}
          <button className="underline" onClick={() => failed.forEach((r) => r.retry())}>
            Thử lại
          </button>
        </div>
      )}

      <main className="flex flex-1 flex-col md:min-h-0 md:flex-row">
        <div className="relative h-[65vh] shrink-0 md:h-auto md:min-h-0 md:flex-1 md:shrink">
          <MapView
            geojson={grids.data}
            values={values}
            stations={stationList}
            selectedId={cell?.properties.grid_id}
            onSelect={setCell}
          />
          <Legend showStations={showStations} />
          {(busy || notice) && (
            <div
              role="status"
              className="absolute top-2 left-1/2 z-10 -translate-x-1/2 rounded bg-white/95 px-3 py-1 text-xs shadow"
            >
              {busy ? 'Đang tải…' : notice}
            </div>
          )}
        </div>

        {cell && model && date && (
          <CellPanel
            key={cell.properties.grid_id}
            feature={cell}
            model={model}
            date={date}
            range={{ min: dates.data.min_date, max: dates.data.max_date }}
            value={values.get(cell.properties.grid_id)}
            loading={map.loading}
            stations={(stationList ?? []).filter((s) => s.grid_id === cell.properties.grid_id)}
            onClose={() => setCell(null)}
          />
        )}
      </main>
    </div>
  )
}
