// Thang màu cố định theo nồng độ µg/m³, KHÔNG phải hạng AQI.
// Ngưỡng 15–75 lấy từ mức hướng dẫn và các mức trung gian 24 giờ của WHO 2021.
export const BINS = [
  { max: 15, color: '#fde8d8' },
  { max: 25, color: '#fbcfb0' },
  { max: 37.5, color: '#f7ae82' },
  { max: 50, color: '#f08a5a' },
  { max: 75, color: '#e0633c' },
  { max: 100, color: '#c23f2a' },
  { max: 150, color: '#92271f' },
  { max: Infinity, color: '#5c1616' },
]
export const NO_DATA = '#d1d5db'

export const colorFor = (v) =>
  v == null ? NO_DATA : BINS.find((b) => v < b.max).color

export const binLabel = (i) => {
  const lo = BINS[i - 1]?.max
  const hi = BINS[i].max
  if (lo === undefined) return `< ${hi}`
  return hi === Infinity ? `≥ ${lo}` : `${lo}–${hi}`
}

export const fmt = (v) =>
  v == null
    ? '—'
    : v.toLocaleString('vi-VN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// Ngày là chuỗi lịch Hà Nội; tính trên UTC để không bị lệch múi giờ của trình duyệt.
export const dayNum = (iso) => Date.parse(`${iso}T00:00:00Z`) / 86400000

export const fmtDate = (iso) => iso.split('-').reverse().join('/')

// Ngày có dữ liệu gần nhất, ưu tiên ngày sau; `dates` tăng dần.
export const nearestDate = (dates, target) =>
  dates.find((d) => d >= target) ?? dates.at(-1)

// Cửa sổ lịch sử: cả năm chứa ngày chọn, luôn ≤ 366 ngày theo giới hạn API.
export const yearWindow = (date, min, max) => {
  const y = date.slice(0, 4)
  const start = `${y}-01-01`
  const end = `${y}-12-31`
  return [start < min ? min : start, end > max ? max : end]
}
