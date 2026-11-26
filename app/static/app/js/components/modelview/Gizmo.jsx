import React from 'react';
import PropTypes from 'prop-types';
import * as THREE from 'THREE';
import '../../css/modelview/Gizmo.scss';
import { _ } from '../../classes/gettext';

const AXES = [
  {dir: [1, 0, 0], label: "X", color: "#f14668", view: "setRightView"},
  {dir: [0, 1, 0], label: "Y", color: "#2ecc71", view: "setBackView"},
  {dir: [0, 0, 1], label: "Z", color: "#3d8bfd", view: "setTopView"},
  {dir: [-1, 0, 0], label: "", color: "#f14668", view: "setLeftView"},
  {dir: [0, -1, 0], label: "", color: "#2ecc71", view: "setFrontView"},
  {dir: [0, 0, -1], label: "", color: "#3d8bfd", view: "setBottomView"}
];

class Gizmo extends React.Component{
  static propTypes = {
    viewer: PropTypes.object.isRequired,
    shifted: PropTypes.bool.isRequired
  }

  componentDidMount(){
    this.balls = [];
    this.props.viewer.addEventListener("update", this.draw);
  }

  componentWillUnmount(){
    this.props.viewer.removeEventListener("update", this.draw);
  }

  draw = () => {
    const camera = this.props.viewer.scene.getActiveCamera();
    const inverse = camera.quaternion.clone().conjugate();
    const size = this.canvas.width;
    const center = size / 2;
    const length = size / 2 - 12;
    const ctx = this.canvas.getContext("2d");

    this.balls = AXES.map(axis => {
      const v = new THREE.Vector3(...axis.dir).applyQuaternion(inverse);
      return {axis, x: center + v.x * length, y: center - v.y * length, depth: v.z};
    }).sort((a, b) => a.depth - b.depth);

    ctx.clearRect(0, 0, size, size);
    this.balls.forEach(ball => {
      const positive = ball.axis.label !== "";

      if (positive){
        ctx.strokeStyle = ball.axis.color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(center, center);
        ctx.lineTo(ball.x, ball.y);
        ctx.stroke();
      }

      ctx.globalAlpha = positive ? 1 : 0.6;
      ctx.fillStyle = ball.axis.color;
      ctx.beginPath();
      ctx.arc(ball.x, ball.y, positive ? 9 : 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;

      if (positive){
        ctx.fillStyle = "#111";
        ctx.font = "bold 11px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(ball.axis.label, ball.x, ball.y + 0.5);
      }
    });
  }

  handleClick = (e) => {
    const rect = this.canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    for (let i = this.balls.length - 1; i >= 0; i--){
      const ball = this.balls[i];
      if (Math.hypot(ball.x - x, ball.y - y) <= 10){
        this.props.viewer[ball.axis.view]();
        return;
      }
    }
  }

  render(){
    return (<canvas className={"mv-gizmo " + (this.props.shifted ? "shifted" : "")} width="96" height="96"
                    title={_("Click an axis to look along it")}
                    onClick={this.handleClick}
                    ref={domNode => { this.canvas = domNode; }}></canvas>);
  }
}

export default Gizmo;
