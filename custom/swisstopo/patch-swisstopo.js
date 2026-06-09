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
const originalProviderControlTail =
  'c.innerHTML="Apply",t.DomEvent.on(c,"click",function(t){' +
  'n.onCustomProviderClick(t,l.value)})},setProviderRadioButton:function(t,e){';
const altitudeProviderControlTail = [
  'c.innerHTML="Apply",t.DomEvent.on(c,"click",function(t){',
  'n.onCustomProviderClick(t,l.value)})},',
  'createAltitudeControls:function(e){',
  'window.__webodmCompareAltitudes="boolean"==',
  'typeof window.__webodmCompareAltitudes?window.__webodmCompareAltitudes:!0;',
  'var n=t.DomUtil.create("div","swisstopo-altitude-controls",e);',
  'n.style.padding="8px 10px",n.style.borderTop="1px solid #ddd",',
  'n.style.background="#fff",n.style.color="#333";',
  'var i=t.DomUtil.create("label","",n);',
  'i.style.display="flex",i.style.alignItems="center",i.style.gap="6px",',
  'i.style.cursor="pointer";',
  'var o=t.DomUtil.create("input","",i);',
  'o.type="checkbox",o.checked=window.__webodmCompareAltitudes,',
  'o.setAttribute("data-testid","compare-gcp-altitudes");',
  'var r=t.DomUtil.create("span","",i);',
  'r.style.color="#333",',
  'r.innerHTML="Comparer les altitudes \\u00e0 la vol\\u00e9e";',
  'var a=t.DomUtil.create("button","btn",n);',
  'a.type="button",a.style.width="100%",a.style.marginTop="8px",',
  'a.style.padding="8px",a.style.color="#333",a.style.background="#f5f5f5",',
  'a.style.border="1px solid #bbb",a.style.borderRadius="2px",',
  'a.innerHTML="Contr\\u00f4ler tous les GCP",',
  'a.setAttribute("data-testid","check-all-gcp-altitudes"),',
  't.DomEvent.on(o,"change",function(e){',
  't.DomEvent.stop(e),window.__webodmCompareAltitudes=o.checked',
  '}).on(a,"click",function(e){',
  'if(t.DomEvent.stop(e),"function"==typeof window.__webodmCheckAllGcpAltitudes){',
  'var n=a.innerHTML;a.disabled=!0,a.innerHTML="Contr\\u00f4le en cours...";',
  'var i=function(){a.disabled=!1,a.innerHTML=n};',
  'Promise.resolve(window.__webodmCheckAllGcpAltitudes()).then(i,function(t){',
  'window.console&&console.warn("Impossible de controler les altitudes GCP",t),',
  'window.alert("Le contr\\u00f4le des altitudes a \\u00e9chou\\u00e9."),i()',
  '})}})},setProviderRadioButton:function(t,e){'
].join('');
const originalProviderControlMount =
  'this.createCustomButton(s),t.DomEvent.on(o,"click",function(t){';
const altitudeProviderControlMount =
  'this.createCustomButton(s),this.createAltitudeControls(s),' +
  't.DomEvent.on(o,"click",function(t){';
const originalLeafletMapBinding =
  't.onMarkerToggle=t.onMarkerToggle.bind(t),' +
  't.onMapClick=t.onMapClick.bind(t),t.state={leafletMap:null}';
const altitudeLeafletMapBinding =
  't.onMarkerToggle=t.onMarkerToggle.bind(t),' +
  't.onMapClick=t.onMapClick.bind(t),' +
  't.checkAllGcpAltitudes=t.checkAllGcpAltitudes.bind(t),' +
  't.state={leafletMap:null}';
const originalLeafletMapMount =
  '{key:"componentDidMount",value:function(){this.initializeMap()}},';
const altitudeLeafletMapMount =
  '{key:"componentDidMount",value:function(){this.initializeMap(),' +
  'window.__webodmCheckAllGcpAltitudes=this.checkAllGcpAltitudes}},' +
  '{key:"componentWillUnmount",value:function(){' +
  'window.__webodmCheckAllGcpAltitudes===this.checkAllGcpAltitudes&&' +
  'delete window.__webodmCheckAllGcpAltitudes}},';
const originalMarkerToggle =
  '{key:"onMarkerToggle",value:function(t,e,n){var i=this.props,' +
  'o=i.toggleControlPointMode,r=i.controlpoints,a=i.setPointProperties,' +
  's=i.joinControlPoint;return r.mode===b.CP_MODES.ADDING?' +
  'a(!1,null,null,null,t,[n.lat,n.lng]):r.mode===b.CP_MODES.IMAGE_EDIT?' +
  's(t):void o(t)}}';
