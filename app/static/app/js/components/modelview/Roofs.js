import * as THREE from 'THREE';
import { unitSystem } from '../../classes/Units';
import { _ } from '../../classes/gettext';

const key = v => `${v.x.toFixed(3)},${v.y.toFixed(3)},${v.z.toFixed(3)}`;

class Roofs{
  constructor(viewer, onInsert){
    this.viewer = viewer;
    this.onInsert = onInsert;
    this.dragged = null;
    this.group = [];
    this.ctrl = false;
    this.shift = false;
    this.pressed = null;
    this.finish = false;
    this.picked = null;

    viewer.addEventListener("update", this.update);
    window.addEventListener("keydown", this.handleKeys, true);
    window.addEventListener("keyup", this.handleKeys, true);
    window.addEventListener("mousemove", this.handleKeys, true);
    window.addEventListener("blur", this.handleBlur);
    viewer.renderer.domElement.addEventListener("mousedown", this.handleMouseDown, true);
    viewer.renderer.domElement.addEventListener("mouseup", this.handleMouseUp, true);
  }

  dispose(){
    this.viewer.removeEventListener("update", this.update);
    window.removeEventListener("keydown", this.handleKeys, true);
    window.removeEventListener("keyup", this.handleKeys, true);
    window.removeEventListener("mousemove", this.handleKeys, true);
    window.removeEventListener("blur", this.handleBlur);
    this.viewer.renderer.domElement.removeEventListener("mousedown", this.handleMouseDown, true);
    this.viewer.renderer.domElement.removeEventListener("mouseup", this.handleMouseUp, true);
  }

  handleKeys = (e) => {
    this.ctrl = e.ctrlKey;
    this.shift = e.shiftKey;
  }

  handleBlur = () => {
    this.ctrl = false;
    this.shift = false;
  }

  pick(current){
    const hovered = this.viewer.inputHandler.hoveredElements;
    const top = hovered.length && hovered[0].object;
    if (!top || !top.parent || top.parent.kind !== "roof" || top.parent.spheres.indexOf(top) === -1) return null;
    const at = key(top.position);
    const spheres = hovered.map(h => h.object).filter(o => o.parent && o.parent.kind === "roof" && o.parent.spheres.indexOf(o) !== -1 && key(o.position) === at);
    const faces = this.viewer.scene.measurements.filter(m => spheres.some(o => o.parent === m));
    const face = faces[(faces.indexOf(current) + 1) % faces.length];
    return {face, sphere: spheres.find(o => o.parent === face)};
  }

  handleMouseDown = (e) => {
    this.handleKeys(e);
    const viewer = this.viewer;
    const input = viewer.inputHandler;
    if (!e.shiftKey && e.button === 0 && !input.drag && !input.paused){
      const pick = this.pick(this.picked);
      if (!pick) return;
      this.picked = pick.face;
      const i = input.hoveredElements.findIndex(h => h.object === pick.sphere);
      input.hoveredElements.unshift(...input.hoveredElements.splice(i, 1));
      return;
    }
    if (!e.shiftKey || e.button !== 0 || input.drag || input.paused) return;

    const hit = input.hoveredElements.map(h => h.object).find(o => o.parent && o.parent.kind === "roof" && o.parent.spheres.indexOf(o) !== -1);
    if (!hit) return;

    e.stopImmediatePropagation();
    e.preventDefault();

    const start = hit.parent.points[hit.parent.spheres.indexOf(hit)].position.clone();
    const face = viewer.measuringTool.startInsertion({showDistances: false, showArea: false, closed: true, name: _("Roof Plane")});
    face.kind = "roof";
    face.open = true;
    face.setPosition(0, start);
    face.addMarker(start.clone());
    input.startDragging(face.spheres[1]);
    this.pressed = {x: e.clientX, y: e.clientY};
    if (this.onInsert) this.onInsert(face);
  }

