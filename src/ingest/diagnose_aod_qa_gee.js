// Paste into a NEW Earth Engine Code Editor script; this creates no export tasks.
// Set GRID_ASSET to the same TV1 asset used by fetch_satellite_gee.js.
// Compare AOD coverage under separate QA conditions, without changing exports.

var GRID_ASSET = 'projects/YOUR_PROJECT/assets/tv1_grid_1km';
if (GRID_ASSET.indexOf('YOUR_PROJECT') !== -1) {
  throw new Error('Set GRID_ASSET first');
}

var grid = ee.FeatureCollection(GRID_ASSET).map(function (feature) {
  var id = ee.String(feature.get('grid_id'));
  var parts = id.split('_');
  var x = ee.Number.parse(ee.String(parts.get(1)));
  var y = ee.Number.parse(ee.String(parts.get(2)));
  return ee.Feature(ee.Geometry.Rectangle(
    [x, y, x.add(1000), y.add(1000)], 'EPSG:3405', false),
    {grid_id: id});
});

var timezone = 'Asia/Ho_Chi_Minh';
var start = ee.Date.fromYMD(2024, 1, 1, timezone);
var end = ee.Date.fromYMD(2025, 1, 1, timezone);
var raw = ee.ImageCollection('MODIS/061/MCD19A2_GRANULES')
  .filterBounds(grid.geometry().bounds(1000)).filterDate(start, end);
// Match the native projection selected by the full-year 2024 export.
var nativeProjection = ee.Image(raw.first())
  .select('Optical_Depth_047').projection();

function policyBands(image) {
  var value = image.select('Optical_Depth_047');
  var qa = image.select('AOD_QA');
  var qaCode = qa.rightShift(8).bitwiseAnd(15);
  var best = qaCode.eq(0);
  var clear = qa.bitwiseAnd(7).eq(1);
  var rawAod = value.multiply(0.001);
  var range = rawAod.updateMask(value.gte(0).and(value.lte(3500)));
  return ee.Image.cat([
    rawAod.rename('raw_native'),
    range.rename('range_only'),
    range.updateMask(best).rename('best_only'),
    range.updateMask(clear).rename('clear_only'),
    range.updateMask(best.and(clear)).rename('best_and_clear'),
    range.updateMask(clear.and(qaCode.eq(3))).rename('clear_qa3'),
    range.updateMask(clear.and(qaCode.eq(4))).rename('clear_qa4'),
    range.updateMask(clear.and(qaCode.eq(11))).rename('clear_qa11'),
    range.updateMask(clear.and(qaCode.neq(0))
      .and(qaCode.neq(3)).and(qaCode.neq(4))
      .and(qaCode.neq(11))).rename('clear_other_qa')
  ]).copyProperties(image, ['system:time_start']);
}

function audit(month, day, expectedStrictCells) {
  var begin = ee.Date.fromYMD(2024, month, day, timezone);
  var dayRaw = raw.filterDate(begin, begin.advance(1, 'day'));
  var daily = dayRaw.map(policyBands).mean();
  var reduced = daily.reduceRegions({
    collection: grid,
    reducer: ee.Reducer.mean(),
    crs: nativeProjection,
    tileScale: 4
  });
  var label = '2024-' + ('0' + month).slice(-2) + '-' +
    ('0' + day).slice(-2);
  print(label + ' — số ô TV1 theo từng điều kiện AOD', ee.Dictionary({
    images_intersecting_box: dayRaw.size(),
    raw_native: reduced.filter(ee.Filter.notNull(['raw_native'])).size(),
    range_only: reduced.filter(ee.Filter.notNull(['range_only'])).size(),
    best_only: reduced.filter(ee.Filter.notNull(['best_only'])).size(),
    clear_only: reduced.filter(ee.Filter.notNull(['clear_only'])).size(),
    best_and_clear: reduced.filter(ee.Filter.notNull(['best_and_clear'])).size(),
    clear_qa3: reduced.filter(ee.Filter.notNull(['clear_qa3'])).size(),
    clear_qa4: reduced.filter(ee.Filter.notNull(['clear_qa4'])).size(),
    clear_qa11: reduced.filter(ee.Filter.notNull(['clear_qa11'])).size(),
    clear_other_qa: reduced.filter(ee.Filter.notNull(['clear_other_qa'])).size(),
    expected_best_and_clear_from_csv: expectedStrictCells
  }));
}

print('Số ô TV1 (phải là 3610)', grid.size());
audit(5, 10, 0);
audit(5, 29, 119);
audit(6, 1, 307);
audit(7, 15, 0);
audit(7, 16, 263);
