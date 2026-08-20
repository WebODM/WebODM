import React from 'react';
import ReactDOM from 'ReactDOM';
import '../css/Map.scss';
import 'leaflet/dist/leaflet.css';
import Leaflet from 'leaflet';
import async from 'async';
import '../vendor/leaflet/Leaflet.Autolayers/css/leaflet.auto-layers.css';
import '../vendor/leaflet/Leaflet.Autolayers/leaflet-autolayers';
// import '../vendor/leaflet/L.TileLayer.NoGap';
import Dropzone from '../vendor/dropzone';
import $ from 'jquery';
import ErrorMessage from './ErrorMessage';
import ImagePopup from './ImagePopup';
import GCPPopup from './GCPPopup';
import MediaView from './MediaView';
import SwitchModeButton from './SwitchModeButton';
import ShareButton from './ShareButton';
import {addOverlayLayer, buildOverlay, recomputeOverlayBounds} from '../classes/OverlayLayer';
import FormDialog from './FormDialog';
import PropTypes from 'prop-types';
import PluginsAPI from '../classes/plugins/API';

import Standby from './Standby';
import LayersControl from './LayersControl';
import AssetDownloadButtons from './AssetDownloadButtons';
import CropButton from './CropButton';
import update from 'immutability-helper';
import ColorMaps from '../classes/ColorMaps';
import Utils from '../classes/Utils';
import 'rbush';
import '../vendor/leaflet/leaflet-markers-canvas';
import '../vendor/leaflet/Leaflet.SideBySide/leaflet-side-by-side';
import { _, interpolate } from '../classes/gettext';
import UnitSelector from './UnitSelector';
import { unitSystem, toMetric } from '../classes/Units';

const IOU_THRESHOLD = 0.7;

class Map extends React.Component {
  static defaultProps = {
    showBackground: false,
    mapType: "orthophoto",
    public: false,
    publicEdit: false,
    shareButtons: true,
    permissions: ["view"],
    thermal: false,
    basemaps: []
  };

  static propTypes = {
    showBackground: PropTypes.bool,
    tiles: PropTypes.array.isRequired,
    mapType: PropTypes.oneOf(['orthophoto', 'plant', 'dsm', 'dtm']),
    public: PropTypes.bool,
    publicEdit: PropTypes.bool,
    shareButtons: PropTypes.bool,
    permissions: PropTypes.array,
    thermal: PropTypes.bool,
    project: PropTypes.object,
    basemaps: PropTypes.array
  };

  constructor(props) {
    super(props);
    
    this.state = {
      error: "",
      singleTask: null, // When this is set to a task, show a switch mode button to view the 3d model
      pluginActionButtons: [],
      showLoading: false, // for drag&drop of files and first load
      opacity: 100,
      imageryLayers: [],
      overlays: [],
      annotations: [],
      userOverlays: [],
      rightLayers: []
    };

    this.basemaps = {};
    this.mapBounds = null;
    this.overlayUploadCount = 0;
    this.pendingDxfFile = null;
    this.pendingDxfTask = null;
    this.serverStamp = null;
    this.clientStamp = null;
    this.autolayers = null;
    this.taskCount = 1;
    this.addedCameraShots = {};
    this.addedMediaLayer = {};
    this.zIndexGroupMap = {};
    this.ious = {};

    this.loadImageryLayers = this.loadImageryLayers.bind(this);
    this.updatePopupFor = this.updatePopupFor.bind(this);
    this.handleMapMouseDown = this.handleMapMouseDown.bind(this);
  }

  countTasks = () => {
    let tasks = {};
    this.props.tiles.forEach(tile => {
        tasks[tile.meta.task.id] = true;
    });
    return Object.keys(tasks).length;
  }

  updateOpacity = (evt) => {
    this.setState({
      opacity: parseFloat(evt.target.value),
    });
  }

  updatePopupFor(layer){
    const popup = layer.getPopup();
    $('#layerOpacity', popup.getContent()).val(layer.options.opacity);
  }

  tdPopupButtonUrl = (task) => {
    if (this.props.public){
      if (location.href.indexOf("/iframe/") !== -1){
        return `/public/task/${task.id}/iframe/3d/`;
      }else{
        return `/public/task/${task.id}/3d/`;
      }
    }else{
      return `/3d/project/${task.project}/task/${task.id}/`;
    }
  }

  typeToHuman = (type, thermal = false) => {
      switch(type){
          case "orthophoto":
              return _("Orthophoto");
          case "plant":
              return thermal ? _("Thermal") : _("Plant Health");
          case "dsm":
              return _("Surface Model");
          case "dtm":
              return _("Terrain Model");
      }
      return "";
  }

  typeToIcon = (type, thermal = false) => {
    switch(type){
        case "orthophoto":
            return "far fa-image fa-fw"
        case "plant":
            return thermal ? "fa fa-thermometer-half fa-fw" : "fa fa-seedling fa-fw";
        case "dsm":
        case "dtm":
            return "fa fa-chart-area fa-fw";
    }
    return "";
  }

  typeZIndex = (type, zIndexGroup = 1) => {
    return ["dsm", "dtm", "orthophoto", "plant"].indexOf(type) + 1 + zIndexGroup * 10;
  }

  hasBands = (bands, orthophoto_bands) => {
    if (!orthophoto_bands) return false;

    for (let i = 0; i < bands.length; i++){
      if (orthophoto_bands.find(b => b.description !== null && b.description.toLowerCase() === bands[i].toLowerCase()) === undefined) return false;
    }
    
    return true;
  }

  computeIOU = (b1, b2) => {
    const [x1Min, y1Min, x1Max, y1Max] = b1;
    const [x2Min, y2Min, x2Max, y2Max] = b2;
  
    const interXMin = Math.max(x1Min, x2Min);
    const interYMin = Math.max(y1Min, y2Min);
    const interXMax = Math.min(x1Max, x2Max);
    const interYMax = Math.min(y1Max, y2Max);
  
    const interWidth = Math.max(0, interXMax - interXMin);
    const interHeight = Math.max(0, interYMax - interYMin);
    const interArea = interWidth * interHeight;
  
    const area1 = (x1Max - x1Min) * (y1Max - y1Min);
    const area2 = (x2Max - x2Min) * (y2Max - y2Min);
    const unionArea = area1 + area2 - interArea;
  
    if (unionArea === 0) return 0;
  
    return interArea / unionArea;
  }

