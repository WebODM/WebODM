import * as THREE from 'THREE';

class HelperMeasure{
  constructor(viewer, args, onDone){
    this.viewer = viewer;
    this.onDone = onDone;
    this.inserting = true;
    this.finished = false;
    this.disposed = false;

    const measure = this.measure = new Potree.Measure();
    measure.showDistances = !!args.showDistances;
    measure.showArea = false;
    measure.closed = !!args.closed;
    measure.maxMarkers = args.maxMarkers;
    measure.name = args.name;

    viewer.measuringTool.scene.add(measure);
    measure.addMarker(new THREE.Vector3());
    viewer.inputHandler.startDragging(measure.spheres[0]);

    viewer.addEventListener("update", this.update);
    viewer.renderer.domElement.addEventListener("mouseup", this.handleMouseUp);
    document.addEventListener("keydown", this.handleKeyDown);
  }

  dispose = () => {
    if (this.disposed) return;
    this.disposed = true;
    const viewer = this.viewer;
    const handler = viewer.inputHandler;
    const own = o => !!o && this.measure.spheres.indexOf(o) !== -1;
    if (handler.drag && own(handler.drag.object)) handler.drag = null;
    if (own(handler.paused)) handler.paused = null;

    viewer.measuringTool.scene.remove(this.measure);
    viewer.removeEventListener("update", this.update);
    viewer.renderer.domElement.removeEventListener("mouseup", this.handleMouseUp);
    document.removeEventListener("keydown", this.handleKeyDown);
  }

  handleMouseUp = (e) => {
    if (!this.inserting) return;

    const measure = this.measure;
    if (e.button === 0){
      measure.addMarker(measure.points[measure.points.length - 1].position.clone());
      if (measure.points.length >= measure.maxMarkers) this.inserting = false;
      this.viewer.inputHandler.startDragging(measure.spheres[measure.spheres.length - 1]);
    }else if (e.button === 2){
      this.dispose();
    }
  }

  handleKeyDown = (e) => {
    if (e.key === "Escape" && !this.finished) this.dispose();
  }

  update = () => {
    const viewer = this.viewer;
    const measure = this.measure;
    const camera = viewer.scene.getActiveCamera();
    const size = viewer.renderer.getSize(new THREE.Vector2());

    measure.lengthUnit = viewer.lengthUnit;
    measure.lengthUnitDisplay = viewer.lengthUnitDisplay;
    measure.update();

    for (const sphere of measure.spheres){
      const pr = Potree.Utils.projectedRadius(1, camera, camera.position.distanceTo(sphere.getWorldPosition(new THREE.Vector3())), size.width, size.height);
      sphere.scale.setScalar(15 / pr);
    }
    for (const label of measure.edgeLabels){
      const pr = Potree.Utils.projectedRadius(1, camera, camera.position.distanceTo(label.getWorldPosition(new THREE.Vector3())), size.width, size.height);
      label.scale.setScalar(70 / pr);
    }

    if (this.inserting || this.finished || viewer.inputHandler.drag || viewer.inputHandler.paused) return;

    this.finished = true;
    this.onDone(measure.points.map(p => p.position.clone()));
  }
}

export default HelperMeasure;
