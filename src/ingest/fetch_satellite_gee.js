// Paste into the Earth Engine Code Editor after uploading tv1_grid_1km.csv.
// See docs/satellite_gee_runbook.md. No task starts until Run in the Tasks tab.

var GRID_ASSET = 'projects/YOUR_PROJECT/assets/tv1_grid_1km';
var YEAR = 2021;             // 2021..2025
var QUARTER = 1;             // first quarter in the batch: 1..4
var QUARTERS_PER_RUN = 1;    // 1..4 consecutive quarters
var PILOT_DAYS = 7;          // 7 for a short trial; 0 for complete quarters
var DRIVE_FOLDER = 'hanoi_pm25_gee';
var OUTPUT_REVISION = 'v2';  // v1 single-band daily exports had blank values
var TZ = 'Asia/Ho_Chi_Minh';

var firstQuarterIndex = (YEAR - 2021) * 4 + QUARTER - 1;
if (YEAR < 2021 || YEAR > 2025 || QUARTER < 1 || QUARTER > 4 ||
    QUARTERS_PER_RUN < 1 || QUARTERS_PER_RUN > 4 ||
    firstQuarterIndex + QUARTERS_PER_RUN > 20 ||
    PILOT_DAYS < 0 || PILOT_DAYS > 28) {
  throw new Error('Invalid YEAR, QUARTER, QUARTERS_PER_RUN or PILOT_DAYS');
}
if (GRID_ASSET.indexOf('YOUR_PROJECT') !== -1) {
  throw new Error('Set GRID_ASSET to the uploaded table asset ID first');
}

// Rebuild straight 1 km edges in EPSG:3405 from TV1 IDs after CSV ingestion.
var grid = ee.FeatureCollection(GRID_ASSET).map(function (feature) {
  var id = ee.String(feature.get('grid_id'));
  var parts = id.split('_');
  var x = ee.Number.parse(ee.String(parts.get(1)));
  var y = ee.Number.parse(ee.String(parts.get(2)));
  var square = ee.Geometry.Rectangle(
    [x, y, x.add(1000), y.add(1000)], 'EPSG:3405', false);
  return ee.Feature(square, {grid_id: id});
});
var aoi = grid.geometry().bounds(1000);
var firstMonth = 1 + (QUARTER - 1) * 3;
var firstMonthIndex = YEAR * 12 + firstMonth - 1;
var endMonthIndex = firstMonthIndex + 3 * QUARTERS_PER_RUN;
var endYear = Math.floor(endMonthIndex / 12);
var endMonth = endMonthIndex % 12 + 1;
var lastQuarterIndex = firstQuarterIndex + QUARTERS_PER_RUN - 1;
var lastYear = 2021 + Math.floor(lastQuarterIndex / 4);
var lastQuarter = lastQuarterIndex % 4 + 1;
var start = ee.Date.fromYMD(YEAR, firstMonth, 1, TZ);
var batchEnd = ee.Date.fromYMD(endYear, endMonth, 1, TZ);
var end = PILOT_DAYS > 0 ? start.advance(PILOT_DAYS, 'day') : batchEnd;
var monthCount = PILOT_DAYS > 0 ? 1 : 3 * QUARTERS_PER_RUN;
var tag = YEAR + '_q' + QUARTER +
  (PILOT_DAYS === 0 && QUARTERS_PER_RUN > 1
    ? '_to_' + lastYear + '_q' + lastQuarter : '') +
  (PILOT_DAYS > 0 ? '_pilot' : '') +
  '_' + OUTPUT_REVISION;

// reduceRegions computes polygon means on each source's native projection.
var aodRaw = ee.ImageCollection('MODIS/061/MCD19A2_GRANULES')
  .filterBounds(aoi).filterDate(start, end);
var no2Raw = ee.ImageCollection('COPERNICUS/S5P/OFFL/L3_NO2')
  .filterBounds(aoi).filterDate(start, end);
var viirsRaw = ee.ImageCollection('NOAA/VIIRS/DNB/MONTHLY_V1/VCMCFG')
  .filterBounds(aoi);
var aodProjection = ee.Image(aodRaw.first()).select('Optical_Depth_047').projection();
var no2Projection = ee.Image(no2Raw.first())
  .select('tropospheric_NO2_column_number_density').projection();
var viirsProjection = ee.Image(viirsRaw.first()).select('avg_rad').projection();

// Provisional conservative QA policy: bits 8..11 = 0 (best quality)
// AND bits 0..2 = 1 (clear). The GEE catalog defines these categories;
// the project guide does not prescribe this exact combination.
// The catalog gives raw values and a 0.001 scale factor.
var aod = aodRaw.map(function (image) {
  var value = image.select('Optical_Depth_047');
  var qa = image.select('AOD_QA');
  var best = qa.rightShift(8).bitwiseAnd(15).eq(0);
  var clear = qa.bitwiseAnd(7).eq(1);
  return value.updateMask(best.and(clear))
    .updateMask(value.gte(0).and(value.lte(3500)))
    .multiply(0.001).rename('aod_047_mean')
    .copyProperties(image, ['system:time_start']);
});

