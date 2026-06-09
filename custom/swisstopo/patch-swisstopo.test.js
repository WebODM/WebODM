const assert = require('assert');

const {
  elevationTolerance,
  epsg2056Definition,
  patchBundleContent,
  swisstopoHeightEndpoint
} = require('./patch-swisstopo');

const fixture = [
  'providers:[{id:"bing",useBing:!0}],custom_placeholder:',
  'mapOptions:{maxZoom:23,maxNativeZoom:20},',
  'c.innerHTML="Apply",t.DomEvent.on(c,"click",function(t){',
  'n.onCustomProviderClick(t,l.value)})},setProviderRadioButton:function(t,e){',
  'this.createCustomButton(s),t.DomEvent.on(o,"click",function(t){',
  'function preview(a){try{(0,C.default)(a,"EPSG:4326",[0,0])}',
  'catch(l){errors.push("Unknown projection "+a)}}',
  'function v(t,e,n){return{type:z,loc:t,id:e,pos:n}}',
  'E=function(t,e){return u({},t,{points:t.points.map(function(t,n){',
  'return e.id===t.id?u({},t,{coord:e.pos}):t})})}',
  't.onMarkerToggle=t.onMarkerToggle.bind(t),',
  't.onMapClick=t.onMapClick.bind(t),t.state={leafletMap:null}',
  '{key:"componentDidMount",value:function(){this.initializeMap()}},',
  '{key:"onMarkerToggle",value:function(t,e,n){var i=this.props,',
  'o=i.toggleControlPointMode,r=i.controlpoints,a=i.setPointProperties,',
  's=i.joinControlPoint;return r.mode===b.CP_MODES.ADDING?',
  'a(!1,null,null,null,t,[n.lat,n.lng]):r.mode===b.CP_MODES.IMAGE_EDIT?',
  's(t):void o(t)}}'
].join('');

const first = patchBundleContent(fixture);

assert.strictEqual(first.changed, true);
assert(first.bundle.includes('label:"SWISSIMAGE (swisstopo)"'));
assert(first.bundle.includes('maxZoom:28,maxNativeZoom:20'));
assert(first.bundle.includes('window.__webodmGcpProj4=C.default'));
assert(first.bundle.includes(`C.default.defs("EPSG:2056","${epsg2056Definition}")`));
assert(first.bundle.includes('(0,C.default)(a,"EPSG:4326",[0,0])'));
assert(first.bundle.includes(swisstopoHeightEndpoint));
assert(first.bundle.includes('elevation_model=COMB'));
assert(first.bundle.includes(`Math.abs(i-c)>${elevationTolerance}`));
assert(first.bundle.includes('Altitude swisstopo :'));
assert(first.bundle.includes('data-testid","compare-gcp-altitudes'));
assert(first.bundle.includes('data-testid","check-all-gcp-altitudes'));
assert(first.bundle.includes('window.__webodmCompareAltitudes!==!1'));
assert(first.bundle.includes('window.__webodmCheckAllGcpAltitudes'));
assert(first.bundle.includes('checkAllGcpAltitudes'));
assert(first.bundle.includes('Contr\\u00f4ler tous les GCP'));
assert(first.bundle.includes('Utiliser les altitudes swisstopo pour ces GCP ?'));
assert(first.bundle.includes('altitude:arguments.length>3?arguments[3]:void 0'));
assert(first.bundle.includes('z:void 0===e.altitude?t.z:e.altitude'));
assert(first.bundle.includes('u("map",t,l.coord,i)'));
assert(first.bundle.includes(
  't.props.setControlPointPosition("map",e.point.id,e.point.coord,e.height)'
));

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

assert.throws(
  () => patchBundleContent(
    fixture.replace(
      'function v(t,e,n){return{type:z,loc:t,id:e,pos:n}}',
      'function positionActionChanged(){}'
    )
  ),
  /Could not locate the GCPI point position action/
);

console.log('SWISSIMAGE, EPSG:2056 and elevation bundle patch tests passed');
