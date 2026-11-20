import React from 'react';
import PropTypes from 'prop-types';
import '../../css/modelview/Magnifier.scss';

class Magnifier extends React.Component{
  static propTypes = {
    viewer: PropTypes.object.isRequired
  }

  componentDidMount(){
    this.props.viewer.addEventListener("update", this.draw);
  }

  componentWillUnmount(){
    this.props.viewer.removeEventListener("update", this.draw);
    if (this.hidden) this.hidden.visible = true;
  }

  draw = () => {
    const { viewer } = this.props;
    const handler = viewer.inputHandler;
    const drag = handler.drag;
    const parent = drag && drag.object ? drag.object.parent : null;

    if (!(parent instanceof Potree.Measure) && !(parent instanceof Potree.Profile) && !(drag && drag.object && drag.object.magnify)){
      if (this.hidden){
        this.hidden.visible = true;
        this.hidden = null;
      }
      if (this.canvas.style.display !== "none") this.canvas.style.display = "none";
      return;
    }

    if (this.hidden !== drag.object){
      if (this.hidden) this.hidden.visible = true;
      this.hidden = drag.object;
      this.hidden.visible = false;
    }

    const source = viewer.renderer.domElement;
    const scale = source.width / source.clientWidth;
    const size = this.canvas.width;
    const sourceSize = size / 4 * scale;
    const ctx = this.canvas.getContext("2d");

    ctx.clearRect(0, 0, size, size);
    ctx.drawImage(source,
      handler.mouse.x * scale - sourceSize / 2, handler.mouse.y * scale - sourceSize / 2, sourceSize, sourceSize,
      0, 0, size, size);

    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(size / 2, size / 2 - 12);
    ctx.lineTo(size / 2, size / 2 + 12);
    ctx.moveTo(size / 2 - 12, size / 2);
    ctx.lineTo(size / 2 + 12, size / 2);
    ctx.stroke();

    let left = handler.mouse.x + 24;
    let top = handler.mouse.y - size - 24;
    if (left + size > source.clientWidth) left = handler.mouse.x - size - 24;
    if (top < 0) top = handler.mouse.y + 24;

    this.canvas.style.left = left + "px";
    this.canvas.style.top = top + "px";
    this.canvas.style.display = "block";
  }

  render(){
    return (<canvas className="mv-magnifier" width="140" height="140" ref={domNode => { this.canvas = domNode; }}></canvas>);
  }
}

export default Magnifier;
