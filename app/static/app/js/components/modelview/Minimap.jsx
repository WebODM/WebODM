import React from 'react';
import PropTypes from 'prop-types';
import * as THREE from 'THREE';
import '../../css/modelview/Minimap.scss';
import { _ } from '../../classes/gettext';

class Minimap extends React.Component{
  static propTypes = {
    viewer: PropTypes.object.isRequired
  }

  constructor(props){
    super(props);

    this.state = {
      open: false,
      width: 248,
      height: 192
    };

    this.image = null;
    this.transform = null;
  }

  componentDidMount(){
    this.props.viewer.addEventListener("update", this.draw);
    this.buildInterval = setInterval(this.buildImage, 3000);
  }

  componentWillUnmount(){
    this.props.viewer.removeEventListener("update", this.draw);
    clearInterval(this.buildInterval);
  }

  componentDidUpdate(prevProps, prevState){
    if (this.state.open && !prevState.open) this.buildImage();
  }

  buildImage = () => {
    const pc = this.props.viewer.scene.pointclouds[0];
    if (!this.state.open || !this.canvas || !pc) return;

    const width = this.canvas.width;
    const height = this.canvas.height;
    const box = pc.pcoGeometry.tightBoundingBox || pc.boundingBox;
    const minX = box.min.x + pc.position.x;
    const maxY = box.max.y + pc.position.y;
    const sizeX = box.max.x - box.min.x;
    const sizeY = box.max.y - box.min.y;
    const scale = Math.min(width / sizeX, height / sizeY) * 0.9;
    const offsetX = (width - sizeX * scale) / 2;
    const offsetY = (height - sizeY * scale) / 2;

    const image = new ImageData(width, height);
    const pixels = image.data;
    const depth = new Float32Array(width * height).fill(-Infinity);
    const dot = scale > 4 ? 2 : 1;

    for (let i = 3; i < pixels.length; i += 4) pixels[i] = 255;

    pc.visibleNodes.forEach(node => {
      const attributes = node.geometryNode.geometry.attributes;
      if (!attributes.position || !attributes.rgba) return;

      const positions = attributes.position.array;
      const colors = attributes.rgba.array;
      const m = node.sceneNode.matrixWorld.elements;

      for (let i = 0, c = 0; i < positions.length; i += 3, c += 4){
        const px = Math.floor(offsetX + (positions[i] + m[12] - minX) * scale);
        const py = Math.floor(offsetY + (maxY - positions[i + 1] - m[13]) * scale);
        const z = positions[i + 2] + m[14];

        for (let dy = 0; dy < dot; dy++){
          for (let dx = 0; dx < dot; dx++){
            const x = px + dx;
            const y = py + dy;
            if (x < 0 || y < 0 || x >= width || y >= height) continue;

            const idx = y * width + x;
            if (z < depth[idx]) continue;

            depth[idx] = z;
            pixels[idx * 4] = colors[c];
            pixels[idx * 4 + 1] = colors[c + 1];
            pixels[idx * 4 + 2] = colors[c + 2];
          }
        }
      }
    });

    this.image = image;
    this.depth = depth;
    this.transform = {minX, maxY, scale, offsetX, offsetY};
  }

  startResize = (e, horizontal, vertical) => {
    e.preventDefault();

    const startX = e.clientX;
    const startY = e.clientY;
    const { width, height } = this.state;
    const parent = this.root.parentElement.getBoundingClientRect();

    const move = (ev) => {
      this.setState({
        width: horizontal ? Math.min(Math.max(width + ev.clientX - startX, 248), parent.width - 24) : width,
        height: vertical ? Math.min(Math.max(height + startY - ev.clientY, 192), parent.height - 24) : height
      });
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      this.buildImage();
    };

    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  }

  handleDoubleClick = (e) => {
    if (!this.image) return;

    const { viewer } = this.props;
    const rect = this.canvas.getBoundingClientRect();
    const px = Math.floor(e.clientX - rect.left);
    const py = Math.floor(e.clientY - rect.top);
    const z = this.depth[py * this.image.width + px];
    if (z === undefined || z === -Infinity) return;

    const { minX, maxY, scale, offsetX, offsetY } = this.transform;
    const view = viewer.scene.view;
    const eyeHeight = 1.7 * viewer.lengthUnit.unitspermeter;

    view.position.set(minX + (px - offsetX) / scale, maxY - (py - offsetY) / scale, z + eyeHeight);
    view.pitch = 0;
    view.radius = 5 * viewer.lengthUnit.unitspermeter;
  }

  draw = () => {
    if (!this.state.open || !this.canvas || !this.image) return;
    if (this.image.width !== this.canvas.width || this.image.height !== this.canvas.height) return;

    const { viewer } = this.props;
    const view = viewer.scene.view;
    const { minX, maxY, scale, offsetX, offsetY } = this.transform;
    const ctx = this.canvas.getContext("2d");
    const x = Math.min(Math.max(offsetX + (view.position.x - minX) * scale, 6), this.canvas.width - 6);
    const y = Math.min(Math.max(offsetY + (maxY - view.position.y) * scale, 6), this.canvas.height - 6);
    const camera = viewer.scene.getActiveCamera();
    const ground = view.getPivot().z;
    const reach = Math.hypot(this.canvas.width, this.canvas.height) / scale;

    ctx.putImageData(this.image, 0, 0);

    ctx.fillStyle = "rgba(255, 221, 51, 0.4)";
    ctx.strokeStyle = "rgba(255, 221, 51, 0.9)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    [[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach((corner, i) => {
      const near = new THREE.Vector3(corner[0], corner[1], -1).unproject(camera);
      const ray = new THREE.Vector3(corner[0], corner[1], 1).unproject(camera).sub(near);
      const t = ray.z < 0 ? (ground - near.z) / ray.z : Infinity;
      let px = near.x + ray.x * t, py = near.y + ray.y * t;

      if (!(Math.hypot(px - near.x, py - near.y) <= reach)){
        const flat = Math.hypot(ray.x, ray.y) || 1;
        px = near.x + ray.x / flat * reach;
        py = near.y + ray.y / flat * reach;
      }

      if (i === 0) ctx.moveTo(offsetX + (px - minX) * scale, offsetY + (maxY - py) * scale);
      else ctx.lineTo(offsetX + (px - minX) * scale, offsetY + (maxY - py) * scale);
    });
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#ff0000";
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  render(){
    const { open, width, height } = this.state;

    return (<div className={"mv-minimap " + (open ? "open" : "")} style={open ? {width, height} : {}}
                 ref={domNode => { this.root = domNode; }}>
      {open ? <canvas width={width - 12} height={height - 12} title={_("Double-click to move here")}
                       onDoubleClick={this.handleDoubleClick}
                       ref={domNode => { this.canvas = domNode; }}></canvas> : ""}
      {open ? [
      <div key="n" className="mv-minimap-resize-n" onPointerDown={e => this.startResize(e, false, true)}></div>,
      <div key="e" className="mv-minimap-resize-e" onPointerDown={e => this.startResize(e, true, false)}></div>,
      <div key="ne" className="mv-minimap-resize-ne" onPointerDown={e => this.startResize(e, true, true)}></div>
      ] : ""}
      {open ?
      <button type="button" className="mv-minimap-close" title={_("Close")}
              onClick={() => this.setState({open: false})}><i className="fa fa-times"></i></button> :
      <button type="button" className="mv-minimap-toggle btn btn-sm btn-secondary" title={_("Minimap")}
              onClick={() => this.setState({open: true})}><i className="fa fa-map"></i></button>}
    </div>);
  }
}

export default Minimap;
