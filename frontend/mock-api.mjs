// API giả theo Hợp đồng v1 (docs/HANDOVER.md mục 5) để dev UI khi chưa có Gói 2.
// Sử dụng hình học lưới GIS thực tế từ outputs/handover_staging/geometry/dim_grid_1km_epsg4326.parquet.
// Chạy: npm run mock (cổng 8000).
import { createServer } from 'node:http'
import { readFileSync } from 'node:fs'

const gridsJson = JSON.parse(readFileSync(new URL('./mock-grids.json', import.meta.url), 'utf8'))
const rawStations = JSON.parse(readFileSync(new URL('./mock-stations.json', import.meta.url), 'utf8'))

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

const cells = gridsJson.features.map((f) => ({
  id: f.properties.grid_id,
  lon: f.properties.centroid_lon,
  lat: f.properties.centroid_lat,
}))
const cellMap = new Map(cells.map((c) => [c.id, c]))

const noise = (a) => Math.abs(Math.sin(a * 127.1) * 43758.5453) % 1

function pm25(c, date, model) {
  const day = Date.parse(date) / DAY
  const season = 30 + 22 * Math.cos((2 * Math.PI * (day - 15)) / 365.25)
  const dCenter = ((c.lon - 105.85) * 100) ** 2 + ((c.lat - 21.03) * 110) ** 2
  const urban = 40 * Math.exp(-dCenter / 150)
  const daily = 25 * noise(day)
  const bias = model === B2 ? 4 * Math.sin(c.lon * 10 + c.lat * 10) : 0
  const localNoise = 3 * noise(c.lon * 1000 + c.lat * 500)
  return Math.max(0, season + urban + daily + bias + localNoise)
}

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
    return { body: gridsJson }
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
    const data = rawStations.map((s, i) => {
      const kind = i % 10 === 0 ? 'missing' : i % 6 === 0 ? 'partial' : 'valid'
      const missing = kind === 'missing'
      const c = cellMap.get(s.grid_id) ?? { lon: s.longitude, lat: s.latitude }
      return {
        station_id: s.station_id,
        station_name: s.station_name,
        grid_id: s.grid_id,
        longitude: s.longitude,
        latitude: s.latitude,
        pm25_observed: missing ? null : pm25(c, date, B1) * (0.85 + 0.3 * noise(i * 7)),
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