  loadImageryLayers(forceAddLayers = false){
    // Cancel previous requests
    if (this.tileJsonRequests) {
        this.tileJsonRequests.forEach(tileJsonRequest => tileJsonRequest.abort());
        this.tileJsonRequests = [];
    }

    this.taskCount = this.countTasks();

    const { tiles } = this.props,
          layerId = layer => {
            const meta = layer[Symbol.for("meta")];
            return meta.task.project + "_" + meta.task.id;
          };

    // Remove all previous imagery layers
    // and keep track of which ones were selected
    const prevSelectedLayers = [];

    this.state.imageryLayers.forEach(layer => {
      if (this.map.hasLayer(layer)) prevSelectedLayers.push(layerId(layer));
      layer.remove();
    });
    this.setState({imageryLayers: [], rightLayers: []});

    // Request new tiles
    return new Promise((resolve, reject) => {
      this.tileJsonRequests = [];

      // Set a zIndexGroup
      this.zIndexGroupMap = {};
      let zIdx = 1;
      for (let i = tiles.length - 1; i >= 0; i--){
        if (!tiles[i].zIndexGroup){
          const taskId = tiles[i].meta.task.id;
          if (!this.zIndexGroupMap[taskId]) this.zIndexGroupMap[taskId] = zIdx++;
          tiles[i].zIndexGroup = this.zIndexGroupMap[taskId];
        }
      }

      // Compute IoU scores
      // This gives us an idea of overlap between tasks
      // so that we can decide to show them in project map view
      this.ious = {};
      for (let i = tiles.length - 1; i >= 0; i--){
        const taskId = tiles[i].meta.task.id;
        if (this.ious[taskId] === undefined){
          for (let j = i - 1; j >= 0; j--){
            const tId = tiles[j].meta.task.id;
            if (tId === taskId) continue;
            if (!tiles[i].meta.task.extent || !tiles[j].meta.task.extent) continue;
            
            const iou = this.computeIOU(tiles[i].meta.task.extent, tiles[j].meta.task.extent);
            if (this.ious[taskId] === undefined){
              this.ious[taskId] = iou;
            }else{
              this.ious[taskId] = Math.max(this.ious[taskId], iou);
            }
          }
        }
      }
      this.ious[tiles[0].meta.task.id] = 0; // First task is always visible

      async.each(tiles, (tile, done) => {
        const { url, type, zIndexGroup } = tile;
        const meta = Utils.clone(tile.meta);

        let metaUrl = url + "metadata";
        let unitForward = value => value;
        let unitBackward = value => value;
        let queryParams = {};

        if (type == "plant"){
          if (meta.task && meta.task.orthophoto_bands && meta.task.orthophoto_bands.length === 2){
            // Single band, probably thermal dataset, in any case we can't render NDVI
            // because it requires 3 bands
            queryParams = {
              formula: 'Celsius',
              bands: 'L',
              color_map: 'magma'
            };
          }else if (meta.task && meta.task.orthophoto_bands){
            let formula = this.hasBands(["red", "green", "nir"], meta.task.orthophoto_bands) ? "NDVI" : "VARI";
            queryParams = {
              formula,
              bands: 'auto',
              color_map: 'rdylgn'
            };
          }else{
            // This should never happen?
            queryParams = {
              formula: 'NDVI',
              bands: 'RGN',
              color_map: 'rdylgn'
            };
          }
        }else if (type == "dsm" || type == "dtm"){
          queryParams = {
            hillshade: 6,
            color_map: 'viridis'
          };
          unitForward = value => {
            return unitSystem().elevation(value).value;
          };
          unitBackward = value => {
            let unitValue = unitSystem().elevation(0);
            unitValue.value = value;
            return toMetric(unitValue).value;
          };
        }

        if (meta.task.crop) queryParams.crop = 1;

        metaUrl += Utils.toSearchQuery(queryParams);

        this.tileJsonRequests.push($.getJSON(metaUrl)
          .done(mres => {
            const { scheme, name, maxzoom, statistics } = mres;

            const bounds = Leaflet.latLngBounds(
                [mres.bounds.value.slice(0, 2).reverse(), mres.bounds.value.slice(2, 4).reverse()]
              );

            // Build URL
            let tileUrl = mres.tiles[0];
            const TILESIZE = 512;
            
            // Set rescale
            if (statistics){
                const params = Utils.queryParams({search: tileUrl.slice(tileUrl.indexOf("?"))});
                if (statistics["1"]){
                    // Add rescale
                    let min = Infinity;
                    let max = -Infinity;
                    if (type === 'plant' || type === 'orthophoto'){
                      // percentile
                      for (let b in statistics){
                        min = Math.min(min, statistics[b]["percentiles"][0]);
                        max = Math.max(max, statistics[b]["percentiles"][1]);
                      }
                    }else{
                      // min/max
                      for (let b in statistics){
                        min = Math.min(min, statistics[b]["min"]);
                        max = Math.max(max, statistics[b]["max"]);
                      }
                    }
                    params.rescale = encodeURIComponent(`${min},${max}`);              
                }else{
                    console.warn("Cannot find min/max statistics for dataset, setting to -1,1");
                    params.rescale = encodeURIComponent("-1,1");
                }
                
                params.size = TILESIZE;
                params.cache = Math.floor(Math.random() * 1000000); // cache bust
                if (meta.task.crop) params.crop = 1;
                tileUrl = Utils.buildUrlWithQuery(tileUrl, params);
            }else{
                let params = { size: TILESIZE, cache: Math.floor(Math.random() * 1000000) };
                if (meta.task.crop) params.crop = 1;
                tileUrl = Utils.buildUrlWithQuery(tileUrl, params);
            }
            
            // Decode colormaps
            ColorMaps.decode(mres.color_maps);

            const layer = Leaflet.tileLayer(tileUrl, {
                  bounds,
                  minZoom: 0,
                  maxZoom: maxzoom + 99,
                  maxNativeZoom: maxzoom - 1,
                  tileSize: TILESIZE,
                  tms: scheme === 'tms',
                  opacity: this.state.opacity / 100,
                  detectRetina: true,
                  zIndex: this.typeZIndex(type, zIndexGroup),
                });
            
            // Associate metadata with this layer
            let thermal = typeof(mres) === 'object' && mres.band_descriptions && 
                          Array.isArray(mres.band_descriptions) && mres.band_descriptions.length > 0 &&
                          mres.band_descriptions[0].indexOf("lwir") !== -1;

            meta.name = this.typeToHuman(type, this.props.thermal || thermal);
            meta.icon = this.typeToIcon(type, this.props.thermal || thermal);
            meta.type = type;
            meta.raster = true;
            meta.zIndexGroup = zIndexGroup;
            meta.autoExpand = this.taskCount === 1 && type === this.props.mapType;
            meta.metaUrl = metaUrl;
            meta.unitForward = unitForward;
            meta.unitBackward = unitBackward;
            if (this.taskCount > 1){
              // Assign to a group
              meta.group = {id: meta.task.id, name: meta.task.name};
            }
            layer[Symbol.for("meta")] = meta;
            layer[Symbol.for("tile-meta")] = mres;

            const iou = this.ious[meta.task.id] || 0;
            if (forceAddLayers || prevSelectedLayers.indexOf(layerId(layer)) !== -1){
              if (type === this.props.mapType && iou <= IOU_THRESHOLD){
                layer.addTo(this.map);
              }
            }

            // Show 3D switch button only if we have a single orthophoto
            if (this.taskCount === 1){
              this.setState({singleTask: meta.task});
            }

            // For some reason, getLatLng is not defined for tileLayer?
            // We need this function if other code calls layer.openPopup()
            const self = this;
            layer.getLatLng = function(){
              let latlng = self.lastClickedLatLng ? 
                            self.lastClickedLatLng : 
                            this.options.bounds.getCenter();
              return latlng;
            };

            // Additional layer methods
            layer.show = function(){
              if (!self.map.hasLayer(this)) self.map.addLayer(this);
              else this.getContainer().style.display = '';
            };
            layer.hide = function(){
              this.getContainer().style.display = 'none';
            };
            layer.isHidden = function(){
              if (!this.getContainer()) return false;
              return this.getContainer().style.display === 'none';
            };
            layer.setZIndex = function(z){
              if (this._originalZ === undefined) this._originalZ = this.options.zIndex;
              this.options.zIndex = z;
              this._updateZIndex();
            };
            layer.restoreZIndex = function(){
              if (this._originalZ !== undefined){
                this.setZIndex(this._originalZ);
              }
            };
            layer.bringToFront = function(){
              this.setZIndex(this.options.zIndex + 10000);
            };

            var popup = L.DomUtil.create('div', 'infoWindow');

            popup.innerHTML = `<div class="title">
                                    ${name}
                                </div>
                                <div class="popup-opacity-slider">Opacity: <input id="layerOpacity" class="opacity" type="range" value="${layer.options.opacity}" min="0" max="1" step="0.01" /></div>
                                <div>Bounds: [${layer.options.bounds.toBBoxString().split(",").join(", ")}]</div>
                                <div class="popup-download-assets loading">
                                  <i class="fa loading fa-spin fa-sync fa-spin fa-fw"></i>
                                </div>

                                <button
                                    onclick="location.href='${this.tdPopupButtonUrl(meta.task)}';"
                                    type="button"
                                    class="switchModeButton btn btn-sm btn-secondary">
                                    <i class="fa fa-cube"></i> 3D
                                </button>`;

            layer.bindPopup(popup);

            $('#layerOpacity', popup).on('change input', function() {
                layer.setOpacity($('#layerOpacity', popup).val());
            });
            
            this.setState(update(this.state, {
                imageryLayers: {$push: [layer]}
            }));

            let mapBounds = this.mapBounds || Leaflet.latLngBounds();
            mapBounds.extend(bounds);
            this.mapBounds = mapBounds;

            // Add media layer if available
            if (meta.task && meta.task.media && !this.addedMediaLayer[meta.task.id]){
                const mediaTypes = ['photo', 'pano', 'video'];
                const mediaIcons = mediaTypes.reduce((obj, type) => {
                  obj[type] = L.icon({
                    iconUrl: `/static/app/js/icons/marker-media-${type}.png`,
                    iconSize: [41, 46],
                    iconAnchor: [17, 46],
                  })
                  return obj;
                }, {});
                  
                const mediaLayer = new L.MarkersCanvas();
                
                mediaLayer.lazyLoad = (cb) => {
                  $.getJSON(meta.task.media)
                    .done((geojson) => {
                      if (geojson.type === 'FeatureCollection'){
                        let markers = [];
  
                        geojson.features.forEach(s => {
                          if (!s.properties) return;
                          if (mediaTypes.indexOf(s.properties.type) === -1) return;

                          let marker = L.marker(
                            [s.geometry.coordinates[1], s.geometry.coordinates[0]],
                            { icon: mediaIcons[s.properties.type] }
                          );
                          markers.push(marker);

                          marker.on('click', (e) => {
                            const basePath = `/api/projects/${meta.task.project}/tasks/${meta.task.id}/media`;

                            if (s.properties.type === 'video' && s.properties.srt) {
                              this.openVideoWithFlightPath(basePath, s.properties, marker, mediaLayer);
                              return;
                            }

                            const container = document.createElement('div');
                            ReactDOM.render(<MediaView
                              basePath={basePath}
                              media={s.properties}
                              autoOpen
                              onClose={() => {
                                ReactDOM.unmountComponentAtNode(container);
                                container.remove();
                                this.map.closePopup();
                              }}
                            />, container);
                            document.body.appendChild(container);
                          });

                        });
  
                        mediaLayer.addMarkers(markers, this.map);
                      }
                      cb();
                    }).fail(() => {
                      cb(new Error("Cannot load media markers"))
                    });
                };
                mediaLayer[Symbol.for("meta")] = {
                  name: _("Media"), 
                  icon: "fa fa-image fa-fw",
                  zIndexGroup
                };
                if (this.taskCount > 1){
                  // Assign to a group
                  mediaLayer[Symbol.for("meta")].group = {id: meta.task.id, name: meta.task.name};
                }

                this.setState(update(this.state, {
                    overlays: {$push: [mediaLayer]}
                }));

                this.addedMediaLayer[meta.task.id] = true;
            }

            // Add camera shots layer if available
            if (meta.task && meta.task.camera_shots && !this.addedCameraShots[meta.task.id]){
                var camIcon = L.icon({
                  iconUrl: "/static/app/js/icons/marker-camera.png",
                  iconSize: [41, 46],
                  iconAnchor: [17, 46],
                });
                
                const shotsLayer = new L.MarkersCanvas();
                
                shotsLayer.lazyLoad = (cb) => {
                  $.getJSON(meta.task.camera_shots)
                    .done((shots) => {
                      if (shots.type === 'FeatureCollection'){
                        let markers = [];
  
                        shots.features.forEach(s => {
                          let marker = L.marker(
                            [s.geometry.coordinates[1], s.geometry.coordinates[0]],
                            { icon: camIcon }
                          );
                          markers.push(marker);
  
                          if (s.properties && s.properties.filename){
                            let root = null;
                            const lazyrender = () => {
                                if (!root) root = document.createElement("div");
                                ReactDOM.render(<ImagePopup task={meta.task} feature={s}/>, root);
                                return root;
                            }
  
                            marker.bindPopup(L.popup(
                                {
                                    lazyrender,
                                    maxHeight: 450,
                                    minWidth: 320
                                }));
                          }
                        });
  
                        shotsLayer.addMarkers(markers, this.map);
                      }
                      cb();
                    }).fail(() => {
                      cb(new Error("Cannot load camera shots"))
                    });
                };
                shotsLayer[Symbol.for("meta")] = {
                  name: _("Cameras"), 
                  icon: "fa fa-camera fa-fw",
                  zIndexGroup
                };
                if (this.taskCount > 1){
                  // Assign to a group
                  shotsLayer[Symbol.for("meta")].group = {id: meta.task.id, name: meta.task.name};
                }

                this.setState(update(this.state, {
                    overlays: {$push: [shotsLayer]}
                }));

                this.addedCameraShots[meta.task.id] = true;
            }

            // Add ground control points layer if available
            if (meta.task && meta.task.ground_control_points && !this.addedGroundControlPoints){
                const gcpIcon = L.icon({
                  iconUrl: "/static/app/js/icons/marker-gcp.png",
                  iconSize: [41, 46],
                  iconAnchor: [17, 46],
                });
                const cpIcon = L.icon({
                  iconUrl: "/static/app/js/icons/marker-cp.png",
                  iconSize: [41, 46],
                  iconAnchor: [17, 46],
                });
                
                const gcpLayer = new L.MarkersCanvas();
                gcpLayer.lazyLoad = (cb) => {
                  $.getJSON(meta.task.ground_control_points)
                    .done((gcps) => {
                      if (gcps.type === 'FeatureCollection'){
                        let markers = [];
  
                        gcps.features.forEach(gcp => {
                          let icon = gcpIcon;
                          if (gcp.properties && typeof gcp.properties.id === "string" && gcp.properties.id.startsWith("CHK-")) icon = cpIcon;
  
                          let marker = L.marker(
                            [gcp.geometry.coordinates[1], gcp.geometry.coordinates[0]],
                            { icon }
                          );
                          markers.push(marker);
  
                          if (gcp.properties && gcp.properties.observations){
                            let root = null;
                            const lazyrender = () => {
                                  if (!root) root = document.createElement("div");
                                  ReactDOM.render(<GCPPopup task={meta.task} feature={gcp}/>, root);
                                  return root;
                            }
  
                            marker.bindPopup(L.popup(
                                {
                                    lazyrender,
                                    maxHeight: 450,
                                    minWidth: 320
                                }));
                          }
                        });
  
                        gcpLayer.addMarkers(markers, this.map);
                      }

                      cb();
                    }).fail(() => {
                      cb(new Error("Cannot load GCPs"))
                    });
                };
                gcpLayer[Symbol.for("meta")] = {
                  name: _("Ground Control Points"), 
                  icon: "far fa-dot-circle fa-fw",
                  zIndexGroup
                };
                
                if (this.taskCount > 1){
                  // Assign to a group
                  gcpLayer[Symbol.for("meta")].group = {id: meta.task.id, name: meta.task.name};
                }

                this.setState(update(this.state, {
                    overlays: {$push: [gcpLayer]}
                }));

                this.addedGroundControlPoints = true;
            }

            done();
          })
          .fail((_, __, err) => done(err))
        );
      }, err => {
        if (err){
          if (err !== "abort"){
              this.setState({error: err.message || JSON.stringify(err)});
          }
          reject();
        }else resolve();
      });
    });
  }

