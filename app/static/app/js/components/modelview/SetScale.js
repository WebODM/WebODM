import HelperMeasure from './HelperMeasure';

class SetScale{
  constructor(viewer, onDone){
    this.viewer = viewer;
    this.onDone = onDone;
    this.helper = null;
  }

  dispose(){
    this.cancel();
  }

  active(){
    return !!this.helper && !this.helper.disposed;
  }

  start(name){
    this.cancel();
    this.helper = new HelperMeasure(this.viewer, {showDistances: true, closed: false, maxMarkers: 2, name}, points => {
      if (points[0].distanceTo(points[1]) < 1e-9) this.cancel();
      else this.onDone(points[0], points[1]);
    });
  }

  cancel = () => {
    if (this.helper) this.helper.dispose();
    this.helper = null;
  }
}

export default SetScale;
