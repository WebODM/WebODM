import React from 'react';
import '../css/MapPreview.scss';
import 'leaflet/dist/leaflet.css';
import Leaflet from 'leaflet';
import PropTypes from 'prop-types';
import $ from 'jquery';
import ErrorMessage from './ErrorMessage';
import Utils from '../classes/Utils';
import Standby from './Standby';
import exifr from '../vendor/exifr';
import '../vendor/leaflet/leaflet-markers-canvas';
import { _, interpolate } from '../classes/gettext';
import CropButton from './CropButton';
import 'leaflet-fullscreen/dist/Leaflet.fullscreen';
import 'leaflet-fullscreen/dist/leaflet.fullscreen.css';
import '../vendor/leaflet/Leaflet.Autolayers/css/leaflet.auto-layers.css';
import '../vendor/leaflet/Leaflet.Autolayers/leaflet-autolayers';

class MapPreview extends React.Component {
  static defaultProps = {
    getFiles: null,
    onPolygonChange: () => {},
    onImagesBboxChanged: () => {},
    basemaps: []
  };
    
  static propTypes = {
    getFiles: PropTypes.func.isRequired,
    onPolygonChange: PropTypes.func,
    onImagesBboxChanged: PropTypes.func,
    basemaps: PropTypes.array
  };

  constructor(props) {
    super(props);
    
    this.state = {
        showLoading: true,
        error: ""
    };

    this.basemaps = {};
    this.mapBounds = null;
    this.exifData = [];
    this.hasTimestamp = true;
    this.MaxImagesPlot = 10000;
  }