  componentDidMount() {
    const { showBackground, tiles } = this.props;

    this.map = Leaflet.map(this.container, {
      scrollWheelZoom: true,
      positionControl: false,
      zoomControl: false,
      minZoom: 0,
      maxZoom: 24
    });

    this.map.on('viewreset', this.layerVisibilityCheck);
    this.map.on('zoomstart', this.layerVisibilityCheck);
    this.map.on('movestart', this.layerVisibilityCheck);

    // For some reason, in production this class is not added (but we need it)
    // leaflet bug?
    $(this.container).addClass("leaflet-touch");

    PluginsAPI.Map.onAddAnnotation(this.handleAddAnnotation);
    PluginsAPI.Map.onAnnotationDeleted(this.handleDeleteAnnotation);
    PluginsAPI.Map.onSideBySideChanged(this.handleSideBySideChange);

    PluginsAPI.Map.triggerWillAddControls({
        map: this.map,
        tiles,
        mapView: this
    });

    const UnitsCtrl = Leaflet.Control.extend({
      options: {
          position: 'bottomleft'
      },
  
      onAdd: function () {
          this.container = Leaflet.DomUtil.create('div', 'leaflet-control-units-selection leaflet-control');
          Leaflet.DomEvent.disableClickPropagation(this.container);
          ReactDOM.render(<UnitSelector />, this.container);
          return this.container;
      }
    });
    new UnitsCtrl().addTo(this.map);

    //add zoom control with your options
    let zoomControl = Leaflet.control.zoom({
         position:'bottomleft'
    }).addTo(this.map);

    if (showBackground) {
      this.basemaps = {};
      const basemaps = this.props.basemaps;
      if (basemaps.length > 0) {
        basemaps.forEach(bm => {
          let layer;
          const opts = {
            layers: bm.layers || '0',
            styles: bm.styles || 'default',
            format: bm.format || 'image/png',
            transparent: (bm.format || 'image/png') == 'image/png',
            attribution: bm.attribution || bm.label,
            maxZoom: (bm.maxzoom || 21) + 99,
            maxNativeZoom: bm.maxzoom || 21,
            minZoom: bm.minzoom || 0,
            subdomains: bm.subdomains || [],
          }
          if (bm.type === 'wms') {
            layer = L.tileLayer.wms(bm.url, opts);
          } else {
            layer = L.tileLayer(bm.url, opts);
          }

          if (bm['default']) {
            layer.addTo(this.map);
          }

          this.basemaps[bm.label] = layer;
        });
      }

      const customLayer = L.layerGroup();
      customLayer.on("add", a => {
        const defaultCustomBm = window.localStorage.getItem('lastCustomBasemap') || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

        let url = window.prompt([_('Enter a tile URL template. Valid coordinates are:'),
_('{z}, {x}, {y} for Z/X/Y tile scheme'),
_('{−y} for flipped TMS-style Y coordinates'),
'',
_('Example:'),
'https://tile.openstreetmap.org/{z}/{x}/{y}.png'].join("\n"), defaultCustomBm);

        if (url){
          customLayer.clearLayers();
          const l = L.tileLayer(url, {
            maxNativeZoom: 24,
            maxZoom: 99,
            minZoom: 0
          });
          customLayer.addLayer(l);
          l.bringToBack();
          window.localStorage.setItem('lastCustomBasemap', url);
        }
     });
      this.basemaps[_("Custom")] = customLayer;
      this.basemaps[_("None")] = L.layerGroup();
    }

    this.layersControl = new LayersControl({
        layers: this.state.imageryLayers,
        overlays: this.state.overlays,
        annotations: this.state.annotations,
        onUserOverlayRemove: this.removeUserOverlay
    }).addTo(this.map);

    this.autolayers = Leaflet.control.autolayers({
      overlays: {},
      selectedOverlays: [],
      baseLayers: this.basemaps
    }).addTo(this.map);

    // Drag & Drop overlays
    const addDnDZone = (container, opts) => {
        const mapOverlayLayerDrop = new Dropzone(container, opts);
        mapOverlayLayerDrop.on("addedfile", (file) => {
          if (/\.dxf$/i.test(file.name)){
            mapOverlayLayerDrop.removeFile(file);
            this.handleDxfDrop(file);
            return;
          }

          // Zipped shapefiles are converted server-side
          if (/\.zip$/i.test(file.name)){
            mapOverlayLayerDrop.removeFile(file);
            if (this.checkOverlayTask()) this.uploadOverlay(file, null, this.getNearestTask());
            return;
          }

          this.setState({showLoading: true});
          addOverlayLayer(file, (err, entry, geojson) => {
            if (!err){
              this.assignOverlayTask(entry, this.getNearestTask());
              entry.children.forEach(c => c.layer.addTo(this.map));
              this.setState(update(this.state, {
                 userOverlays: {$push: [entry]}
              }));
              if (this.layersControl) this.layersControl.openPanel();
              //zoom to all features
              if (entry.bounds.isValid()) this.map.fitBounds(entry.bounds);
              this.storeOverlay(entry, geojson);
            }else{
              this.setState({ error: err.message || JSON.stringify(err) });
            }

            this.setState({showLoading: false});
          });
        });
        mapOverlayLayerDrop.on("error", (file) => {
          mapOverlayLayerDrop.removeFile(file);
        });
    };

    addDnDZone(this.container, {url : "/", clickable : false});

    const AddOverlayCtrl = Leaflet.Control.extend({
        options: {
            position: 'topright'
        },
    
        onAdd: function () {
            this.container = Leaflet.DomUtil.create('div', 'leaflet-control-add-overlay leaflet-bar leaflet-control');
            Leaflet.DomEvent.disableClickPropagation(this.container);
            const btn = Leaflet.DomUtil.create('a', 'leaflet-control-add-overlay-button');
            btn.setAttribute("title", _("Add a GeoJSON (.json), ShapeFile (.zip) or AutoCAD (.dxf) overlay"));
            
            this.container.append(btn);
            addDnDZone(btn, {url: "/", clickable: true});
            
            return this.container;
        }
    });
    new AddOverlayCtrl().addTo(this.map);

    if (this.props.permissions.indexOf("change") !== -1){
      const updateCropArea = geojson => {
        // Find tasks IDs
        const taskMap = {};
        const requests = [];
        if (!geojson) geojson = '';

        // Crop affects all tasks in the map
        for (let layer of this.state.imageryLayers){
          if (layer._map){
            const meta = layer[Symbol.for("meta")];
            const task = meta.task;
            if (!taskMap[task.id]){
              requests.push($.ajax({
                url: `/api/projects/${task.project}/tasks/${task.id}/`,
                contentType: 'application/json',
                data: JSON.stringify({
                  crop: geojson
                }),
                dataType: 'json',
                type: 'PATCH'
              }));
              taskMap[task.id] = meta;
            }
          }
        }

        Promise.all(requests)
          .then(responses => {
            if (!Array.isArray(responses)){
              responses = [responses];
            }

            // Update task in meta and tiles objects
            responses.forEach(task => {
              if (!task) return;

              const meta = taskMap[task.id];
              meta.task = task;

              for (let i = 0; i < this.props.tiles.length; i++){
                const tile = this.props.tiles[i];
                if (tile.meta && tile.meta.task.id === task.id){
                  tile.meta.task = task;                  
                }
              }
            });
            
            this.loadImageryLayers();
          })
          .catch(e => {
            this.setState({error: _("Cannot set cropping area. Check your internet connection.")});
            console.error(e);
          }).finally(() => {
            setTimeout(() => {
              this.cropButton.deletePolygon({triggerEvents: false, fade: true});
            }, 1000);
          });
      };

      this.cropButton = new CropButton({
        position:'topright',
        color:'#fff',
        pulse: true,
        willCrop: () => {
          this.removeSideBySideCtrl();
          let foundCrop = false;

          for (let layer of this.state.imageryLayers){
            const meta = layer[Symbol.for("meta")];
            if (meta.task.crop){
              foundCrop = true;
              break;
            }
          }
          
          if (foundCrop){
            if (window.confirm(_('Are you sure you want to set a new crop area?'))){
              updateCropArea(null);
            }else{
              // Stop crop button from toggling
              return true;
            }
          }
        },
        onPolygonChange: updateCropArea
      });
      this.map.addControl(this.cropButton);
    }

    this.map.fitBounds([
     [13.772919746115805,
     45.664640939831735],
     [13.772825784981254,
     45.664591558975154]]);
    this.map.attributionControl.setPrefix("");

    this.setState({showLoading: true});
    this.loadImageryLayers(true).then(() => {
        this.setState({showLoading: false});
        this.map.fitBounds(this.mapBounds);
        this.loadStoredOverlays();

        this.map.on('click', e => {
          if (PluginsAPI.Map.handleClick(e)) return;
          if (this.sideBySideCtrl) return;
          
          // Find first visible tile layer at the selected coordinates 
          for (let layer of this.state.imageryLayers){
            if (layer._map && !layer.isHidden() && layer.options.bounds.contains(e.latlng)){
              this.lastClickedLatLng = this.map.mouseEventToLatLng(e.originalEvent);
              this.updatePopupFor(layer);
              layer.openPopup();
              break;
            }
          }
        }).on('popupopen', e => {
            // Load task assets links in popup
            if (e.popup && e.popup._source && e.popup._content && !e.popup.options.lazyrender){
                const infoWindow = e.popup._content;
                if (typeof infoWindow === 'string') return;
                
                const $downloadAssets = $(".popup-download-assets", infoWindow);
                if ($downloadAssets.length > 0 && $downloadAssets.hasClass('loading')){
                  const {id, project} = (e.popup._source[Symbol.for("meta")] || {}).task;
                  
                  $.getJSON(`/api/projects/${project}/tasks/${id}/`)
                  .done(task => {
                    if (task){
                      let hideItems = [];
                      if (this.props.permissions.indexOf("change") === -1){
                        if (task.crop){
                          hideItems = ["all.zip", "backup.zip"];
                        }else{
                          hideItems = ["backup.zip"];
                        }
                      }

                      ReactDOM.render(<AssetDownloadButtons task={task} 
                                      showLabel={false} 
                                      buttonClass="btn-secondary"
                                      hideItems={hideItems} 
                                      modalContainer={this.modalContainer} />, $downloadAssets.get(0));
                    }
                  })
                  .fail(() => {
                      $downloadAssets.append($(_("Error: cannot load assets list.")));
                  })
                  .always(() => {
                      $downloadAssets.removeClass('loading');
                  });
                }
            }

            if (e.popup && e.popup.options.lazyrender){
                e.popup.setContent(e.popup.options.lazyrender());
            }
        });
    }).catch(e => {
        this.setState({showLoading: false, error: e.message});
    });
    
    PluginsAPI.Map.triggerDidAddControls({
      map: this.map,
      tiles: tiles,
      controls:{
        autolayers: this.autolayers,
        zoom: zoomControl
      }
    });

    PluginsAPI.Map.triggerAddActionButton({
      map: this.map,
      tiles
    }, (button) => {
      this.setState(update(this.state, {
        pluginActionButtons: {$push: [button]}
      }));
    });
  }

