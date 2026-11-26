import * as THREE from 'THREE';

const material = new THREE.ShaderMaterial({
  uniforms: {
    height: {value: 1}
  },
  vertexShader: `
    attribute float size;
    attribute float alpha;
    uniform float height;
    varying float vAlpha;
    void main() {
      vAlpha = alpha;
      vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
      gl_Position = projectionMatrix * mvPosition;
      gl_PointSize = size * length(modelViewMatrix[0].xyz) * projectionMatrix[1][1] * height * 0.5 / -mvPosition.z;
    }
  `,
  fragmentShader: `
    varying float vAlpha;
    void main() {
      float a = (1.0 - smoothstep(0.2, 1.0, length(gl_PointCoord - 0.5) * 2.0)) * vAlpha;
      if (a < 0.01) discard;
      gl_FragColor = vec4(0.96, 0.96, 0.96, a);
    }
  `,
  transparent: true,
  depthTest: false,
  depthWrite: false
});

const smokes = [];

const update = e => {
  const viewer = e.target;
  const session = viewer.renderer.xr.getSession();
  if (session) material.uniforms.height.value = session.renderState.baseLayer.framebufferHeight;

  for (let k = smokes.length - 1; k >= 0; k--){
    const smoke = smokes[k];
    const geometry = smoke.cloud.geometry;
    const delta = Math.min(e.delta, 0.1) * 2;
    smoke.age += delta;
    if (smoke.age > 1){
      viewer.measuringTool.scene.remove(smoke.cloud);
      geometry.dispose();
      smokes.splice(k, 1);
      continue;
    }

    const position = geometry.attributes.position, size = geometry.attributes.size, alpha = geometry.attributes.alpha;
    for (let i = 0; i < smoke.life.length; i++){
      const t = Math.min(1, (smoke.age - smoke.delay[i]) / smoke.life[i]);
      if (t <= 0) continue;
      for (let j = 0; j < 3; j++) position.array[i * 3 + j] += smoke.velocity[i * 3 + j] * delta * (1 - t);
      size.array[i] = smoke.puff * (0.6 + 2 * t);
      alpha.array[i] = 0.3 * Math.min(1, t * 8) * (1 - t);
    }
    position.needsUpdate = true;
    size.needsUpdate = true;
    alpha.needsUpdate = true;
  }

  if (!smokes.length) viewer.removeEventListener("update", update);
};

export const smoke = (viewer, measurement, index, puff, height) => {
  const points = measurement.points.map(p => p.position || p);
  if (!points.length) return;

  const segments = [];
  if (index !== undefined || points.length === 1){
    segments.push([points[index || 0], points[index || 0]]);
  }else{
    const edges = measurement.closed && points.length > 2 ? points.length : points.length - 1;
    for (let i = 0; i < edges; i++) segments.push([points[i], points[(i + 1) % points.length]]);
  }

  const origin = segments[0][0].clone();
  const lengths = segments.map(segment => segment[0].distanceTo(segment[1]));
  const total = lengths.reduce((a, b) => a + b, 0);
  const count = Math.min(1200, Math.max(24, Math.round(total / (puff * 0.15))));
  const position = new Float32Array(count * 3);
  const velocity = new Float32Array(count * 3);
  const delay = new Float32Array(count);
  const life = new Float32Array(count);

  for (let i = 0; i < count; i++){
    let at = Math.random() * total, k = 0;
    while (k < segments.length - 1 && at > lengths[k]) at -= lengths[k++];
    const p = segments[k][0].clone().lerp(segments[k][1], lengths[k] > 0 ? at / lengths[k] : 0).sub(origin);
    const v = new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).normalize().multiplyScalar(puff * 0.6);
    v.z += puff * (0.8 + Math.random() * 0.8);
    p.z += Math.random() * height;
    p.add(new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).multiplyScalar(puff * 0.4)).toArray(position, i * 3);
    v.toArray(velocity, i * 3);
    delay[i] = Math.random() * 0.15;
    life[i] = 0.6 + Math.random() * 0.25;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(position, 3));
  geometry.setAttribute("size", new THREE.BufferAttribute(new Float32Array(count), 1));
  geometry.setAttribute("alpha", new THREE.BufferAttribute(new Float32Array(count), 1));
  const cloud = new THREE.Points(geometry, material);
  cloud.position.copy(origin);
  cloud.frustumCulled = false;
  viewer.measuringTool.scene.add(cloud);

  if (!smokes.length) viewer.addEventListener("update", update);
  smokes.push({cloud, velocity, delay, life, puff, age: 0});
};
