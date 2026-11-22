import * as THREE from 'THREE';
import { _ } from '../../classes/gettext';
import { systems, getUnitSystem, setUnitSystem } from '../../classes/Units';

const SLIDE_SPEED = 3;
const COMFORT_ASSIST = 0.5;
const RAY_GRAVITY = -0.1 / 2.25;
const SNAP_ANGLE = Math.PI / 6;
const THRESHOLD = 0.8;
const MAX_DROP = 5;
const JUMP_HEIGHT = 1.5;
const JUMP_COOLDOWN = 0.1;
const GRAVITY = 9.81;
const ACCELERATION = 100;
const DECELERATION = 100;
const AIR_CONTROL = 0.3;
const RADIUS = 0.5;
const FLOAT_HEIGHT = 0.01;
const SPRING = 30;
const DAMPING = 8;
const MAX_FORCE = 50;
const MAX_SLOPE = Math.cos(1);
const MAX_VELOCITY = 20;
const SLEEP = 500;
const EYE_HEIGHT = 1.8;
const TABLE_RADIUS = 0.75;

const WATCH_POSITION = new THREE.Vector3(-0.04, -0.015, 0.18);
const WATCH_FACE = new THREE.Vector3(-1, 0, 0);
const TRAY_POSITION = new THREE.Vector3(0.045, 0, 0.08);
const PALETTE_WIDTH = 0.18;
const MARGIN = 0.006;
const TITLE = 0.018;
const ROW = 0.034;
const EXTRUDE = 0.015;
const TRAVEL = 0.012;
const POKE_RADIUS = 0.01;
const HIT_MARGIN = 0.012;

const GRID = 32;
const grids = new WeakMap();
const UP = new THREE.Vector3(0, 0, 1);
const AXES = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2);

const sampleParabola = (start, direction, minZ, gravity, points, offset) => {
  const a = 0.5 * gravity;
  const b = direction.z;
  const c = start.z - minZ;
  const end = (-b + Math.sqrt(Math.max(0, b * b - 4 * a * c))) / (2 * a);
  for (let i = offset; i < points.length + offset; i++){
    const t = i / (offset + points.length - 1) * end;
    points[i - offset].set(start.x + direction.x * t, start.y + direction.y * t, start.z + direction.z * t + 0.5 * gravity * t * t);
  }
};

const canvasTexture = (width, height) => {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return new THREE.CanvasTexture(canvas);
};

