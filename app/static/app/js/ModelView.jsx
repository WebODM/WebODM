import React from 'react';
import './css/ModelView.scss';
import ErrorMessage from './components/ErrorMessage';
import SwitchModeButton from './components/SwitchModeButton';
import AssetDownloadButtons from './components/AssetDownloadButtons';
import Standby from './components/Standby';
import ShareButton from './components/ShareButton';
import ImagePopup from './components/ImagePopup';
import Utils from './classes/Utils';
import PropTypes from 'prop-types';
import PluginsAPI from './classes/plugins/API';
import update from 'immutability-helper';
import * as THREE from 'THREE';
import $ from 'jquery';
import { _, interpolate } from './classes/gettext';
import { getUnitSystem, setUnitSystem, onUnitSystemChanged, offUnitSystemChanged } from './classes/Units';
import UnitSelector from './components/UnitSelector';
import Toolbar from './components/modelview/Toolbar';
import ProjectPanel from './components/modelview/ProjectPanel';
import SettingsWindow from './components/modelview/SettingsWindow';
import Magnifier from './components/modelview/Magnifier';
import Roofs from './components/modelview/Roofs';
import Highlight from './components/modelview/Highlight';
import Reorient from './components/modelview/Reorient';
import ProfilePanel from './components/modelview/ProfilePanel';
import HistoryPanel from './components/modelview/HistoryPanel';
import Gizmo from './components/modelview/Gizmo';
import Minimap from './components/modelview/Minimap';

require('./vendor/OBJLoader');
require('./vendor/MTLLoader');
require('./vendor/GLTFLoader');
require('./vendor/DRACOLoader');

const CAMERA_SCALES = {
    'm': 1.0,
    'ft': 3.28,
    'US survey foot': 3.28
};

class ModelView extends React.Component {
  static defaultProps = {
    task: null,
    public: false,
    shareButtons: true,
    modelType: "cloud",
    title: ""
  };

  static propTypes = {
      task: PropTypes.object.isRequired, // The object should contain two keys: {id: <taskId>, project: <projectId>}
      public: PropTypes.bool, // Is the view being displayed via a shared link?
      shareButtons: PropTypes.bool,
      modelType: PropTypes.oneOf(['cloud', 'mesh', 'splats']),
      title: PropTypes.string
  };

  constructor(props){
    super(props);

    this.state = {
      error: "",
      showingTexturedModel: false,
      initializingModel: false,
      texModelLoadProgress: null,
      showingSplats: false,
      initializingSplats: false,
      splatsLoadProgress: null,
      selectedCamera: null,
      modalOpen: false,
      cameraScale: CAMERA_SCALES[props.task.srs.units] || 1.0,
      camerasVisible: false,
      pluginActionButtons: [],
      viewer: null,
      panel: null,
      vr: false,
      inserted: null,
      focused: null
    };

    this.settings = {};
    try{
        this.settings = JSON.parse(localStorage.getItem("modelview_settings")) || {};
    }catch(e){
        console.warn("Cannot read 3D view settings", e);
    }
    this.history = [];
    this.historyIndex = 0;

    this.prevSceneData = null;
    this.saveSceneReq = null;
    this.saveSceneInterval = null;
    this.saveSceneErrors = 0;

    this.pointCloud = null;
    this.modelReference = null;
    this.splatsReference = null;
    this.sparkRenderer = null;

    this.cameraMeshes = [];
    this.orientation = new THREE.Matrix4();
    this.modelRoot = new THREE.Group();
    this.modelRoot.matrixAutoUpdate = false;
  }

  basePath = () => {
    return `/api/projects/${this.props.task.project}/tasks/${this.props.task.id}`;
  }

  assetsPath = () => {
    return `${this.basePath()}/assets`;
  }

  urlExists = (url, cb) => {
    $.ajax({
        url: url,
        type:'HEAD',
        error: () => {
            cb(false);
        },
        success: () => {
            cb(true);
        }
    });
  }

  loadGeoreferencingOffset = (cb) => {
    $.ajax({
        url: `${this.basePath()}/rtc`,
        type: 'GET',
        error: () => {
            console.warn(`Cannot retrieve georeferencing offset (not georeferenced?)`);
            cb({x: 0, y: 0});
        },
        success: (data) => {
            const [ x, y ] = data.coords;
            cb({x, y});
        }
    });
  }

  pointCloudFilePath = (cb) => {
    // Check if entwine point cloud exists, 
    // otherwise fallback to potree point cloud binary format path
    const entwinePointCloud = this.assetsPath() + '/entwine_pointcloud/ept.json';
    const potreePointCloud = this.assetsPath() + '/potree_pointcloud/cloud.js';

    this.urlExists(entwinePointCloud, (exists) => {
        if (exists) cb(entwinePointCloud);
        else cb(potreePointCloud);
    });
  }

  texturedModelDirectoryPath = () => {
    return this.assetsPath() + '/odm_texturing/';
  }

  hasGeoreferencedAssets = () => {
    return this.props.task.available_assets.indexOf('orthophoto.tif') !== -1;
  }

  hasTexturedModel = () => {
    return this.props.task.available_assets.indexOf('textured_model.zip') !== -1;
  }

  getTexturedModelType = () => {
    if (this.props.task.available_assets.indexOf('textured_model.glb') !== -1) return 'gltf';
    else return 'obj';
  }

  hasCameras = () => {
    return this.props.task.available_assets.indexOf('shots.geojson') !== -1;
  }

  hasSplats = () => {
    return this.props.task.available_assets.indexOf('splats.rad') !== -1;
  }

  objFilePath = (cb) => {
    // Mostly for backward compatibility
    // as newer versions of ODX do not have 
    // a odm_textured_model.obj
    const geoUrl = this.texturedModelDirectoryPath() + 'odm_textured_model_geo.obj';
    const nongeoUrl = this.texturedModelDirectoryPath() + 'odm_textured_model.obj';

    $.ajax({
        type: "HEAD",
        url: geoUrl
    }).done(() => {
        cb(geoUrl);
    }).fail(() => {
        cb(nongeoUrl);
    });
  }

