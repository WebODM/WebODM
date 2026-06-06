const fs = require('fs');
const path = require('path');

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
let bundle = fs.readFileSync(bundlePath, 'utf8');
let changed = false;

const provider = [
  '{id:"swisstopo",',
  'label:"SWISSIMAGE (swisstopo)",',
  'url:"https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg",',
  'attribution:"&copy; swisstopo",',
  'maxZoom:20}'
].join('');
const existingProvider = /{id:"swisstopo",label:"SWISSIMAGE \(swisstopo\)",url:"https:\/\/wmts\.geo\.admin\.ch\/1\.0\.0\/ch\.swisstopo\.swissimage\/default\/current\/3857\/{z}\/{x}\/{y}\.jpeg",attribution:"&copy; swisstopo",maxZoom:\d+}/;

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

if (changed) {
  fs.writeFileSync(bundlePath, bundle);
  console.log(`Added SWISSIMAGE overzoom support to ${bundleName}`);
}