  componentDidMount() {
    this.map = Leaflet.map(this.container, {
      scrollWheelZoom: true,
      positionControl: false,
      zoomControl: false,
      minZoom: 0,
      maxZoom: 24
    });

    this.group = L.layerGroup();
    this.group.addTo(this.map);

    // For some reason, in production this class is not added (but we need it)
    // leaflet bug?
    $(this.container).addClass("leaflet-touch");

    //add zoom control with your options
    Leaflet.control.zoom({
         position:'bottomleft'
    }).addTo(this.map);

    this.basemaps = {};
    const basemaps = this.props.basemaps;
    if (basemaps.length > 0) {
      let defaultBmLayer = null;
      let osmLayer = null;

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
          defaultBmLayer = layer;
        }
        if (bm.label === "OpenStreetMap"){
          osmLayer = layer;
        }

        this.basemaps[bm.label] = layer;
      });
      
      // Prioritize OSM layer for map preview (if available)
      if (osmLayer) osmLayer.addTo(this.map);
      else if (defaultBmLayer) defaultBmLayer.addTo(this.map);
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

    this.autolayers = Leaflet.control.autolayers({
      overlays: {},
      selectedOverlays: [],
      baseLayers: this.basemaps
    }).addTo(this.map);

    this.map.addControl(new L.Control.Fullscreen({
        position: 'bottomleft'
    }));

    var fullscreenchange;

    if ('onfullscreenchange' in document) {
        fullscreenchange = 'fullscreenchange';
    } else if ('onmozfullscreenchange' in document) {
        fullscreenchange = 'mozfullscreenchange';
    } else if ('onwebkitfullscreenchange' in document) {
        fullscreenchange = 'webkitfullscreenchange';
    } else if ('onmsfullscreenchange' in document) {
        fullscreenchange = 'MSFullscreenChange';
    }

    if (fullscreenchange) {
        var onFullscreenChange = L.bind(this.map._onFullscreenChange, this.map);

        this.map.whenReady(function () {
            L.DomEvent.on(document, fullscreenchange, onFullscreenChange);
        });

        this.map.on('unload', function () {
            L.DomEvent.off(document, fullscreenchange, onFullscreenChange);
        });
    }

    this.cropButton = new CropButton({
      position:'bottomleft',
      title: _("Set Reconstruction Area (optional)"),
      group: this.group,
      onPolygonCreated: this.onPolygonCreated,
      onPolygonChange: this.props.onPolygonChange
    });
    this.map.addControl(this.cropButton);

    this.map.fitBounds([
     [13.772919746115805,
     45.664640939831735],
     [13.772825784981254,
     45.664591558975154]]);
    this.map.attributionControl.setPrefix("");

    this.loadNewFiles();
  }

  onPolygonCreated = (polygon) => {
    const popupContainer = L.DomUtil.create('div');
    popupContainer.className = "crop-button-delete";
    const deleteLink = L.DomUtil.create('a');
    deleteLink.href = "javascript:void(0)";
    deleteLink.innerHTML = `<i class="fa fa-trash"></i> ${_("Delete")}`;
    deleteLink.onclick = (e) => {
        L.DomEvent.stop(e);
        this.cropButton.deletePolygon();
    };
    popupContainer.appendChild(deleteLink);

    polygon.bindPopup(popupContainer);
  }

  sampled = (arr, N) => {
    // Return a uniformly sampled array with max N elements
    if (arr.length <= N) return arr;
    else{
      const res = [];
      const step = arr.length / N;
      for (let i = 0; i < N; i++){
        res.push(arr[Math.floor(i * step)]);
      }

      return res;
    }
  };

  loadNewFiles = () => {
    this.setState({showLoading: true});

    if (this.imagesGroup){
      this.map.removeLayer(this.imagesGroup);
      this.imagesGroup = null;
    }

    this.readExifData().then(() => {
      let images = this.sampled(this.exifData, this.MaxImagesPlot).map(exif => {
        let layer = L.circleMarker([exif.gps.latitude, exif.gps.longitude], {
          radius: 8,
          fillOpacity: 1,
          color: "#fcfcff", //ff9e67
          fillColor: "#4b96f3",
          weight: 1.5,
        }).bindPopup(exif.image.name);
        layer.feature = layer.feature || {};
        layer.feature.type = "Feature";
        layer.feature.properties = layer.feature.properties || {};
        layer.feature.properties["Filename"] = exif.image.name;
        if (this.hasTimestamp) layer.feature.properties["Timestamp"] = exif.timestamp;
        return layer;
      });
      
      if (this.capturePath){
        this.map.removeLayer(this.capturePath);
        this.capturePath = null;
      }

      // Only show line if we have reliable date/time info
      if (this.hasTimestamp){
        let coords = this.exifData.map(exif => [exif.gps.latitude, exif.gps.longitude]);
        this.capturePath = L.polyline(coords, {
          color: "#4b96f3",
          weight: 3
        });
        this.capturePath.addTo(this.map);
      }
      
      if (images.length > 0){
        this.imagesGroup = L.featureGroup(images).addTo(this.map);
        this.map.fitBounds(this.imagesGroup.getBounds());
      }

      this.props.onImagesBboxChanged(this.computeBbox(this.exifData));

      this.setState({showLoading: false});

    }).catch(e => {
      this.setState({showLoading: false, error: e.message});
    });
  }

  computeBbox = exifData => {
    // minx, miny, maxx, maxy
    let bbox = [Infinity, Infinity, -Infinity, -Infinity];
    exifData.forEach(ed => {
      if (ed.gps){
        bbox[0] = Math.min(bbox[0], ed.gps.longitude);
        bbox[1] = Math.min(bbox[1], ed.gps.latitude);
        bbox[2] = Math.max(bbox[2], ed.gps.longitude);
        bbox[3] = Math.max(bbox[3], ed.gps.latitude);
      }
    });
    return bbox;
  }

  readExifData = () => {
    return new Promise((resolve, reject) => {
      const files = this.props.getFiles();
      const images = [];
      // TODO: gcps? geo files?

      for (let i = 0; i < files.length; i++){
        const f = files[i];
        if (f.type.indexOf("image") === 0) images.push(f);
      }

      // Parse EXIF
      const options = {
        ifd0: false,
        exif: [0x9003],
        gps: [0x0001, 0x0002, 0x0003, 0x0004, 0x0005, 0x0006],
        interop: false,
        ifd1: false // thumbnail
      };

      const next = (i) => {
        if (i < images.length - 1) parseImage(i+1);
        else{
          // Sort by date/time
          if (this.hasTimestamp){
            this.exifData.sort((a, b) => {
              if (a.timestamp < b.timestamp) return -1;
              else if (a.timestamp > b.timestamp) return 1;
              else return 0;
            });
          }

          resolve();
        }
      };
      
      const parseImage = i => {
        const img = images[i];
        const readExif = img => {
          if (img instanceof Blob) return exifr.parse(img, options);
          if (typeof img.parseExif === "function") return img.parseExif(options);
          return Promise.resolve({});
        };

        readExif(img).then(exif => {
          if (!exif || !exif.latitude || !exif.longitude){
              // reject(new Error(interpolate(_("Cannot extract GPS data from %(file)s"), {file: img.name})));
              next(i);
              return;
          }

          let dateTime = exif.DateTimeOriginal;
          let timestamp = null;
          if (dateTime && dateTime.getTime) timestamp = dateTime.getTime();
          if (!timestamp) this.hasTimestamp = false;

          this.exifData.push({
            image: img,
            gps: {
              latitude: exif.latitude,
              longitude: exif.longitude,
              altitude: exif.GPSAltitude !== undefined ? exif.GPSAltitude : null,
            },
            timestamp
          });

          next(i);
        }).catch((e) => {
          console.warn(e);
          next(i);
        });
      };

      if (images.length > 0) parseImage(0);
      else resolve();
    });
  }

  componentWillUnmount() {
    this.map.remove();
  }

  getCropPolygon = () => {
    return this.cropButton.getCropPolygon();
  }

  setAlignmentPolygon = (task) => {
    if (this.alignPoly){
      this.map.removeLayer(this.alignPoly);
      this.alignPoly = null;
    }

    if (!task || !task.extent){
      if (this.imagesGroup) this.map.fitBounds(this.imagesGroup.getBounds());
      return;
    }

    const [xmin, ymin, xmax, ymax] = task.extent;
    
    this.alignPoly = L.polygon([
      [ymin, xmin],
      [ymax, xmin],
      [ymax, xmax],
      [ymin, xmax],
      [ymin, xmin]
    ], {
      clickable: true,
      weight: 3,
      opacity: 0.9,
      color: "#808f9b",
      fillColor: "#808f9b",
      fillOpacity: 0.2
    }).bindPopup(task.name).addTo(this.map);

    this.alignPoly.bringToBack();
    this.map.fitBounds(this.alignPoly.getBounds());
  }

  download = format => {
    let output = "";
    let filename = `images.${format}`;
    if (format === "geo"){
      filename = "geo.txt";
    }

    const feats = {
      type: "FeatureCollection",
      features: this.exifData.map(ed => {
        return {
          type: "Feature",
          properties: {
            Filename: ed.image.name,
            Timestamp: ed.timestamp
          },
          geometry:{
            type: "Point",
            coordinates: [
              ed.gps.longitude,
              ed.gps.latitude,
              ed.gps.altitude !== null ? ed.gps.altitude : 0
            ]
          }
        }
      })
    };

    if (format === 'geojson'){
      output = JSON.stringify(feats, null, 4);
    }else if (format === 'csv'){
      output = `Filename,Timestamp,Latitude,Longitude,Altitude\r\n${feats.features.map(feat => {
        return `${feat.properties.Filename},${feat.properties.Timestamp},${feat.geometry.coordinates[1]},${feat.geometry.coordinates[0]},${feat.geometry.coordinates[2]}`
      }).join("\r\n")}`;
    }else if (format === 'geo'){
      output = `EPSG:4326\r\n${feats.features.map(feat => {
        return `${feat.properties.Filename} ${feat.geometry.coordinates[0]} ${feat.geometry.coordinates[1]} ${feat.geometry.coordinates[2]}`
      }).join("\r\n")}`;
    }else{
      console.error("Invalid format");
    }

    Utils.saveAs(output, filename);
  }

  render() {
    return (
      <div style={{height: "280px"}} className="map-preview">
        <ErrorMessage bind={[this, 'error']} />

        <Standby 
            message={_("Plotting GPS locations...")}
            show={this.state.showLoading}
            />

        {this.state.error === "" && this.exifData.length > this.MaxImagesPlot ? 
        <div className="plot-warning btn-warning" title={interpolate(_("For performance reasons, only %(num)s images are plotted"), {num: this.MaxImagesPlot})}>
          <i className="fa fa-exclamation-triangle"></i>
        </div>
        : ""}

        {this.state.error === "" ? <div className="download-control">
          <button title={_("Download")} type="button" className="btn btn-sm btn-secondary dropdown-toggle" data-toggle="dropdown">
            <i className="fa fa-download"></i>
          </button>
          <ul className="dropdown-menu">
            <li>
              <a href="javascript:void(0);" onClick={() => this.download('geojson')}><i className="fas fa-map fa-fw"></i> {_("GeoJSON")}</a>
              <a href="javascript:void(0);" onClick={() => this.download('csv')}><i className="fas fa-file-alt fa-fw"></i> {_("CSV")}</a>
              <a href="javascript:void(0);" onClick={() => this.download('geo')}><i className="fas fa-file-alt fa-fw"></i> {_("Geolocation File")}</a>
            </li>
          </ul>
        </div> : ""}

        <div 
          style={{height: "100%"}}
          ref={(domNode) => (this.container = domNode)}
        >
          
        </div>


      </div>
    );
  }
}

export default MapPreview;