  glbFilePath = () => {
    let url = this.basePath() + '/textured_model/';
    
    if (Utils.isIOS()) url += "?platform=ios";
    else if (Utils.isMobile()) url += "?platform=mobile";
    
    return url;
  }

  mtlFilename = (cb) => {
    // Mostly for backward compatibility
    // as newer versions of ODX do not have 
    // a odm_textured_model.mtl
    const geoUrl = this.texturedModelDirectoryPath() + 'odm_textured_model_geo.mtl';

    $.ajax({
        type: "HEAD",
        url: geoUrl
    }).done(() => {
        cb("odm_textured_model_geo.mtl");
    }).fail(() => {
        cb("odm_textured_model.mtl");
    });
  }

  getSceneData(){
      let json = Potree.saveProject(window.viewer);

      // Remove view, settings since we don't want to trigger
      // scene updates when these change.
      delete json.view;
      delete json.settings;

      if (!this.orientation.equals(new THREE.Matrix4())) json.orientation = this.orientation.toArray();

      return json;
  }

  setOrientation = (matrix) => {
    this.orientation.copy(matrix);
    const rotation = new THREE.Quaternion().setFromRotationMatrix(matrix);

    viewer.scene.pointclouds.forEach(pc => {
      if (!pc.userData.base) pc.userData.base = {position: pc.position.clone(), quaternion: pc.quaternion.clone()};
      pc.position.copy(pc.userData.base.position).applyMatrix4(matrix);
      pc.quaternion.copy(pc.userData.base.quaternion).premultiply(rotation);
      pc.updateMatrixWorld(true);
    });

    this.modelRoot.matrix.copy(matrix);
    this.modelRoot.matrixWorldNeedsUpdate = true;
  }

  applyReorientation = (rotation, center) => {
    const scene = viewer.scene;
    const matrix = new THREE.Matrix4().compose(center.clone().sub(center.clone().applyQuaternion(rotation)), rotation, new THREE.Vector3(1, 1, 1));

    scene.measurements.forEach(m => m.points.forEach((p, i) => m.setPosition(i, p.position.clone().applyMatrix4(matrix))));
    scene.profiles.forEach(profile => profile.points.forEach((p, i) => profile.setPosition(i, p.clone().applyMatrix4(matrix))));
    scene.volumes.forEach(volume => {
      volume.position.applyMatrix4(matrix);
      volume.quaternion.premultiply(rotation);
    });
    scene.annotations.descendants().forEach(a => {
      a.position.applyMatrix4(matrix);
      if (a.hasView()){
        a.cameraPosition.applyMatrix4(matrix);
        a.cameraTarget.applyMatrix4(matrix);
      }
    });
    scene.cameraAnimations.forEach(a => {
      if (a.orbit){
        a.orbit.center.applyMatrix4(matrix);
        a.orbit.target.applyMatrix4(matrix);
      }
    });

    const target = scene.view.getPivot().applyMatrix4(matrix);
    scene.view.position.applyMatrix4(matrix);
    scene.view.lookAt(target);

    this.setOrientation(matrix.multiply(this.orientation));
  }

