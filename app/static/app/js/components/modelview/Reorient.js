import * as THREE from 'THREE';

class Reorient{
  constructor(viewer, onDone){
    this.viewer = viewer;
    this.onDone = onDone;
    this.measure = null;
    this.group = null;
    this.arrow = null;
    this.center = null;
    this.normal = null;
    this.radius = 0;
    this.sign = 1;
    this.pressed = null;

    viewer.addEventListener("update", this.update);
    document.addEventListener("keydown", this.handleKeyDown);
    viewer.renderer.domElement.addEventListener("mousemove", this.handleMouseMove);
    viewer.renderer.domElement.addEventListener("mousedown", this.handleMouseDown, true);
    viewer.renderer.domElement.addEventListener("mouseup", this.handleMouseUp, true);
  }

  dispose(){
    this.cancel();
    this.viewer.removeEventListener("update", this.update);
    document.removeEventListener("keydown", this.handleKeyDown);
    this.viewer.renderer.domElement.removeEventListener("mousemove", this.handleMouseMove);
    this.viewer.renderer.domElement.removeEventListener("mousedown", this.handleMouseDown, true);
    this.viewer.renderer.domElement.removeEventListener("mouseup", this.handleMouseUp, true);
  }

  active(){
    return !!(this.measure || this.group);
  }

  start(measure){
    this.cancel();
    this.measure = measure;
  }

  cancel = () => {
    if (this.measure) this.viewer.scene.removeMeasurement(this.measure);
    if (this.group){
      this.viewer.measuringTool.scene.remove(this.group);
      this.group.traverse(o => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) o.material.dispose();
      });
    }
    this.measure = null;
    this.group = null;
    this.arrow = null;
    this.pressed = null;
  }

  update = () => {
    const viewer = this.viewer;
    if (!this.measure) return;

    if (viewer.scene.measurements.indexOf(this.measure) === -1){
      this.measure = null;
      return;
    }
    if (viewer.inputHandler.drag || viewer.inputHandler.paused) return;

    const points = this.measure.points.map(p => p.position.clone());
    this.cancel();
    if (points.length !== 3) return;

    const normal = points[1].clone().sub(points[0]).cross(points[2].clone().sub(points[0]));
    if (normal.length() < 1e-9) return;

    this.normal = normal.normalize();
    if (this.normal.z < 0) this.normal.negate();
    this.sign = 1;
    this.center = points[0].clone().add(points[1]).add(points[2]).divideScalar(3);
    this.radius = 1.5 * Math.max(...points.map(p => p.distanceTo(this.center)));

    const plane = new THREE.Mesh(new THREE.CircleGeometry(this.radius, 64), new THREE.MeshBasicMaterial({
      color: 0xffffff, transparent: true, opacity: 0.3, side: THREE.DoubleSide, depthTest: false, depthWrite: false
    }));
    plane.position.copy(this.center);
    plane.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), this.normal);

    const material = new THREE.MeshBasicMaterial({color: 0xff0000, depthTest: false, depthWrite: false});
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(this.radius * 0.02, this.radius * 0.02, this.radius * 0.75, 12), material);
    shaft.position.y = this.radius * 0.375;
    const head = new THREE.Mesh(new THREE.ConeGeometry(this.radius * 0.08, this.radius * 0.25, 16), material);
    head.position.y = this.radius * 0.875;
    this.arrow = new THREE.Group();
    this.arrow.add(shaft);
    this.arrow.add(head);
    this.arrow.position.copy(this.center);
    this.arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), this.normal);

    this.group = new THREE.Group();
    this.group.add(plane);
    this.group.add(this.arrow);
    viewer.measuringTool.scene.add(this.group);
  }

  handleKeyDown = (e) => {
    if (e.key === "Escape" && this.group) this.cancel();
  }

  handleMouseMove = (e) => {
    if (!this.group) return;

    const camera = this.viewer.scene.getActiveCamera();
    const rect = this.viewer.renderer.domElement.getBoundingClientRect();
    const base = this.center.clone().project(camera);
    const tip = this.center.clone().addScaledVector(this.normal, this.radius).project(camera);
    const dx = (tip.x - base.x) * rect.width, dy = -(tip.y - base.y) * rect.height;
    if (Math.hypot(dx, dy) < 4) return;

    const mx = e.clientX - rect.left - (base.x + 1) / 2 * rect.width;
    const my = e.clientY - rect.top - (1 - base.y) / 2 * rect.height;
    this.sign = dx * mx + dy * my >= 0 ? 1 : -1;
    this.arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), this.normal.clone().multiplyScalar(this.sign));
  }

  handleMouseDown = (e) => {
    if (this.group) this.pressed = {x: e.clientX, y: e.clientY};
  }

  handleMouseUp = (e) => {
    if (!this.group || !this.pressed) return;

    const moved = Math.hypot(e.clientX - this.pressed.x, e.clientY - this.pressed.y) > 3;
    this.pressed = null;
    if (moved) return;

    const rotation = new THREE.Quaternion().setFromUnitVectors(this.normal.clone().multiplyScalar(this.sign), new THREE.Vector3(0, 0, 1));
    const center = this.center;
    this.cancel();
    if (e.button === 0) this.onDone(rotation, center);
  }
}

export default Reorient;