  handleAddAnnotation = (layer, name, task, stored) => {
      const zIndexGroup = this.zIndexGroupMap[task.id] || 1;
      const annotationsVisibility = Utils.queryParams(window.location).annotations || "";

      const meta = {
        name: name || "", 
        icon: "fa fa-sticky-note fa-fw",
        zIndexGroup
      };

      if (this.taskCount > 1 && task){
        meta.group = {id: task.id, name: task.name};
        
        if (stored){
          // Only show annotations for top-most tasks
          if (this.ious[task.id] >= 0.01 && annotationsVisibility !== "all"){
            PluginsAPI.Map.toggleAnnotation(layer, false);
          }
        }
      }
      layer[Symbol.for("meta")] = meta;

      this.setState(update(this.state, {
        annotations: {$push: [layer]}
     }));
  }

  handleDeleteAnnotation = (layer) => {
    this.setState({annotations: this.state.annotations.filter(l => l !== layer)});
  }

  handleSideBySideChange = (layer, side) => {
    let { rightLayers, imageryLayers } = this.state;

    imageryLayers.forEach(l => l.restoreZIndex());

    rightLayers = rightLayers.filter(l => l !== layer);
    if (side){
      rightLayers.push(layer);
    }
    rightLayers.forEach(l => l.bringToFront());

    this.setState({rightLayers});

    // Make sure to reset clipping
    imageryLayers.forEach(l => {
      let container = l.getContainer();
      if (container) container.style.clip = '';
    });

    if (rightLayers.length > 0){
      if (!this.sideBySideCtrl){
        this.sideBySideCtrl = L.control.sideBySide([], rightLayers).addTo(this.map);
      }else{
        this.sideBySideCtrl.setRightLayers(rightLayers);
      }
    }else{
      this.removeSideBySideCtrl();
    }
  }