  componentDidMount() {
    let container = this.container;
    if (!container) return; // Enzyme tests don't have support for all WebGL methods so we just skip this

    window.viewer = new Potree.Viewer(container);
    viewer.setEDLEnabled(true);
    viewer.setFOV(60);

    if (Utils.isIOS()){
        viewer.setPointBudget(1000*1000);
    }else if (Utils.isMobile()){
        viewer.setPointBudget(2*1000*1000);
    }else{
        viewer.setPointBudget(10*1000*1000);
    }
    viewer.setEDLEnabled(true);
    viewer.loadSettingsFromURL();

    viewer.compass.dom.css({top: "12px", left: "12px", right: "", zIndex: 2, cursor: "pointer"});
    viewer.compass.setVisible(this.settings.compass !== false);

    onUnitSystemChanged(this.handleUnitSystemChanged);
    document.addEventListener("keydown", this.handleKeyDown);

    Potree.VRButton.createButton(viewer.renderer).then(vrButton => {
        if (!vrButton) return;

        viewer.renderer.xr.enabled = true;
        vrButton.onStart(() => viewer.dispatchEvent({type: "vr_start"}));
        vrButton.onEnd(() => viewer.dispatchEvent({type: "vr_end"}));
        this.vrButton = vrButton;
        this.setState({vr: true});
    });

    this.setState({viewer});

    viewer.scene.scene.add( new THREE.AmbientLight( 0x404040, 2.0 ) ); // soft white light );
    viewer.scene.scene.add( new THREE.DirectionalLight( 0xcccccc, 0.5 ) );

    const directional = new THREE.DirectionalLight( 0xcccccc, 0.5 );
    directional.position.z = 99999999999;
    viewer.scene.scene.add( directional );
    viewer.scene.scene.add(this.modelRoot);

    this.pointCloudFilePath(pointCloudPath =>{ 
        Potree.loadPointCloud(pointCloudPath, "Point Cloud", e => {
          if (e.type == "loading_failed"){
            this.setState({error: _("Could not load point cloud. This task doesn't seem to have one. Try processing the task again.")});
            return;
          }
          
          // Set crop vertices if needed
          e.pointcloud.material.cropVertices = this.getCropCoordinates();

          // Automatically load 3D model if required
          if (this.hasTexturedModel() && this.props.modelType === "mesh"){
            this.toggleTexturedModel(true);
          }else if (this.hasSplats() && this.props.modelType === "splats"){
            this.toggleSplats(true);
          }
    
          let scene = viewer.scene;
          scene.addPointCloud(e.pointcloud);

          this.pointCloud = e.pointcloud;
    
          let material = e.pointcloud.material;
          material.size = 1;

          viewer.fitToScreen();
        
          this.handleUnitSystemChanged();

          this.defaults = {
              magnifier: true,
              gizmo: false,
              compass: true,
              minimap: true,
              background: "gradient",
              fov: viewer.getFOV(),
              cameraMode: "PERSPECTIVE",
              pointBudget: viewer.getPointBudget(),
              pointSizeType: Object.keys(Potree.PointSizeType).find(k => Potree.PointSizeType[k] === material.pointSizeType),
              pointShape: Object.keys(Potree.PointShape).find(k => Potree.PointShape[k] === material.shape),
              pointSize: material.size,
              edlEnabled: true,
              edlStrength: viewer.edlStrength,
              edlRadius: viewer.edlRadius,
              hq: false,
              smoothness: "standard",
              moveSpeed: Math.log10(viewer.getMoveSpeed())
          };

          for (let k in this.settings) this.setSetting(k, this.settings[k]);

          // Load saved scene (if any)
          $.ajax({
              type: "GET",
              url: `/api/projects/${this.props.task.project}/tasks/${this.props.task.id}/3d/scene`
          }).done(sceneData => {
            let localSceneData = Potree.saveProject(viewer);

            // Check if we do not have a view set
            // if so, just keep the current view information
            if (!sceneData.view || !sceneData.view.position){
                sceneData.view = localSceneData.view;
            }

            const keepKeys = ['pointclouds', 'settings'];
            for (let k of keepKeys){
                sceneData[k] = localSceneData[k];
            }
            
            for (let k in localSceneData){
                if (keepKeys.indexOf(k) === -1){
                    sceneData[k] = sceneData[k] || localSceneData[k];
                }
            }

            if (sceneData.orientation) this.setOrientation(new THREE.Matrix4().fromArray(sceneData.orientation));

            // Load
            const potreeLoadProject = () => {
                Potree.loadProject(viewer, sceneData);
                viewer.scene.annotations.descendants().forEach(a => { if (a.hasView()) a.visible = false; });
                viewer.scene.cameraAnimations.forEach(a => a.setVisible(false));
                viewer.removeEventListener("update", potreeLoadProject);
            };
            viewer.addEventListener("update", potreeLoadProject);

            this.prevSceneData = JSON.stringify(this.getSceneData());

            // Give Potree a moment to load the saved scene before
            // taking the first undo snapshot
            setTimeout(() => {
                this.history = [{label: "", data: this.getHistoryData()}];
                this.historyIndex = 0;
                this.historyInterval = setInterval(this.recordHistory, 500);
                this.latLonInterval = setInterval(this.updateLatLon, 500);
            }, 1000);

            // Every 3 seconds, check if the scene has changed
            // if it has, save the changes server-side
            // Unfortunately Potree does not have reliable events
            // for trivially detecting changes in measurements
            this.saveSceneInterval = setInterval(() => {
                if (this.canEdit()) this.saveScene();

                // Potree is a bit strange, sometimes fitToScreen does
                // not work, so we check whether the camera position is still
                // at zero and recall fitToScreen
                const pos = viewer.scene.view.position;
                if (pos.x === 0 && pos.y === 0 && pos.z === 0) viewer.fitToScreen();
            }, 3000);
          }).fail(e => {
            console.error("Cannot load 3D scene information", e);
          });
        });
    });

    this.highlight = new Highlight(viewer);
    this.reorient = new Reorient(viewer, this.applyReorientation);
    viewer.roofTool = new Roofs(viewer, item => this.setState({panel: "project", inserted: item, focused: null}));
    viewer.renderer.domElement.addEventListener( 'mousedown', this.handleRenderMouseClick );
    viewer.renderer.domElement.addEventListener( 'mousedown', this.handleRenderMouseDownCapture, true );
    viewer.renderer.domElement.addEventListener( 'mouseup', this.handleRenderMouseUpCapture, true );
    viewer.renderArea.addEventListener( 'contextmenu', this.handleAnnotationContextMenu );
    viewer.renderer.domElement.addEventListener( 'dblclick', this.handleRenderDoubleClickCapture, true );
    viewer.renderer.domElement.addEventListener( 'mousemove', this.handleRenderMouseMove );
    viewer.renderer.domElement.addEventListener( 'touchstart', this.handleRenderTouchStart );
    
    PluginsAPI.ModelView.triggerAddActionButton({
      viewer
    }, (button) => {
      this.setState(update(this.state, {
        pluginActionButtons: {$push: [button]}
      }));
    });
  }

  getHistoryData = () => {
    const json = Potree.saveProject(viewer);

    return JSON.stringify({
        type: json.type,
        version: json.version,
        measurements: json.measurements.map(m => Object.assign({}, m, {latlon: undefined})),
        volumes: json.volumes,
        profiles: json.profiles,
        annotations: json.annotations,
        cameraAnimations: json.cameraAnimations.map(a => Object.assign({}, a, {t: 0})),
        orientation: this.orientation.toArray()
    });
  }

  updateLatLon = () => {
    if (this.latLonReq || viewer.inputHandler.drag) return;

    const stale = viewer.scene.measurements.filter(m => m.display === "latlon" && m.points.length === 1 &&
      (!m.latlon || m.latlon.x !== m.points[0].position.x || m.latlon.y !== m.points[0].position.y));
    if (stale.length === 0) return;

    const { task } = this.props;
    const positions = stale.map(m => m.points[0].position.clone());

    this.latLonReq = $.ajax({
        url: `/api/projects/${task.project}/tasks/${task.id}/reproject`,
        contentType: 'application/json',
        data: JSON.stringify({
            geojson: {type: "MultiPoint", coordinates: positions.map(p => [p.x, p.y])},
            source: task.epsg ? `EPSG:${task.epsg}` : task.wkt,
            target: "EPSG:4326"
        }),
        type: 'POST'
    }).done(result => {
        stale.forEach((m, i) => {
            m.latlon = {x: positions[i].x, y: positions[i].y, lat: result.coordinates[i][1], lon: result.coordinates[i][0]};
            m.update();
        });
    }).fail(() => {
        stale.forEach(m => {
            m.display = "native";
            m.update();
        });
    }).always(() => {
        this.latLonReq = null;
    });
  }

