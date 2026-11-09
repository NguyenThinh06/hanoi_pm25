// API giả theo Hợp đồng v1 (docs/HANDOVER.md mục 5) để dev UI khi chưa có Gói 2.
// Số liệu là giả lập. Chạy: npm run mock (cổng 8000).
import { createServer } from 'node:http'

const B1 = 'Baseline_1_OpenAQ_Meteo:v2.0.0-retrospective'
const B2 = 'Baseline_2_OpenAQ_Meteo_Sat:v2.0.0-retrospective'
const models = [
  { model_id: B2, model_version: 'v2.0.0-retrospective', label: 'Baseline 2 — Khí tượng + Vệ tinh (Khuyến nghị)', is_default: true, feature_count: 34 },
  { model_id: B1, model_version: 'v2.0.0-retrospective', label: 'Baseline 1 — Khí tượng', is_default: false, feature_count: 27 },
]

const DAY = 86400000
const MIN = Date.parse('2021-01-01')
const MAX = Date.parse('2026-09-30')
const iso = (t) => new Date(t).toISOString().slice(0, 10)
const dates = Array.from({ length: (MAX - MIN) / DAY + 1 }, (_, i) => iso(MIN + i * DAY))
const dateSet = new Set(dates)

const COLS = 61 // 61 × 60 ≈ 3.660, cắt còn 3.610 ô
const cells = []
for (let n = 0; n < 60; n++) {
  for (let e = 0; e < COLS; e++) {
    if (cells.length < 3610) cells.push({ id: `grid_${555000 + e * 1000}_${2300000 + n * 1000}`, e, n })
  }
}
const cellMap = new Map(cells.map((c) => [c.id, c]))
const lon = (e) => 105.3 + e * 0.0096
const lat = (n) => 20.75 + n * 0.009

const noise = (a) => Math.abs(Math.sin(a * 127.1) * 43758.5453) % 1

function pm25(c, date, model) {
  const day = Date.parse(date) / DAY
  const season = 30 + 22 * Math.cos((2 * Math.PI * (day - 15)) / 365.25)
  const urban = 40 * Math.exp(-((c.e - 30) ** 2 + (c.n - 30) ** 2) / 300)
  const daily = 25 * noise(day)
  const bias = model === B2 ? 4 * Math.sin((c.e + c.n) / 6) : 0
  return Math.max(0, season + urban + daily + bias + 3 * noise(c.e * 13 + c.n))
}

const stations = [
  ['openaq_2161290', 'United States Embassy Hanoi', 30, 30, 'valid'],
  ['openaq_1001', 'Trạm Hoàn Kiếm', 32, 31, 'valid'],
  ['openaq_1002', 'Trạm Hà Đông', 25, 25, 'partial'],
  ['openaq_1003', 'Trạm Sóc Sơn', 28, 50, 'valid'],
  ['openaq_1004', 'Trạm mất tín hiệu', 15, 18, 'missing'],
].map(([station_id, station_name, e, n, kind]) => ({ station_id, station_name, e, n, kind }))

const fail = (status, code, message) => ({ status, body: { error: { code, message } } })
const badDate = (d) => !/^\d{4}-\d{2}-\d{2}$/.test(d ?? '') || Number.isNaN(Date.parse(d))
const invalid = (message) => fail(422, 'INVALID_REQUEST', message)
const noModel = fail(404, 'MODEL_NOT_FOUND', 'Không tìm thấy mô hình.')
const hasModel = (id) => id === B1 || id === B2

function route(path, q) {
  const model_id = q.get('model_id')
  if (path === '/health') return { body: { status: 'ok', database: 'ready' } }
  if (path === '/api/models') return { body: { count: models.length, data: models } }
  if (path === '/api/dates') {
    if (!hasModel(model_id)) return noModel
    return { body: { model_id, count: dates.length, min_date: dates[0], max_date: dates.at(-1), data: dates } }
  }
  if (path === '/api/grids') {
    const size = 0.0048
    return {
      body: {
        type: 'FeatureCollection',
        features: cells.map((c) => {
          const [x, y] = [lon(c.e), lat(c.n)]
          return {
            type: 'Feature',
            id: c.id,
            properties: { grid_id: c.id, centroid_lon: x, centroid_lat: y, is_boundary: c.e === 0 || c.n === 0 },
            geometry: {
              type: 'Polygon',
              coordinates: [[[x - size, y - 0.0045], [x + size, y - 0.0045], [x + size, y + 0.0045], [x - size, y + 0.0045], [x - size, y - 0.0045]]],
            },
          }
        }),
      },
    }
  }
  if (path === '/api/map') {
    const date = q.get('date')
    if (badDate(date)) return invalid('Ngày không đúng định dạng YYYY-MM-DD.')
    if (!hasModel(model_id)) return noModel
    const data = dateSet.has(date) ? cells.map((c) => ({ grid_id: c.id, pm25_pred: pm25(c, date, model_id) })) : []
    return { body: { date, model_id, unit: 'µg/m³', count: data.length, data } }
  }
  const hist = path.match(/^\/api\/grids\/([^/]+)\/history$/)
  if (hist) {
    const grid_id = decodeURIComponent(hist[1])
    const [start, end] = [q.get('start'), q.get('end')]
    if (badDate(start) || badDate(end)) return invalid('Ngày không đúng định dạng YYYY-MM-DD.')
    if ((Date.parse(end) - Date.parse(start)) / DAY + 1 > 366) return invalid('Khoảng thời gian vượt quá 366 ngày.')
    if (!hasModel(model_id)) return noModel
    const c = cellMap.get(grid_id)
    if (!c) return fail(404, 'GRID_NOT_FOUND', 'Không tìm thấy ô lưới.')
    const data = dates.filter((d) => d >= start && d <= end).map((date) => ({ date, pm25_pred: pm25(c, date, model_id) }))
    return { body: { grid_id, model_id, start, end, unit: 'µg/m³', count: data.length, data } }
  }
  if (path === '/api/stations') {
    const date = q.get('date')
    if (badDate(date)) return invalid('Ngày không đúng định dạng YYYY-MM-DD.')
    const data = stations.map(({ station_id, station_name, e, n, kind }) => {
      const missing = kind === 'missing'
      return {
        station_id,
        station_name,
        grid_id: cells.find((c) => c.e === e && c.n === n).id,
        longitude: lon(e),
        latitude: lat(n),
        pm25_observed: missing ? null : pm25({ e, n }, date, B1) * 0.9,
        pm25_valid_hours: missing ? 0 : kind === 'partial' ? 12 : 24,
        is_valid_day: kind === 'valid',
        has_observation: !missing,
      }
    })
    return { body: { date, unit: 'µg/m³', count: data.length, data } }
  }
  return fail(404, 'NOT_FOUND', 'Không tìm thấy tài nguyên.')
}

createServer((req, res) => {
  const u = new URL(req.url, 'http://x')
  const { status = 200, body } = route(u.pathname, u.searchParams)
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(body))
}).listen(8000, () => console.log('Mock API: http://localhost:8000'))
