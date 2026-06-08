const assert = require('assert');

const {
  epsg2056Definition,
  patchBundleContent
} = require('./patch-swisstopo');

const fixture = [
  'providers:[{id:"bing",useBing:!0}],custom_placeholder:',
  'mapOptions:{maxZoom:23,maxNativeZoom:20},',
  'function preview(a){try{(0,C.default)(a,"EPSG:4326",[0,0])}',
  'catch(l){errors.push("Unknown projection "+a)}}'
].join('');

const first = patchBundleContent(fixture);

assert.strictEqual(first.changed, true);
assert(first.bundle.includes('label:"SWISSIMAGE (swisstopo)"'));
assert(first.bundle.includes('maxZoom:28,maxNativeZoom:20'));
assert(first.bundle.includes(`C.default.defs("EPSG:2056","${epsg2056Definition}")`));
assert(first.bundle.includes('(0,C.default)(a,"EPSG:4326",[0,0])'));

const second = patchBundleContent(first.bundle);

assert.strictEqual(second.changed, false);
assert.strictEqual(second.bundle, first.bundle);

assert.throws(
  () => patchBundleContent(
    fixture.replace(
      'try{(0,C.default)(a,"EPSG:4326",[0,0])}catch(l){',
      'try{validateProjection(a)}catch(l){'
    )
  ),
  /Could not locate the GCPI projection validation/
);

console.log('SWISSIMAGE and EPSG:2056 bundle patch tests passed');
