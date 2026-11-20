import React from 'react';
import PropTypes from 'prop-types';
import $ from 'jquery';
import * as THREE from 'THREE';
import '../../css/modelview/Panel.scss';
import { _, interpolate } from '../../classes/gettext';
import { systems } from '../../classes/Units';

class ProjectPanel extends React.Component{
  static propTypes = {
    viewer: PropTypes.object.isRequired,
    task: PropTypes.object.isRequired,
    hasCameras: PropTypes.bool.isRequired,
    camerasVisible: PropTypes.bool.isRequired,
    onToggleCameras: PropTypes.func.isRequired,
    onCameraScaleChange: PropTypes.func.isRequired,
    onAttributeChange: PropTypes.func.isRequired,
    inserted: PropTypes.object,
    focused: PropTypes.object,
    onSetInitialCameraView: PropTypes.func,
    onClose: PropTypes.func.isRequired
  }

  constructor(props){
    super(props);

    this.state = {
      selected: props.inserted || (props.focused ? props.focused.item : null),
      tab: "properties",
      cameraScale: 1,
      search: "",
      closed: {},
      renaming: props.inserted instanceof Potree.Annotation && !props.inserted.hasView() ? null : props.inserted,
      menu: null,
      exportOpen: false,
      recording: false,
      updated: null
    };
  }

  componentDidMount(){
    this.refreshInterval = setInterval(() => this.forceUpdate(), 500);
    document.addEventListener("click", this.closeMenus);
    document.addEventListener("keydown", this.handleKeyDown);
    if (this.props.focused && this.panel.querySelector(".mv-tree-row.selected")) this.panel.querySelector(".mv-tree-row.selected").scrollIntoView({block: "nearest"});
  }

  componentDidUpdate(prevProps){
    if (this.props.focused && this.props.focused !== prevProps.focused){
      this.setState({selected: this.props.focused.item, renaming: null, tab: "properties", closed: {}, search: ""}, () => {
        if (this.panel.querySelector(".mv-tree-row.selected")) this.panel.querySelector(".mv-tree-row.selected").scrollIntoView({block: "nearest"});
      });
    }
    if (this.props.inserted && this.props.inserted !== prevProps.inserted){
      this.setState({selected: this.props.inserted, renaming: this.props.inserted instanceof Potree.Annotation && !this.props.inserted.hasView() ? null : this.props.inserted, tab: "properties", closed: {}});
    }
  }

  componentWillUnmount(){
    clearInterval(this.refreshInterval);
    clearTimeout(this.deselectTimeout);
    this.props.viewer.selectedItem = null;
    document.removeEventListener("click", this.closeMenus);
    document.removeEventListener("keydown", this.handleKeyDown);
    this.stopRecording();
  }

  closeMenus = (e) => {
    if (e.target.closest && e.target.closest(".mv-menu-toggle")) return;
    if (this.state.menu || this.state.exportOpen) this.setState({menu: null, exportOpen: false});
  }

  fmt = (n) => {
    return Potree.Utils.addCommas(n.toFixed(3));
  }

  copy = (text, key) => {
    const done = () => {
      this.setState({updated: key});
      setTimeout(() => { if (this.state.updated === key) this.setState({updated: null}); }, 2000);
    };
    if (navigator.clipboard !== undefined){
      navigator.clipboard.writeText(text).then(done, () => {});
    }else{
      const el = document.createElement("textarea");
      el.value = text;
      el.style.position = "fixed";
      el.style.opacity = "0";
      document.body.appendChild(el);
      el.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(el);
      if (ok) done();
    }
  }

  remove = (item) => {
    const { scene } = this.props.viewer;
    if (item.type === "measure") scene.removeMeasurement(item.obj);
    else if (item.type === "volume") scene.removeVolume(item.obj);
    else if (item.type === "profile") scene.removeProfile(item.obj);
    else if (item.type === "animation") scene.removeCameraAnimation(item.obj);
    else if (item.type === "polyclip") scene.removePolygonClipVolume(item.obj);
    else scene.removeAnnotation(item.obj);
    if (this.state.selected === item.obj) this.setState({selected: null});
  }

  zoomTo = (item) => {
    const { viewer } = this.props;

    if (item.type === "polyclip") return;

    if (item.type === "annotation" && item.obj.hasView()){
      item.obj.moveHere(viewer.scene.getActiveCamera());
      return;
    }

    let box;
    if (item.type === "measure") box = new THREE.Box3().setFromPoints(item.obj.points.map(p => p.position));
    else if (item.type === "profile") box = new THREE.Box3().setFromPoints(item.obj.points);
    else if (item.type === "animation") box = new THREE.Box3().setFromPoints(item.obj.positions);
    else if (item.type === "annotation") box = new THREE.Box3().setFromPoints([item.obj.position]);
    else box = item.obj.boundingBox.clone().applyMatrix4(item.obj.matrixWorld);

    if (box.isEmpty()) return;
    if (box.getSize(new THREE.Vector3()).length() === 0) box.expandByScalar(5);

    const node = new THREE.Object3D();
    node.boundingBox = box;
    viewer.zoomTo(node, 2, 500);
  }

  setVisible = (item, visible) => {
    if (item.type === "animation") item.obj.setVisible(visible);
    else item.obj.visible = visible;
  }

  stopRecording = () => {
    clearTimeout(this.recordTimeout);
    if (this.recorder && this.recorder.state === "recording") this.recorder.stop();
    else if (this.recorded && this.props.viewer.recording){
      this.props.viewer.recording = false;
      this.recorded.setVisible(true);
      this.setState({recording: false});
    }
  }

  handleKeyDown = (e) => {
    if (e.key === "Escape" && this.state.recording) this.stopRecording();
  }

  seek = (animation, t, show) => {
    const view = this.props.viewer.scene.view;
    const before = animation.at(animation.t);
    const follow = before && view.position.distanceTo(before.position) < 0.01;
    animation.stop();
    animation.set(t);
    const frame = animation.at(t);
    if (follow && frame){
      view.position.copy(frame.position);
      view.lookAt(frame.target);
    }else if (show) animation.setVisible(true);
    this.forceUpdate();
  }

