import React from 'react';
import PropTypes from 'prop-types';
import '../../css/modelview/Toolbar.scss';
import '../../css/modelview/Icons.scss';
import { _, interpolate } from '../../classes/gettext';

class Toolbar extends React.Component{
  static propTypes = {
    viewer: PropTypes.object.isRequired,
    modelType: PropTypes.string.isRequired,
    panel: PropTypes.string,
    onTogglePanel: PropTypes.func.isRequired,
    hasCameras: PropTypes.bool.isRequired,
    camerasVisible: PropTypes.bool.isRequired,
    onToggleCameras: PropTypes.func.isRequired,
    onAttributeChange: PropTypes.func.isRequired,
    onInsert: PropTypes.func.isRequired,
    onReorient: PropTypes.func,
    onEnterVR: PropTypes.func
  }

  constructor(props){
    super(props);

    this.state = {
      open: null
    };
  }

  componentDidMount(){
    document.addEventListener("keydown", this.handleKeyDown);
    this.props.viewer.measuringTool.addEventListener("start_inserting_measurement", this.handleInsertion);
    this.props.viewer.renderer.domElement.addEventListener("mousedown", this.handleMouseDown, true);
  }

  componentWillUnmount(){
    document.removeEventListener("keydown", this.handleKeyDown);
    this.props.viewer.measuringTool.removeEventListener("start_inserting_measurement", this.handleInsertion);
    this.props.viewer.renderer.domElement.removeEventListener("mousedown", this.handleMouseDown, true);
  }

  handleKeyDown = (e) => {
    if (e.key === "Escape") this.cancelInsertion();
  }

  handleInsertion = (e) => {
    this.inserting = e.measure;
  }

  handleMouseDown = () => {
    if (!this.props.viewer.inputHandler.drag && !this.props.viewer.inputHandler.paused) this.inserting = null;
  }

  cancelInsertion = () => {
    const { viewer } = this.props;
    const item = this.inserting;
    this.inserting = null;
    if (viewer.inputHandler.paused){
      viewer.inputHandler.startDragging(viewer.inputHandler.paused);
      viewer.inputHandler.paused = null;
    }
    if (!item || !viewer.inputHandler.drag) return;

    viewer.renderer.domElement.dispatchEvent(new MouseEvent("mouseup", {button: 2, bubbles: true}));

    if (item instanceof Potree.Measure){
      if (item.maxMarkers !== Infinity || item.points.length < (item.closed ? 3 : 2)) viewer.scene.removeMeasurement(item);
    }else if (item instanceof Potree.Profile){
      if (item.points.length < 2){
        viewer.scene.removeProfile(item);
        viewer.profileWindow.hide();
      }
    }else if (item instanceof Potree.Volume){
      viewer.scene.removeVolume(item);
    }else if (item instanceof Potree.PolygonClipVolume){
      viewer.scene.removePolygonClipVolume(item);
    }
  }

  measure = (args, kind) => {
    this.inserting = this.props.viewer.measuringTool.startInsertion(args);
    if (kind) this.inserting.kind = kind;
    this.props.onInsert(this.inserting);
  }

  setAttribute = (name) => {
    this.props.viewer.scene.pointclouds.forEach(pc => {
      pc.material.activeAttributeName = name;
    });
    this.props.onAttributeChange();
  }

  activeAttribute = () => {
    const pc = this.props.viewer.scene.pointclouds[0];
    return pc ? pc.material.activeAttributeName : "";
  }