  removeSideBySideCtrl = () => {
    if (this.sideBySideCtrl){
      this.sideBySideCtrl.remove();
      this.sideBySideCtrl = null;
    }
  }

  checkOverlayTask = () => {
    if (!this.props.tiles.length){
      this.setState({error: _("Cannot import overlay: no task is loaded.")});
      return false;
    }
    return true;
  }

  // Find the task closest to the current map center
  // by looking at the bounds of the tasks' imagery layers
  getNearestTask = () => {
    if (!this.props.tiles.length) return null;
    if (this.taskCount === 1) return this.props.tiles[0].meta.task;

    let candidates = this.state.imageryLayers.filter(l => {
      const meta = l[Symbol.for("meta")] || {};
      return meta.task && l.options.bounds;
    });
    if (!candidates.length) return this.props.tiles[0].meta.task;

    const visible = candidates.filter(l => l._map && !l.isHidden());
    if (visible.length) candidates = visible;

    const center = this.map.getCenter();
    const zIndexOf = l => (l[Symbol.for("meta")].zIndexGroup || 1);

    // Topmost layer containing the center
    const containing = candidates.filter(l => l.options.bounds.contains(center));
    if (containing.length){
      return containing.sort((a, b) => zIndexOf(b) - zIndexOf(a))[0][Symbol.for("meta")].task;
    }

    // Otherwise, nearest bounds
    const distanceTo = l => {
      const bounds = l.options.bounds;
      const closest = L.latLng(
        Math.min(Math.max(center.lat, bounds.getSouth()), bounds.getNorth()),
        Math.min(Math.max(center.lng, bounds.getWest()), bounds.getEast())
      );
      return center.distanceTo(closest);
    };
    return candidates.sort((a, b) => (distanceTo(a) - distanceTo(b)) || (zIndexOf(b) - zIndexOf(a)))[0][Symbol.for("meta")].task;
  }