const altitudeMarkerToggle = [
  '{key:"getSwisstopoElevation",value:function(t){',
  'if(!window.__webodmGcpProj4)',
  'return Promise.reject(new Error("Proj4 EPSG:2056 indisponible"));',
  'var e=window.__webodmGcpProj4("EPSG:4326","EPSG:2056",',
  '[t.coord[1],t.coord[0]]),n=e[0],i=e[1];',
  `return fetch("${swisstopoHeightEndpoint}?easting="+encodeURIComponent(n)+`,
  '"&northing="+encodeURIComponent(i)+',
  '"&sr=2056&elevation_model=COMB").then(function(t){',
  'if(!t.ok)throw new Error("HTTP "+t.status);return t.json()',
  '}).then(function(t){var e=parseFloat(t.height);',
  'if(!isFinite(e))throw new Error("Altitude swisstopo invalide");return e})}},',
  '{key:"checkAllGcpAltitudes",value:function(){var t=this,',
  'e=this.props.controlpoints.points.filter(function(t){return"map"===t.type}),',
  'n=e.filter(function(t){return t.coord&&2===t.coord.length&&',
  'isFinite(parseFloat(t.coord[0]))&&isFinite(parseFloat(t.coord[1]))&&',
  'isFinite(parseFloat(t.z))});',
  'if(!n.length)return window.alert("Aucun GCP avec une altitude valide \\u00e0 contr\\u00f4ler."),',
  'Promise.resolve({checked:0,updated:0,failed:e.length});',
  'return Promise.all(n.map(function(e,n){',
  'return t.getSwisstopoElevation(e).then(function(t){',
  'return{point:e,index:n,height:t,current:parseFloat(e.z)}',
  '},function(t){return{point:e,index:n,error:t}})',
  '})).then(function(i){',
  'var o=i.filter(function(t){return!t.error}),',
  'r=i.filter(function(t){return t.error}).length+e.length-n.length,',
  `a=o.filter(function(t){return Math.abs(t.height-t.current)>${elevationTolerance}});`,
  'if(!a.length)return window.alert("Contr\\u00f4le termin\\u00e9 : "+o.length+',
  '" GCP, aucune diff\\u00e9rence sup\\u00e9rieure \\u00e0 0,10 m."+(r?',
  '"\\n"+r+" GCP non contr\\u00f4l\\u00e9(s).":"")),',
  '{checked:o.length,updated:0,failed:r};',
  'var s=a.slice(0,12).map(function(t){',
  'var e=t.point.label||"GCP "+(t.index+1),n=Math.abs(t.height-t.current);',
  'return e+" : "+t.current.toFixed(1)+" m \\u2192 "+',
  't.height.toFixed(1)+" m (\\u0394 "+n.toFixed(1)+" m)"',
  '}).join("\\n"),',
  'u=a.length>12?"\\n... et "+(a.length-12)+" autre(s) GCP.":"",',
  'l="Altitude diff\\u00e9rente pour "+a.length+" GCP sur "+o.length+".\\n\\n"+',
  's+u+(r?"\\n\\n"+r+" GCP non contr\\u00f4l\\u00e9(s).":"")+',
  '"\\n\\nUtiliser les altitudes swisstopo pour ces GCP ?";',
  'return window.confirm(l)&&(a.forEach(function(e){',
  't.props.setControlPointPosition("map",e.point.id,e.point.coord,e.height)',
  '}),{checked:o.length,updated:a.length,failed:r})||',
  '{checked:o.length,updated:0,failed:r}',
  '})}},',
  '{key:"onMarkerToggle",value:function(t,e,n){var i=this.props,',
  'o=i.toggleControlPointMode,r=i.controlpoints,a=i.setPointProperties,',
  's=i.joinControlPoint,u=i.setControlPointPosition;',
  'if(r.mode===b.CP_MODES.ADDING)return a(!1,null,null,null,t,[n.lat,n.lng]);',
  'if(r.mode===b.CP_MODES.IMAGE_EDIT)return s(t);',
  'var l=r.points.find(function(e){return e.id===t}),c=l?parseFloat(l.z):NaN;',
  'if(window.__webodmCompareAltitudes!==!1&&l&&isFinite(c))',
  'this.getSwisstopoElevation(l).then(function(e){var i=e;',
  `if(isFinite(i)&&Math.abs(i-c)>${elevationTolerance}){`,
  'var r=Math.abs(i-c);',
  'window.confirm("Altitude du GCP : "+c.toFixed(1)+" m\\n"+',
  '"Altitude swisstopo : "+i.toFixed(1)+" m\\n"+',
  '"Diff\\u00e9rence : "+r.toFixed(1)+" m\\n\\n"+',
  '"Utiliser l\'altitude swisstopo ?")&&',
  'u("map",t,l.coord,i)}}).catch(function(t){',
  'window.console&&console.warn("Impossible de recuperer l\'altitude swisstopo",t)',
  '});',
  'o(t)}}'
].join('');
const altitudePatchMarker = 'data-testid","check-all-gcp-altitudes';

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

  if (bundle.includes(originalPositionAction)) {
    bundle = bundle.replace(originalPositionAction, altitudePositionAction);
    changed = true;
  } else if (!bundle.includes('altitude:arguments.length>3?arguments[3]:void 0')) {
      throw new Error('Could not locate the GCPI point position action');
  }

  if (bundle.includes(originalPositionReducer)) {
    bundle = bundle.replace(originalPositionReducer, altitudePositionReducer);
    changed = true;
  } else if (!bundle.includes('z:void 0===e.altitude?t.z:e.altitude')) {
      throw new Error('Could not locate the GCPI point position reducer');
  }

  if (!bundle.includes(altitudePatchMarker)) {
    if (!bundle.includes(originalMarkerToggle)) {
      throw new Error('Could not locate the GCPI map marker selection handler');
    }

    if (!bundle.includes(originalProviderControlTail) ||
        !bundle.includes(originalProviderControlMount)) {
      throw new Error('Could not locate the GCPI map provider control');
    }

    if (!bundle.includes(originalLeafletMapBinding) ||
        !bundle.includes(originalLeafletMapMount)) {
      throw new Error('Could not locate the GCPI map component lifecycle');
    }

    bundle = bundle
      .replace(originalProviderControlTail, altitudeProviderControlTail)
      .replace(originalProviderControlMount, altitudeProviderControlMount)
      .replace(originalLeafletMapBinding, altitudeLeafletMapBinding)
      .replace(originalLeafletMapMount, altitudeLeafletMapMount)
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
