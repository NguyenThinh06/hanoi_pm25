// Paste into a NEW Earth Engine Code Editor script. This creates no export tasks.
// Compare 2021 and 2024 days with and without valid AOD/NO2 retrievals.

var box = ee.Geometry.Rectangle(
  [528000, 2273000, 607000, 2367000], 'EPSG:3405', false);
var timezone = 'Asia/Ho_Chi_Minh';
var aodSource = ee.ImageCollection('MODIS/061/MCD19A2_GRANULES')
  .filterBounds(box);
var no2Source = ee.ImageCollection('COPERNICUS/S5P/OFFL/L3_NO2')
  .filterBounds(box);

// Count non-masked 1 km analysis pixels inside the TV1 bounding box.
function pixels(image, band) {
  return image.reduceRegion({
    reducer: ee.Reducer.count(),
    geometry: box,
    crs: 'EPSG:3405',
    scale: 1000,
    maxPixels: 1000000,
    tileScale: 4
  }).get(band);
}

function audit(year, month, day) {
  var begin = ee.Date.fromYMD(year, month, day, timezone);
  var finish = begin.advance(1, 'day');
  var aodImages = aodSource.filterDate(begin, finish);
  var no2Images = no2Source.filterDate(begin, finish);

  var rawAod = aodImages.select('Optical_Depth_047').mean()
    .rename('raw_aod');
  var bestClear = aodImages.map(function (image) {
    var qa = image.select('AOD_QA');
    return qa.rightShift(8).bitwiseAnd(15).eq(0)
      .and(qa.bitwiseAnd(7).eq(1))
      .selfMask().rename('best_clear');
  }).max();
  var acceptedAod = aodImages.map(function (image) {
    var raw = image.select('Optical_Depth_047');
    var qa = image.select('AOD_QA');
    var quality = qa.rightShift(8).bitwiseAnd(15).eq(0)
      .and(qa.bitwiseAnd(7).eq(1));
    return raw.updateMask(quality)
      .updateMask(raw.gte(0).and(raw.lte(3500)))
      .multiply(0.001).rename('accepted_aod');
  }).mean();

  var no2 = no2Images.select('tropospheric_NO2_column_number_density')
    .mean().rename('no2');
  var no2CloudFraction = no2Images.select('cloud_fraction')
    .mean().rename('cloud_fraction');

  var label = year + '-' + ('0' + month).slice(-2) + '-' +
    ('0' + day).slice(-2);
  print(label + ' (ngày Hà Nội)', ee.Dictionary({
    aod_images_intersecting_box: aodImages.size(),
    aod_raw_pixels: pixels(rawAod, 'raw_aod'),
    aod_best_clear_qa_pixels: pixels(bestClear, 'best_clear'),
    aod_accepted_pixels: pixels(acceptedAod, 'accepted_aod'),
    no2_images_intersecting_box: no2Images.size(),
    no2_l3_tropospheric_pixels: pixels(no2, 'no2'),
    no2_cloud_fraction_pixels: pixels(no2CloudFraction, 'cloud_fraction')
  }));
}

audit(2021, 1, 1);
audit(2021, 3, 15);
audit(2021, 5, 10);
audit(2021, 5, 20);
audit(2024, 5, 10);
audit(2024, 7, 15);
