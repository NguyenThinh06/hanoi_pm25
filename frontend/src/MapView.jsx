import { useEffect, useRef } from 'react'
import L from 'leaflet'
import { NO_DATA, colorFor, fmt } from './lib.js'

const esc = (s) => {
  const el = document.createElement('span')
  el.textContent = s
  return el.innerHTML
}

function stationStyle(s) {
  const pane = 'stations'
  if (!s.has_observation || s.pm25_observed == null) {
    return { pane, radius: 5, color: '#4b5563', weight: 1.5, fillColor: '#fff', fillOpacity: 1 }
  }
  const fillColor = colorFor(s.pm25_observed)
  return s.is_valid_day
    ? { pane, radius: 7, color: '#111827', weight: 2, fillColor, fillOpacity: 1 }
    : { pane, radius: 7, color: '#111827', weight: 2, dashArray: '3 3', fillColor, fillOpacity: 1 }
}

function stationPopup(s, estimate) {
  const measured = s.has_observation && s.pm25_observed != null
  const measuredHtml = measured
    ? `<b>${fmt(s.pm25_observed)} µg/m³</b><br>Số giờ hợp lệ: ${s.pm25_valid_hours ?? '—'}/24`
    : 'Không có số đo trong ngày'
  const warn =
    measured && !s.is_valid_day
      ? '<br><span style="color:#b45309">⚠ Dưới 18 giờ hợp lệ, không đạt chuẩn thống kê ngày</span>'
      : ''
  const estimateHtml = s.grid_id
    ? `<br><br>Ước tính mô hình cho ô 1 km chứa trạm:<br><b>${fmt(estimate)} µg/m³</b>`
    : ''
  return `<b>${esc(s.station_name)}</b><br><br>Quan trắc tại trạm (số đo thực):<br>${measuredHtml}${warn}${estimateHtml}`
}

export default function MapView({ geojson, values, stations, selectedId, onSelect }) {
  const elRef = useRef(null)
  const mapRef = useRef(null)
  const gridRef = useRef(null)
  const stationsRef = useRef(null)
  const latest = useRef()
  latest.current = { values, onSelect }

  useEffect(() => {
    const map = L.map(elRef.current).setView([21.03, 105.75], 10)
    // Lưu ý: tile công cộng OSM chỉ đủ cho demo, lưu lượng lớn cần nhà cung cấp tile riêng.
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map)
    // pointerEvents none: lớp SVG của trạm không được chặn click xuống canvas lưới.
    const pane = map.createPane('stations')
    pane.style.zIndex = 450
    pane.style.pointerEvents = 'none'
    stationsRef.current = L.layerGroup().addTo(map)
    mapRef.current = map
    const resize = new ResizeObserver(() => map.invalidateSize())
    resize.observe(elRef.current)
    return () => {
      resize.disconnect()
      map.remove()
    }
  }, [])

  useEffect(() => {
    if (!geojson) return
    const grid = L.geoJSON(geojson, {
      renderer: L.canvas({ padding: 0.5 }),
      style: { weight: 0, fillColor: NO_DATA, fillOpacity: 0.8 },
      onEachFeature: (f, layer) => layer.on('click', () => latest.current.onSelect(f)),
    })
      .bindTooltip(
        (l) => `Ước tính: <b>${fmt(latest.current.values.get(l.feature.properties.grid_id))} µg/m³</b>`,
        { sticky: true },
      )
      .addTo(mapRef.current)
    gridRef.current = grid
    mapRef.current.fitBounds(grid.getBounds())
    return () => {
      grid.remove()
      gridRef.current = null
    }
  }, [geojson])

  useEffect(() => {
    if (!gridRef.current) return
    gridRef.current.setStyle((f) => {
      const selected = f.properties.grid_id === selectedId
      return {
        fillColor: colorFor(values.get(f.properties.grid_id)),
        weight: selected ? 2.5 : 0,
        color: '#111827',
      }
    })
    gridRef.current.eachLayer((l) => {
      if (l.feature.properties.grid_id === selectedId) l.bringToFront()
    })
    gridRef.current.getTooltip()?.update() // tooltip đang mở không được giữ giá trị ngày cũ
  }, [geojson, values, selectedId])

  useEffect(() => {
    const group = stationsRef.current
    group.clearLayers()
    for (const s of stations ?? []) {
      L.circleMarker([s.latitude, s.longitude], stationStyle(s))
        .bindTooltip(`Trạm: ${esc(s.station_name)}`)
        .bindPopup(stationPopup(s, values.get(s.grid_id)))
        .addTo(group)
    }
  }, [stations, values])

  return <div ref={elRef} className="isolate h-full w-full" aria-label="Bản đồ lưới PM2.5 Hà Nội" />
}