  handleMouseUp = (e) => {
    if (e.button === 0 && e.shiftKey) this.finish = true;
    if (!this.pressed) return;
    const moved = Math.hypot(e.clientX - this.pressed.x, e.clientY - this.pressed.y) > 3;
    this.pressed = null;
    if (!moved && e.button === 0) e.stopImmediatePropagation();
  }

  closeLoop(face, faces){
    const points = face.points.map(p => p.position);
    if (points.length < 2) return null;
    const first = points[0], last = points[points.length - 1];
    if (key(first) === key(last)) return null;

    const nodes = new Map();
    const edges = [];
    const node = (v) => {
      let n = nodes.get(key(v));
      if (!n){
        n = {pos: v, links: [], on: []};
        nodes.set(key(v), n);
      }
      return n;
    };
    const link = (a, b) => {
      const w = a.pos.distanceTo(b.pos);
      a.links.push({to: b, w});
      b.links.push({to: a, w});
    };

    for (const other of faces){
      if (other === face || other.points.length < 2) continue;
      other.points.forEach((p, i) => {
        const a = node(p.position), b = node(other.points[(i + 1) % other.points.length].position);
        if (a === b) return;
        link(a, b);
        edges.push([a, b]);
      });
    }

    const attach = (v) => {
      if (nodes.has(key(v))) return nodes.get(key(v));
      const n = node(v);
      for (const edge of edges){
        const c = new THREE.Line3(edge[0].pos, edge[1].pos).closestPointToPoint(v, true, new THREE.Vector3());
        if (c.distanceTo(v) < 1e-3){
          link(n, edge[0]);
          link(n, edge[1]);
          n.on.push(edge);
        }
      }
      return n;
    };

    const src = attach(last), dst = attach(first);
    if (src.links.length === 0 || dst.links.length === 0) return null;
    if (src.on.some(e => dst.on.indexOf(e) !== -1 || e.indexOf(dst) !== -1) || dst.on.some(e => e.indexOf(src) !== -1)) return null;

    const blocked = new Set(points.slice(1, -1).map(key));
    const dist = new Map([[src, 0]]);
    const prev = new Map();
    const done = new Set();
    for (;;){
      let best = null;
      for (const [n, d] of dist){
        if (!done.has(n) && (!best || d < dist.get(best))) best = n;
      }
      if (!best || best === dst) break;
      done.add(best);
      for (const {to, w} of best.links){
        if (done.has(to) || (to !== dst && blocked.has(key(to.pos)))) continue;
        const d = dist.get(best) + w;
        if (!dist.has(to) || d < dist.get(to)){
          dist.set(to, d);
          prev.set(to, best);
        }
      }
    }
    if (!prev.has(dst)) return null;

    const path = [];
    for (let n = prev.get(dst); n !== src; n = prev.get(n)) path.unshift(n.pos);
    return path;
  }