  recordHistory = () => {
    if (viewer.inputHandler.drag || viewer.scene.cameraAnimations.some(a => a.dragging) || this.reorient.active()) return;

    const data = this.getHistoryData();
    const prevData = this.history[this.historyIndex].data;
    if (data === prevData) return;

    const prev = JSON.parse(prevData);
    const next = JSON.parse(data);
    let label = _("Changed scene");

    for (let key of ["measurements", "volumes", "profiles", "annotations", "cameraAnimations"]){
        const added = next[key].find(n => !prev[key].find(p => p.uuid === n.uuid));
        const removed = prev[key].find(p => !next[key].find(n => n.uuid === p.uuid));
        const modified = next[key].find(n => {
            const p = prev[key].find(p => p.uuid === n.uuid);
            return p && JSON.stringify(p) !== JSON.stringify(n);
        });

        if (added) label = interpolate(_("Added %(name)s"), {name: added.name || added.title});
        else if (removed) label = interpolate(_("Removed %(name)s"), {name: removed.name || removed.title});
        else if (modified) label = interpolate(_("Modified %(name)s"), {name: modified.name || modified.title});

        if (added || removed || modified) break;
    }

    this.history = this.history.slice(Math.max(0, this.historyIndex - 49), this.historyIndex + 1).concat([{label, data}]);
    this.historyIndex = this.history.length - 1;
    this.forceUpdate();
  }

  restoreHistory = (index) => {
    if (index < 0 || index >= this.history.length || viewer.inputHandler.drag) return;

    const scene = viewer.scene;
    const live = Potree.saveProject(viewer);
    const data = JSON.parse(this.history[index].data);
    data.view = live.view;
    data.settings = live.settings;
    data.classification = live.classification;
    data.pointclouds = [];

    const hidden = scene.annotations.descendants().concat(scene.cameraAnimations).filter(a => !a.visible).map(a => a.uuid);

    viewer.inputHandler.deselectAll();
    scene.removeAllMeasurements();
    scene.annotations.removeAllChildren();
    while (scene.cameraAnimations.length > 0) scene.removeCameraAnimation(scene.cameraAnimations[0]);

    this.setOrientation(new THREE.Matrix4().fromArray(data.orientation));
    Potree.loadProject(viewer, data);

    scene.annotations.descendants().forEach(a => { if (hidden.indexOf(a.uuid) !== -1) a.visible = false; });
    scene.cameraAnimations.forEach(a => { if (hidden.indexOf(a.uuid) !== -1) a.setVisible(false); });

    this.historyIndex = index;
    this.forceUpdate();
  }

  handleKeyDown = (e) => {
    if (!(e.ctrlKey || e.metaKey) || ["INPUT", "TEXTAREA", "SELECT"].indexOf(e.target.tagName) !== -1) return;

    const key = e.key.toLowerCase();
    if (key === "z" && !e.shiftKey){
        e.preventDefault();
        this.restoreHistory(this.historyIndex - 1);
    }else if (key === "y" || (key === "z" && e.shiftKey)){
        e.preventDefault();
        this.restoreHistory(this.historyIndex + 1);
    }
  }

  canEdit = () => {
    return !this.props.public || !!this.props.task.public_edit;
  }

  saveScene = () => {
    if (this.prevSceneData === null) return;

    const sceneData = JSON.stringify(this.getSceneData());
    if (sceneData === this.prevSceneData) return;

    if (this.saveSceneReq) this.saveSceneReq.abort();

    this.saveSceneReq = $.ajax({
        url: `${this.basePath()}/3d/scene`,
        contentType: 'application/json',
        data: sceneData,
        dataType: 'json',
        type: 'POST'
    }).done(result => {
        if (result.success){
            this.saveSceneErrors = 0;
            this.prevSceneData = sceneData;
        }else{
            console.warn("Cannot save Potree scene");
        }
    }).fail((xhr, status) => {
        if (status === "abort") return;
        console.error("Cannot save Potree scene");
        if (++this.saveSceneErrors === 5) clearInterval(this.saveSceneInterval);
    });
  }

  setInitialCameraView = (cb, view) => {
    $.ajax({
        url: `${this.basePath()}/3d/cameraview`,
        contentType: 'application/json',
        data: JSON.stringify(view || Potree.saveProject(viewer).view),
        dataType: 'json',
        type: 'POST'
    }).done(result => {
        cb(result.success ? "" : _("Cannot set initial camera view"));
    }).fail(() => {
        cb(_("Cannot set initial camera view"));
    });
  }

  setSetting = (key, value) => {
    const pointclouds = viewer.scene.pointclouds;

    if (key === "background"){
        viewer.setBackground(value === "gradient" ? "gradient" : null);
        this.container.style.background = value === "gradient" ? "" : value;
    }
    else if (key === "fov") viewer.setFOV(value);
    else if (key === "cameraMode") viewer.setCameraMode(Potree.CameraMode[value]);
    else if (key === "pointBudget") viewer.setPointBudget(value);
    else if (key === "pointSizeType") pointclouds.forEach(pc => { pc.material.pointSizeType = Potree.PointSizeType[value]; });
    else if (key === "pointShape") pointclouds.forEach(pc => { pc.material.shape = Potree.PointShape[value]; });
    else if (key === "pointSize") pointclouds.forEach(pc => { pc.material.size = value; });
    else if (key === "edlEnabled"){
        if (this.getCurrentModelType() === "cloud") viewer.setEDLEnabled(value);
    }
    else if (key === "edlStrength") viewer.setEDLStrength(value);
    else if (key === "edlRadius") viewer.setEDLRadius(value);
    else if (key === "hq"){
        if (this.getCurrentModelType() === "cloud") viewer.useHQ = value;
    }
    else if (key === "compass") viewer.compass.setVisible(value);
    else if (key === "smoothness"){
        const factor = {smooth: 0.5, standard: 1, snappy: 2.5}[value] || 1;
        viewer.orbitControls.fadeFactor = 20 * factor;
        viewer.earthControls.fadeFactor = 20 * factor;
        viewer.fpControls.fadeFactor = 50 * factor;
    }
    else if (key === "moveSpeed"){
        viewer.setMoveSpeed(Math.pow(10, value));
        return;
    }

    this.settings[key] = value;
    localStorage.setItem("modelview_settings", JSON.stringify(this.settings));
    this.forceUpdate();
  }

