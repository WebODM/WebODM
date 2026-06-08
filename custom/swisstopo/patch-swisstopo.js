const fs = require('fs');
const path = require('path');

const provider = [
  '{id:"swisstopo",',
  'label:"SWISSIMAGE (swisstopo)",',
  'url:"https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg",',
  'attribution:"&copy; swisstopo",',
  'maxZoom:20}'
].join('');
const existingProvider = /{id:"swisstopo",label:"SWISSIMAGE \(swisstopo\)",url:"https:\/\/wmts\.geo\.admin\.ch\/1\.0\.0\/ch\.swisstopo\.swissimage\/default\/current\/3857\/{z}\/{x}\/{y}\.jpeg",attribution:"&copy; swisstopo",maxZoom:\d+}/;
const epsg2056Definition = [
  '+proj=somerc',
  '+lat_0=46.95240555555556',
  '+lon_0=7.439583333333333',
  '+k_0=1',
  '+x_0=2600000',
  '+y_0=1200000',
  '+ellps=bessel',
  '+towgs84=674.374,15.056,405.346,0,0,0,0',
  '+units=m',
  '+no_defs'
].join(' ');
const epsg2056Marker = '.defs("EPSG:2056",';
const projectionValidationPattern =
  /try\{\(0,([A-Za-z_$][\w$]*)\.default\)\(([A-Za-z_$][\w$]*),"EPSG:4326",\[0,0\]\)\}catch\(([A-Za-z_$][\w$]*)\)\{/;

function patchBundleContent(input) {
  let bundle = input;
  let changed = false;

  if (existingProvider.test(bundle)) {
    const updatedBundle = bundle.replace(existingProvider, provider);
    changed = changed || updatedBundle !== bundle;
    bundle = updatedBundle;
  } else {
    const marker = 'useBing:!0}],custom_placeholder:';

    if (!bundle.includes(marker)) {
      throw new Error('Could not locate the map provider configuration in the GCPI bundle');
    }

    bundle = bundle.replace(
      marker,
      `useBing:!0},${provider}],custom_placeholder:`
    );
    changed = true;
  }

  const defaultMapZoom = 'maxZoom:23,maxNativeZoom:';
  const overzoomMapZoom = 'maxZoom:28,maxNativeZoom:';

  if (bundle.includes(defaultMapZoom)) {
    bundle = bundle.split(defaultMapZoom).join(overzoomMapZoom);
    changed = true;
  } else if (!bundle.includes(overzoomMapZoom)) {
    throw new Error('Could not locate the GCPI map zoom configuration');
  }

  if (!bundle.includes(epsg2056Marker)) {
    if (!projectionValidationPattern.test(bundle)) {
      throw new Error('Could not locate the GCPI projection validation');
    }

    bundle = bundle.replace(
      projectionValidationPattern,
      (match, proj4Module, sourceProjection, errorVariable) =>
        `try{${proj4Module}.default.defs("EPSG:2056","${epsg2056Definition}");` +
        `(0,${proj4Module}.default)(${sourceProjection},"EPSG:4326",[0,0])}` +
        `catch(${errorVariable}){`
    );
    changed = true;
  }

  return { bundle, changed };
}

function patchInstalledBundle() {
  const bundleDirectory = path.join(
    __dirname,
    'node_modules',
    'webodm-posm-gcpi',
    'static',
    'js'
  );
  const bundleName = fs
    .readdirSync(bundleDirectory)
    .find(name => /^main\..+\.js$/.test(name));

  if (!bundleName) {
    throw new Error('Could not find the webodm-posm-gcpi JavaScript bundle');
  }

  const bundlePath = path.join(bundleDirectory, bundleName);
  const result = patchBundleContent(fs.readFileSync(bundlePath, 'utf8'));

  if (result.changed) {
    fs.writeFileSync(bundlePath, result.bundle);
    console.log(`Added SWISSIMAGE overzoom and EPSG:2056 support to ${bundleName}`);
  }
}

if (require.main === module) {
  patchInstalledBundle();
}

module.exports = {
  epsg2056Definition,
  patchBundleContent
};