  assignOverlayTask = (entry, task) => {
    entry.task = task;
    if (this.taskCount > 1 && task){
      entry.group = {id: task.id, name: task.name};
    }
  }

  canEditTask = () => {
    return this.props.permissions.indexOf("change") !== -1 || (this.props.public && this.props.publicEdit);
  }

  overlayMeta = entry => {
    return {
      opacity: entry.opacity,
      visible: entry.visible !== false,
      colors: entry.children.reduce((obj, c) => { obj[c.name] = c.colorKey; return obj; }, {}),
      hidden: entry.children.filter(c => c.visible === false).map(c => c.name)
    };
  }

  overlayUrl = (entry, overlayId = "") => {
    return `/api/projects/${entry.task.project}/tasks/${entry.task.id}/overlays/${overlayId ? overlayId + ".geojson" : "sync"}`;
  }

  storeOverlay = (entry, geojson) => {
    if (!this.canEditTask() || !entry.task) return;

    const formData = new FormData();
    formData.append("file", new Blob([JSON.stringify(geojson)], {type: "application/json"}), entry.name + ".geojson");
    formData.append("name", entry.name);
    formData.append("meta", JSON.stringify(this.overlayMeta(entry)));

    entry.syncing = true;
    this.setState({userOverlays: this.state.userOverlays.slice()});

    $.ajax({
      url: this.overlayUrl(entry),
      type: 'POST',
      data: formData,
      processData: false,
      contentType: false
    }).done(res => {
      entry.storageId = res.id;
      entry.stored = true;
      this.setOverlaySync(entry);
    }).fail(() => {
      this.setState({error: interpolate(_("Cannot save overlay %(name)s"), {name: entry.name})});
    }).always(() => {
      entry.syncing = false;
      this.setState({userOverlays: this.state.userOverlays.slice()});
    });
  }

  setOverlaySync = entry => {
    entry.onSync = e => {
      if (e._syncTimeout) clearTimeout(e._syncTimeout);
      e._syncTimeout = setTimeout(() => this.patchOverlay(e), 500);
    };
  }

  patchOverlay = (entry, extra = {}) => {
    if (!entry.storageId || !entry.task || !this.canEditTask()) return;

    // Stamps are in the server's clock domain: fetch server time once,
    // then derive subsequent stamps from the elapsed client time
    if (!this.serverStamp){
      $.ajax({
        type: 'GET',
        url: `/api/projects/${entry.task.project}/tasks/${entry.task.id}/overlays/stamp`,
        contentType: "application/json"
      }).done(result => {
        if (result.stamp){
          this.serverStamp = result.stamp;
          this.clientStamp = new Date().getTime();
          this.patchOverlay(entry, extra); // Resume
        }else{
          console.warn(result);
        }
      }).fail(() => {
        this.setState({error: interpolate(_("Cannot save overlay %(name)s"), {name: entry.name})});
      });

      return;
    }

    $.ajax({
      url: this.overlayUrl(entry, entry.storageId),
      type: 'PATCH',
      contentType: 'application/json',
      data: JSON.stringify(Object.assign({
        stamp: this.serverStamp + (new Date().getTime() - this.clientStamp),
        name: entry.name,
        meta: this.overlayMeta(entry)
      }, extra))
    }).done(result => {
      if (!result.updated) console.warn(result);
    }).fail(() => {
      this.setState({error: interpolate(_("Cannot save overlay %(name)s"), {name: entry.name})});
    });
  }

  loadStoredOverlays = () => {
    const seen = {};

    this.props.tiles.forEach(tile => {
      const task = tile.meta.task;
      if (seen[task.id]) return;
      seen[task.id] = true;

      (task.overlays || []).forEach(item => {
        const placeholder = {
          id: `overlay-load-${item.id}`,
          name: item.name || _("Overlay"),
          loading: true,
          progress: 0,
          converting: false,
          opacity: 100,
          bounds: null,
          children: []
        };
        this.assignOverlayTask(placeholder, task);
        this.setState(update(this.state, {
          userOverlays: {$push: [placeholder]}
        }));

        const removePlaceholder = () => {
          this.setState({userOverlays: this.state.userOverlays.filter(o => o !== placeholder)});
        };

        $.ajax({
          url: `/api/projects/${task.project}/tasks/${task.id}/overlays/${item.id}.geojson`,
          dataType: 'json',
          xhr: () => {
            const xhr = $.ajaxSettings.xhr();
            xhr.addEventListener('progress', e => {
              if (e.lengthComputable){
                placeholder.progress = e.loaded / e.total * 100;
                this.setState({userOverlays: this.state.userOverlays.slice()});
              }
            }, false);
            return xhr;
          }
        }).done(geojson => {
          const idx = this.state.userOverlays.indexOf(placeholder);
          if (idx === -1) return; // Removed in the meantime

          if (!geojson || geojson.type !== "FeatureCollection"){
            removePlaceholder();
            return;
          }

          const meta = item.meta || {};
          const entry = buildOverlay(geojson, item.name || _("Overlay"), {
            colors: meta.colors || {},
            opacity: meta.opacity,
            visible: meta.visible,
            hidden: meta.hidden
          });
          entry.storageId = item.id;
          entry.stored = true;
          this.assignOverlayTask(entry, task);
          this.setOverlaySync(entry);
          if (entry.visible){
            entry.children.forEach(c => { if (c.visible) c.layer.addTo(this.map); });
          }
          this.setState(update(this.state, {
            userOverlays: {$splice: [[idx, 1, entry]]}
          }));
        }).fail(removePlaceholder);
      });
    });
  }

  handleDxfDrop = file => {
    if (!this.checkOverlayTask()) return;

    // One DXF import at a time
    if (this.pendingDxfFile) return;

    this.pendingDxfFile = file;
    this.pendingDxfTask = this.getNearestTask();
    if (this.dxfDialog) this.dxfDialog.show();
  }