  resetSettings = () => {
    for (let k in this.defaults) this.setSetting(k, this.defaults[k]);
    this.settings = {};
    localStorage.removeItem("modelview_settings");
    setUnitSystem("metric");
    this.forceUpdate();
  }

  togglePanel = (panel) => {
    this.setState({panel: this.state.panel === panel ? null : panel, inserted: null, focused: null});
  }

  handleUnitSystemChanged = () => {
    if (!window.viewer) return;

    const us = getUnitSystem();
    
    // GDAL --> Potree
    const UNIT_MAP = { 
        'm': 'm',
        'ft': 'ft',
        'US survey foot': 'ft (US)'
    };

    const dsUnit = UNIT_MAP[this.props.task.srs.units] || 'm';

    if (us === 'metric'){
        window.viewer.setLengthUnitAndDisplayUnit(dsUnit, 'm');
    }else if (us === 'imperial'){
        window.viewer.setLengthUnitAndDisplayUnit(dsUnit, 'ft');
    }else if (us === 'imperialUS'){
        window.viewer.setLengthUnitAndDisplayUnit(dsUnit, 'ft (US)');
    }

    if (window.viewer.profileWindowController) window.viewer.profileWindowController.recompute();
  }

  getCropCoordinates(){
    if (this.props.task.crop_projected && this.props.task.crop_projected.length >= 3){
        return this.props.task.crop_projected.map(coord => {
            return new THREE.Vector3(coord[0], coord[1], 0.0);
        });
    }
  }

  componentWillUnmount(){
    offUnitSystemChanged(this.handleUnitSystemChanged);
    clearInterval(this.saveSceneInterval);
    clearInterval(this.historyInterval);
    clearInterval(this.latLonInterval);
    document.removeEventListener("keydown", this.handleKeyDown);
    viewer.roofTool.dispose();
    this.highlight.dispose();
    this.reorient.dispose();
    viewer.renderer.domElement.removeEventListener( 'mousedown', this.handleRenderMouseClick );
    viewer.renderer.domElement.removeEventListener( 'mousedown', this.handleRenderMouseDownCapture, true );
    viewer.renderer.domElement.removeEventListener( 'mouseup', this.handleRenderMouseUpCapture, true );
    viewer.renderArea.removeEventListener( 'contextmenu', this.handleAnnotationContextMenu );
    viewer.renderer.domElement.removeEventListener( 'dblclick', this.handleRenderDoubleClickCapture, true );
    viewer.renderer.domElement.removeEventListener( 'mousemove', this.handleRenderMouseMove );
    viewer.renderer.domElement.removeEventListener( 'touchstart', this.handleRenderTouchStart );
    
  }

  getCameraUnderCursor = (evt) => {
    const raycaster = new THREE.Raycaster();
    const rect = viewer.renderer.domElement.getBoundingClientRect();
    const [x, y] = [evt.clientX, evt.clientY];
    const array = [ 
        ( x - rect.left ) / rect.width, 
        ( y - rect.top ) / rect.height 
    ];
    const onClickPosition = new THREE.Vector2(...array);
    const camera = viewer.scene.getActiveCamera();
    const mouse = new THREE.Vector3(
        + ( onClickPosition.x * 2 ) - 1, 
        - ( onClickPosition.y * 2 ) + 1 );
    raycaster.setFromCamera( mouse, camera );
    const intersects = raycaster.intersectObjects( this.cameraMeshes );

    if ( intersects.length > 0){
        const intersection = intersects[0];
        return intersection.object.parent.parent;
    }
  }

  setCameraOpacity(camera, opacity){
    camera.traverse(obj => {
        if (obj.material) obj.material.opacity = opacity;
    });
  }

  handleRenderMouseMove = (evt) => {
    if (this._prevCamera && this._prevCamera !== this.state.selectedCamera) {
        this.setCameraOpacity(this._prevCamera, 0.7);
    }

    const camera = this.getCameraUnderCursor(evt);
    if (camera){
        viewer.renderer.domElement.classList.add("pointer-cursor");
        this.setCameraOpacity(camera, 1);
    }else{
        viewer.renderer.domElement.classList.remove("pointer-cursor");
    }
    this._prevCamera = camera;
  }

  handleRenderTouchStart = (evt) => {
    if (evt.touches.length === 1){
        this.handleRenderMouseClick({clientX: evt.touches[0].clientX, clientY: evt.touches[0].clientY});
    }
  }

  handleRenderMouseDownCapture = () => {
    this.placingOnMouseDown = !!viewer.inputHandler.drag;
  }

  handleRenderMouseUpCapture = (evt) => {
    if (evt.button !== 2 || this.placingOnMouseDown || viewer.inputHandler.getNormalizedDrag().length() !== 0) return;

    const hovered = viewer.inputHandler.hoveredElements.map(h => h.object);
    const item = viewer.scene.measurements.concat(viewer.scene.profiles).find(m => m.spheres.some(s => hovered.indexOf(s) !== -1)) || viewer.scene.volumes.find(v => hovered.indexOf(v) !== -1) || this.pointOfViewAt(evt);
    if (item) this.setState({panel: "project", inserted: null, focused: {item}});
  }

