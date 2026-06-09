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
const proj4GlobalMarker = 'window.__webodmGcpProj4=';
const projectionValidationPattern =
  /try\{\(0,([A-Za-z_$][\w$]*)\.default\)\(([A-Za-z_$][\w$]*),"EPSG:4326",\[0,0\]\)\}catch\(([A-Za-z_$][\w$]*)\)\{/;
const swisstopoHeightEndpoint =
  'https://api3.geo.admin.ch/rest/services/height';
const elevationTolerance = 0.1;
const originalPositionAction =
  'function v(t,e,n){return{type:z,loc:t,id:e,pos:n}}';
const altitudePositionAction =
  'function v(t,e,n){return{type:z,loc:t,id:e,pos:n,' +
  'altitude:arguments.length>3?arguments[3]:void 0}}';
const originalPositionReducer =
  'E=function(t,e){return u({},t,{points:t.points.map(function(t,n){' +
  'return e.id===t.id?u({},t,{coord:e.pos}):t})})}';
const altitudePositionReducer =
  'E=function(t,e){return u({},t,{points:t.points.map(function(t,n){' +
  'return e.id===t.id?u({},t,{coord:e.pos,' +
  'z:void 0===e.altitude?t.z:e.altitude}):t})})}';
const originalMarkerToggle =
  '{key:"onMarkerToggle",value:function(t,e,n){var i=this.props,' +
  'o=i.toggleControlPointMode,r=i.controlpoints,a=i.setPointProperties,' +
  's=i.joinControlPoint;return r.mode===b.CP_MODES.ADDING?' +
  'a(!1,null,null,null,t,[n.lat,n.lng]):r.mode===b.CP_MODES.IMAGE_EDIT?' +
  's(t):void o(t)}}';
const altitudeMarkerToggle = [
  '{key:"onMarkerToggle",value:function(t,e,n){var i=this.props,',
  'o=i.toggleControlPointMode,r=i.controlpoints,a=i.setPointProperties,',
  's=i.joinControlPoint,u=i.setControlPointPosition;',
  'if(r.mode===b.CP_MODES.ADDING)return a(!1,null,null,null,t,[n.lat,n.lng]);',
  'if(r.mode===b.CP_MODES.IMAGE_EDIT)return s(t);',
  'var l=r.points.find(function(e){return e.id===t}),c=l?parseFloat(l.z):NaN;',
  'if(l&&isFinite(c)&&window.__webodmGcpProj4)try{',
  'var h=window.__webodmGcpProj4("EPSG:4326","EPSG:2056",[n.lng,n.lat]),',
  'p=h[0],d=h[1];',
  `fetch("${swisstopoHeightEndpoint}?easting="+encodeURIComponent(p)+`,
  '"&northing="+encodeURIComponent(d)+',
  '"&sr=2056&elevation_model=COMB").then(function(t){',
  'if(!t.ok)throw new Error("HTTP "+t.status);return t.json()',
  '}).then(function(e){var i=parseFloat(e.height);',
  `if(isFinite(i)&&Math.abs(i-c)>${elevationTolerance}){`,
  'var o=Math.abs(i-c);',
  'window.confirm("Altitude du GCP : "+c.toFixed(1)+" m\\n"+',
  '"Altitude swisstopo : "+i.toFixed(1)+" m\\n"+',
  '"Diff\\u00e9rence : "+o.toFixed(1)+" m\\n\\n"+',
  '"Utiliser l\'altitude swisstopo ?")&&',
  'u("map",t,[n.lat,n.lng],i)}}).catch(function(t){',
  'window.console&&console.warn("Impossible de recuperer l\'altitude swisstopo",t)',
  '})}catch(f){window.console&&',
  'console.warn("Impossible de calculer les coordonnees EPSG:2056",f)}',
  'o(t)}}'
].join('');
const altitudePatchMarker = 'elevation_model=COMB';

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
        `try{window.__webodmGcpProj4=${proj4Module}.default;` +
        `${proj4Module}.default.defs("EPSG:2056","${epsg2056Definition}");` +
        `(0,${proj4Module}.default)(${sourceProjection},"EPSG:4326",[0,0])}` +
        `catch(${errorVariable}){`
    );
    changed = true;
  } else if (!bundle.includes(proj4GlobalMarker)) {
    const existingDefinitionPattern =
      /([A-Za-z_$][\w$]*)\.default\.defs\("EPSG:2056",/;

    if (!existingDefinitionPattern.test(bundle)) {
      throw new Error('Could not expose the GCPI Proj4 instance');
    }

    bundle = bundle.replace(
      existingDefinitionPattern,
      (match, proj4Module) =>
        `window.__webodmGcpProj4=${proj4Module}.default;${match}`
    );
    changed = true;
  }

  if (!bundle.includes(altitudePatchMarker)) {
    if (!bundle.includes(originalPositionAction)) {
      throw new Error('Could not locate the GCPI point position action');
    }

    if (!bundle.includes(originalPositionReducer)) {
      throw new Error('Could not locate the GCPI point position reducer');
    }

    if (!bundle.includes(originalMarkerToggle)) {
      throw new Error('Could not locate the GCPI map marker selection handler');
    }

    bundle = bundle
      .replace(originalPositionAction, altitudePositionAction)
      .replace(originalPositionReducer, altitudePositionReducer)
      .replace(originalMarkerToggle, altitudeMarkerToggle);
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
    console.log(
      `Added SWISSIMAGE, EPSG:2056 and swisstopo elevation support to ${bundleName}`
    );
  }
}

if (require.main === module) {
  patchInstalledBundle();
}

module.exports = {
  elevationTolerance,
  epsg2056Definition,
  patchBundleContent,
  swisstopoHeightEndpoint
};
