/**
 * @license
 * Based on the Immersive Web SDK (IWSDK, https://github.com/facebook/immersive-web-sdk).
 * Adapted from @iwsdk/xr-input 1.1.0 (AnimatedHand, BaseHandVisual, XRHandVisualAdapter).
 *
 * Original code: Copyright (c) Meta Platforms, Inc. and affiliates, MIT License (see below)
 * Adaptation: Copyright (c) Piero Toffanin, GNU AGPL v3 (see LICENSE.md at the WebODM repository root)
 * The combined work is distributed under the terms of the GNU AGPL v3.
 *
 * The original IWSDK license is retained below.
 *
 * MIT License
 *
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */
import * as THREE from 'THREE';

const stencilMaterial = new THREE.ShaderMaterial({
    uniforms: {
        outlineThickness: { value: 0.0012 },
    },
    vertexShader: `
        #include <common>
        #include <skinning_pars_vertex>
        uniform float outlineThickness;

        void main() {
          #include <skinbase_vertex>
          #include <beginnormal_vertex>
          #include <skinnormal_vertex>
          #include <defaultnormal_vertex>

          vec3 transformed = position - normal * outlineThickness;
          #include <skinning_vertex>
          vec4 mvPosition = modelViewMatrix * vec4(transformed, 1.0);
          gl_Position = projectionMatrix * mvPosition;
        }
      `,
    fragmentShader: `
        void main() {
          gl_FragColor = vec4(0,0,0,0);
        }
      `,
    transparent: true,
    depthWrite: true,
    depthTest: true,
    alphaTest: 0.05,
    side: THREE.FrontSide,
    skinning: true,
});
const outlineMaterial = new THREE.ShaderMaterial({
    uniforms: {
        outlineColor: {
            value: new THREE.Color(0xffffff),
        },
        opacityThresholds: {
            value: new THREE.Vector2(0.03, 0.08),
        },
    },
    vertexShader: `
        #include <common>
        #include <skinning_pars_vertex>

        attribute float wristDist;
        varying float vWristDist;

        void main() {
          #include <skinbase_vertex>
          #include <beginnormal_vertex>
          #include <skinnormal_vertex>
          #include <defaultnormal_vertex>

          vec3 transformed = vec3(position);
          #include <skinning_vertex>

          vec4 mvPosition = modelViewMatrix * vec4(transformed, 1.0);
          gl_Position = projectionMatrix * mvPosition;
          vWristDist = wristDist;
        }
      `,
    fragmentShader: `
        uniform vec3 outlineColor;
        uniform vec2 opacityThresholds;
        varying float vWristDist;

        void main() {
          float alpha = smoothstep(opacityThresholds.x, opacityThresholds.y, vWristDist);
          alpha = clamp(alpha, 0.0, 1.0);

          gl_FragColor = vec4(outlineColor, alpha);
        }
      `,
    side: THREE.BackSide,
    transparent: true,
    depthWrite: false,
    depthTest: true,
    skinning: true,
});

class HandVisual {
    constructor(model) {
        this.model = model;
        this.joints = [];
        this.jointSpaces = [];
        this.enabled = true;
        this.init();
    }
    init() {
        var _a;
        const skinnedMesh = this.model.getObjectByProperty('type', 'SkinnedMesh');
        skinnedMesh.frustumCulled = false;
        skinnedMesh.parent.scale.multiplyScalar(1.05);
        const wrist = this.model.getObjectByName('wrist');
        const geometry = skinnedMesh.geometry;
        const wristWorldPos = wrist.getWorldPosition(new THREE.Vector3());
        const wristLocal = skinnedMesh.worldToLocal(wristWorldPos.clone());
        const posAttr = geometry.attributes.position;
        const vertexCount = posAttr.count;
        const distances = new Float32Array(vertexCount);
        for (let i = 0; i < vertexCount; i++) {
            const x = posAttr.getX(i);
            const y = posAttr.getY(i);
            const z = posAttr.getZ(i);
            distances[i] = Math.sqrt((x - wristLocal.x) * (x - wristLocal.x) +
                (y - wristLocal.y) * (y - wristLocal.y) +
                (z - wristLocal.z) * (z - wristLocal.z));
        }
        geometry.setAttribute('wristDist', new THREE.BufferAttribute(distances, 1));
        skinnedMesh.material = stencilMaterial;
        const skinnedOutline = skinnedMesh.clone();
        skinnedOutline.material = outlineMaterial;
        (_a = skinnedMesh.parent) === null || _a === void 0 ? void 0 : _a.add(skinnedOutline);
        skinnedOutline.renderOrder = 999;
    }
    connect(inputSource, enabled) {
        this.toggle(enabled);
        this.joints.length = 0;
        this.jointSpaces.length = 0;
        const hand = inputSource.hand;
        this.gripXRSpace = inputSource.gripSpace || inputSource.targetRaySpace;
        hand.forEach((jointSpace) => {
            this.jointSpaces.push(jointSpace);
            this.joints.push(this.model.getObjectByName(jointSpace.jointName));
        });
        this.jointTransforms = new Float32Array(hand.size * 16);
    }
    disconnect() {
        this.joints.length = 0;
        this.jointSpaces.length = 0;
        this.jointTransforms = undefined;
        this.gripXRSpace = undefined;
    }
    toggle(enabled) {
        if (this.enabled !== enabled) {
            this.model.visible = enabled;
            this.enabled = enabled;
        }
    }
    update(frame, gripSpace) {
        var _a, _b;
        if (!this.jointTransforms) return false;
        const success = (_b = (_a = frame.fillPoses) === null || _a === void 0 ? void 0 : _a.call(frame, this.jointSpaces, this.gripXRSpace, this.jointTransforms)) !== null && _b !== void 0 ? _b : false;
        if (success) {
            this.model.position.copy(gripSpace.position);
            this.model.quaternion.copy(gripSpace.quaternion);
            if (this.enabled) {
                this.joints.forEach((bone, index) => {
                    if (bone) {
                        bone.matrix.fromArray(this.jointTransforms, index * 16);
                        bone.matrix.decompose(bone.position, bone.quaternion, bone.scale);
                    }
                });
            }
        }
        return success;
    }
}

export default HandVisual;