  handleAnnotationContextMenu = (evt) => {
    const el = evt.target.closest(".annotation");
    if (!el) return;

    const item = viewer.scene.annotations.descendants().find(a => a.domElement[0] === el);
    if (item) this.setState({panel: "project", inserted: null, focused: {item}});
  }

  pointOfViewAt = (evt) => {
    const rect = viewer.renderer.domElement.getBoundingClientRect();
    const camera = viewer.scene.getActiveCamera();
    return viewer.scene.annotations.descendants().find(a => {
      if (!a.marker || !a.marker.visible) return false;
      const p = a.marker.localToWorld(new THREE.Vector3(0, 0, 0.5)).project(camera);
      return Math.abs(p.z) < 1 && Math.hypot(rect.left + (p.x + 1) / 2 * rect.width - evt.clientX, rect.top + (1 - p.y) / 2 * rect.height - evt.clientY) < 25;
    });
  }

  handleRenderDoubleClickCapture = (evt) => {
    const item = this.pointOfViewAt(evt);
    if (!item) return;

    evt.stopImmediatePropagation();
    item.moveHere(viewer.scene.getActiveCamera());
    this.setState({panel: "project", inserted: null, focused: {item}});
  }

  handleRenderMouseClick = (evt) => {
    let camera = this.getCameraUnderCursor(evt);
    // Deselect
    if (camera === this.state.selectedCamera){
        this.setState({selectedCamera: null});
    }else if (camera){
        if (this.state.selectedCamera){
            this.setCameraOpacity(this.state.selectedCamera, 0.7);
        }
        this.setState({selectedCamera: camera});
    }
  }

  closeThumb = (e) => {
    e.stopPropagation();
    this.setState({selectedCamera: null});
  }

  loadCameras(){
    const { task } = this.props;

    function getMatrix(translation, rotation, scale) {
        var axis = new THREE.Vector3(-rotation[0],
                                    -rotation[1],
                                    -rotation[2]);
        var angle = axis.length();
        axis.normalize();
        var matrix = new THREE.Matrix4().makeRotationAxis(axis, angle);
        matrix.setPosition(new THREE.Vector3(translation[0], translation[1], translation[2]));
        
        if (scale != 1.0){
            matrix.scale(new THREE.Vector3(scale, scale, scale));
        }

        return matrix.transpose();
    }

    if (this.hasCameras()){
        const fileloader = new THREE.FileLoader();
        
        this.loadGltf('/static/app/models/camera.glb', (err, gltf) => {
            if (err){
                console.error(err);
                return;
            }

            const cameraObj = gltf.scene;

            fileloader.load(`/api/projects/${task.project}/tasks/${task.id}/download/shots.geojson`,  ( data ) => {
                const geojson = JSON.parse(data);
                cameraObj.traverse(obj => {
                    if (obj.material){
                        obj.material.transparent = true; 
                        obj.material.opacity = 0.7;
                    }
                });
                
                let i = 0;
                geojson.features.forEach(feat => {
                    const cameraMesh = cameraObj.clone();
                    cameraMesh.traverse((node) => {
                        if (node.isMesh) {
                            node.material = node.material.clone();
                        }
                    });

                    cameraMesh.matrixAutoUpdate = false;
                    let scale = this.state.cameraScale;
                    // if (!this.pointCloud.projection) scale = 0.1;

                    cameraMesh.matrix.set(...getMatrix(feat.properties.translation, feat.properties.rotation, scale).elements);
                    
                    this.modelRoot.add(cameraMesh);

                    cameraMesh._feat = feat;
                    this.cameraMeshes.push(cameraMesh.children[0].children[1]);

                    i++;
                });
            }, undefined, console.error);
        });
    }
  }

  setPointCloudsVisible = (flag) => {
    viewer.setEDLEnabled(true);
    
    // Using opacity we can still perform measurements
    viewer.setEDLOpacity(flag ? 1 : 0);
    viewer.useHQ = flag && !!this.settings.hq;

    // On mobile, for performance and because opacity doesn't
    // seem to work consistently, we remove the ability to do
    // measurements
    if (Utils.isMobile()){
        for(let pointcloud of viewer.scene.pointclouds){
            pointcloud.visible = flag;
        }
    }
  }

  toggleCameras = () => {
    this.setState({camerasVisible: !this.state.camerasVisible});

    if (this.cameraMeshes.length === 0){
        this.loadCameras();
        if (this.cameraMeshes.length === 0) return;
    }

    const isVisible = this.cameraMeshes[0].visible;
    this.cameraMeshes.forEach(cam => {
        cam.visible = !isVisible;
        cam.parent.visible = cam.visible;
    });
  }

  changeCameraScale = (value) => {
    if (this.cameraMeshes.length === 0) return;

    this.cameraMeshes.forEach(cam => {
        cam.parent.scale.setScalar(value);
    });
  }

  loadGltf = (url, cb, onProgress) => {
    if (!this.gltfLoader) this.gltfLoader = new THREE.GLTFLoader();
    if (!this.dracoLoader) {
        this.dracoLoader = new THREE.DRACOLoader();
        this.dracoLoader.setDecoderPath( '/static/app/js/vendor/draco/' );
        this.gltfLoader.setDRACOLoader( this.dracoLoader );
    }

    // Load a glTF resource
    this.gltfLoader.load(url,
        gltf => { cb(null, gltf) },
        onProgress,
        error => { cb(error); },
        {crop: this.getCropCoordinates()}
    );
  }

  getCurrentModelType = () => {
    if (this.state.showingTexturedModel || this.state.initializingModel) return "mesh";
    if (this.state.showingSplats || this.state.initializingSplats) return "splats";
    return "cloud";
  }