class VRControls{
  constructor(viewer, {modelTypes, getModelType, setModelType, getLoading, undo, redo}){
    this.viewer = viewer;
    this.undo = undo;
    this.redo = redo;
    this.getModelType = getModelType;
    this.setModelType = setModelType;
    this.getLoading = getLoading;
    this.loadingState = "";
    this.mode = "walk";
    this.scale = 1;
    this.eyeOffset = 0;
    this.calibrate = false;
    this.place = false;
    this.yaw = 0;
    this.position = new THREE.Vector3();
    this.velocity = new THREE.Vector3();
    this.movement = new THREE.Vector3();
    this.grounded = false;
    this.jumping = false;
    this.lastJump = -Infinity;
    this.updating = false;
    this.lastUpdate = 0;
    this.rig = new THREE.Matrix4();
    this.rigInverse = new THREE.Matrix4();
    this.rigQuaternion = new THREE.Quaternion();
    this.hands = {};
    this.previous = {turn: 0, teleport: false, jump: false, toggle: false, undo: false, redo: false, trigger: false, leftTrigger: false};
    this.measureMode = "measure";
    this.drag = null;
    this.editHand = "right";
    this.hover = null;
    this.hits = new Set();
    this.editing = new Set();
    this.deleting = false;
    this.hit = null;
    this.pinch = null;
    this.grab = null;
    this.pointBudget = null;
    this.recenter = false;
    this.recenterStart = 0;
    this.recenterRetry = 0;
    this.labeled = new Set();
    this.markerPosition = new THREE.Vector3();
    this.markerQuaternion = new THREE.Quaternion();
    this.markerTarget = new THREE.Object3D();
    this.rayPoints = Array.from({length: 10}, () => new THREE.Vector3());
    this.linePoints = Array.from({length: 20}, () => new THREE.Vector3());
    this.panels = [];
    this.buttons = [];
    this.tooltipButton = null;

    const light = new THREE.PointLight(0xffffff, 5, 0, 1);
    light.position.set(0, 2, 0);
    viewer.sceneVR.add(light);

    const xr = viewer.renderer.xr;
    const models = new Potree.XRControllerModelFactory();
    for (let i = 0; i < 2; i++){
      const ray = xr.getController(i);
      const grip = xr.getControllerGrip(i);
      grip.add(models.createControllerModel(grip));
      viewer.sceneVR.add(ray, grip);
      ray.addEventListener("connected", e => {
        this.hands[e.data.handedness] = {ray, grip, source: e.data};
        if (e.data.handedness === "left") ray.add(this.watch, this.palette, this.tray);
      });
      ray.addEventListener("disconnected", () => {
        for (const k in this.hands) if (this.hands[k].ray === ray) delete this.hands[k];
        ray.remove(this.watch, this.palette, this.tray);
      });
    }

    this.vignette = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.15, 0.3, 16, 1, true), new THREE.ShaderMaterial({
      vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: "uniform float uAlpha; varying vec2 vUv; void main(){ gl_FragColor = vec4(0.0, 0.0, 0.0, uAlpha * vUv.y); }",
      uniforms: {uAlpha: {value: 0}},
      depthTest: false,
      side: THREE.BackSide,
      transparent: true
    }));
    this.vignette.frustumCulled = false;
    this.vignette.renderOrder = 999;
    this.vignette.rotateX(Math.PI / 2);
    this.vignette.position.z = -0.15;
    this.headGroup = new THREE.Group();
    this.headGroup.add(this.vignette);

    this.cover = new THREE.Mesh(new THREE.SphereGeometry(0.5, 16, 12), new THREE.MeshBasicMaterial({color: 0x111111, side: THREE.BackSide, transparent: true, opacity: 0, depthTest: false}));
    this.cover.frustumCulled = false;
    this.cover.renderOrder = 1000;
    this.cover.visible = false;
    this.loadingTexture = canvasTexture(768, 256);
    this.loadingPanel = new THREE.Mesh(new THREE.PlaneGeometry(0.6, 0.2), new THREE.MeshBasicMaterial({map: this.loadingTexture, transparent: true, opacity: 0, depthTest: false}));
    this.loadingPanel.position.z = -0.45;
    this.loadingPanel.scale.setScalar(0.3);
    this.loadingPanel.frustumCulled = false;
    this.loadingPanel.renderOrder = 1001;
    this.loadingPanel.visible = false;
    this.headGroup.add(this.cover, this.loadingPanel);

    this.pins = new THREE.Group();
    this.pinGeometry = new THREE.ConeGeometry(0.5, 1, 4).rotateX(Math.PI).translate(0, 0.5, 0);
    this.pinMaterial = new THREE.MeshBasicMaterial({color: 0xff2222, transparent: true, opacity: 0.6, depthWrite: false});
    this.pinHoverMaterial = new THREE.MeshBasicMaterial({color: 0xff2222});
    this.dots = new THREE.Group();
    this.dotGeometry = new THREE.SphereGeometry(0.5, 16, 12);

    this.marker = new THREE.Mesh(new THREE.RingGeometry(0.12, 0.15).translate(0, 0, 0.02), new THREE.MeshBasicMaterial());
    this.marker.visible = false;

    const line = new THREE.BufferGeometry();
    line.setAttribute("position", new THREE.BufferAttribute(new Float32Array(this.linePoints.length * 6), 3));
    line.setAttribute("alpha", new THREE.BufferAttribute(new Float32Array(this.linePoints.length * 2), 1));
    const index = [];
    for (let i = 0; i < this.linePoints.length - 1; i++) index.push(i * 2, i * 2 + 1, i * 2 + 2, i * 2 + 1, i * 2 + 3, i * 2 + 2);
    line.setIndex(index);
    this.line = new THREE.Mesh(line, new THREE.ShaderMaterial({
      vertexShader: "attribute float alpha; varying float vAlpha; void main(){ vAlpha = alpha; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: "varying float vAlpha; void main(){ gl_FragColor = vec4(1.0, 1.0, 1.0, vAlpha); }",
      side: THREE.DoubleSide,
      transparent: true
    }));
    this.line.frustumCulled = false;
    this.line.visible = false;

    this.pointer = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 0, -1)]), new THREE.LineBasicMaterial({color: 0xffffff}));
    this.pointer.visible = false;
    this.laser = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 0, -1)]), new THREE.LineBasicMaterial({color: 0xff3333}));
    this.laser.visible = false;
    this.dragLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), new THREE.LineBasicMaterial({color: 0xffffff}));
    this.dragLine.frustumCulled = false;
    this.dragLine.visible = false;

    this.watch = new THREE.Group();
    this.watch.position.copy(WATCH_POSITION);
    this.watch.rotation.z = -15 * Math.PI / 180;
    const watchCase = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.006, 32).rotateZ(Math.PI / 2), new THREE.MeshBasicMaterial({color: 0x555555}));
    watchCase.position.set(-0.033, 0, 0);
    const caseBack = new THREE.Mesh(new THREE.CylinderGeometry(0.019, 0.019, 0.003, 32).rotateZ(Math.PI / 2), new THREE.MeshBasicMaterial({color: 0x2a2a2a}));
    caseBack.position.set(-0.0285, 0, 0);
    this.watch.add(caseBack);
    const bezel = new THREE.Mesh(new THREE.TorusGeometry(0.0205, 0.0015, 8, 32).rotateY(Math.PI / 2), new THREE.MeshBasicMaterial({color: 0x888888}));
    bezel.position.set(-0.0362, 0, 0);
    this.watch.add(bezel);
    this.clockTexture = canvasTexture(256, 256);
    const face = new THREE.Mesh(new THREE.CircleGeometry(0.02, 32).rotateZ(Math.PI).rotateY(-Math.PI / 2), new THREE.MeshBasicMaterial({map: this.clockTexture}));
    face.position.set(-0.0365, 0, 0);
    this.watch.add(watchCase, face);
    this.clockTime = "";

    const sides = [0x3a3a3a, 0x3a3a3a, 0x4a4a4a, 0x252525];
    const panel = (rows, position, basis) => {
      const height = MARGIN + rows.reduce((total, row) => total + (row.title ? TITLE : 0) + row.height + MARGIN, 0);
      const titleTexture = canvasTexture(512, Math.round(512 * height / PALETTE_WIDTH));
      const base = new THREE.Mesh(new THREE.BoxGeometry(PALETTE_WIDTH, height, 0.004).translate(0, 0, -0.002), [
        ...sides.map(color => new THREE.MeshBasicMaterial({color})),
        new THREE.MeshBasicMaterial({map: titleTexture}),
        new THREE.MeshBasicMaterial({color: 0x222222})
      ]);
      const group = new THREE.Group();
      group.add(base);
      group.position.copy(position);
      group.quaternion.setFromRotationMatrix(basis);
      group.updateMatrix();
      group.visible = false;
      const result = {group, height, buttons: [], visible: false, tip: null, lastTipZ: 1};
      const c = titleTexture.image.getContext("2d");
      const px = 512 / PALETTE_WIDTH;
      c.fillStyle = "#222222";
      c.fillRect(0, 0, titleTexture.image.width, titleTexture.image.height);
      c.fillStyle = "#ffffff";
      c.font = "bold 36px sans-serif";
      c.textAlign = "left";
      c.textBaseline = "middle";
      let top = height / 2 - MARGIN;
      for (const row of rows){
        if (row.title){
          c.fillText(row.title, MARGIN * px, (height / 2 - top + TITLE / 2) * px);
          top -= TITLE;
        }
        const w = row.width || (PALETTE_WIDTH - MARGIN * (row.items.length + 1)) / row.items.length;
        row.items.forEach((item, i) => {
          const x = -(row.items.length * w + (row.items.length - 1) * MARGIN) / 2 + w / 2 + i * (w + MARGIN);
          const y = top - row.height / 2;
          const texture = canvasTexture(256, Math.round(256 * row.height / w));
          const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, row.height, EXTRUDE).translate(0, 0, EXTRUDE / 2), [
            ...sides.map(color => new THREE.MeshBasicMaterial({color})),
            new THREE.MeshBasicMaterial({map: texture}),
            new THREE.MeshBasicMaterial({color: 0x222222})
          ]);
          mesh.position.set(x, y, 0);
          group.add(mesh);
          const button = {...item, panel: result, x, y, w, h: row.height, mesh, texture, press: 0, engaged: false, armed: true, state: ""};
          result.buttons.push(button);
          this.buttons.push(button);
        });
        top -= row.height + MARGIN;
      }
      titleTexture.needsUpdate = true;
      this.panels.push(result);
      return result;
    };

    const paletteRows = [{title: _("Mode"), height: ROW, items: [{group: "mode", key: "walk", label: _("Walk")}, {group: "mode", key: "tabletop", label: _("Tabletop")}]}];
    if (modelTypes.length > 1) paletteRows.push({title: _("Model"), height: ROW, items: modelTypes.map(t => ({group: "model", key: t.type, label: t.label}))});
    paletteRows.push({title: _("Units"), height: ROW, items: Object.keys(systems).map(k => ({group: "units", key: k, label: systems[k].getName()}))});
    this.palettePanel = panel(paletteRows, WATCH_POSITION.clone().addScaledVector(WATCH_FACE, 0.07), new THREE.Matrix4().makeBasis(new THREE.Vector3(0, 0, -1), new THREE.Vector3(0, -1, 0), new THREE.Vector3(-1, 0, 0)));
    this.palette = this.palettePanel.group;

    const tools = [
      {icon: "mv-icon mv-icon-point", label: _("Point"), args: {showDistances: false, showAngles: false, showCoordinates: true, showArea: false, closed: true, maxMarkers: 1, name: _("Point")}},
      {icon: "mv-icon mv-icon-distance", label: _("Distance"), args: {showDistances: true, showArea: false, closed: false, name: _("Distance")}},
      {icon: "mv-icon mv-icon-height", label: _("Height"), args: {showDistances: false, showHeight: true, showArea: false, closed: false, maxMarkers: 2, name: _("Height")}},
      {icon: "mv-icon mv-icon-angle", label: _("Angle"), args: {showDistances: false, showAngles: true, showArea: false, closed: true, maxMarkers: 3, name: _("Angle")}},
      {icon: "mv-icon mv-icon-circle", label: _("Circle"), args: {showDistances: false, showHeight: false, showArea: false, showCircle: true, showEdges: false, closed: false, maxMarkers: 3, name: _("Circle")}},
      {icon: "mv-icon mv-icon-roof", label: _("Roof Plane"), kind: "roof", args: {showDistances: false, showArea: false, closed: true, name: _("Roof Plane")}},
      {icon: "mv-icon mv-icon-perpendicular", label: _("Perpendicular distance"), kind: "perpendicular", args: {showDistances: false, showArea: false, closed: false, maxMarkers: 2, name: _("Perpendicular distance")}},
      {icon: "mv-icon mv-icon-area", label: _("Surface area"), args: {showDistances: true, showArea: true, closed: true, name: _("Area")}},
      {icon: "mv-icon mv-icon-azimuth", label: _("Azimuth"), args: {showDistances: false, showHeight: false, showArea: false, showCircle: false, showEdges: false, showAzimuth: true, closed: false, maxMarkers: 2, name: _("Azimuth")}}
    ].map((tool, i) => ({...tool, group: "tool", key: i}));
    const cell = (PALETTE_WIDTH - MARGIN * 4) / 3;
    const rows = [0, 3, 6].map((start, r) => ({title: r === 0 ? _("Measurements") : null, height: cell, items: tools.slice(start, start + 3)}));
    rows.push({title: null, height: cell, width: cell, items: [{group: "delete", key: "delete", label: _("Delete"), glyph: "fa fa-trash"}]});
    this.trayPanel = panel(rows, TRAY_POSITION, new THREE.Matrix4().makeBasis(new THREE.Vector3(0, -1, 0), new THREE.Vector3(0, 0, -1), new THREE.Vector3(1, 0, 0)));
    this.tray = this.trayPanel.group;
    for (const button of this.trayPanel.buttons){
      const span = document.createElement("i");
      span.className = button.icon || button.glyph;
      document.body.appendChild(span);
      const style = getComputedStyle(span);
      const before = getComputedStyle(span, "::before");
      const match = /url\("?(.*?)"?\)/.exec(style.maskImage || style.webkitMaskImage || "");
      if (button.glyph) button.glyph = {text: before.content.replace(/["']/g, ""), weight: before.fontWeight, family: before.fontFamily};
      span.remove();
      if (!match) continue;
      const image = new Image();
      image.onload = () => {
        button.image = image;
        button.state = "";
      };
      image.src = match[1];
    }
    this.tooltipTexture = canvasTexture(512, 80);
    this.tooltip = new THREE.Mesh(new THREE.PlaneGeometry(0.11, 0.0172), new THREE.MeshBasicMaterial({map: this.tooltipTexture, transparent: true, depthTest: false}));
    this.tooltip.renderOrder = 1003;
    this.tooltip.visible = false;
    this.tray.add(this.tooltip);

    viewer.sceneVR.add(this.headGroup, this.marker, this.line, this.pointer, this.laser, this.dragLine, this.pins, this.dots);
    viewer.addEventListener("vr_start", this.start);
    viewer.addEventListener("vr_end", () => {
      if (this.pointBudget !== null) viewer.setPointBudget(this.pointBudget);
      this.pointBudget = null;
    });
  }

  start = () => {
    const viewer = this.viewer;
    this.pointBudget = viewer.getPointBudget();
    this.measureMode = "measure";
    this.drag = null;
    this.editHand = "right";
    this.hover = null;
    this.hits = new Set();
    this.editing = new Set();
    this.deleting = false;
    viewer.setPointBudget(Math.min(this.pointBudget, 2000000));
    const view = viewer.scene.view;
    const direction = view.direction;
    this.yaw = Math.atan2(direction.y, direction.x) - Math.PI / 2;
    const box = viewer.getBoundingBox();
    const ground = this.raycast(new THREE.Vector3(view.position.x, view.position.y, Math.max(view.position.z, box.max.z) + 1), new THREE.Vector3(view.position.x, view.position.y, Math.min(view.position.z, box.min.z) - 1));
    this.position.copy(ground ? ground.point : view.position);
    this.recenter = !ground;
    this.markerPosition.copy(this.position);
    this.markerTarget.position.copy(this.position);
    this.velocity.set(0, 0, 0);
    this.scale = 1;
    this.grounded = false;
    this.updating = true;
    this.lastUpdate = performance.now();
    this.calibrate = this.mode === "walk";
    this.place = this.mode === "tabletop";
    this.updateRig();
  }

  updateRig(){
    this.rigQuaternion.setFromAxisAngle(UP, this.yaw).multiply(AXES);
    const origin = this.position.clone();
    if (this.mode === "walk") origin.addScaledVector(UP, this.eyeOffset * this.scale);
    this.rig.compose(origin, this.rigQuaternion, new THREE.Vector3(this.scale, this.scale, this.scale));
    this.rigInverse.copy(this.rig).invert();
  }

  getCamera(){
    const camera = new THREE.PerspectiveCamera();
    camera.near = 0.1;
    camera.far = 1000;
    camera.up.set(0, 0, 1);
    this.rig.decompose(camera.position, camera.quaternion, camera.scale);
    camera.updateMatrix();
    camera.updateMatrixWorld();
    camera.matrixAutoUpdate = false;
    return camera;
  }

  setScene(){
  }

  raycast(a, b, thick = 0){
    const local = new THREE.Matrix4();
    const la = new THREE.Vector3();
    const lb = new THREE.Vector3();
    let best = null;
    let bestT = Infinity;

    for (const pointcloud of this.viewer.scene.pointclouds){
      if (!pointcloud.visible || !pointcloud.root || !pointcloud.root.sceneNode) continue;
      const stack = [pointcloud.root];
      while (stack.length){
        const node = stack.pop();
        if (!node.sceneNode) continue;
        const geometryNode = node.geometryNode;
        local.copy(node.sceneNode.matrixWorld).invert();
        la.copy(a).applyMatrix4(local);
        lb.copy(b).applyMatrix4(local);
        const r = 0.5 * (geometryNode.spacing || pointcloud.pcoGeometry.spacing / Math.pow(2, node.getLevel()));
        const size = geometryNode.boundingBox.getSize(new THREE.Vector3());
        const minX = Math.min(la.x, lb.x) - r, maxX = Math.max(la.x, lb.x) + r;
        const minY = Math.min(la.y, lb.y) - r, maxY = Math.max(la.y, lb.y) + r;
        const tolerance = thick * r;
        const minZ = Math.min(la.z, lb.z) - tolerance, maxZ = Math.max(la.z, lb.z) + tolerance;
        if (maxX < 0 || maxY < 0 || maxZ < 0 || minX > size.x || minY > size.y || minZ > size.z) continue;

        for (const child of node.children) if (child && child.sceneNode) stack.push(child);

        const geometry = node.sceneNode.geometry;
        const position = geometry.attributes.position;
        if (!position) continue;
        const p = position.array;
        const gx = GRID / Math.max(size.x, 1e-9), gy = GRID / Math.max(size.y, 1e-9);
        let grid = grids.get(geometry);
        if (!grid){
          const count = p.length / 3;
          const cells = new Uint16Array(count);
          const start = new Uint32Array(GRID * GRID + 1);
          for (let i = 0; i < count; i++){
            const c = Math.min(GRID - 1, Math.max(0, Math.floor(p[i * 3 + 1] * gy))) * GRID + Math.min(GRID - 1, Math.max(0, Math.floor(p[i * 3] * gx)));
            cells[i] = c;
            start[c + 1]++;
          }
          for (let c = 0; c < GRID * GRID; c++) start[c + 1] += start[c];
          const cursor = start.slice(0, GRID * GRID);
          const order = new Uint32Array(count);
          for (let i = 0; i < count; i++) order[cursor[cells[i]]++] = i * 3;
          grid = {start, order};
          grids.set(geometry, grid);
        }
        const {start, order} = grid;
        const cellX = v => Math.min(GRID - 1, Math.max(0, Math.floor(v * gx)));
        const cellY = v => Math.min(GRID - 1, Math.max(0, Math.floor(v * gy)));

        const dx = lb.x - la.x, dy = lb.y - la.y, dz = lb.z - la.z;
        const flat = dx * dx + dy * dy;
        const r2 = r * r;
        let found = -1;
        let foundT = bestT;
        for (let j = cellY(minY); j <= cellY(maxY); j++){
          for (let k = cellX(minX); k <= cellX(maxX); k++){
            for (let o = start[j * GRID + k], end = start[j * GRID + k + 1]; o < end; o++){
              const i = order[o];
              const x = p[i], y = p[i + 1], z = p[i + 2];
              if (x < minX || x > maxX || y < minY || y > maxY || z < minZ || z > maxZ) continue;
              let t0 = 0, t1 = 1;
              if (flat > 1e-12){
                const tc = ((x - la.x) * dx + (y - la.y) * dy) / flat;
                const ex = x - la.x - dx * tc, ey = y - la.y - dy * tc;
                const d2 = ex * ex + ey * ey;
                if (d2 > r2) continue;
                const half = Math.sqrt((r2 - d2) / flat);
                t0 = Math.max(0, tc - half);
                t1 = Math.min(1, tc + half);
                if (t0 > t1) continue;
              }else if ((x - la.x) * (x - la.x) + (y - la.y) * (y - la.y) > r2) continue;
              if (la.z + dz * t0 + tolerance < z || la.z + dz * t1 - tolerance > z) continue;
              const t = dz < 0 ? Math.min(t1, Math.max(t0, (la.z - z) / -dz)) : t0;
              if (t < foundT){
                found = i;
                foundT = t;
              }
            }
          }
        }
        if (found === -1) continue;

        const cx = p[found], cy = p[found + 1], cz = p[found + 2];
        const reach = 9 * r2;
        let n = 0, sx = 0, sy = 0, sz = 0, sxx = 0, sxy = 0, syy = 0, sxz = 0, syz = 0;
        for (let j = cellY(cy - 3 * r); j <= cellY(cy + 3 * r); j++){
          for (let k = cellX(cx - 3 * r); k <= cellX(cx + 3 * r); k++){
            for (let o = start[j * GRID + k], end = start[j * GRID + k + 1]; o < end; o++){
              const i = order[o];
              const x = p[i] - cx, y = p[i + 1] - cy, z = p[i + 2] - cz;
              if (x * x + y * y + z * z > reach) continue;
              n++; sx += x; sy += y; sz += z; sxx += x * x; sxy += x * y; syy += y * y; sxz += x * z; syz += y * z;
            }
          }
        }
        const normal = new THREE.Vector3();
        if (n >= 3){
          const xx = sxx - sx * sx / n, xy = sxy - sx * sy / n, yy = syy - sy * sy / n;
          const xz = sxz - sx * sz / n, yz = syz - sy * sz / n;
          const det = xx * yy - xy * xy;
          if (Math.abs(det) > 1e-12 * (xx + yy) * (xx + yy)){
            normal.set(-(xz * yy - yz * xy) / det, -(yz * xx - xz * xy) / det, 1).transformDirection(node.sceneNode.matrixWorld);
          }
        }
        bestT = foundT;
        best = {point: new THREE.Vector3(la.x + dx * foundT, la.y + dy * foundT, cz).applyMatrix4(node.sceneNode.matrixWorld), normal, t: foundT};
      }
    }
    return best;
  }

  update(delta){
    const viewer = this.viewer;
    const xr = viewer.renderer.xr;
    if (!xr.isPresenting) return;
    delta = Math.min(delta, 0.1);
    const left = this.hands.left;
    const right = this.hands.right;
    const pad = hand => hand && hand.source.gamepad;
    const stick = (gamepad) => {
      if (!gamepad) return {x: 0, y: 0};
      const axes = gamepad.axes;
      return axes.length >= 4 ? {x: axes[2], y: axes[3]} : {x: axes[0] || 0, y: axes[1] || 0};
    };
    const pressed = (gamepad, i) => !!(gamepad && gamepad.buttons[i] && gamepad.buttons[i].pressed);
    const move = stick(pad(left));
    const turn = stick(pad(right));
    const jump = pressed(pad(right), 4);
    const toggle = pressed(pad(right), 5);
    const undo = pressed(pad(left), 5), redo = pressed(pad(left), 4);
    const creating = !!this.drag && !!this.drag.creating;
    const busy = creating || this.deleting;
    if (busy && ((undo && !this.previous.undo) || (redo && !this.previous.redo) || (toggle && !this.previous.toggle) || (jump && !this.previous.jump))){
      if (creating){
        const measurement = this.drag.measurement;
        if (measurement.maxMarkers > 3) measurement.removeMarker(measurement.points.length - 1);
        if (!measurement.points.length) viewer.scene.removeMeasurement(measurement);
        this.drag = null;
      }
      this.deleting = false;
    }
    if (!busy && undo && !this.previous.undo) this.undo();
    if (!busy && redo && !this.previous.redo) this.redo();
    this.previous.undo = undo;
    this.previous.redo = redo;
    if (!busy && toggle && !this.previous.toggle) this.measureMode = this.measureMode === "measure" ? "off" : "measure";
    this.previous.toggle = toggle;
    const trigger = pressed(pad(right), 0);
    const pinching = this.mode === "tabletop" && !!left && !!right &&(trigger || pressed(pad(right), 1)) && (pressed(pad(left), 0) || pressed(pad(left), 1));
    const teleportAxis = Math.hypot(turn.x, turn.y) >= THRESHOLD && Math.abs(turn.y) >= Math.abs(turn.x);

    const head = xr.getCamera(new THREE.PerspectiveCamera());
    const headPosition = new THREE.Vector3();
    const headQuaternion = new THREE.Quaternion();
    head.matrixWorld.decompose(headPosition, headQuaternion, new THREE.Vector3());
    this.headGroup.position.copy(headPosition);
    this.headGroup.quaternion.copy(headQuaternion);

    const loading = this.getLoading();
    const fadeTarget = loading ? 0.9 : 0;
    const fade = this.cover.material.opacity + Math.max(-delta * 2, Math.min(delta * 2, fadeTarget - this.cover.material.opacity));
    this.cover.material.opacity = fade;
    this.loadingPanel.material.opacity = fade / 0.9;
    this.cover.visible = this.loadingPanel.visible = fade > 0.001;
    if (loading){
      const spin = !isFinite(loading.progress) || loading.progress === null;
      const state = `${loading.message}|${loading.progress}`;
      if (spin || state !== this.loadingState){
        this.loadingState = state;
        const canvas = this.loadingTexture.image;
        const c = canvas.getContext("2d");
        c.clearRect(0, 0, canvas.width, canvas.height);
        c.fillStyle = "rgba(255, 255, 255, 0.3)";
        if (spin){
          c.strokeStyle = "#ffffff";
          c.lineWidth = 8;
          c.beginPath();
          const angle = performance.now() / 150;
          c.arc(384, 90, 30, angle, angle + Math.PI * 1.5);
          c.stroke();
        }else{
          c.beginPath();
          c.roundRect(184, 86, 400, 8, 4);
          c.fill();
          c.fillStyle = "#ffffff";
          c.beginPath();
          c.roundRect(184, 86, 400 * Math.min(100, Math.max(0, loading.progress)) / 100, 8, 4);
          c.fill();
        }
        c.fillStyle = "#ffffff";
        c.font = "36px sans-serif";
        c.textAlign = "center";
        c.textBaseline = "middle";
        c.fillText(loading.message, 384, 170);
        this.loadingTexture.needsUpdate = true;
      }
    }

    if (this.calibrate){
      this.calibrate = false;
      this.eyeOffset = EYE_HEIGHT - headPosition.y;
      this.updateRig();
    }

    const now = performance.now();
    if (this.recenter && now >= this.recenterRetry){
      if (!this.recenterStart) this.recenterStart = now;
      const box = viewer.getBoundingBox();
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      let ground = null;
      for (let ring = 0; ring <= 4 && !ground; ring++){
        const steps = ring === 0 ? 1 : 8 * ring;
        for (let k = 0; k < steps && !ground; k++){
          const angle = k / steps * Math.PI * 2, distance = ring * 0.05 * Math.min(size.x, size.y);
          const x = center.x + Math.cos(angle) * distance, y = center.y + Math.sin(angle) * distance;
          ground = this.raycast(new THREE.Vector3(x, y, box.max.z + 1), new THREE.Vector3(x, y, box.min.z - 1));
        }
      }
      if (ground || !this.recenterRetry){
        this.position.copy(ground ? ground.point : new THREE.Vector3(center.x, center.y, box.min.z));
        this.velocity.set(0, 0, 0);
        this.grounded = false;
        this.updating = true;
        this.lastUpdate = now;
        this.updateRig();
      }
      this.recenterRetry = now + 500;
      if (ground || now - this.recenterStart > 5000){
        this.recenter = false;
        this.recenterStart = 0;
        this.recenterRetry = 0;
      }
    }

    if (this.place){
      this.place = false;
      const box = viewer.getBoundingBox();
      const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 1e-3);
      this.scale = radius / TABLE_RADIUS;
      const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(headQuaternion);
      forward.y = 0;
      if (forward.lengthSq() < 1e-6) forward.set(0, 0, -1);
      forward.normalize();
      const table = headPosition.clone().addScaledVector(forward, 0.2 + TABLE_RADIUS);
      table.y -= 0.5;
      this.position.set(0, 0, 0);
      this.updateRig();
      this.position.copy(box.getCenter(new THREE.Vector3())).sub(table.applyMatrix4(this.rig));
      this.velocity.set(0, 0, 0);
      this.updateRig();
    }

    if (pinching){
      const a = left.ray.position, b = right.ray.position;
      const middle = a.clone().add(b).multiplyScalar(0.5);
      const angle = Math.atan2(a.z - b.z, b.x - a.x);
      const distance = Math.max(a.distanceTo(b), 1e-3);
      if (!this.pinch){
        this.pinch = {anchor: middle.clone().applyMatrix4(this.rig), angle, distance, yaw: this.yaw, scale: this.scale};
        this.velocity.set(0, 0, 0);
      }
      this.yaw = this.pinch.yaw - (angle - this.pinch.angle);
      this.scale = this.pinch.scale * this.pinch.distance / distance;
      this.position.set(0, 0, 0);
      this.updateRig();
      this.position.copy(this.pinch.anchor).sub(middle.clone().applyMatrix4(this.rig));
      this.updateRig();
    }else this.pinch = null;

    const gripLeft = pressed(pad(left), 1), gripRight = pressed(pad(right), 1);
    const grabHand = !pinching && this.mode === "tabletop" && gripLeft !== gripRight ? (gripLeft ? left : right) : null;
    if (grabHand){
      const at = grabHand.ray.position;
      if (!this.grab || this.grab.hand !== grabHand) this.grab = {hand: grabHand, anchor: at.clone().applyMatrix4(this.rig)};
      this.position.set(0, 0, 0);
      this.updateRig();
      this.position.copy(this.grab.anchor).sub(at.clone().applyMatrix4(this.rig));
      this.updateRig();
    }else this.grab = null;
    const tabletop = this.mode === "tabletop";
    const s = this.scale;

    let pointerBusy = false;
    let hover = null;
    let rayHover = null;
    let rayPress = null;
    const palm = left && new THREE.Vector3(1, 0, 0).applyQuaternion(left.ray.quaternion);
    const panelFacing = [
      left && WATCH_FACE.clone().applyQuaternion(left.ray.quaternion).dot(headPosition.clone().sub(WATCH_POSITION.clone().applyMatrix4(left.ray.matrix)).normalize()),
      left && Math.max(palm.y, palm.dot(headPosition.clone().sub(TRAY_POSITION.clone().applyMatrix4(left.ray.matrix)).normalize()))
    ];
    this.pointer.visible = false;
    let pointerT = Infinity;
    this.panels.forEach((panel, i) => {
      if (!left) panel.visible = false;
      else if (!panel.visible && panelFacing[i] > 0.7) panel.visible = true;
      else if (panel.visible && panelFacing[i] < 0.5 && !panel.buttons.some(b => b.engaged)) panel.visible = false;
      panel.group.visible = panel.visible;
      panel.tip = null;
      if (!panel.visible || !right) return;
      const toPanel = left.ray.matrix.clone().multiply(panel.group.matrix).invert();
      panel.tip = right.ray.position.clone().applyMatrix4(toPanel);
      const direction = new THREE.Vector3(0, 0, -1).applyQuaternion(right.ray.quaternion).transformDirection(toPanel);
      const t = direction.z < 0 ? (EXTRUDE - panel.tip.z) / direction.z : -1;
      const at = panel.tip.clone().addScaledVector(direction, t);
      if (t > 0 && t < 1 && t < pointerT && Math.abs(at.x) <= PALETTE_WIDTH / 2 && Math.abs(at.y) <= panel.height / 2){
        pointerT = t;
        pointerBusy = true;
        const button = panel.buttons.find(b => Math.abs(at.x - b.x) <= b.w / 2 && Math.abs(at.y - b.y) <= b.h / 2);
        hover = rayHover = button || null;
        rayPress = button && trigger && !pinching ? button : null;
        this.pointer.position.copy(right.ray.position);
        this.pointer.quaternion.copy(right.ray.quaternion);
        this.pointer.scale.set(1, 1, t);
        this.pointer.visible = true;
      }
    });

    const leftTrigger = pressed(pad(left), 0);
    const leftEdge = leftTrigger && !this.previous.leftTrigger, rightEdge = trigger && !this.previous.trigger && !pointerBusy;
    this.previous.leftTrigger = leftTrigger;
    this.previous.trigger = trigger;
    const measuring = this.measureMode === "measure";
    if (!this.drag && (leftEdge || rightEdge)) this.editHand = leftEdge ? "left" : "right";
    const editHand = this.hands[this.editHand];
    const laserHand = measuring && !pinching && editHand && !(editHand === right && pointerBusy) ? editHand : null;
    const holding = !!laserHand && (laserHand === left ? leftTrigger : trigger);
    const edge = !!laserHand && (laserHand === left ? leftEdge : rightEdge);
    const buzz = hand => {
      const haptic = pad(hand) && pad(hand).hapticActuators && pad(hand).hapticActuators[0];
      if (haptic) haptic.pulse(0.15, 25);
    };
    const measurements = [...viewer.scene.measurements, ...viewer.scene.profiles];
    for (const measurement of this.editing) if (!measuring || !measurement.visible || !measurements.includes(measurement)) this.editing.delete(measurement);
    if (this.drag && this.drag.creating && !this.editing.has(this.drag.measurement)) this.drag = null;
    if (this.drag && !this.drag.creating && (this.drag.hand !== laserHand || !holding || !this.editing.has(this.drag.measurement))){
      this.drag.measurement.dispatchEvent({type: "marker_dropped", [this.drag.measurement instanceof Potree.Profile ? "profile" : "measurement"]: this.drag.measurement, index: this.drag.index});
      buzz(this.drag.hand);
      this.drag = null;
    }
    let nearest = 200 * s;
    const origin = laserHand && laserHand.ray.position.clone().applyMatrix4(this.rig);
    const direction = laserHand && new THREE.Vector3(0, 0, -1).applyQuaternion(laserHand.ray.quaternion).applyQuaternion(this.rigQuaternion);
    const forward = laserHand && new THREE.Vector3(0, 0, -1).applyQuaternion(laserHand.ray.quaternion);
    if (this.drag && laserHand){
      let ray = null;
      if (this.drag.creating) ray = direction;
      else{
        const turn = Math.atan2(-forward.x, -forward.z) - this.drag.handYaw;
        const yaw = this.drag.yaw + Math.atan2(Math.sin(turn), Math.cos(turn));
        const pitch = Math.max(-1.55, Math.min(1.55, this.drag.pitch + (tabletop ? 2 : 1) * (Math.asin(forward.y) - this.drag.handPitch)));
        if (Math.abs(pitch - this.drag.pitch) + Math.abs(yaw - this.drag.yaw) > 0.003) this.drag.moved = true;
        if (this.drag.moved) ray = new THREE.Vector3(-Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch)).applyQuaternion(this.rigQuaternion);
      }
      if (ray){
        let hit = null;
        for (const thick of [0, 0.25]) for (let i = 0; i < 100 && !hit; i++) hit = this.raycast(origin.clone().addScaledVector(ray, i * 2 * s), origin.clone().addScaledVector(ray, (i + 1) * 2 * s), thick);
        const point = this.drag.measurement.points[this.drag.index];
        const level = (point.position || point).z;
        if (hit) this.drag.measurement.setPosition(this.drag.index, hit.point);
        else if (ray.z < 0 && (level - origin.z) / ray.z > 0) this.drag.measurement.setPosition(this.drag.index, origin.clone().addScaledVector(ray, (level - origin.z) / ray.z));
      }
    }

    const hits = new Set();
    let first = null;
    if (laserHand && !this.drag){
      for (const measurement of measurements){
        if (!measurement.visible) continue;
        const points = measurement.points.map(p => p.position || p);
        if (!points.length) continue;
        const edges = Math.max(1, measurement.closed && points.length > 2 ? points.length : points.length - 1);
        for (let i = 0; i < edges; i++){
          const a = points[i].clone().sub(origin);
          const u = points[(i + 1) % points.length].clone().sub(points[i]);
          const uu = u.dot(u), ud = u.dot(direction), denominator = uu - ud * ud;
          const k = denominator > 1e-12 ? Math.min(1, Math.max(0, (ud * a.dot(direction) - a.dot(u)) / denominator)) : 0;
          const closest = a.addScaledVector(u, k);
          const t = Math.max(0, closest.dot(direction));
          if (closest.distanceTo(direction.clone().multiplyScalar(t)) < Math.max(0.03 * s, t * 0.026)){
            hits.add(measurement);
            if (t < nearest) first = measurement;
            nearest = Math.min(nearest, t);
          }
        }
      }
    }

    let pins = 0;
    let pinHover = null;
    let pinNearest = Infinity;
    let highlight = null;
    const rayDirection = laserHand && new THREE.Vector3(0, 0, -1).applyQuaternion(laserHand.ray.quaternion);
    const h = (tabletop ? 5 : 1) / s, w = (tabletop ? 1.875 : 0.3) / s;
    for (const measurement of this.editing){
      measurement.points.forEach((point, index) => {
        if (pins === this.pins.children.length) this.pins.add(new THREE.Mesh(this.pinGeometry, this.pinMaterial));
        const pin = this.pins.children[pins++];
        const tip = (point.position || point).clone().applyMatrix4(this.rigInverse);
        pin.position.copy(tip);
        pin.scale.set(w, h, w);
        pin.visible = true;
        pin.material = this.pinMaterial;
        if (this.drag && this.drag.measurement === measurement && this.drag.index === index) highlight = pin;
        if (laserHand && !this.drag){
          const a = tip.clone().sub(laserHand.ray.position);
          const ud = h * rayDirection.y, denominator = h * h - ud * ud;
          const k = denominator > 1e-12 ? Math.min(1, Math.max(0, (ud * a.dot(rayDirection) - h * a.y) / denominator)) : 0;
          a.y += h * k;
          const t = a.dot(rayDirection);
          if (t > 0 && t < pinNearest && a.distanceTo(rayDirection.clone().multiplyScalar(t)) < w / 2 + 0.01){
            pinNearest = t;
            pinHover = {hand: laserHand, measurement, index};
            highlight = pin;
          }
        }
      });
    }
    for (let i = pins; i < this.pins.children.length; i++) this.pins.children[i].visible = false;
    let dots = 0;
    if (measuring){
      for (const measurement of viewer.scene.measurements){
        if (!measurement.visible || !measurement.showCoordinates || measurement.points.length !== 1) continue;
        if (dots === this.dots.children.length) this.dots.add(new THREE.Mesh(this.dotGeometry, this.pinHoverMaterial));
        const dot = this.dots.children[dots++];
        dot.position.copy(measurement.points[0].position).applyMatrix4(this.rigInverse);
        dot.scale.setScalar(w);
        dot.visible = true;
      }
    }
    for (let i = dots; i < this.dots.children.length; i++) this.dots.children[i].visible = false;
    if (highlight) highlight.material = this.pinHoverMaterial;
    if (pinHover) nearest = Math.min(nearest, pinNearest * s);

    if ((pinHover && (!this.hover || this.hover.measurement !== pinHover.measurement || this.hover.index !== pinHover.index)) || [...hits].some(m => !this.hits.has(m))) buzz(laserHand);
    this.hover = pinHover;
    this.hits = hits;
    if (edge && this.drag && this.drag.creating){
      const measurement = this.drag.measurement;
      if (measurement.points.length >= measurement.maxMarkers) this.drag = null;
      else{
        measurement.addMarker(measurement.points[measurement.points.length - 1].position.clone());
        this.drag.index = measurement.points.length - 1;
      }
      buzz(laserHand);
    }else if (edge && this.deleting){
      if (first){
        if (first instanceof Potree.Profile) viewer.scene.removeProfile(first);
        else viewer.scene.removeMeasurement(first);
        this.editing.delete(first);
        hits.delete(first);
        buzz(laserHand);
      }
    }else if (edge){
      if (pinHover){
        const point = pinHover.measurement.points[pinHover.index];
        const aim = (point.position || point).clone().applyMatrix4(this.rigInverse).sub(laserHand.ray.position).normalize();
        this.drag = {...pinHover, pitch: Math.asin(aim.y), yaw: Math.atan2(-aim.x, -aim.z), handPitch: Math.asin(forward.y), handYaw: Math.atan2(-forward.x, -forward.z), moved: false};
        this.hover = null;
      }else this.editing = new Set(hits);
    }

    this.labeled = new Set(hits);
    if (this.drag) this.labeled.add(this.drag.measurement);
    this.laser.visible = !!laserHand && !this.drag;
    this.dragLine.visible = !!this.drag;
    if (this.drag){
      const point = this.drag.measurement.points[this.drag.index];
      const positions = this.dragLine.geometry.attributes.position;
      positions.setXYZ(0, this.drag.hand.ray.position.x, this.drag.hand.ray.position.y, this.drag.hand.ray.position.z);
      const tip = (point.position || point).clone().applyMatrix4(this.rigInverse);
      positions.setXYZ(1, tip.x, tip.y, tip.z);
      positions.needsUpdate = true;
    }
    if (this.laser.visible){
      this.laser.position.copy(laserHand.ray.position);
      this.laser.quaternion.copy(laserHand.ray.quaternion);
      this.laser.scale.set(1, 1, nearest / s);
    }

    let activated = null;
    let touched = null;
    let closest = Infinity;
    for (const button of this.buttons){
      const tip = button.panel.tip;
      if (!tip) continue;
      const d = Math.hypot(Math.max(0, Math.abs(tip.x - button.x) - button.w / 2), Math.max(0, Math.abs(tip.y - button.y) - button.h / 2));
      if (d <= HIT_MARGIN && d < closest){
        closest = d;
        touched = button;
      }
    }
    const top = EXTRUDE + POKE_RADIUS;
    for (const button of this.buttons){
      const tip = button.panel.tip;
      const toggled = button.group === "delete" && this.deleting;
      const rest = toggled ? EXTRUDE * 2 / 3 : 0, depth = toggled ? EXTRUDE * 0.95 : TRAVEL;
      if (button === touched && button.panel.lastTipZ > top - 0.002 && tip.z < top + 0.04) button.engaged = true;
      if (button !== touched || tip.z < -0.04 || tip.z > top + 0.04) button.engaged = false;
      if (button.engaged){
        button.press = Math.min(depth, Math.max(rest, top - tip.z));
        hover = button;
      }else{
        const target = rayPress === button ? depth : rest;
        button.press = target > button.press ? Math.min(target, button.press + delta * 0.15) : Math.max(target, button.press - delta * 0.15);
      }
      if (button.press >= rest + (depth - rest) * 0.9 && button.armed){
        button.armed = false;
        activated = button;
        buzz(right);
      }else if (button.press < rest + (depth - rest) * 0.3) button.armed = true;
      button.mesh.scale.z = (EXTRUDE - button.press) / EXTRUDE;
    }
    for (const panel of this.panels) panel.lastTipZ = panel.tip ? panel.tip.z : 1;

    if (activated && (activated.group === "tool" || activated.group === "delete") && this.drag && this.drag.creating){
      const measurement = this.drag.measurement;
      if (measurement.maxMarkers > 3) measurement.removeMarker(measurement.points.length - 1);
      if (!measurement.points.length) viewer.scene.removeMeasurement(measurement);
      this.drag = null;
    }
    if (activated && activated.group === "delete"){
      this.deleting = !this.deleting;
      this.measureMode = "measure";
    }else if (activated && activated.group === "tool"){
      this.deleting = false;
      const args = activated.args;
      const measurement = new Potree.Measure();
      measurement.showDistances = args.showDistances === null ? true : args.showDistances;
      measurement.showArea = !!args.showArea;
      measurement.showAngles = !!args.showAngles;
      measurement.showCoordinates = !!args.showCoordinates;
      measurement.showHeight = !!args.showHeight;
      measurement.showCircle = !!args.showCircle;
      measurement.showAzimuth = !!args.showAzimuth;
      measurement.showEdges = args.showEdges !== false;
      measurement.closed = !!args.closed;
      measurement.maxMarkers = args.maxMarkers || Infinity;
      measurement.name = args.name;
      if (activated.kind) measurement.kind = activated.kind;
      if (activated.kind === "roof") measurement.open = true;
      measurement.addMarker(this.position.clone());
      viewer.scene.addMeasurement(measurement);
      this.measureMode = "measure";
      this.editing.add(measurement);
      this.drag = {hand: this.hands[this.editHand] || right, measurement, index: 0, creating: activated};
    }else if (activated && activated.group === "model"){
      this.setModelType(activated.key);
    }else if (activated && activated.group === "units"){
      setUnitSystem(activated.key);
    }else if (activated && activated.group === "mode" && activated.key !== this.mode){
      this.mode = activated.key;
      this.scale = 1;
      this.velocity.set(0, 0, 0);
      this.grounded = false;
      this.updating = true;
      this.lastUpdate = performance.now();
      if (this.mode === "walk") this.calibrate = this.recenter = true;
      else this.place = true;
      this.updateRig();
    }

    const modelType = this.getModelType();
    const units = getUnitSystem();
    for (const button of this.buttons){
      const active = button.group === "tool" ? !!this.drag && this.drag.creating === button : button.group === "delete" ? this.deleting : button.group === "mode" ? button.key === this.mode : button.group === "units" ? button.key === units : button.key === modelType;
      const state = `${active}|${button === hover}`;
      if (state === button.state) continue;
      button.state = state;
      const canvas = button.texture.image;
      const c = canvas.getContext("2d");
      c.fillStyle = button.group === "delete" ? (active ? "#e74c3c" : "#922b21") : active ? "#3498db" : "#555555";
      c.fillRect(0, 0, canvas.width, canvas.height);
      if (button === hover){
        c.strokeStyle = "#ffffff";
        c.lineWidth = 10;
        c.strokeRect(5, 5, canvas.width - 10, canvas.height - 10);
      }
      if (button.icon){
        if (button.image){
          const size = Math.round(Math.min(canvas.width, canvas.height) * 0.6);
          const icon = document.createElement("canvas");
          icon.width = icon.height = size;
          const ic = icon.getContext("2d");
          ic.drawImage(button.image, 0, 0, size, size);
          ic.globalCompositeOperation = "source-in";
          ic.fillStyle = "#ffffff";
          ic.fillRect(0, 0, size, size);
          c.drawImage(icon, (canvas.width - size) / 2, (canvas.height - size) / 2);
        }
      }else if (button.glyph){
        c.font = `${button.glyph.weight} ${Math.round(canvas.height * 0.5)}px ${button.glyph.family}`;
        c.fillStyle = "#ffffff";
        c.textAlign = "center";
        c.textBaseline = "middle";
        c.fillText(button.glyph.text, canvas.width / 2, canvas.height / 2);
      }else{
        let size = Math.round(canvas.height * 0.4);
        c.font = `bold ${size}px sans-serif`;
        while (size > 12 && c.measureText(button.label).width > canvas.width - 24){
          size -= 2;
          c.font = `bold ${size}px sans-serif`;
        }
        c.fillStyle = "#ffffff";
        c.textAlign = "center";
        c.textBaseline = "middle";
        c.fillText(button.label, canvas.width / 2, canvas.height / 2);
      }
      button.texture.needsUpdate = true;
    }

    const tooltip = rayHover && rayHover.panel === this.trayPanel ? rayHover : null;
    this.tooltip.visible = !!tooltip;
    if (tooltip && tooltip !== this.tooltipButton){
      const c = this.tooltipTexture.image.getContext("2d");
      c.clearRect(0, 0, 512, 80);
      c.font = "bold 40px sans-serif";
      const width = Math.min(512, c.measureText(tooltip.label).width + 40);
      c.fillStyle = "rgba(0, 0, 0, 0.8)";
      c.beginPath();
      c.roundRect((512 - width) / 2, 0, width, 80, 16);
      c.fill();
      c.fillStyle = "#ffffff";
      c.textAlign = "center";
      c.textBaseline = "middle";
      c.fillText(tooltip.label, 256, 42);
      this.tooltipTexture.needsUpdate = true;
      this.tooltip.position.set(tooltip.x, tooltip.y + tooltip.h / 2 + 0.012, EXTRUDE + 0.006);
    }
    this.tooltipButton = tooltip;

    const date = new Date();
    const time = `${date.getHours()}:${String(date.getMinutes()).padStart(2, "0")}`;
    if (time !== this.clockTime){
      this.clockTime = time;
      const c = this.clockTexture.image.getContext("2d");
      c.fillStyle = "#111111";
      c.fillRect(0, 0, 256, 256);
      c.strokeStyle = "#888888";
      for (let i = 0; i < 12; i++){
        const a = i / 12 * Math.PI * 2;
        c.lineWidth = i % 3 === 0 ? 8 : 4;
        c.beginPath();
        c.moveTo(128 + Math.sin(a) * 104, 128 - Math.cos(a) * 104);
        c.lineTo(128 + Math.sin(a) * (i % 3 === 0 ? 86 : 94), 128 - Math.cos(a) * (i % 3 === 0 ? 86 : 94));
        c.stroke();
      }
      c.fillStyle = "#ffffff";
      c.font = "bold 64px sans-serif";
      c.textAlign = "center";
      c.textBaseline = "middle";
      c.fillText(time, 128, 122);
      c.strokeStyle = "#666666";
      c.lineWidth = 3;
      c.strokeRect(106, 166, 44, 30);
      c.font = "bold 22px sans-serif";
      c.fillText(String(date.getDate()), 128, 182);
      this.clockTexture.needsUpdate = true;
    }

    if (turn.x <= -THRESHOLD && this.previous.turn > -THRESHOLD) this.yaw += SNAP_ANGLE;
    else if (turn.x >= THRESHOLD && this.previous.turn < THRESHOLD) this.yaw -= SNAP_ANGLE;
    this.updateRig();

    const teleportActive = !tabletop && !pointerBusy && !pinching && teleportAxis && !!right;
    const targetValid = !!this.hit && this.hit.normal.z > 0.7;
    if (teleportActive){
      if (!this.previous.teleport){
        this.line.visible = true;
        this.marker.visible = true;
      }
      const origin = right.ray.position.clone().applyMatrix4(this.rig);
      const direction = new THREE.Vector3(0, 0, 1).applyQuaternion(right.ray.quaternion).applyQuaternion(this.rigQuaternion).multiplyScalar(s);
      sampleParabola(origin, direction, this.position.z - MAX_DROP * s, RAY_GRAVITY * s, this.rayPoints, 0);
      this.hit = null;
      for (let i = 0; i < this.rayPoints.length - 1 && !this.hit; i++) this.hit = this.raycast(this.rayPoints[i], this.rayPoints[i + 1]);
      sampleParabola(origin, direction, this.hit ? this.hit.point.z : this.position.z - MAX_DROP * s, RAY_GRAVITY * s, this.linePoints, 1);

      if (this.hit){
        this.markerTarget.position.copy(this.hit.point);
        this.markerTarget.lookAt(this.hit.point.clone().add(this.hit.normal));
      }
      this.markerPosition.lerp(this.markerTarget.position, 0.2);
      this.markerQuaternion.slerp(this.markerTarget.quaternion, 0.2);
      this.marker.material.color.lerp(new THREE.Color(targetValid ? 0xffffff : 0xed4337), 0.2);
      this.marker.scale.lerp(targetValid ? new THREE.Vector3(1, 1, 1) : new THREE.Vector3(0.5, 0.5, 0.5), 0.2);

      const points = this.linePoints.map(p => p.clone().applyMatrix4(this.rigInverse));
      const start = points[0];
      const end = points[points.length - 1];
      const positions = this.line.geometry.attributes.position.array;
      const alphas = this.line.geometry.attributes.alpha.array;
      for (let i = 0; i < points.length; i++){
        const tangent = points[Math.min(i + 1, points.length - 1)].clone().sub(points[Math.max(i - 1, 0)]);
        const side = tangent.cross(headPosition.clone().sub(points[i])).normalize().multiplyScalar(0.005);
        points[i].clone().add(side).toArray(positions, i * 6);
        points[i].clone().sub(side).toArray(positions, i * 6 + 3);
        alphas[i * 2] = alphas[i * 2 + 1] = Math.min(THREE.MathUtils.smoothstep(points[i].distanceTo(start), 0, 0.8), THREE.MathUtils.smoothstep(points[i].distanceTo(end), 0.5, 2.0));
      }
      this.line.geometry.attributes.position.needsUpdate = true;
      this.line.geometry.attributes.alpha.needsUpdate = true;
    }else if (this.previous.teleport){
      if (targetValid && !teleportAxis && !pinching){
        this.position.copy(this.hit.point);
        this.velocity.set(0, 0, 0);
        this.jumping = false;
        this.grounded = false;
        this.updating = true;
        this.lastUpdate = performance.now();
      }
      this.line.visible = false;
      this.marker.visible = false;
    }

    if (!busy && !tabletop && jump && !this.previous.jump && this.grounded && performance.now() / 1000 - this.lastJump > JUMP_COOLDOWN){
      this.velocity.z = Math.sqrt(2 * GRAVITY * s * JUMP_HEIGHT * s);
      this.grounded = false;
      this.jumping = true;
      this.lastJump = performance.now() / 1000;
      this.updating = true;
      this.lastUpdate = performance.now();
    }

    let vignetteTarget = 0;
    const input = pinching ? 0 : Math.min(Math.hypot(move.x, move.y), 1);
    if (input > 0){
      this.movement.set(move.x, 0, move.y).applyQuaternion(headQuaternion);
      this.movement.y = 0;
      this.movement.normalize().multiplyScalar(input * SLIDE_SPEED * s * (this.mode === "tabletop" ? 0.2 : 1)).applyQuaternion(this.rigQuaternion);
      this.updating = true;
      this.lastUpdate = performance.now();
      vignetteTarget = input * COMFORT_ASSIST;
    }else this.movement.set(0, 0, 0);
    this.vignette.material.uniforms.uAlpha.value = THREE.MathUtils.lerp(this.vignette.material.uniforms.uAlpha.value, vignetteTarget, delta * 10);

    if (this.updating && !pinching){
      if ((tabletop || this.grounded) && performance.now() - this.lastUpdate > SLEEP){
        this.updating = false;
        if (tabletop) this.velocity.set(0, 0, 0);
      }else{
        const grounded = tabletop || this.grounded;
        const planar = new THREE.Vector3(this.velocity.x, this.velocity.y, 0);
        if (this.movement.lengthSq() > 0){
          this.velocity.add(this.movement.clone().sub(planar).clampLength(0, ACCELERATION * s * (grounded ? 1 : AIR_CONTROL) * delta));
        }else{
          this.velocity.sub(planar.clampLength(0, DECELERATION * s * (grounded ? 1 : 0.7) * delta));
        }

        if (tabletop){
          this.velocity.z = 0;
        }else{
          if (!this.grounded) this.velocity.z -= GRAVITY * s * delta;
          const reach = (FLOAT_HEIGHT + RADIUS + 0.15) * s;
          const top = this.position.clone().addScaledVector(UP, RADIUS * s);
          const ground = this.raycast(top, top.clone().addScaledVector(UP, -reach));
          const ascending = this.jumping && this.velocity.z > 0;
          this.grounded = !ascending && !!ground && ground.normal.z > MAX_SLOPE;
          if (this.jumping && !ascending) this.jumping = false;
          if (this.grounded){
            const distance = ground.t * reach;
            const force = Math.max(-MAX_FORCE * s, Math.min(MAX_FORCE * s, SPRING * ((FLOAT_HEIGHT + RADIUS) * s - distance) - DAMPING * this.velocity.z));
            this.velocity.z += force * delta;
                  }
        }

        this.velocity.clampLength(0, MAX_VELOCITY * s);
        this.position.addScaledVector(this.velocity, delta);

        const floor = viewer.getBoundingBox().min.z;
        if (!tabletop && this.position.z < floor){
          this.position.z = floor;
          this.velocity.z = Math.max(0, this.velocity.z);
          this.grounded = true;
        }
      }
      this.updateRig();
    }

    if (this.marker.visible){
      this.marker.position.copy(this.markerPosition).applyMatrix4(this.rigInverse);
      this.marker.quaternion.copy(this.rigQuaternion).invert().multiply(this.markerQuaternion);
    }

    const scenePosition = headPosition.clone().applyMatrix4(this.rig);
    const sceneTarget = new THREE.Vector3(0, 0, -1).applyQuaternion(headQuaternion).multiplyScalar(s).applyQuaternion(this.rigQuaternion).add(scenePosition);
    viewer.scene.view.setView(scenePosition, sceneTarget);

    this.previous.turn = turn.x;
    this.previous.teleport = teleportActive;
    this.previous.jump = jump;
  }
}

export default VRControls;
