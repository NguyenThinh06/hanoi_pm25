// Paste into a NEW Earth Engine Code Editor script. No export tasks are created.
// Replace GRID_ASSET with the same asset ID used by fetch_satellite_gee.js.

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
var box = grid.geometry().bounds(1000);
var timezone = 'Asia/Ho_Chi_Minh';
var source = ee.ImageCollection('MODIS/061/MCD19A2_GRANULES')
  .filterBounds(box);

function cellsWithAod(image, projection, scale) {
  var options = {
    collection: grid,
    reducer: ee.Reducer.mean().setOutputs(['aod_047_mean']),
    crs: projection,
    tileScale: 4
  };
  if (scale !== null) options.scale = scale;
  var values = image.reduceRegions(options)
    .filter(ee.Filter.notNull(['aod_047_mean']));
  return ee.Dictionary({
    cells: values.size(),
    example_grid_ids: values.limit(10).aggregate_array('grid_id')
  });
}

function audit(year, month, day, batchStartMonth, batchMonths) {
  // Match the first-image projection chosen by the corresponding CSV batch.
  var batchStart = ee.Date.fromYMD(year, batchStartMonth, 1, timezone);
  var raw = source.filterDate(batchStart,
    batchStart.advance(batchMonths, 'month'));
  var nativeProjection = ee.Image(raw.first())
    .select('Optical_Depth_047').projection();
  var begin = ee.Date.fromYMD(year, month, day, timezone);
  var accepted = raw.filterDate(begin, begin.advance(1, 'day'))
    .map(function (image) {
      var value = image.select('Optical_Depth_047');
      var qa = image.select('AOD_QA');
      var best = qa.rightShift(8).bitwiseAnd(15).eq(0);
      var clear = qa.bitwiseAnd(7).eq(1);
      return value.updateMask(best.and(clear))
        .updateMask(value.gte(0).and(value.lte(3500)))
        .multiply(0.001).rename('aod_047_mean')
        .copyProperties(image, ['system:time_start']);
    });
  var daily = accepted.mean();
  var label = year + '-' + ('0' + month).slice(-2) + '-' +
    ('0' + day).slice(-2);
  print(label + ' — polygon TV1, projection gốc như CSV',
    cellsWithAod(daily, nativeProjection, null));
  print(label + ' — polygon TV1, lưới EPSG:3405 1 km',
    cellsWithAod(daily, 'EPSG:3405', 1000));
}

print('Số ô TV1 (phải là 3610)', grid.size());
audit(2021, 5, 10, 4, 3);  // CSV Q2: 2,593 cells with AOD
audit(2021, 5, 20, 4, 3);  // CSV Q2: 0 cells with AOD
audit(2024, 5, 10, 1, 12); // CSV 2024: 0 cells with AOD
audit(2024, 7, 15, 1, 12); // CSV 2024: 0 cells with AOD