  setModelType = (type) => {
    if (this.state.initializingModel || this.state.initializingSplats) return;

    const current = this.getCurrentModelType();
    if (current === type) return;

    if (current === "mesh") this.toggleTexturedModel(false);
    else if (current === "splats") this.toggleSplats(false);

    if (type === "mesh") this.toggleTexturedModel(true);
    else if (type === "splats") this.toggleSplats(true);
  }

  loadSplatsModule = (cb) => {
    if (window.THREEdgs){
        cb();
        return;
    }

    $.ajax({
        url: "/static/app/js/vendor/threedgs.umd.min.js",
        dataType: "script",
        cache: true
    }).done(() => {
        if (window.THREEdgs) cb();
        else cb(new Error(_("Cannot load splats renderer")));
    }).fail(() => {
        cb(new Error(_("Cannot load splats renderer")));
    });
  }

  initSplatsRenderer = () => {
    this.sparkRenderer = new THREEdgs.SparkRenderer({renderer: viewer.renderer});
    viewer.scene.scene.add(this.sparkRenderer);
  }

  setSplatsVisible = (flag) => {
    if (this.sparkRenderer) this.sparkRenderer.visible = flag;
  }

  toggleSplats = (show) => {
    if (show){
      // Need to load splats for the first time?
      if (this.splatsReference === null && !this.state.initializingSplats){

        this.setState({initializingSplats: true, splatsLoadProgress: null});

        this.loadSplatsModule(err => {
            if (err){
                this.setState({initializingSplats: false, error: err.message});
                return;
            }

            if (!this.sparkRenderer) this.initSplatsRenderer();

            const url = this.assetsPath() + '/splats/model.rad';
            const splats = new THREEdgs.SplatMesh({
                url,
                paged: true,
                onProgress: e => {
                    if (e.lengthComputable){
                        this.setState({splatsLoadProgress: Math.round((e.loaded / e.total) * 100)});
                    }
                },
                onLoad: () => {
                    this.setState({splatsLoadProgress: null});
                    this.loadGeoreferencingOffset((offset) => {
                        splats.translateX(offset.x);
                        splats.translateY(offset.y);

                        const cropCoords = this.getCropCoordinates();
                        if (cropCoords){
                            this.sparkRenderer.cropVertices = cropCoords.map(v => new THREE.Vector2(v.x, v.y));
                        }

                        this.modelRoot.add(splats);
                        this.splatsReference = splats;

                        this.sparkRenderer.addEventListener("firstDisplay", () => {
                            this.setPointCloudsVisible(false);
                            this.setState({
                                initializingSplats: false,
                                showingSplats: true
                            });
                        });
                    });
                }
            });

            splats.initialized.catch(e => {
                console.error(e);
                this.setState({initializingSplats: false, error: _("Could not load splats. This task doesn't seem to have a valid splats file.")});
            });
        });
      }else{
        // Already initialized
        this.setSplatsVisible(true);
        this.setPointCloudsVisible(false);
        this.setState({showingSplats: true});
      }
    }else{
      this.setSplatsVisible(false);
      this.setPointCloudsVisible(true);
      this.setState({showingSplats: false});
    }
  }

  toggleTexturedModel = (show) => {
    if (show){
      // Need to load model for the first time?
      if (this.modelReference === null && !this.state.initializingModel){

        this.setState({initializingModel: true});

        const addObject = (object, offset) => {
            object.translateX(offset.x);
            object.translateY(offset.y);

            this.modelRoot.add(object);

            this.modelReference = object;
            this.setPointCloudsVisible(false);

            this.setState({
                initializingModel: false,
                showingTexturedModel: true
            });
        }

        if (this.getTexturedModelType() === 'gltf'){
            this.loadGltf(this.glbFilePath(), (err, gltf) => {
                if (err){
                    this.setState({initializingModel: false, error: err});
                    return;
                }
                this.setState({texModelLoadProgress: null});
                
                setTimeout(() => {
                    const offset = {x: 0, y: 0};
                    if (gltf.scene.CESIUM_RTC && gltf.scene.CESIUM_RTC.center){
                        offset.x = gltf.scene.CESIUM_RTC.center[0];
                        offset.y = gltf.scene.CESIUM_RTC.center[1];
                    }
    
                    addObject(gltf.scene, offset);
                }, 0);
            }, xhr => {
                const progress = Math.round((xhr.loaded / xhr.total) * 100);
                this.setState({texModelLoadProgress: progress});
            });
        }else{
            // Legacy OBJ

            const mtlLoader = new THREE.MTLLoader();
            mtlLoader.setPath(this.texturedModelDirectoryPath());
    
            this.mtlFilename(mtlPath => {
                mtlLoader.load(mtlPath, (materials) => {
                    materials.preload();
        
                    const objLoader = new THREE.OBJLoader();
                    objLoader.setMaterials(materials);
                    this.objFilePath(filePath => {
                        objLoader.load(filePath, (object) => {
                            this.loadGeoreferencingOffset((offset) => {
                                addObject(object, offset);
                            });
                        });
                    });
                });
            });
        }
      }else{
        // Already initialized
        this.modelReference.visible = true;
        this.setPointCloudsVisible(false);
        this.setState({showingTexturedModel: true});
      }
    }else{
      this.modelReference.visible = false;
      this.setPointCloudsVisible(true);
      this.setState({showingTexturedModel: false});
    }
  }