// GEE already applied the 0.75 QA threshold for this NO2 L3 band.
// Preserve negative retrievals; they can result from measurement noise.
var no2 = no2Raw.select('tropospheric_NO2_column_number_density')
  .map(function (image) {
    return image.rename('no2_tropospheric_mol_m2')
      .copyProperties(image, ['system:time_start']);
  });

function dailyRows(source, band, projection) {
  var days = end.difference(start, 'day').toInt();
  var chunks = ee.List.sequence(0, days.subtract(1)).map(function (offset) {
    var day = start.advance(ee.Number(offset), 'day');
    var images = source.filterDate(day, day.advance(1, 'day'));
    var empty = ee.Image.constant(0).rename(band).selfMask();
    var image = ee.Image(ee.Algorithms.If(images.size().gt(0), images.mean(), empty));
    var dateId = ee.Number.parse(day.format('YYYYMMdd', TZ));
    var reduced = image.reduceRegions({
      collection: grid,
      // With one input band, reduceRegions uses the reducer output name.
      // Set it explicitly so feature.get(band) reads the computed value.
      reducer: ee.Reducer.mean().setOutputs([band]),
      crs: projection,
      tileScale: 4
    });
    return reduced.map(function (feature) {
      return ee.Feature(null, {
        grid_id: feature.get('grid_id'),
        date_id: dateId,
        source_image_count: images.size()
      }).set(band, feature.get(band));
    });
  });
  return ee.FeatureCollection(chunks).flatten();
}

function viirsRows() {
  var months = [];
  for (var i = 0; i < monthCount; i++) {
    var monthIndex = firstMonthIndex + i;
    var monthYear = Math.floor(monthIndex / 12);
    var month = monthIndex % 12 + 1;
    var monthStart = ee.Date.fromYMD(monthYear, month, 1);
    var images = viirsRaw.filterDate(monthStart, monthStart.advance(1, 'month'));
    var empty = ee.Image.constant([0, 0])
      .rename(['viirs_nightlight_rad', 'viirs_cf_cvg_mean']).selfMask();
    var composite = ee.Image(ee.Algorithms.If(images.size().gt(0),
      ee.Image(images.first()).select('avg_rad')
        .updateMask(ee.Image(images.first()).select('cf_cvg').gt(0))
        .rename('viirs_nightlight_rad')
        .addBands(ee.Image(images.first()).select('cf_cvg')
          .rename('viirs_cf_cvg_mean')),
      empty));
    var reduced = composite.reduceRegions({
      collection: grid,
      reducer: ee.Reducer.mean(),
      crs: viirsProjection,
      tileScale: 4
    });
    var monthId = monthYear * 100 + month;
    months.push(reduced.map(function (feature) {
      return ee.Feature(null, {
        grid_id: feature.get('grid_id'),
        month_id: monthId,
        source_image_count: images.size(),
        viirs_nightlight_rad: feature.get('viirs_nightlight_rad'),
        viirs_cf_cvg_mean: feature.get('viirs_cf_cvg_mean')
      });
    }));
  }
  return ee.FeatureCollection(months).flatten();
}

print('TV1 grid cells (expect 3610)', grid.size());
print('Period (local time)', start, end);
print('Expected rows per daily source', end.difference(start, 'day').multiply(3610));
print('Expected VIIRS rows', monthCount * 3610);
print('Image counts in period', aodRaw.size(), no2Raw.size());

Export.table.toDrive({
  collection: dailyRows(aod, 'aod_047_mean', aodProjection),
  description: 'hanoi_aod_' + tag,
  folder: DRIVE_FOLDER,
  fileNamePrefix: 'hanoi_aod_' + tag,
  fileFormat: 'CSV',
  selectors: ['grid_id', 'date_id', 'source_image_count', 'aod_047_mean']
});
Export.table.toDrive({
  collection: dailyRows(no2, 'no2_tropospheric_mol_m2', no2Projection),
  description: 'hanoi_no2_' + tag,
  folder: DRIVE_FOLDER,
  fileNamePrefix: 'hanoi_no2_' + tag,
  fileFormat: 'CSV',
  selectors: ['grid_id', 'date_id', 'source_image_count', 'no2_tropospheric_mol_m2']
});
Export.table.toDrive({
  collection: viirsRows(),
  description: 'hanoi_viirs_' + tag,
  folder: DRIVE_FOLDER,
  fileNamePrefix: 'hanoi_viirs_' + tag,
  fileFormat: 'CSV',
  selectors: ['grid_id', 'month_id', 'source_image_count',
    'viirs_nightlight_rad', 'viirs_cf_cvg_mean']
});