  handleDxfDialogShow = () => {
    if (this.dxfEpsgInput){
      const task = this.pendingDxfTask;
      this.dxfEpsgInput.value = (task && task.epsg) ? task.epsg : "";
      this.dxfEpsgInput.focus();
    }
  }

  handleDxfDialogHide = () => {
    this.pendingDxfFile = null;
    this.pendingDxfTask = null;
  }

  handleDxfImport = formData => {
    const file = this.pendingDxfFile;
    const task = this.pendingDxfTask;
    if (!file || !task) return null;

    const epsg = parseInt(formData.epsg);
    if (isNaN(epsg)){
      return $.Deferred().reject({message: _("Invalid EPSG code")}).promise();
    }

    this.pendingDxfFile = null;
    this.pendingDxfTask = null;
    this.uploadOverlay(file, epsg, task);
    return null;
  }

  uploadOverlay = (file, epsg, task) => {
    const entry = {
      id: `overlay-upload-${++this.overlayUploadCount}`,
      name: file.name.replace(/\.[^/.]+$/, ""),
      loading: true,
      progress: 0,
      converting: false,
      opacity: 100,
      bounds: null,
      children: []
    };
    this.assignOverlayTask(entry, task);

    this.setState(update(this.state, {
      userOverlays: {$push: [entry]}
    }));

    // Show the upload progress in the layer list
    if (this.layersControl) this.layersControl.openPanel();

    const formData = new FormData();
    formData.append("file", file);
    if (epsg !== null && epsg !== undefined) formData.append("epsg", epsg);

    $.ajax({
        url: `/api/projects/${task.project}/tasks/${task.id}/overlays/convert`,
        contentType: false,
        processData: false,
        data: formData,
        type: 'POST',
        xhr: () => {
          const xhr = $.ajaxSettings.xhr();
          if (xhr.upload){
            xhr.upload.addEventListener('progress', e => {
              if (e.lengthComputable){
                entry.progress = e.loaded / e.total * 100;
                if (entry.progress >= 100) entry.converting = true;
                this.setState({userOverlays: this.state.userOverlays.slice()});
              }
            }, false);
          }
          return xhr;
        }
    }).done(geojson => {
        const idx = this.state.userOverlays.indexOf(entry);
        if (idx === -1) return; // Removed in the meantime

        if (geojson && geojson.type === "FeatureCollection"){
          const newEntry = buildOverlay(geojson, file.name);
          newEntry.task = entry.task;
          newEntry.group = entry.group;
          newEntry.children.forEach(c => c.layer.addTo(this.map));
          this.setState(update(this.state, {
            userOverlays: {$splice: [[idx, 1, newEntry]]}
          }));
          if (newEntry.bounds && newEntry.bounds.isValid()) this.map.fitBounds(newEntry.bounds);
          this.storeOverlay(newEntry, geojson);
        }else{
          this.setState({userOverlays: this.state.userOverlays.filter(o => o !== entry),
                         error: interpolate(_("Cannot convert %(file)s"), {file: file.name})});
        }
    }).fail(xhr => {
        let error;
        const rj = xhr.responseJSON;
        if (rj){
          if (Array.isArray(rj)) error = rj.join(" ");
          else error = rj.error || rj.detail;
        }
        if (!error) error = interpolate(_("Cannot convert %(file)s"), {file: file.name});
        this.setState({userOverlays: this.state.userOverlays.filter(o => o !== entry), error});
    });
  }

  removeUserOverlay = (entry, child) => {
    // Remove a single sublayer, unless it's the last one
    if (child && entry.children.length > 1){
      this.map.removeLayer(child.layer);
      entry.children = entry.children.filter(c => c !== child);
      recomputeOverlayBounds(entry);
      this.setState({userOverlays: this.state.userOverlays.slice()});
      if (entry.storageId) this.patchOverlay(entry, {removeLayer: child.name});
      return;
    }

    entry.children.forEach(c => this.map.removeLayer(c.layer));
    this.setState({userOverlays: this.state.userOverlays.filter(o => o !== entry)});
    if (entry.storageId && entry.task && this.canEditTask()){
      $.ajax({
        url: this.overlayUrl(entry, entry.storageId),
        type: 'DELETE'
      });
    }
  }

  layerVisibilityCheck = () => {
    // Check if imageryLayers are invisible and remove them to prevent tiles from loading
    this.state.imageryLayers.forEach(layer => {
      if (layer.isHidden()) this.map.removeLayer(layer);
    }); 
  }

  componentDidUpdate(prevProps, prevState) {
    this.state.imageryLayers.forEach(imageryLayer => {
      imageryLayer.setOpacity(this.state.opacity / 100);
      this.updatePopupFor(imageryLayer);
    });

    if (this.layersControl && prevProps.mapType !== this.props.mapType){
      PluginsAPI.Map.mapTypeChanged(this.props.mapType, this.taskCount === 1);
    }

    if (this.layersControl && (prevState.imageryLayers !== this.state.imageryLayers ||
                            prevState.overlays !== this.state.overlays ||
                            prevState.annotations !== this.state.annotations ||
                            prevState.userOverlays !== this.state.userOverlays)){
      this.updateLayersControl();
    }
  }

  updateLayersControl = () => {
    this.layersControl.update(this.state.imageryLayers, this.state.overlays, this.state.annotations, this.state.userOverlays);
  }

  componentWillUnmount() {
    this.map.remove();
    this.map.off('viewreset', this.layerVisibilityCheck);
    this.map.off('zoomstart', this.layerVisibilityCheck);
    this.map.off('movestart', this.layerVisibilityCheck);

    if (this.tileJsonRequests) {
      this.tileJsonRequests.forEach(tileJsonRequest => tileJsonRequest.abort());
      this.tileJsonRequests = [];
    }

    PluginsAPI.Map.offAddAnnotation(this.handleAddAnnotation);
    PluginsAPI.Map.offAnnotationDeleted(this.handleAddAnnotation);
    PluginsAPI.Map.offSideBySideChanged(this.handleSideBySideChange);
  }

  handleMapMouseDown(e){
    // Make sure the share popup closes
    if (this.shareButton) this.shareButton.hidePopup();
  }