  // React render
  render(){
    const { selectedCamera, showingTexturedModel, initializingModel, showingSplats, initializingSplats } = this.state;
    const { task } = this.props;
    const queryParams = {};
    if (showingTexturedModel){
        queryParams.t = "mesh";
    }else if (showingSplats){
        queryParams.t = "splats";
    }

    let modelTypeButtons = [
      {
        label: _("Point Cloud"),
        type: "cloud",
        icon: "fa fa-pointcloud"
      }
    ];
    if (this.hasTexturedModel()){
      modelTypeButtons.push({
        label: _("Textured Model"),
        type: "mesh",
        icon: "fab fa-connectdevelop"
      });
    }
    if (this.hasSplats()){
      modelTypeButtons.push({
        label: _("Splats"),
        type: "splats",
        icon: "fa fa-splat"
      });
    }

    // If we have only one type available, hide the buttons
    if (modelTypeButtons.length === 1) modelTypeButtons = [];

    const selectedModelType = this.getCurrentModelType();
    const initializing = initializingModel || initializingSplats;

    const { viewer, panel } = this.state;
    return (<div className="model-view">
          <ErrorMessage bind={[this, "error"]} />

          {(this.props.title || modelTypeButtons.length > 0) ?
          <div className="model-view-header">
            {this.props.title ?
              <h3 className="model-title" title={this.props.title}><i className="fa fa-cube"></i> {this.props.title}</h3>
            : ""}

            <div className="model-type-selector btn-group" role="group">
              {modelTypeButtons.map(modelType =>
                <button
                  key={modelType.type}
                  onClick={() => this.setModelType(modelType.type)}
                  disabled={initializing}
                  title={modelType.label}
                  className={"btn btn-sm " + (modelType.type === selectedModelType ? "btn-primary" : "btn-default")}><i className={modelType.icon + " fa-fw"}></i><span className="hidden-sm hidden-xs"> {modelType.label}</span></button>
              )}
            </div>
          </div>
          : ""}

          <div className="mv-body">
            <div className="container potree_container"
                style={{width: "100%", position: "relative"}}
                onContextMenu={(e) => {e.preventDefault();}}>
                    <div id="potree_render_area"
                        ref={(domNode) => { this.container = domNode; }}></div>

                    {viewer ? <Toolbar viewer={viewer} modelType={selectedModelType} panel={panel} onTogglePanel={this.togglePanel}
                                        hasCameras={this.hasCameras()}
                                        camerasVisible={this.state.camerasVisible}
                                        onToggleCameras={this.toggleCameras}
                                        onAttributeChange={() => this.forceUpdate()}
                                        onInsert={item => this.setState({panel: "project", inserted: item, focused: null})}
                                        onReorient={this.props.task.epsg || this.props.task.wkt ? null : measure => this.reorient.start(measure)}
                                        onEnterVR={this.state.vr ? () => this.vrButton.element.click() : null} /> : ""}

                    {viewer && panel === "project" ?
                    <ProjectPanel viewer={viewer}
                                task={this.props.task}
                                hasCameras={this.hasCameras()}
                                camerasVisible={this.state.camerasVisible}
                                onToggleCameras={this.toggleCameras}
                                onAttributeChange={() => this.forceUpdate()}
                                inserted={this.state.inserted}
                                focused={this.state.focused}
                                onSetInitialCameraView={this.props.public ? null : this.setInitialCameraView}
                                onCameraScaleChange={this.changeCameraScale}
                                onClose={() => this.setState({panel: null, inserted: null, focused: null})} />
                    : ""}

                    {viewer && panel === "history" ?
                    <HistoryPanel history={this.history}
                                index={this.historyIndex}
                                onRestore={this.restoreHistory}
                                onClose={() => this.setState({panel: null})} />
                    : ""}

                    {viewer && panel === "settings" ?
                    <SettingsWindow viewer={viewer}
                                task={task}
                                title={this.props.title}
                                settings={this.settings}
                                modelType={selectedModelType}
                                onChange={this.setSetting}
                                onReset={this.resetSettings}
                                onSetInitialCameraView={this.props.public ? null : this.setInitialCameraView}
                                onClose={() => this.setState({panel: null})} />
                    : ""}

                    {viewer ? <ProfilePanel viewer={viewer} /> : ""}

                    {viewer && this.settings.gizmo === true ? <Gizmo viewer={viewer} shifted={panel === "project" || panel === "history"} /> : ""}

                    {viewer && this.settings.minimap !== false ? <Minimap viewer={viewer} /> : ""}

                    {viewer && this.settings.magnifier !== false ? <Magnifier viewer={viewer} /> : ""}

                    <Standby
                    message={initializingSplats ? _("Loading splats...") : _("Loading textured model...")}
                    show={initializing}
                    progress={initializingSplats ? this.state.splatsLoadProgress : this.state.texModelLoadProgress}
                    />

                    <div className={"model-action-buttons " + (this.state.modalOpen ? "modal-open" : "") + (panel === "project" || panel === "history" ? " panel-open" : "") + (panel === "settings" ? " hide" : "")}>
                        <UnitSelector />
                        <AssetDownloadButtons 
                                        task={this.props.task} 
                                        direction="up" 
                                        showLabel={false}
                                        buttonClass="btn-secondary"
                                        onModalOpen={() => this.setState({modalOpen: true})}
                                        onModalClose={() => this.setState({modalOpen: false})} />
                        {this.state.pluginActionButtons.map((button, i) => <div key={i}>{button}</div>)}
                        {(this.props.shareButtons && !this.props.public) ? 
                        <ShareButton 
                            ref={(ref) => { this.shareButton = ref; }}
                            task={this.props.task} 
                            popupPlacement="top"
                            linksTarget="3d"
                            queryParams={queryParams}
                        />
                        : ""}
                        <SwitchModeButton 
                            public={this.props.public}
                            task={this.props.task}
                            type="modelToMap" />
                    </div>

                    {selectedCamera ? <div className="thumbnail">
                        <a className="close-thumb" href="javascript:void(0)" onClick={this.closeThumb}><i className="fa fa-window-close"></i></a>
                        <ImagePopup feature={selectedCamera._feat} task={task} />
                    </div> : ""}
            </div>

          </div>
      </div>);
  }
}

$(function(){
    $("[data-modelview]").each(function(){
        let props = $(this).data();
        delete(props.modelview);
        window.ReactDOM.render(<ModelView {...props}/>, $(this).get(0));
    });
});

export default ModelView;