  render(){
    const { viewer, modelType } = this.props;
    const { open } = this.state;
    const pc = viewer.scene.pointclouds[0];
    const fp = viewer.fpControls;

    const groups = [
      {
        id: "navigation", icon: "mv-icon mv-icon-navigation", title: _("Navigation"),
        items: [
          { icon: "mv-icon mv-icon-orbit", title: _("Orbit"),
            active: viewer.controls === viewer.orbitControls,
            onClick: () => viewer.setControls(viewer.orbitControls) },
          { icon: "mv-icon mv-icon-earth", title: _("Earth"),
            active: viewer.controls === viewer.earthControls,
            onClick: () => viewer.setControls(viewer.earthControls) },
          { icon: "mv-icon mv-icon-fly", title: _("Fly"),
            active: viewer.controls === fp && !fp.lockElevation,
            onClick: () => { viewer.setControls(fp); fp.lockElevation = false; } },
          { icon: "mv-icon mv-icon-walk", title: _("Walk"),
            active: viewer.controls === fp && fp.lockElevation,
            onClick: () => { viewer.setControls(fp); fp.lockElevation = true; } },
          { separator: true },
          { icon: "mv-icon mv-icon-viewpoint", title: _("Viewpoint"),
            onClick: () => viewer.fitToScreen() }
        ].concat(this.props.onReorient ? [
          { icon: "mv-icon mv-icon-reorient", title: _("Reorient"),
            onClick: () => {
              this.inserting = viewer.measuringTool.startInsertion({showDistances: false, showArea: false, closed: true, maxMarkers: 3, name: _("Reorient")});
              this.props.onReorient(this.inserting);
            } }
        ] : [])
      },
      {
        id: "display", icon: "mv-icon mv-icon-display", title: _("Display"),
        items: [
          { icon: "mv-icon mv-icon-rgba", title: _("Colors"),
            active: this.activeAttribute() === "rgba",
            onClick: () => this.setAttribute("rgba") },
          { icon: "mv-icon mv-icon-elevation", title: _("Elevation"),
            active: this.activeAttribute() === "elevation",
            onClick: () => this.setAttribute("elevation") },
          { icon: "mv-icon mv-icon-classification", title: _("Classification"),
            active: this.activeAttribute() === "classification",
            disabled: !pc || !pc.pcoGeometry.pointAttributes.attributes.some(a => a.name === "classification"),
            onClick: () => this.setAttribute("classification") },
          { separator: true },
          { icon: "mv-icon mv-icon-xray", title: _("X-ray"),
            active: !!pc && pc.material.opacity < 1,
            disabled: modelType !== "cloud",
            onClick: () => {
              const xray = pc.material.opacity < 1;
              viewer.scene.pointclouds.forEach(p => { p.material.opacity = xray ? 1 : 0.15; });
              viewer.setEDLEnabled(xray);
            } },
          { icon: "mv-icon mv-icon-camera", title: _("Cameras"),
            active: this.props.camerasVisible,
            disabled: !this.props.hasCameras,
            onClick: this.props.onToggleCameras }
        ]
      },
      {
        id: "measures", icon: "mv-icon mv-icon-ruler", title: _("Measurements"),
        items: [
          { icon: "mv-icon mv-icon-point", title: _("Point"),
            onClick: () => this.measure({showDistances: false, showAngles: false, showCoordinates: true, showArea: false, closed: true, maxMarkers: 1, name: _("Point")}) },
          { icon: "mv-icon mv-icon-distance", title: _("Distance"),
            onClick: () => this.measure({showDistances: true, showArea: false, closed: false, name: _("Distance")}) },
          { icon: "mv-icon mv-icon-height", title: _("Height"),
            onClick: () => this.measure({showDistances: false, showHeight: true, showArea: false, closed: false, maxMarkers: 2, name: _("Height")}) },
          { icon: "mv-icon mv-icon-angle", title: _("Angle"),
            onClick: () => this.measure({showDistances: false, showAngles: true, showArea: false, closed: true, maxMarkers: 3, name: _("Angle")}) },
          { icon: "mv-icon mv-icon-circle", title: _("Circle"),
            onClick: () => this.measure({showDistances: false, showHeight: false, showArea: false, showCircle: true, showEdges: false, closed: false, maxMarkers: 3, name: _("Circle")}) },
          { icon: "mv-icon mv-icon-roof", title: _("Roof Plane"),
            onClick: () => { this.measure({showDistances: false, showArea: false, closed: true, name: _("Roof Plane")}, "roof"); this.inserting.open = true; } },
          { icon: "mv-icon mv-icon-perpendicular", title: _("Perpendicular distance"),
            onClick: () => this.measure({showDistances: false, showArea: false, closed: false, maxMarkers: 2, name: _("Perpendicular distance")}, "perpendicular") },
          { icon: "mv-icon mv-icon-area", title: _("Surface area"),
            onClick: () => this.measure({showDistances: true, showArea: true, closed: true, name: _("Area")}) },
          { icon: "mv-icon mv-icon-azimuth", title: _("Azimuth"),
            onClick: () => this.measure({showDistances: false, showHeight: false, showArea: false, showCircle: false, showEdges: false, showAzimuth: true, closed: false, maxMarkers: 2, name: _("Azimuth")}) },
          { icon: "mv-icon mv-icon-volume", title: _("Volume"),
            onClick: () => { this.inserting = viewer.volumeTool.startInsertion(); this.props.onInsert(this.inserting); } },
          { icon: "mv-icon mv-icon-profile", title: _("Height profile"),
            onClick: () => {
              this.inserting = viewer.profileTool.startInsertion();
              viewer.profileWindow.show();
              viewer.profileWindowController.setProfile(this.inserting);
              this.props.onInsert(this.inserting);
            } }
        ]
      },
      {
        id: "annotation", icon: "mv-icon mv-icon-annotation", title: _("Annotation"),
        onClick: () => { this.inserting = viewer.annotationTool.startInsertion(); this.props.onInsert(this.inserting); }
      },
      {
        id: "camera", icon: "mv-icon mv-icon-video", title: _("Camera"),
        items: [
          { icon: "mv-icon mv-icon-pov", title: _("Point of View"),
            onClick: () => {
              const view = viewer.scene.view;
              const [prefix, suffix] = _("View %(num)s").split("%(num)s");
              const nums = viewer.scene.annotations.descendants()
                .filter(a => a.hasView() && a.title.startsWith(prefix) && a.title.endsWith(suffix))
                .map(a => parseInt(a.title.slice(prefix.length, a.title.length - suffix.length)))
                .filter(n => !isNaN(n));
              this.props.onInsert(viewer.scene.addAnnotation(view.getPivot(), {
                title: interpolate(_("View %(num)s"), {num: Math.max(0, ...nums) + 1}),
                cameraPosition: view.position.clone(),
                cameraTarget: view.getPivot()
              }));
            } },
          { icon: "mv-icon mv-icon-film", title: _("Video animation"),
            onClick: () => {
              const animation = new Potree.CameraAnimation(viewer);
              animation.name = _("Camera Animation");
              animation.setKind(viewer.scene.annotations.descendants().some(a => a.hasView()) ? "views" : "orbit");
              viewer.scene.addCameraAnimation(animation);
              this.props.onInsert(animation);
            } }
        ]
      },
      {
        id: "clipping", icon: "mv-icon mv-icon-clip", title: _("Clipping"),
        items: [
          { icon: "mv-icon mv-icon-clipbox", title: _("Clip box"),
            onClick: () => { this.inserting = viewer.volumeTool.startInsertion({clip: true, name: _("Clip box")}); this.props.onInsert(this.inserting); } },
          { icon: "mv-icon mv-icon-clippolygon", title: _("Clip polygon"),
            onClick: () => {
              this.inserting = viewer.clippingTool.startInsertion({type: "polygon"});
              this.inserting.name = _("Clip polygon");
            } },
          { icon: "mv-icon mv-icon-highlight", title: _("Highlight"),
            active: viewer.clipTask === Potree.ClipTask.HIGHLIGHT,
            onClick: () => viewer.setClipTask(Potree.ClipTask.HIGHLIGHT) },
          { icon: "mv-icon mv-icon-clipin", title: _("Clip In"),
            active: viewer.clipTask === Potree.ClipTask.SHOW_INSIDE,
            onClick: () => viewer.setClipTask(Potree.ClipTask.SHOW_INSIDE) },
          { icon: "mv-icon mv-icon-clipout", title: _("Clip Out"),
            active: viewer.clipTask === Potree.ClipTask.SHOW_OUTSIDE,
            onClick: () => viewer.setClipTask(Potree.ClipTask.SHOW_OUTSIDE) },
          { icon: "mv-icon mv-icon-trash", title: _("Remove all clips"),
            onClick: () => viewer.scene.removeAllClipVolumes() }
        ]
      },
      { separator: true },
      {
        id: "project", icon: "mv-icon mv-icon-project", title: _("Layer List"),
        active: this.props.panel === "project",
        onClick: () => this.props.onTogglePanel("project")
      },
      {
        id: "history", icon: "mv-icon mv-icon-history", title: _("Action history"),
        active: this.props.panel === "history",
        onClick: () => this.props.onTogglePanel("history")
      },
      {
        id: "settings", icon: "mv-icon mv-icon-settings", title: _("Settings"),
        active: this.props.panel === "settings",
        onClick: () => this.props.onTogglePanel("settings")
      }
    ];

    if (this.props.onEnterVR){
      groups.push({
        id: "vr", icon: "mv-icon mv-icon-vr", title: _("VR"),
        onClick: this.props.onEnterVR
      });
    }

    const openGroup = groups.find(g => g.id === open);

    return (<div className="mv-toolbar-container">
      <div className="mv-toolbar">
        {groups.map((g, i) => g.separator ?
          <div key={i} className="mv-toolbar-separator"></div> :
          <button key={g.id} type="button" title={g.title} disabled={!!g.disabled}
                  className={"mv-toolbar-btn " + (open === g.id || g.active ? "active" : "")}
                  onClick={() => {
                    if (g.items){
                      if (open === "measures") this.cancelInsertion();
                      this.setState({open: open === g.id ? null : g.id});
                    }else if (this.inserting && this.started === g.title && (viewer.inputHandler.drag || viewer.inputHandler.paused)) this.cancelInsertion();
                    else{
                      g.onClick();
                      this.started = g.title;
                    }
                  }}>
            <i className={g.icon}></i>
          </button>
        )}
      </div>
      {openGroup ? <div className="mv-toolbar mv-toolbar-sub">
        {openGroup.items.map((item, i) => item.separator ?
          <div key={i} className="mv-toolbar-separator"></div> :
          <button key={i} type="button" title={item.title}
                  disabled={!!item.disabled}
                  className={"mv-toolbar-btn " + (item.active ? "active" : "")}
                  onClick={() => {
                    if (this.inserting && this.started === item.title && (viewer.inputHandler.drag || viewer.inputHandler.paused)) this.cancelInsertion();
                    else{
                      item.onClick();
                      this.started = item.title;
                    }
                    this.forceUpdate();
                  }}>
            <i className={item.icon}></i>
          </button>
        )}
      </div> : ""}
    </div>);
  }
}

export default Toolbar;