  openVideoWithFlightPath = (basePath, media, marker, mediaLayer) => {
    if (marker._flightPathLoading) return;
    marker._flightPathLoading = true;

    const flightPathUrl = `${basePath}/video/${encodeURIComponent(media.filename)}/flightpath.geojson`;

    const markerLatLng = marker.getLatLng();
    const spinnerIcon = L.divIcon({
      className: 'video-marker-spinner',
      html: '<i class="fa fa-circle-notch fa-spin"></i>',
      iconSize: [41, 46],
      iconAnchor: [15, 44]
    });
    const spinnerMarker = L.marker(markerLatLng, { icon: spinnerIcon }).addTo(this.map);

    const onFlightPathLoaded = (feature) => {
      if (!feature || !feature.geometry || !feature.geometry.coordinates || feature.geometry.coordinates.length < 2) {
        return;
      }
      marker._flightPathFeature = feature; // cache
      mediaLayer.removeMarker(marker);

      const coords = feature.geometry.coordinates;
      const timestamps = feature.properties.timestamps;
      const latLngs = coords.map(c => [c[1], c[0]]);

      const flightPathLine = L.polyline(latLngs, {
        color: '#4A90D9',
        weight: 4,
        opacity: 0.8
      }).addTo(this.map);

      const startDot = L.circleMarker(latLngs[0], {
        radius: 8,
        color: '#fff',
        weight: 2,
        fillColor: '#2ECC71',
        fillOpacity: 1
      }).addTo(this.map);

      const endDot = L.circleMarker(latLngs[latLngs.length - 1], {
        radius: 8,
        color: '#fff',
        weight: 2,
        fillColor: '#E74C3C',
        fillOpacity: 1
      }).addTo(this.map);

      const positionDot = L.circleMarker(latLngs[0], {
        radius: 8,
        color: '#fff',
        weight: 2,
        fillColor: '#FF9E67',
        fillOpacity: 1
      }).addTo(this.map);

      const mapEl = this.container.parentElement;
      const mapHeight = mapEl ? mapEl.clientHeight : 0;
      this.map.fitBounds(flightPathLine.getBounds(), {
        paddingTopLeft: [50, mapHeight / 2 + 50],
        paddingBottomRight: [50, 50]
      });

      const getPositionAtTime = (currentTime) => {
        if (!timestamps || timestamps.length < 2) return latLngs[0];
        if (currentTime <= timestamps[0]) return latLngs[0];
        if (currentTime >= timestamps[timestamps.length - 1]) return latLngs[latLngs.length - 1];

        for (let i = 1; i < timestamps.length; i++) {
          if (currentTime <= timestamps[i]) {
            const t0 = timestamps[i - 1];
            const t1 = timestamps[i];
            const frac = (currentTime - t0) / (t1 - t0);
            const lat = latLngs[i - 1][0] + frac * (latLngs[i][0] - latLngs[i - 1][0]);
            const lng = latLngs[i - 1][1] + frac * (latLngs[i][1] - latLngs[i - 1][1]);
            return [lat, lng];
          }
        }
        return latLngs[latLngs.length - 1];
      };

      const getTimeAtPoint = (latlng) => {
        if (!timestamps || timestamps.length < 2) return 0;

        let bestDist = Infinity;
        let bestTime = 0;

        for (let i = 1; i < latLngs.length; i++) {
          const ax = latLngs[i - 1][1], ay = latLngs[i - 1][0];
          const bx = latLngs[i][1], by = latLngs[i][0];
          const px = latlng.lng, py = latlng.lat;

          const dx = bx - ax, dy = by - ay;
          const lenSq = dx * dx + dy * dy;
          let t = lenSq > 0 ? ((px - ax) * dx + (py - ay) * dy) / lenSq : 0;
          t = Math.max(0, Math.min(1, t));

          const cx = ax + t * dx, cy = ay + t * dy;
          const dist = (px - cx) * (px - cx) + (py - cy) * (py - cy);

          if (dist < bestDist) {
            bestDist = dist;
            bestTime = timestamps[i - 1] + t * (timestamps[i] - timestamps[i - 1]);
          }
        }
        return bestTime;
      };

      let videoEl = null;
      let animFrameId = null;

      flightPathLine.on('click', (e) => {
        if (videoEl) {
          L.DomEvent.stopPropagation(e);
          videoEl.currentTime = getTimeAtPoint(e.latlng);
        }
      });
      
      let cleanupCalled = false;
      const cleanup = () => {
        if (cleanupCalled) return;
        cleanupCalled = true;
        if (animFrameId) cancelAnimationFrame(animFrameId);
        this.map.removeLayer(flightPathLine);
        this.map.removeLayer(startDot);
        this.map.removeLayer(endDot);
        this.map.removeLayer(positionDot);
        mediaLayer.addMarker(marker, this.map);
        marker._flightPathLoading = false;
        ReactDOM.unmountComponentAtNode(container);
        container.remove();
      };

      const mapContainer = this.container.parentElement;
      const container = document.createElement('div');
      ReactDOM.render(<MediaView
        basePath={basePath}
        media={media}
        autoOpen
        halfScreen
        mapContainer={mapContainer}
        onVideoElement={(el) => {
          videoEl = el;
          const tick = () => {
            positionDot.setLatLng(getPositionAtTime(el.currentTime));
            animFrameId = requestAnimationFrame(tick);
          };
          animFrameId = requestAnimationFrame(tick);
        }}
        onClose={cleanup}
      />, container);
      document.body.appendChild(container);
    };

    // Check cache
    if (marker._flightPathFeature){
      onFlightPathLoaded(marker._flightPathFeature);
      this.map.removeLayer(spinnerMarker);
      marker._flightPathLoading = false;
    }else{
      $.getJSON(flightPathUrl)
        .done(onFlightPathLoaded)
        .fail(() => {
          const container = document.createElement('div');
          ReactDOM.render(<MediaView
            basePath={basePath}
            media={media}
            autoOpen
            onClose={() => {
              ReactDOM.unmountComponentAtNode(container);
              container.remove();
            }}
          />, container);
          document.body.appendChild(container);
        })
        .always(() => {
          this.map.removeLayer(spinnerMarker);
          marker._flightPathLoading = false;
        });
    }
  }

  render() {
    return (
      <div style={{height: "100%"}} className="map">
        <div className="map-modal-container" ref={(domNode) => this.modalContainer = domNode}></div>

        <ErrorMessage bind={[this, 'error']} />
        <div className="opacity-slider theme-secondary hidden-xs">
            <div className="opacity-slider-label" title={_("Opacity")}><i className="fa fa-adjust"></i></div> <input type="range" className="opacity" step="1" value={this.state.opacity} onChange={this.updateOpacity} />
        </div>

        <Standby
            message={_("Loading...")}
            show={this.state.showLoading}
            />

        <FormDialog
            ref={(domNode) => { this.dxfDialog = domNode; }}
            title={_("Import DXF")}
            saveLabel={_("Import")}
            savingLabel={_("Importing...")}
            saveIcon="fa fa-file-import"
            getFormData={() => ({epsg: this.dxfEpsgInput ? this.dxfEpsgInput.value : ""})}
            saveAction={this.handleDxfImport}
            onShow={this.handleDxfDialogShow}
            onHide={this.handleDxfDialogHide}>
          <div className="form-group">
            <label className="col-sm-3 control-label">EPSG:</label>
            <div className="col-sm-9">
              <input type="number" className="form-control" ref={(domNode) => { this.dxfEpsgInput = domNode; }} placeholder="32617" />
            </div>
          </div>
        </FormDialog>
            
        <div 
          style={{height: "100%"}}
          ref={(domNode) => (this.container = domNode)}
          onMouseDown={this.handleMapMouseDown}
        />

        <div className="actionButtons">
          
          {this.state.pluginActionButtons.map((button, i) => <div key={i}>{button}</div>)}
          {((this.state.singleTask || this.props.project) && this.props.shareButtons && !this.props.public) ? 
            <ShareButton 
              ref={(ref) => { this.shareButton = ref; }}
              task={this.state.singleTask}
              project={this.props.project}
              linksTarget="map"
              queryParams={{t: this.props.mapType}}
            />
          : ""}
          
          <SwitchModeButton 
            task={this.state.singleTask}
            type="mapToModel" 
            public={this.props.public} />
        </div>
      </div>
    );
  }
}

export default Map;
