import assert from 'node:assert/strict'
import { test } from 'node:test'
import { BINS, NO_DATA, binLabel, colorFor, dayNum, fmtDate, nearestDate, yearWindow } from './lib.js'

test('thang màu: biên thuộc bin trên, thiếu dữ liệu không thành 0', () => {
  assert.equal(colorFor(0), BINS[0].color)
  assert.equal(colorFor(14.99), BINS[0].color)
  assert.equal(colorFor(15), BINS[1].color)
  assert.equal(colorFor(1000), BINS.at(-1).color)
  assert.equal(colorFor(null), NO_DATA)
  assert.equal(colorFor(undefined), NO_DATA)
})

test('nhãn chú giải', () => {
  assert.equal(binLabel(0), '< 15')
  assert.equal(binLabel(2), '25–37.5')
  assert.equal(binLabel(BINS.length - 1), '≥ 150')
})

test('ngày không lệch múi giờ', () => {
  assert.equal(dayNum('2024-03-01') - dayNum('2024-02-29'), 1)
  assert.equal(fmtDate('2024-01-15'), '15/01/2024')
})

test('nearestDate chọn ngày kế tiếp, hết thì ngày cuối', () => {
  const d = ['2024-01-01', '2024-01-03']
  assert.equal(nearestDate(d, '2024-01-02'), '2024-01-03')
  assert.equal(nearestDate(d, '2023-01-01'), '2024-01-01')
  assert.equal(nearestDate(d, '2025-01-01'), '2024-01-03')
})

test('yearWindow kẹp theo min/max và không vượt 366 ngày', () => {
  assert.deepEqual(yearWindow('2026-05-01', '2021-01-01', '2026-09-30'), ['2026-01-01', '2026-09-30'])
  assert.deepEqual(yearWindow('2024-06-01', '2024-01-05', '2024-01-31'), ['2024-01-05', '2024-01-31'])
  const [s, e] = yearWindow('2024-06-01', '2021-01-01', '2026-09-30')
  assert.ok(dayNum(e) - dayNum(s) + 1 <= 366)
})