  download = (filename, text) => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([text], {type: "application/octet-stream"}));
    link.download = filename;
    link.click();
  }

  folder = (id, label, items, canDelete) => {
    const open = !this.state.closed[id];
    const anyVisible = items.some(item => item.obj.visible);

    return (<div key={id} className="mv-tree-row mv-tree-folder"
                 onClick={() => this.setState({closed: Object.assign({}, this.state.closed, {[id]: open})})}>
      <i className={"fa fa-fw " + (open ? "fa-caret-down" : "fa-caret-right")}></i>
      <i className="far fa-folder fa-fw"></i>
      <span className="mv-tree-label">{label}</span>
      {canDelete && items.length > 0 ? [
      <button key="delete" type="button" className="mv-panel-btn mv-danger" title={_("Delete all")}
              onClick={e => {
                e.stopPropagation();
                if (window.confirm(_("Delete all items in this folder?"))){
                  items.forEach(this.remove);
                }
              }}><i className="fa fa-trash"></i></button>,
      <button key="eye" type="button" className="mv-panel-btn" title={anyVisible ? _("Hide") : _("Show")}
              onClick={e => {
                e.stopPropagation();
                items.forEach(item => this.setVisible(item, !anyVisible));
                this.forceUpdate();
              }}><i className={anyVisible ? "far fa-eye" : "far fa-eye-slash"}></i></button>
      ] : ""}
    </div>);
  }

  itemRow = (item) => {
    const { selected, renaming } = this.state;

    return (<div key={item.obj.uuid}
         className={"mv-tree-row mv-tree-child " + (selected === item.obj ? "selected" : "")}
         onClick={e => {
           if (e.detail > 1) return;
           const row = e.currentTarget;
           const toggle = () => this.setState({selected: this.state.selected === item.obj ? null : item.obj, tab: "properties"}, () => row.scrollIntoView({block: "nearest"}));
           clearTimeout(this.deselectTimeout);
           if (selected === item.obj || e.target.closest(".mv-tree-text")) this.deselectTimeout = setTimeout(toggle, 250);
           else toggle();
         }}
         onDoubleClick={e => {
           if (e.target.closest("button")) return;
           clearTimeout(this.deselectTimeout);
           this.setState({selected: item.obj});
           this.zoomTo(item);
         }}
         onContextMenu={e => {
           e.preventDefault();
           e.stopPropagation();
           const rect = e.currentTarget.parentElement.parentElement.getBoundingClientRect();
           this.setState({menu: {item, x: e.clientX - rect.left, y: e.clientY - rect.top}});
         }}>
      <i className={item.icon}></i>
      {renaming === item.obj ?
      <input type="text" className="mv-tree-rename" autoFocus defaultValue={item.obj[item.nameKey]}
             onClick={e => e.stopPropagation()}
             onDoubleClick={e => e.stopPropagation()}
             onFocus={e => e.target.select()}
             onBlur={e => { item.obj[item.nameKey] = e.target.value || item.obj[item.nameKey]; this.setState({renaming: null}); }}
             onKeyDown={e => { if (e.key === "Enter" || e.key === "Escape") e.target.blur(); }} />
      : <span className="mv-tree-label"><span className="mv-tree-text" onDoubleClick={e => { e.stopPropagation(); clearTimeout(this.deselectTimeout); this.setState({renaming: item.obj}); }}>{item.obj[item.nameKey] || _("Annotation")}</span></span>}
      <button type="button" className="mv-panel-btn mv-danger" title={_("Delete")}
              onClick={e => { e.stopPropagation(); if (e.detail <= 1) this.remove(item); }}><i className="fa fa-trash"></i></button>
      <button type="button" className="mv-panel-btn" title={item.obj.visible ? _("Hide") : _("Show")}
              onClick={e => { e.stopPropagation(); this.setVisible(item, !item.obj.visible); this.forceUpdate(); }}>
        <i className={item.obj.visible ? "far fa-eye" : "far fa-eye-slash"}></i>
      </button>
    </div>);
  }

  render(){
    const { viewer } = this.props;
    const { selected, tab, cameraScale, search, closed, menu, exportOpen, recording, updated, timeEdit } = this.state;
    const scene = viewer.scene;
    viewer.selectedItem = selected;
    const name = this.props.task.name || "";
    const exportName = ((name.replace(/[ /]/g, "-").replace(/[^0-9a-zA-Z-_]+/g, "") + (name ? "-" : "")) + "measurements").replace(/-[-]+/g, "-");
    const pc = scene.pointclouds[0];

    let measures = scene.measurements.map(obj => {
      let icon = "mv-icon mv-icon-distance";
      if (obj.kind === "perpendicular") icon = "mv-icon mv-icon-perpendicular";
      else if (obj.kind === "roof") icon = "mv-icon mv-icon-roof";
      else if (obj.showAngles) icon = "mv-icon mv-icon-angle";
      else if (obj.showCoordinates) icon = "mv-icon mv-icon-point";
      else if (obj.showCircle) icon = "mv-icon mv-icon-circle";
      else if (obj.showAzimuth) icon = "mv-icon mv-icon-azimuth";
      else if (obj.showHeight) icon = "mv-icon mv-icon-height";
      else if (obj.showArea) icon = "mv-icon mv-icon-area";
      return {obj, type: "measure", icon, nameKey: "name"};
    }).concat(
      scene.volumes.filter(obj => !obj.clip).map(obj => ({obj, type: "volume", icon: "mv-icon mv-icon-volume", nameKey: "name"})),
      scene.profiles.map(obj => ({obj, type: "profile", icon: "mv-icon mv-icon-profile", nameKey: "name"}))
    );
    let clips = scene.volumes.filter(obj => obj.clip).map(obj => ({obj, type: "volume", icon: "mv-icon mv-icon-clipbox", nameKey: "name"})).concat(
      scene.polygonClipVolumes.map(obj => ({obj, type: "polyclip", icon: "mv-icon mv-icon-clippolygon", nameKey: "name"}))
    );
    let annotations = scene.annotations.descendants().filter(obj => !obj.hasView()).map(obj => ({obj, type: "annotation", icon: "mv-icon mv-icon-annotation", nameKey: "title"}));
    let animations = scene.annotations.descendants().filter(obj => obj.hasView()).map(obj => ({obj, type: "annotation", icon: "mv-icon mv-icon-pov", nameKey: "title"})).concat(
      scene.cameraAnimations.map(obj => ({obj, type: "animation", icon: "mv-icon mv-icon-film", nameKey: "name"}))
    );

    if (search){
      const matches = item => String(item.obj[item.nameKey]).toLowerCase().indexOf(search.toLowerCase()) !== -1;
      measures = measures.filter(matches);
      annotations = annotations.filter(matches);
      animations = animations.filter(matches);
      clips = clips.filter(matches);
    }

    const selectedItem = measures.concat(annotations, animations, clips).find(item => item.obj === selected);

    const conv = viewer.lengthUnitDisplay.unitspermeter / viewer.lengthUnit.unitspermeter;
    const unit = viewer.lengthUnitDisplay.code;
    const properties = [];
    let points = [];

    if (selectedItem && selectedItem.type === "measure"){
      const m = selectedItem.obj;
      points = m.points.map(p => p.position);

      if (m.kind === "perpendicular" && points.length === 2) properties.push([_("Distance"), `${this.fmt(m.getPerpendicularDistance() * conv)} ${unit}`]);
      if (m.showDistances && points.length > 1) properties.push([_("Total distance"), `${this.fmt(m.getTotalDistance() * conv)} ${unit}`]);
      if (m.showArea && points.length > 2) properties.push([_("Area"), `${this.fmt(m.getArea() * conv * conv)} ${unit}²` + (m.kind === "roof" && unit.indexOf("ft") === 0 ? ` (${(m.getArea() * conv * conv / 100).toFixed(2)} sq)` : "")]);
      if (m.kind === "roof" && m.roof && m.showArea) properties.push([_("Pitch"), `${systems.imperial.pitch(m.roof.pitch)} · ${systems.metric.pitch(m.roof.pitch)}`]);
      if (m.showHeight && points.length > 1){
        const zs = points.map(p => p.z);
        properties.push([_("Height"), `${this.fmt((Math.max(...zs) - Math.min(...zs)) * conv)} ${unit}`]);
        properties.push([_("Distance"), `${this.fmt(points[0].distanceTo(points[1]) * conv)} ${unit}`]);
        properties.push([_("Delta X"), `${this.fmt((points[1].x - points[0].x) * conv)} ${unit}`]);
        properties.push([_("Delta Y"), `${this.fmt((points[1].y - points[0].y) * conv)} ${unit}`]);
      }
      if (m.showAngles && points.length > 2){
        points.forEach((p, i) => properties.push([[_("Alpha (α)"), _("Beta (β)"), _("Gamma (γ)")][i] || interpolate(_("Angle %(num)s"), {num: i + 1}), `${this.fmt(m.getAngle(i) * (180.0 / Math.PI))}°`]));
      }
      if (m.showCircle && points.length === 3){
        const center = Potree.Utils.computeCircleCenter(points[0], points[1], points[2]);
        const radius = center.distanceTo(points[0]);
        properties.push([_("Center"), `${this.fmt(center.x)}, ${this.fmt(center.y)}, ${this.fmt(center.z * conv)}`]);
        properties.push([_("Radius"), `${this.fmt(radius * conv)} ${unit}`]);
        properties.push([_("Circumference"), `${this.fmt(2 * Math.PI * radius * conv)} ${unit}`]);
      }
      if (m.showAzimuth && points.length === 2){
        const azimuth = (Math.atan2(points[1].x - points[0].x, points[1].y - points[0].y) * (180.0 / Math.PI) + 360) % 360;
        properties.push([_("Azimuth"), `${this.fmt(azimuth)}°`]);
      }
    }else if (selectedItem && selectedItem.type === "volume"){
      properties.push([_("Volume"), `${this.fmt(selectedItem.obj.getVolume() * conv * conv * conv)} ${unit}³`]);
    }else if (selectedItem && selectedItem.type === "profile"){
      points = selectedItem.obj.points;
    }else if (selectedItem && selectedItem.type === "animation"){
      points = selectedItem.obj.positions;
    }else if (selectedItem && selectedItem.type === "annotation"){
      points = [selectedItem.obj.position];
    }

    const isPoint = !!selectedItem && selectedItem.type === "measure" && selectedItem.obj.showCoordinates;
    const m = selectedItem ? selectedItem.obj : null;
    const rebalance = selectedItem && selectedItem.type === "animation" ?
      <button type="button" className="mv-panel-rebalance" disabled={!(m.total > 0) || Math.abs(m.total - m.duration) < 0.05}
              title={interpolate(_("Times add up to %(total)s s. Scale them to fit %(duration)s s."), {total: m.total.toFixed(1), duration: m.duration.toFixed(1)})}
              onClick={() => {
                const scale = m.duration / m.total;
                m.views.filter(o => o.enabled).forEach((o, j) => { if (m.segments[j]) o.time = m.segments[j].time * scale; });
                m.update();
                this.forceUpdate();
              }}>{_("Rebalance")}</button> : null;
    const { task } = this.props;
    const srsName = task.epsg ? (task.srs.name ? `${task.srs.name} (EPSG:${task.epsg})` : `EPSG:${task.epsg}`) : task.srs.name;
    let coordinates = [];
    if (isPoint && points.length === 1){
      const located = m.latlon && m.latlon.x === points[0].x && m.latlon.y === points[0].y;
      if (m.display !== "latlon") coordinates = [points[0].x.toFixed(3), points[0].y.toFixed(3), (points[0].z * conv).toFixed(3)];
      else coordinates = [located ? m.latlon.lon.toFixed(9) : "", located ? m.latlon.lat.toFixed(9) : "", (points[0].z * conv).toFixed(3)];
    }
    const canEditPoints = !!selectedItem && (selectedItem.type === "profile" ||
      (selectedItem.type === "measure" && !m.showCoordinates && !m.showAngles && !m.showCircle && !m.showAzimuth && !m.showHeight && m.kind !== "perpendicular"));
    const minPoints = selectedItem && selectedItem.type === "measure" && m.closed ? 3 : 2;

    let pointCloudProperties = "";
    if (selected === "pointcloud" && pc){
      const material = pc.material;
      const attributes = pc.pcoGeometry.pointAttributes.attributes.map(a => a.name)
                           .filter(name => ["rgba", "intensity", "classification", "returnNumber", "number of returns"].indexOf(name) !== -1)
                           .concat(["elevation"]);
      const box = pc.pcoGeometry.tightBoundingBox || pc.boundingBox;
      const zMin = box.min.z + pc.position.z;
      const zMax = box.max.z + pc.position.z;
      const elevation = material.elevationRange;
      const intensity = material.intensityRange;

      pointCloudProperties = (<div className="mv-panel-properties">
        <div className="mv-panel-tabs">
          <div className="mv-panel-tab active">{_("Properties")}</div>
        </div>
        <div className="mv-panel-field">
          <label>{_("Attribute")}</label>
          <select value={material.activeAttributeName}
                  onChange={e => { material.activeAttributeName = e.target.value; this.props.onAttributeChange(); }}>
            {attributes.map(name => <option key={name} value={name}>{name === "rgba" ? _("Colors") : name.charAt(0).toUpperCase() + name.slice(1)}</option>)}
          </select>
        </div>

        {material.activeAttributeName === "elevation" ? [
        <div key="gradient" className="mv-panel-field">
          <label>{_("Gradient")}</label>
          <select value={Object.keys(Potree.Gradients).find(k => Potree.Gradients[k] === material.gradient) || ""}
                  onChange={e => { material.gradient = Potree.Gradients[e.target.value]; this.forceUpdate(); }}>
            {Object.keys(Potree.Gradients).map(name => <option key={name} value={name}>{name.charAt(0) + name.slice(1).toLowerCase().replace(/_/g, " ")}</option>)}
          </select>
        </div>,
        <div key="range" className="mv-panel-field">
          <label>{`${this.fmt(elevation[0] * conv)} ${unit || ""}`.trim()}</label>
          <label style={{marginLeft: "auto"}}>{`${this.fmt(elevation[1] * conv)} ${unit || ""}`.trim()}</label>
          <div className="mv-panel-dual">
            <div className="mv-panel-dual-fill" style={{
              left: `calc(8px + ${(elevation[0] - zMin) / (zMax - zMin)} * (100% - 16px))`,
              width: `calc(${(elevation[1] - elevation[0]) / (zMax - zMin)} * (100% - 16px))`}}></div>
            <input type="range" min={zMin} max={zMax} step={(zMax - zMin) / 200} value={elevation[0]}
                   style={{zIndex: elevation[0] > (zMin + zMax) / 2 ? 2 : 1}}
                   onChange={e => { material.elevationRange = [parseFloat(e.target.value), Math.max(parseFloat(e.target.value), elevation[1])]; this.forceUpdate(); }} />
            <input type="range" min={zMin} max={zMax} step={(zMax - zMin) / 200} value={elevation[1]}
                   style={{zIndex: 1}}
                   onChange={e => { material.elevationRange = [Math.min(parseFloat(e.target.value), elevation[0]), parseFloat(e.target.value)]; this.forceUpdate(); }} />
          </div>
        </div>] : ""}

        {material.activeAttributeName === "intensity" ? [
        <div key="imin" className="mv-panel-field">
          <label>{_("Min")}</label>
          <input type="number" min="0" max="65535" value={intensity[0]}
                 onChange={e => { material.intensityRange = [parseFloat(e.target.value) || 0, intensity[1]]; this.forceUpdate(); }} />
        </div>,
        <div key="imax" className="mv-panel-field">
          <label>{_("Max")}</label>
          <input type="number" min="0" max="65535" value={intensity[1]}
                 onChange={e => { material.intensityRange = [intensity[0], parseFloat(e.target.value) || 0]; this.forceUpdate(); }} />
        </div>] : ""}

        {material.activeAttributeName === "classification" ?
        <div className="mv-panel-classes">
          {Object.keys(viewer.classifications).filter(code => code !== "DEFAULT").map(code => {
            const c = viewer.classifications[code];
            return (<label key={code}>
              <input type="checkbox" checked={c.visible}
                     onChange={e => { viewer.setClassificationVisibility(code, e.target.checked); this.forceUpdate(); }} />
              <span className="mv-class-color" style={{background: `rgb(${c.color.slice(0, 3).map(v => Math.round(v * 255)).join(",")})`}}></span>
              {_(c.name)}
            </label>);
          })}
        </div> : ""}
      </div>);
    }

    return (<div className="mv-panel" ref={domNode => { this.panel = domNode; }}>
      <div className="mv-panel-toolbar">
        <div className="mv-panel-search">
          <i className="fa fa-search"></i>
          <input type="text" placeholder={_("Search")} value={search} onChange={e => this.setState({search: e.target.value})} />
        </div>
        <button type="button" className={"mv-panel-btn mv-menu-toggle " + (exportOpen ? "active" : "")} title={_("Export")}
                onClick={e => { e.stopPropagation(); this.setState({exportOpen: !exportOpen, menu: null}); }}><i className="mv-icon mv-icon-export"></i></button>
        <button type="button" className="mv-panel-btn" title={_("Close")} onClick={this.props.onClose}><i className="mv-icon mv-icon-close"></i></button>
      </div>

      <div className="mv-panel-body">
        {this.props.hasCameras ?
        <div className={"mv-tree-row mv-tree-root " + (selected === "cameras" ? "selected" : "")}
             onClick={e => { if (e.detail <= 1) this.setState({selected: selected === "cameras" ? null : "cameras"}); }}
             onDoubleClick={e => { if (!e.target.closest("button")) this.props.onToggleCameras(); }}>
          <i className="fa fa-camera fa-fw"></i>
          <span className="mv-tree-label">{_("Cameras")}</span>
          <button type="button" className="mv-panel-btn"
                  title={this.props.camerasVisible ? _("Hide") : _("Show")}
                  onClick={e => { e.stopPropagation(); this.props.onToggleCameras(); }}>
            <i className={this.props.camerasVisible ? "far fa-eye" : "far fa-eye-slash"}></i>
          </button>
        </div> : ""}
        <div className={"mv-tree-row mv-tree-root " + (selected === "pointcloud" ? "selected" : "")}
             onClick={e => { if (e.detail <= 1) this.setState({selected: selected === "pointcloud" ? null : "pointcloud"}); }}>
          <i className="fa fa-pointcloud"></i>
          <span className="mv-tree-label">{_("Point Cloud")}</span>
        </div>

        {this.folder("measures", _("Measurements"), measures, true)}
        {!closed.measures ? measures.map(this.itemRow) : ""}

        {this.folder("annotations", _("Annotations"), annotations, true)}
        {!closed.annotations ? annotations.map(this.itemRow) : ""}

        {this.folder("animations", _("Animations"), animations, true)}
        {!closed.animations ? animations.map(this.itemRow) : ""}

        {this.folder("clips", _("Clips"), clips, true)}
        {!closed.clips ? clips.map(this.itemRow) : ""}
      </div>

      {selected === "cameras" ?
      <div className="mv-panel-properties">
        <div className="mv-panel-tabs">
          <div className="mv-panel-tab active">{_("Properties")}</div>
        </div>
        <div className="mv-panel-field">
          <label>{_("Size")}</label>
          <input type="range" min="0.1" max="4" step="0.1" value={cameraScale}
                 onChange={e => {
                   const value = parseFloat(e.target.value);
                   this.setState({cameraScale: value});
                   this.props.onCameraScaleChange(value);
                 }} />
        </div>
      </div> : ""}

      {pointCloudProperties}

      {selectedItem ?
      <div className="mv-panel-properties">
        <div className="mv-panel-tabs">
          <div className={"mv-panel-tab " + (tab === "properties" ? "active" : "")} onClick={() => this.setState({tab: "properties"})}>{_("Properties")}</div>
          {selectedItem.type !== "volume" && selectedItem.type !== "polyclip" && m.kind !== "perpendicular" ?
          <div className={"mv-panel-tab " + (tab === "points" ? "active" : "")} onClick={() => this.setState({tab: "points"})}>{isPoint ? _("Point attributes") : _("Points")}</div>
          : ""}
        </div>

        {tab === "properties" ? <div>
          {properties.map((p, i) => <div key={i} className="mv-panel-property">
            <span>{p[0]}</span><span>{p[1]}</span>
          </div>)}

          {isPoint && points.length === 1 ? [
          <div key="coordinates" className="mv-panel-field mv-panel-xyz">
            <label>{_("Coordinates")}</label>
            {coordinates.map((value, i) =>
            <input key={i + value} type="number" step="any" title={(m.display === "latlon" ? ["lon", "lat", "alt"] : ["x", "y", "z"])[i]}
                   defaultValue={value} readOnly={m.display === "latlon" && i < 2}
                   style={{flex: `${value.length || 1} 1 0`, minWidth: 0, padding: m.display === "latlon" ? "0 2px" : "0 4px"}}
                   onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
                   onBlur={e => {
                     const number = parseFloat(e.target.value);
                     if (isNaN(number) || (m.display === "latlon" && i < 2)) return;
                     const position = points[0].clone();
                     position[["x", "y", "z"][i]] = i === 2 ? number / conv : number;
                     m.setPosition(0, position);
                     this.forceUpdate();
                   }} />)}
            <button type="button" className="mv-panel-btn" title={_("Copy")}
                    onClick={() => this.copy(coordinates.join(", "), "copy")}><i className={updated === "copy" ? "fa fa-check" : "far fa-copy"}></i></button>
          </div>,
          task.epsg || task.wkt ?
          <div key="display" className="mv-panel-field">
            <label>{_("Display")}</label>
            <select value={m.display === "latlon" ? "latlon" : "native"}
                    onChange={e => { m.display = e.target.value; m.update(); this.forceUpdate(); }}>
              <option value="native">{srsName}</option>
              <option value="latlon">{_("Lat/Lon")} (EPSG:4326)</option>
            </select>
          </div> : null] : ""}

          {selectedItem.type === "volume" ? ["position", "rotation", "scale"].map(prop =>
          <div key={prop} className="mv-panel-field mv-panel-xyz">
            <label>{{position: _("Position"), rotation: _("Rotation"), scale: _("Scale")}[prop]}</label>
            {["x", "y", "z"].map(axis => {
              let factor = 1;
              if (prop === "rotation") factor = 180.0 / Math.PI;
              else if (prop === "scale" || axis === "z") factor = conv;

              return (<input key={axis + m[prop][axis]} type="number" step="any" title={axis}
                   defaultValue={(m[prop][axis] * factor).toFixed(3)}
                   onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
                   onBlur={e => {
                     const value = parseFloat(e.target.value);
                     if (isNaN(value) || (prop === "scale" && value <= 0)) return;
                     m[prop][axis] = value / factor;
                     this.forceUpdate();
                   }} />);
            })}
          </div>) : ""}

          {selectedItem.type === "profile" ? [
          <div key="width" className="mv-panel-field">
            <label>{interpolate(_("Width (%(unit)s)"), {unit: viewer.lengthUnit.code})}</label>
            <input type="number" min="0" step="0.1" value={selectedItem.obj.width}
                   onChange={e => { selectedItem.obj.setWidth(parseFloat(e.target.value) || 0); this.forceUpdate(); }} />
          </div>,
          <div key="show" className="mv-panel-field">
            <button type="button" className="mv-panel-action"
                    onClick={() => {
                      viewer.profileWindow.show();
                      viewer.profileWindowController.setProfile(selectedItem.obj);
                    }}><i className="mv-icon mv-icon-profile"></i> {_("Height Profile")}</button>
          </div>] : ""}

          {selectedItem.type === "animation" ? [
          <div key="kind" className="mv-panel-field">
            <label>{_("Type")}</label>
            <select value={m.kind} onChange={e => { m.stop(); m.setKind(e.target.value); m.update(); this.forceUpdate(); }}>
              <option value="views" disabled={!scene.annotations.descendants().some(a => a.hasView())}>{_("Views")}</option>
              <option value="orbit">{_("Orbit")}</option>
            </select>
          </div>,
          m.kind === "views" ?
          <div key="interpolation" className="mv-panel-field">
            <label>{_("Interpolation")}</label>
            <select value={m.curveType} onChange={e => { m.curveType = e.target.value; m.update(); this.forceUpdate(); }}>
              <option value="centripetal">{_("Centripetal")}</option>
              <option value="chordal">{_("Chordal")}</option>
            </select>
          </div> : null,
          m.kind === "views" ?
          <div key="views" className="mv-panel-keys">
            {m.views.map((v, i) => {
              const view = scene.annotations.descendants().find(a => a.uuid === v.uuid);
              if (!view) return null;
              const segment = v.enabled ? m.segments[m.views.slice(0, i).filter(o => o.enabled).length] : null;
              return (<div key={v.uuid} className="mv-panel-key" draggable
                           onDragStart={e => { this.draggedView = i; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", ""); }}
                           onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}
                           onDrop={e => {
                             e.preventDefault();
                             m.views.splice(i, 0, m.views.splice(this.draggedView, 1)[0]);
                             m.update();
                             this.forceUpdate();
                           }}>
                <i className="fa fa-grip-vertical"></i>
                <label>
                  <input type="checkbox" checked={v.enabled} tabIndex="-1"
                         onChange={e => { v.enabled = e.target.checked; m.update(); this.forceUpdate(); }} />
                  {view.title}
                </label>
                {v.enabled && !segment && m.segments.length > 0 ? rebalance : ""}
                {segment ?
                <input type="number" min="0.1" step="0.1" title={_("Seconds to the next view")}
                       draggable onDragStart={e => { e.preventDefault(); e.stopPropagation(); }}
                       value={timeEdit && timeEdit.key === v.uuid ? timeEdit.value : +segment.time.toFixed(1)}
                       onChange={e => this.setState({timeEdit: {key: v.uuid, value: e.target.value}})}
                       onDoubleClick={() => this.setState({timeEdit: {key: v.uuid, value: ""}})}
                       onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
                       onBlur={e => {
                         const seconds = parseFloat(e.target.value);
                         if (timeEdit && timeEdit.key === v.uuid && seconds > 0){
                           m.views.filter(o => o.enabled).forEach((o, j) => { if (m.segments[j]) o.time = m.segments[j].time; });
                           v.time = seconds;
                           m.update();
                         }
                         this.setState({timeEdit: null});
                       }} /> : ""}
              </div>);
            })}
            {m.loop && m.segments.length > 0 ? <div className="mv-panel-key"><label></label>{rebalance}</div> : ""}
          </div> : null,
          m.kind === "orbit" && m.orbit ?
          <div key="lookat" className="mv-panel-field">
            <button type="button" className="mv-panel-action"
                    onClick={() => viewer.annotationTool.startLookAt({cameraTarget: m.orbit.target, cameraPosition: (m.at(m.t) || {position: m.orbit.center}).position.clone(), position: new THREE.Vector3(), marker: {parent: scene.scene}})}><i className="fa fa-crosshairs"></i> {_("Look At")}</button>
          </div> : null,
          <div key="loop" className="mv-panel-field">
            <label><input type="checkbox" checked={m.loop}
                          onChange={e => { m.stop(); m.loop = e.target.checked; m.update(); this.forceUpdate(); }} /> {_("Loop")}</label>
            {m.kind === "orbit" && m.orbit ?
            <label><input type="checkbox" checked={m.orbit.reverse}
                          onChange={e => { m.stop(); m.orbit.reverse = e.target.checked; m.update(); this.forceUpdate(); }} /> {_("Reverse")}</label> : ""}
          </div>,
          <div key="duration" className="mv-panel-field">
            <label>{_("Duration (s)")}</label>
            <input type="number" min="0.1" step="0.5" value={timeEdit && timeEdit.key === "duration" ? timeEdit.value : +selectedItem.obj.duration.toFixed(1)}
                   onChange={e => this.setState({timeEdit: {key: "duration", value: e.target.value}})}
                   onDoubleClick={() => this.setState({timeEdit: {key: "duration", value: ""}})}
                   onKeyDown={e => { if (e.key === "Enter") e.target.blur(); }}
                   onBlur={e => {
                     const seconds = parseFloat(e.target.value);
                     if (timeEdit && timeEdit.key === "duration" && seconds > 0) selectedItem.obj.setDuration(seconds);
                     this.setState({timeEdit: null});
                   }} />
          </div>,
          m.kind === "orbit" && m.orbit ?
          <div key="length" className="mv-panel-field">
            <label>{_("Length")}</label>
            <input type="range" min="0.05" max="1" step="0.01" value={m.orbit.length}
                   onChange={e => { m.orbit.length = parseFloat(e.target.value); m.update(); this.forceUpdate(); }} />
          </div> : null,
          <div key="time" className="mv-panel-field">
            <label>{_("Playback")}</label>
            <input type="range" min="0" max="1" step="0.001" value={selectedItem.obj.t}
                   onChange={e => this.seek(m, parseFloat(e.target.value), true)} />
          </div>,
          <div key="resolution" className="mv-panel-field">
            <label>{_("Quality")}</label>
            <select value={this.state.recordSize || "native"} disabled={recording} onChange={e => this.setState({recordSize: e.target.value})}>
              <option value="native">{_("Native")}</option>
              <option value="4k">4K</option>
            </select>
          </div>,
          <div key="controls" className="mv-panel-controls">
            <button type="button" className="mv-panel-btn" title={m.onPlay ? _("Pause") : _("Play")} disabled={recording || !m.cameraCurve}
                    onClick={() => {
                      if (m.onPlay) m.stop();
                      else m.play();
                      this.forceUpdate();
                    }}><i className={m.onPlay ? "fa fa-pause" : "fa fa-play"}></i></button>
            <button type="button" className="mv-panel-btn" title={_("Rewind")} disabled={recording}
                    onClick={() => this.seek(m, 0, false)}><i className="fa fa-redo"></i></button>
            <button type="button" className="mv-panel-btn mv-danger" title={recording ? _("Stop recording") : _("Record movie")} disabled={!m.cameraCurve}
                    onClick={() => {
                      if (recording){
                        this.stopRecording();
                        return;
                      }

                      const animation = selectedItem.obj;
                      this.recorded = animation;
                      this.setState({recording: true});
                      animation.stop();
                      animation.setVisible(false);
                      viewer.recording = true;

                      this.recordTimeout = setTimeout(() => {
                        const chunks = [];
                        const mimeType = ["video/mp4;codecs=avc1.42E01E", "video/mp4;codecs=avc1", "video/mp4;codecs=h264", "video/mp4", "video/webm; codecs=vp8"].find(type => MediaRecorder.isTypeSupported(type));
                        let stream = null;
                        let draw = null;
                        if (this.state.recordSize === "4k"){
                          const canvas = document.createElement("canvas");
                          canvas.width = 3840;
                          canvas.height = 2160;
                          const context = canvas.getContext("2d", {alpha: false});
                          draw = () => {
                            const source = viewer.renderer.domElement;
                            const scale = Math.min(canvas.width / source.width, canvas.height / source.height);
                            context.fillStyle = "#000";
                            context.fillRect(0, 0, canvas.width, canvas.height);
                            context.drawImage(source, (canvas.width - source.width * scale) / 2, (canvas.height - source.height * scale) / 2, source.width * scale, source.height * scale);
                          };
                          viewer.addEventListener("render.pass.perspective_overlay", draw);
                          stream = canvas.captureStream(30);
                        }else stream = viewer.renderer.domElement.captureStream(29.97);
                        const recorder = new MediaRecorder(stream, {
                          mimeType,
                          videoBitsPerSecond: draw ? 35000000 : Math.round(Math.min(50000000, Math.max(8000000, 70000000 * viewer.renderer.domElement.width * viewer.renderer.domElement.height / (3840 * 2160))))
                        });
                        this.recorder = recorder;
                        recorder.ondataavailable = e => chunks.push(e.data);
                        recorder.onstop = () => {
                          if (draw) viewer.removeEventListener("render.pass.perspective_overlay", draw);
                          const video = new Blob(chunks, {type: mimeType});
                          if (video.size > 0){
                            const link = document.createElement("a");
                            link.href = URL.createObjectURL(video);
                            link.download = mimeType.indexOf("mp4") !== -1 ? "recording.mp4" : "recording.webm";
                            link.click();
                          }
                          this.recorder = null;
                          viewer.recording = false;
                          animation.stop();
                          animation.setVisible(true);
                          this.setState({recording: false});
                        };
                        recorder.start();
                        this.recordTimeout = setTimeout(this.stopRecording, (animation.t >= 1 ? 1 : 1 - animation.t) * animation.duration * 1000 + 1000);
                        animation.play(true);
                      }, 1000);
                    }}><i className={recording ? "fa fa-circle-notch fa-spin" : "fa fa-circle"}></i></button>
          </div>] : ""}

          {selectedItem.type === "annotation" ? [
          m.hasView() ? null :
          <div key="title" className="mv-panel-field">
            <label>{_("Title")}</label>
            <input type="text" value={selectedItem.obj.title || ""}
                   onChange={e => { selectedItem.obj.title = e.target.value; this.forceUpdate(); }}
                   onBlur={e => { if (!e.target.value.trim()){ selectedItem.obj.title = _("Annotation"); this.forceUpdate(); } }} />
          </div>,
          m.hasView() ? null :
          <div key="description" className="mv-panel-field">
            <textarea rows="3" placeholder={_("Description")} value={selectedItem.obj.description || ""}
                      onChange={e => { selectedItem.obj.description = e.target.value; this.forceUpdate(); }}></textarea>
          </div>,
          m.hasView() ? null :
          <div key="link" className="mv-panel-field">
            <label>{_("Link")}</label>
            <input type="text" placeholder="https://" value={selectedItem.obj.link || ""}
                   onChange={e => { selectedItem.obj.link = e.target.value; this.forceUpdate(); }} />
          </div>] : ""}

          <div className="mv-panel-field">
            {selectedItem.type !== "polyclip" ?
            <button type="button" className="mv-panel-action" onClick={() => this.zoomTo(selectedItem)}><i className="fa fa-search"></i> {_("Zoom to")}</button> : ""}
            {selectedItem.type === "annotation" && !m.hasView() ?
            <button type="button" className="mv-panel-action" onClick={() => viewer.annotationTool.startInsertion({annotation: m})}><i className="fa fa-arrows-alt"></i> {_("Set Position")}</button> : ""}
            {selectedItem.type === "measure" ?
            <button type="button" className="mv-panel-action"
                    onClick={() => {
                      let maxMarkers = Infinity;
                      if (m.showCoordinates) maxMarkers = 1;
                      else if (m.showAngles || m.showCircle) maxMarkers = 3;
                      else if (m.showAzimuth || m.showHeight || m.kind === "perpendicular") maxMarkers = 2;

                      scene.removeMeasurement(m);
                      const fresh = viewer.measuringTool.startInsertion({
                        showDistances: m.showDistances, showArea: m.showArea, showAngles: m.showAngles,
                        showCoordinates: m.showCoordinates, showHeight: m.showHeight, showCircle: m.showCircle,
                        showAzimuth: m.showAzimuth, showEdges: m.showEdges, closed: m.closed,
                        maxMarkers, name: m.name
                      });
                      if (m.kind) fresh.kind = m.kind;
                      this.setState({selected: fresh});
                    }}><i className="far fa-edit"></i> {_("Redo")}</button> : ""}
            {selectedItem.type === "annotation" && m.hasView() ?
            <button type="button" className="mv-panel-action"
                    onClick={() => {
                      m.cameraPosition.copy(scene.view.position);
                      m.cameraTarget.copy(scene.view.getPivot());
                      m.position.copy(scene.view.getPivot());
                      this.setState({updated: "view"});
                      setTimeout(() => this.setState({updated: null}), 2000);
                    }}><i className={updated === "view" ? "fa fa-check" : "fa fa-expand"}></i> {_("Update")}</button> : ""}
            {selectedItem.type === "annotation" && m.hasView() ?
            <button type="button" className="mv-panel-action" onClick={() => viewer.annotationTool.startLookAt(m)}><i className="fa fa-crosshairs"></i> {_("Look At")}</button> : ""}
            {selectedItem.type === "annotation" && m.hasView() && this.props.onSetInitialCameraView ?
            <button type="button" className="mv-panel-action" disabled={updated === "saving"}
                    onClick={() => {
                      this.setState({updated: "saving"});
                      this.props.onSetInitialCameraView(err => {
                        this.setState({updated: err ? null : "initial"});
                        setTimeout(() => this.setState({updated: null}), 2000);
                      }, {position: m.cameraPosition.toArray(), target: m.cameraTarget.toArray()});
                    }}><i className={updated === "saving" ? "fa fa-circle-notch fa-spin" : (updated === "initial" ? "fa fa-check" : "fa fa-video")}></i> {_("Set As Initial View")}</button> : ""}
            {selectedItem.type === "measure" || selectedItem.type === "volume" || selectedItem.type === "animation" ?
            <button type="button" className="mv-panel-action"
                    onClick={() => {
                      const key = {measure: "measurements", volume: "volumes", animation: "cameraAnimations"}[selectedItem.type];
                      const live = Potree.saveProject(viewer);
                      const data = Object.assign({}, live[key].find(d => d.uuid === m.uuid), {
                        uuid: THREE.MathUtils.generateUUID(),
                        name: interpolate(_("%(name)s (copy)"), {name: m.name})
                      });
                      Potree.loadProject(viewer, Object.assign(live, {pointclouds: [], [key]: [data]}));
                      const copy = scene[key].find(o => o.uuid === data.uuid);
                      scene[key].splice(scene[key].indexOf(copy), 1);
                      scene[key].splice(scene[key].indexOf(m) + 1, 0, copy);
                      this.setState({selected: copy, renaming: copy, tab: "properties"});
                    }}><i className="far fa-clone"></i> {_("Duplicate")}</button> : ""}
            <button type="button" className="mv-panel-action mv-danger" onClick={() => this.remove(selectedItem)}><i className="fa fa-trash"></i> {_("Delete")}</button>
          </div>
        </div> :
        isPoint ?
        <div>
          {Object.keys(m.points[0] || {}).filter(key => key !== "position").map(key => {
            const value = m.points[0][key];
            return (<div key={key} className="mv-panel-property">
              <span>{key}</span><span>{value && value.length !== undefined && typeof value !== "string" ? Array.from(value).join(", ") : String(value)}</span>
            </div>);
          })}
          {Object.keys(m.points[0] || {}).length <= 1 ? <div className="mv-panel-property"><span>{_("No attributes")}</span></div> : ""}
        </div> :
        <div className="mv-panel-points">
          <table>
            <thead><tr><th></th><th>x</th><th>y</th><th>z ({unit})</th><th></th></tr></thead>
            <tbody>
              {points.map((p, i) => <tr key={i}>
                <td>{i + 1}</td>
                <td>{this.fmt(p.x)}</td>
                <td>{this.fmt(p.y)}</td>
                <td>{this.fmt(p.z * conv)}</td>
                <td>
                  {selectedItem.type !== "animation" ?
                  <a href="javascript:void(0)" title={_("Copy")}
                     onClick={() => this.copy(`${p.x.toFixed(3)}, ${p.y.toFixed(3)}, ${(p.z * conv).toFixed(3)}`, "copy" + i)}><i className={updated === "copy" + i ? "fa fa-check" : "far fa-copy"}></i></a> : ""}
                  {canEditPoints && (i < points.length - 1 || m.closed) ?
                  <a href="javascript:void(0)" title={_("Add point")}
                     onClick={() => {
                       const positions = points.map(point => point.clone());
                       const count = positions.length;
                       m.addMarker(positions[count - 1].clone());
                       for (let j = count; j > i + 1; j--) m.setPosition(j, positions[j - 1]);
                       m.setPosition(i + 1, positions[i].clone().add(positions[(i + 1) % count]).multiplyScalar(0.5));
                       this.forceUpdate();
                     }}><i className="fa fa-plus"></i></a> : ""}
                  {canEditPoints && points.length > minPoints ?
                  <a href="javascript:void(0)" title={_("Remove point")} className="mv-danger"
                     onClick={() => { m.removeMarker(i); this.forceUpdate(); }}><i className="fa fa-times"></i></a> : ""}
                </td>
              </tr>)}
            </tbody>
          </table>
        </div>}
      </div> : ""}

      {menu ?
      <div className="mv-context-menu" style={{left: menu.x, top: menu.y}}>
        <div onClick={() => { this.setVisible(menu.item, !menu.item.obj.visible); this.forceUpdate(); }}><i className={"fa-fw " + (menu.item.obj.visible ? "far fa-eye-slash" : "far fa-eye")}></i> {menu.item.obj.visible ? _("Hide") : _("Show")}</div>
        <div onClick={() => this.zoomTo(menu.item)}><i className="fa fa-search fa-fw"></i> {_("Zoom To")}</div>
        <div onClick={() => this.setState({renaming: menu.item.obj})}><i className="fa fa-pen fa-fw"></i> {_("Rename")}</div>
        <div onClick={() => this.remove(menu.item)}><i className="fa fa-trash fa-fw"></i> {_("Delete")}</div>
      </div> : ""}

      {exportOpen ?
      <div className="mv-context-menu mv-export-menu">
        <div onClick={() => {
          const { task } = this.props;
          const geojson = Potree.GeoJSONExporter.toString([...scene.measurements, ...scene.profiles, ...scene.volumes]);
          const srs = task.epsg ? `EPSG:${task.epsg}` : task.wkt;
          if (!srs){
            this.download(`${exportName}.geojson`, geojson);
            return;
          }
          $.ajax({
            url: `/api/projects/${task.project}/tasks/${task.id}/reproject`,
            contentType: "application/json",
            data: JSON.stringify({geojson: JSON.parse(geojson), source: srs, target: "EPSG:4979"}),
            type: 'POST'
          }).done(result => this.download(`${exportName}.geojson`, JSON.stringify(result, null, "\t")))
            .fail(xhr => window.alert((xhr.responseJSON && (xhr.responseJSON.error || xhr.responseJSON[0])) || _("Cannot export GeoJSON")));
        }}>GeoJSON</div>
        <div onClick={() => this.download(`${exportName}.dxf`, Potree.DXFExporter.toString([...scene.measurements, ...scene.profiles, ...scene.volumes]))}>DXF</div>
      </div> : ""}
    </div>);
  }
}

export default ProjectPanel;
