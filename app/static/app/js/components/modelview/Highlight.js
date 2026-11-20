import * as THREE from 'THREE';

class Highlight{
  constructor(viewer){
    this.viewer = viewer;
    this.last = null;
    this.filled = "";

    const material = new THREE.MeshBasicMaterial({color: 0xffff00, transparent: true, opacity: 0.3, side: THREE.DoubleSide, depthTest: false, depthWrite: false});
    this.fill = new THREE.Mesh(new THREE.BufferGeometry(), material);
    this.disc = new THREE.Mesh(new THREE.CircleGeometry(1, 64), material);
    this.fill.visible = false;
    this.disc.visible = false;
    viewer.measuringTool.scene.add(this.fill, this.disc);

    viewer.addEventListener("update", this.update);
  }

  dispose(){
    this.viewer.removeEventListener("update", this.update);
    this.viewer.renderer.domElement.style.cursor = "";
    this.viewer.measuringTool.scene.remove(this.fill, this.disc);
    this.fill.geometry.dispose();
    this.disc.geometry.dispose();
    this.fill.material.dispose();
  }

  update = () => {
    const item = this.viewer.selectedItem;
    const drag = this.viewer.inputHandler.drag;
    const handle = this.viewer.inputHandler.hoveredElements.some(h => h.object.parent && h.object.parent.spheres && h.object.parent.spheres.indexOf(h.object) !== -1);
    this.viewer.renderer.domElement.style.cursor = drag && drag.object ? (this.viewer.clippingTool.closing ? "pointer" : "crosshair") : (handle ? "pointer" : "");
    const measure = item instanceof Potree.Measure && item.visible && !item.open ? item : null;
    const polygon = measure && measure.closed && (measure.showArea || measure.showAngles) && measure.points.length >= 3;
    const circle = measure && measure.showCircle && measure.points.length === 3;
    const azimuth = measure && measure.showAzimuth && measure.points.length === 2;

    for (const [obj, on] of [[this.last !== item ? this.last : null, false], [item, true]]){
      if (obj instanceof Potree.Measure){
        const dot = obj.showCoordinates;
        const lines = !dot && !(obj.closed && (obj.showArea || obj.showAngles)) && !obj.showCircle && !obj.showAzimuth;
        obj.color.set(on && dot ? 0xffff00 : 0xff0000);
        obj.spheres.forEach(s => s.material.color.set(obj.color));
        obj.edges.forEach(e => e.material.color.set(on && lines ? 0xffff00 : 0xff0000));
      }else if (obj instanceof Potree.BoxVolume){
        obj.material.color.set(on ? 0xffff00 : 0x00ff00);
      }
    }
    this.last = item;

    const filled = polygon ? measure.points.map(p => p.position.toArray().join(",")).join(" ") : "";
    this.fill.visible = !!polygon;
    if (polygon && filled !== this.filled){
      const points = measure.points.map(p => p.position);
      const origin = points[0];
      let x = 0, y = 0, z = 0;
      points.forEach((p, i) => {
        const n = points[(i + 1) % points.length];
        x += (p.y - n.y) * (p.z + n.z);
        y += (p.z - n.z) * (p.x + n.x);
        z += (p.x - n.x) * (p.y + n.y);
      });
      const drop = Math.abs(z) >= Math.abs(x) && Math.abs(z) >= Math.abs(y) ? "z" : (Math.abs(y) >= Math.abs(x) ? "y" : "x");
      const flat = points.map(p => drop === "z" ? new THREE.Vector2(p.x - origin.x, p.y - origin.y) :
                                   drop === "y" ? new THREE.Vector2(p.x - origin.x, p.z - origin.z) :
                                                  new THREE.Vector2(p.y - origin.y, p.z - origin.z));
      const positions = [];
      for (const triangle of THREE.ShapeUtils.triangulateShape(flat, [])){
        for (const i of triangle) positions.push(points[i].x - origin.x, points[i].y - origin.y, points[i].z - origin.z);
      }
      this.fill.geometry.dispose();
      this.fill.geometry = new THREE.BufferGeometry();
      this.fill.geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      this.fill.position.copy(origin);
    }
    this.filled = filled;

    this.disc.visible = !!(circle || azimuth);
    if (circle){
      const a = measure.points[0].position, b = measure.points[1].position, c = measure.points[2].position;
      const centre = Potree.Utils.computeCircleCenter(a, b, c);
      const radius = centre.distanceTo(a) || 0;
      this.disc.position.copy(centre);
      this.disc.scale.set(radius, radius, radius);
      this.disc.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), c.clone().sub(a).cross(b.clone().sub(a)).normalize());
    }else if (azimuth){
      const radius = measure.points[0].position.distanceTo(measure.points[1].position);
      this.disc.position.copy(measure.points[0].position);
      this.disc.scale.set(radius, radius, radius);
      this.disc.quaternion.set(0, 0, 0, 1);
    }
  }
}

export default Highlight;