  update = () => {
    const viewer = this.viewer;
    const faces = viewer.scene.measurements.filter(m => m.kind === "roof");
    const drag = viewer.inputHandler.drag;
    const vr = viewer.renderer.xr.isPresenting;
    const vrDrag = vr && viewer.vrControls && viewer.vrControls.drag && (!viewer.vrControls.drag.direct || viewer.vrControls.drag.held) ? viewer.vrControls.drag : null;
    const held = vrDrag ? (vrDrag.measurement.kind === "roof" ? {face: vrDrag.measurement, index: vrDrag.index} : null) :
                 drag && drag.object && drag.object.parent && drag.object.parent.kind === "roof" ? {face: drag.object.parent, index: drag.object.parent.spheres.indexOf(drag.object)} : null;
    if (held && held.index >= 0 && (!this.dragged || this.dragged.face !== held.face || this.dragged.index !== held.index)){
      const at = held.face.points[held.index].position;
      this.group = [];
      if (this.ctrl && !held.face.open){
        for (const face of faces){
          for (const p of face.points){
            if (p !== held.face.points[held.index] && p.position.distanceTo(at) < 1e-3) this.group.push({face, point: p});
          }
        }
      }
    }
    const grouped = new Set(this.group.map(g => g.point));
    const camera = viewer.scene.getActiveCamera();
    const width = viewer.renderer.domElement.clientWidth;
    const height = viewer.renderer.domElement.clientHeight;
    const screen = (v) => {
      const p = v.clone().project(camera);
      return new THREE.Vector2((p.x + 1) / 2 * width, (1 - p.y) / 2 * height);
    };
    const gap = (a, b) => {
      if (!vr) return screen(a).distanceTo(screen(b));
      const eye = viewer.scene.view.position;
      return a.clone().sub(eye).angleTo(b.clone().sub(eye)) / 0.026 * 20;
    };

    for (const item of [this.dragged, held]){
      if (!item || item.index < 0 || item.index >= item.face.points.length) continue;

      const point = item.face.points[item.index].position;
      const others = faces.filter(m => m !== item.face && m.points.length >= 2);
      let best = null;
      let distance = 20;

      let own = false;

      if (!item.face.open && item.face.points.length > 3){
        item.face.points.forEach((p, i) => {
          if (i !== item.index && !grouped.has(p) && gap(p.position, point) <= distance){
            distance = gap(p.position, point);
            best = p.position.clone();
            own = true;
          }
        });
      }

      if (!best){
        for (const other of others){
          for (const p of other.points){
            if (!grouped.has(p) && gap(p.position, point) <= distance){
              distance = gap(p.position, point);
              best = p.position.clone();
            }
          }
        }
      }

      if (!best){
        for (const other of others){
          other.points.forEach((p, i) => {
            if (grouped.has(p) || grouped.has(other.points[(i + 1) % other.points.length])) return;
            const onEdge = new THREE.Line3(p.position, other.points[(i + 1) % other.points.length].position).closestPointToPoint(point, true, new THREE.Vector3());
            if (gap(onEdge, point) <= distance){
              distance = gap(onEdge, point);
              best = onEdge;
            }
          });
        }
      }

      if (own && !held && !viewer.inputHandler.paused){
        item.face.removeMarker(item.index);
        continue;
      }
      if (best && best.distanceTo(point) > 1e-6) item.face.setPosition(item.index, best);

      for (const g of this.group){
        const i = g.face.points.indexOf(g.point);
        if (i !== -1 && g.point.position.distanceTo(point) > 1e-9) g.face.setPosition(i, point);
      }
    }
    if (!held) this.group = [];
    this.dragged = held;

    if (this.finish){
      this.finish = false;
      const path = held && held.face.open ? this.closeLoop(held.face, faces) : null;
      if (path){
        viewer.renderer.domElement.dispatchEvent(new MouseEvent("mouseup", {button: 2, bubbles: true}));
        path.forEach(p => held.face.addMarker(p.clone()));
        held.face.open = false;
        held.face.showDistances = true;
        held.face.showArea = true;
        this.dragged = null;
      }
    }

    for (const face of faces){
      if (face.open && !(held && held.face === face) && !(viewer.inputHandler.paused && viewer.inputHandler.paused.parent === face)){
        if (face.points.length < 3){
          viewer.scene.removeMeasurement(face);
          continue;
        }
        face.open = false;
        face.showDistances = true;
        face.showArea = true;
        const path = this.shift ? this.closeLoop(face, faces) : null;
        if (path) path.forEach(p => face.addMarker(p.clone()));
      }

      if (face.points.length < 3){
        face.roof = null;
        continue;
      }

      const points = face.points.map(p => p.position);
      let x = 0, y = 0, z = 0;
      points.forEach((p, i) => {
        const n = points[(i + 1) % points.length];
        x += (p.y - n.y) * (p.z + n.z);
        y += (p.z - n.z) * (p.x + n.x);
        z += (p.x - n.x) * (p.y + n.y);
      });
      const pitch = Math.atan2(Math.hypot(x, y), Math.abs(z)) * 180 / Math.PI;
      const label = unitSystem().pitch(pitch).toString();
      const stale = !face.roof || face.roof.label !== label;
      face.roof = {pitch, label};
      if (stale) face.update();
    }
  }
}

export default Roofs;
