'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { MeshBasicNodeMaterial, WebGPURenderer } from 'three/webgpu';
import {
  Fn,
  abs,
  clamp,
  cos,
  dFdx,
  dFdy,
  dot,
  float,
  length,
  max,
  min,
  mix,
  normalize,
  pow,
  sin,
  smoothstep,
  time,
  uniform,
  uv,
  vec2,
  vec3,
  vec4,
} from 'three/tsl';
import type { Thread } from '../../lib/api';
import type Node from 'three/src/nodes/core/Node.js';
import type { DomRegistry, WorkspaceMotion } from './InfiniteWorkspace';
import styles from './SpatialWorkspace.module.css';

const CARD_WIDTH_WORLD = 3.62;
const CARD_HEIGHT_WORLD = 2.42;
const GRID_SPACING_X = 4.12;
const GRID_SPACING_Y = 3.12;
const GRID_COLUMNS = 5;
const GRID_ROWS = 3;
const WRAP_WIDTH = GRID_COLUMNS * GRID_SPACING_X;
const SLOT_COORDINATES = [
  [0, 0], [1, 0], [-1, 0], [2, 0], [-2, 0],
  [0, 1], [0, -1], [1, 1], [-1, 1], [1, -1], [-1, -1], [2, 1], [-2, -1],
] as const;

type TSLControl = Node<'float'> & { value: number };

type TSLMaterial = MeshBasicNodeMaterial & {
  userData: {
    controls?: {
      hover: TSLControl;
      focus: TSLControl;
      motion: TSLControl;
      clock: TSLControl;
    };
  };
};

type CardRecord = {
  mesh: THREE.Mesh;
  material: TSLMaterial;
};

function wrap(value: number, range: number) {
  const half = range / 2;
  return ((((value + half) % range) + range) % range) - half;
}

function makeLiquidGlassTSL(accent: THREE.Color) {
  const hover = uniform(0) as TSLControl;
  const focus = uniform(0) as TSLControl;
  const motion = uniform(0) as TSLControl;
  const accentNode = uniform(accent) as any;
  const uvNode = uv() as any;
  const animatedTime = uniform(0) as TSLControl;

  const material = new MeshBasicNodeMaterial({ transparent: true, opacity: 0.88 }) as TSLMaterial;
  material.side = THREE.DoubleSide;
  material.depthWrite = false;
  material.userData.controls = { hover, focus, motion, clock: animatedTime };

  material.colorNode = Fn(() => {
    const p = uvNode.mul(2).sub(1);
    const halfSize = vec2(0.95, 0.92);
    const radius = float(0.12);
    const q = abs(p).sub(halfSize).add(radius);
    const distanceToEdge = length(max(q, vec2(0))).add(min(max(q.x, q.y), float(0))).sub(radius);
    const alpha = smoothstep(float(0.012), float(0), distanceToEdge);

    const bevelWidth = float(0.28);
    const bevelEdge = clamp(float(1).add(distanceToEdge.div(bevelWidth)), 0, 1);
    const height = pow(max(float(1).sub(pow(bevelEdge, 2)), 0), 0.5);
    const normal = normalize(vec3(dFdx(height).mul(1.8), dFdy(height).mul(1.8), 1));

    const refractedUv = uvNode.add(normal.xy.mul(float(0.032).add(hover.mul(0.024)).add(motion.mul(0.006))));
    const drift = sin(animatedTime.mul(0.13).add(refractedUv.x.mul(3.4))).mul(0.5).add(0.5);
    const grain = sin(refractedUv.x.mul(31).add(refractedUv.y.mul(17)).add(animatedTime.mul(0.2))).mul(0.5).add(0.5);
    const deep = vec3(0.045, 0.062, 0.055);
    const moss = vec3(0.11, 0.16, 0.13);
    const paper = vec3(0.23, 0.23, 0.19);
    let refracted = mix(deep, moss, smoothstep(0.1, 0.92, refractedUv.y.add(drift.mul(0.18))));
    refracted = mix(refracted, paper, smoothstep(0.56, 1, refractedUv.x.mul(0.36).add(refractedUv.y.mul(0.46))).mul(0.24));
    refracted = refracted.add(grain.mul(0.018));

    const fresnel = pow(float(1).sub(max(dot(normal, vec3(0, 0, 1)), 0)), 3.1);
    let reflection = mix(vec3(0.31, 0.38, 0.31), vec3(0.82, 0.76, 0.62), uvNode.y);
    reflection = reflection.add(accentNode.mul(float(0.18).add(hover.mul(0.25))));
    const rim = smoothstep(0.075, -0.008, distanceToEdge);
    const rimColor = mix(vec3(0.68, 0.75, 0.64), vec3(0.88, 0.78, 0.56), uvNode.y);
    let color = mix(refracted.add(accentNode.mul(0.16)), reflection, fresnel.mul(0.72).add(focus.mul(0.16)));
    color = color.add(rimColor.mul(rim.mul(0.1).add(fresnel.mul(0.6)).add(hover.mul(0.18))));
    color = color.add(vec3(0.9, 0.88, 0.78).mul(smoothstep(0.06, -0.01, distanceToEdge)).mul(0.07));
    color = color.add(accentNode.mul(height).mul(0.045));
    color = color.mul(float(0.82).add(smoothstep(0.93, 0.35, length(p)).mul(0.22)));
    return vec4(color, alpha.mul(0.73).add(focus.mul(0.12)));
  })() as any;

  material.opacityNode = float(1);
  return material;
}

function updateDomCard(
  record: CardRecord,
  dom: HTMLDivElement | null,
  camera: THREE.PerspectiveCamera,
  width: number,
  height: number,
  spatialScale: number,
  targetRotation: THREE.Euler,
  focusActive: boolean,
  isFocused: boolean,
) {
  if (!dom) return;
  const projected = new THREE.Vector3().setFromMatrixPosition(record.mesh.matrixWorld).project(camera);
  const left = (projected.x * 0.5 + 0.5) * width;
  const top = (-projected.y * 0.5 + 0.5) * height;
  const distance = Math.max(camera.position.z - record.mesh.position.z, 1);
  const pixelsPerWorldUnit = height / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * distance);
  dom.style.width = `${(CARD_WIDTH_WORLD * record.mesh.scale.x * pixelsPerWorldUnit).toFixed(2)}px`;
  dom.style.height = `${(CARD_HEIGHT_WORLD * record.mesh.scale.y * pixelsPerWorldUnit).toFixed(2)}px`;
  dom.style.transform = `translate3d(${left.toFixed(2)}px, ${top.toFixed(2)}px, 0) translate(-50%, -50%) rotateX(${targetRotation.x.toFixed(4)}rad) rotateY(${targetRotation.y.toFixed(4)}rad) rotateZ(${targetRotation.z.toFixed(4)}rad)`;
  dom.style.opacity = focusActive ? (isFocused ? '1' : '0') : String(THREE.MathUtils.clamp(0.52 + spatialScale * 0.58, 0.72, 1));
  dom.style.zIndex = String(Math.round((record.mesh.position.z + 10) * 10));
  dom.dataset.focused = String(isFocused);
  dom.setAttribute('aria-hidden', focusActive && !isFocused ? 'true' : 'false');
}

export function WebGPUField({
  threads,
  motion,
  focusId,
  hoveredId,
  domRegistry,
  reducedMotion,
  onReady,
  onError,
}: {
  threads: Thread[];
  motion: React.MutableRefObject<WorkspaceMotion>;
  focusId: string | null;
  hoveredId: React.MutableRefObject<string | null>;
  domRegistry: DomRegistry;
  reducedMotion: boolean;
  onReady: () => void;
  onError: (error: unknown) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const threadsRef = useRef(threads);
  threadsRef.current = threads;
  const focusRef = useRef(focusId);
  const reducedMotionRef = useRef(reducedMotion);
  const onReadyRef = useRef(onReady);
  const onErrorRef = useRef(onError);

  useEffect(() => { focusRef.current = focusId; }, [focusId]);
  useEffect(() => { reducedMotionRef.current = reducedMotion; }, [reducedMotion]);
  useEffect(() => { onReadyRef.current = onReady; }, [onReady]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let disposed = false;
    let renderer: WebGPURenderer | null = null;
    let resizeObserver: ResizeObserver | null = null;
    let previousTime = performance.now();
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    camera.position.set(0, 0, 12);
    camera.lookAt(0, 0, 0);
    const geometry = new THREE.PlaneGeometry(CARD_WIDTH_WORLD, CARD_HEIGHT_WORLD, 28, 22);
    let records: CardRecord[] = [];
    let currentThreads: Thread[] | null = null;
    let clock = 0;
    let initialized = false;
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      records.forEach(({ material }) => material.dispose());
      geometry.dispose();
      scene.clear();
      renderer?.dispose();
    };
    const syncCards = () => {
      if (currentThreads === threadsRef.current) return;
      const previous = new Map((currentThreads ?? []).map((thread, index) => [thread.id, { thread, record: records[index] }]));
      records = threadsRef.current.map((thread) => {
        const existing = previous.get(thread.id);
        previous.delete(thread.id);
        if (existing && existing.thread.status === thread.status) return existing.record;
        if (existing) { scene.remove(existing.record.mesh); existing.record.material.dispose(); }
        const material = makeLiquidGlassTSL(new THREE.Color({
          waiting_for_me: 0xa7bca3, ready: 0xd1c5a3, replied: 0x8d9d9a,
          no_action: 0x787c74, do_not_reply: 0xc7a591,
        }[thread.status] ?? 0xa7bca3));
        const mesh = new THREE.Mesh(geometry, material);
        mesh.frustumCulled = false;
        if (existing) { mesh.position.copy(existing.record.mesh.position); mesh.rotation.copy(existing.record.mesh.rotation); mesh.scale.copy(existing.record.mesh.scale); }
        scene.add(mesh);
        return { mesh, material };
      });
      previous.forEach(({ record }) => { scene.remove(record.mesh); record.material.dispose(); });
      currentThreads = threadsRef.current;
    };

    const resize = () => {
      if (!renderer) return;
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(1, rect.width);
      const height = Math.max(1, rect.height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.8));
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan((height / 720) * Math.tan(THREE.MathUtils.degToRad(19))));
      camera.updateProjectionMatrix();
    };

    const render = () => {
      if (disposed || !renderer) return;
      syncCards();
      const threads = currentThreads!;
      const now = performance.now();
      const delta = Math.min((now - previousTime) / 1000, 0.05);
      previousTime = now;
      if (!reducedMotionRef.current) clock += delta;
      const state = motion.current;
      if (!state.pointerDown) {
        state.x += state.vx * delta;
        state.y += state.vy * delta;
        const friction = Math.exp(-(reducedMotionRef.current ? 13 : 5.2) * delta);
        state.vx *= friction;
        state.vy *= friction;
      }

      const rect = canvas.getBoundingClientRect();
      const width = Math.max(1, rect.width);
      const height = Math.max(1, rect.height);
      const responsiveScale = width < 640 ? 0.76 : width < 980 ? 0.9 : 1;
      const verticalSpacing = width < 640 ? 2.72 : GRID_SPACING_Y;
      const verticalWrap = GRID_ROWS * verticalSpacing;
      const activeFocus = focusRef.current;
      // WebGPURenderer does not own the camera transform update like R3F's
      // render loop does. Keep the DOM projection in the same camera space as
      // the canvas before projecting each real HTML card.
      camera.updateMatrixWorld();

      records.forEach((record, index) => {
        const slot = SLOT_COORDINATES[index % SLOT_COORDINATES.length];
        const x = wrap(slot[0] * GRID_SPACING_X + state.x, WRAP_WIDTH);
        const y = wrap(slot[1] * verticalSpacing + state.y, verticalWrap);
        const curvedDistance = Math.sqrt(x * x + y * y);
        const curveX = x * (1 + Math.min(Math.abs(x) / WRAP_WIDTH, 0.46) * 0.08);
        const curveY = y * (1 + Math.min(Math.abs(y) / verticalWrap, 0.46) * 0.1);
        const curvedZ = -0.035 * x * x - 0.062 * y * y;
        const spatialScale = THREE.MathUtils.clamp(1.03 - curvedDistance * 0.04, 0.66, 1.04);
        const isFocused = activeFocus === threads[index].id;
        const phase = now * 0.001;
        const drift = reducedMotionRef.current || state.pointerDown ? 0 : Math.sin(phase * 0.8 + index * 1.7) * 0.14;
        const isHovering = hoveredId.current === threads[index].id;
        const lift = isHovering ? 0.48 : 0;
        const targetPosition = isFocused
          ? new THREE.Vector3(0, 0, 2.05)
          : activeFocus
            ? new THREE.Vector3(curveX * 1.52, curveY * 1.52, curvedZ - 3.7 - curvedDistance * 0.15)
            : new THREE.Vector3(curveX, curveY + drift, curvedZ + drift * 0.65 + lift);
        const targetRotation = isFocused
          ? new THREE.Euler(0, 0, 0)
          : activeFocus
            ? new THREE.Euler(curveY * -0.035, curveX * 0.04, 0)
            : new THREE.Euler(curveY * -0.072, curveX * 0.075, curveX * curveY * 0.006);
        const targetScaleValue = isFocused
          ? 1.13 * responsiveScale
          : activeFocus
            ? spatialScale * 0.53 * responsiveScale
            : spatialScale * responsiveScale;
        const ease = 1 - Math.exp(-(reducedMotionRef.current ? 18 : isFocused ? 8 : 11) * delta);
        record.mesh.position.lerp(targetPosition, ease);
        record.mesh.rotation.x = THREE.MathUtils.lerp(record.mesh.rotation.x, targetRotation.x, ease);
        record.mesh.rotation.y = THREE.MathUtils.lerp(record.mesh.rotation.y, targetRotation.y, ease);
        record.mesh.rotation.z = THREE.MathUtils.lerp(record.mesh.rotation.z, targetRotation.z, ease);
        record.mesh.scale.lerp(new THREE.Vector3(targetScaleValue, targetScaleValue, targetScaleValue), ease);
        record.mesh.updateMatrixWorld();

        const controls = record.material.userData.controls;
        if (controls) {
          const isHovered = hoveredId.current === threads[index].id;
          controls.clock.value = clock;
          controls.hover.value = THREE.MathUtils.damp(controls.hover.value, isHovered ? 1 : 0, 8, delta);
          controls.focus.value = THREE.MathUtils.damp(controls.focus.value, isFocused ? 1 : 0, 7, delta);
          controls.motion.value = Math.min(Math.abs(state.vx) + Math.abs(state.vy), 1.5);
        }
        updateDomCard(record, domRegistry.current[threads[index].id], camera, width, height, spatialScale, targetRotation, Boolean(activeFocus), isFocused);
      });

      renderer.render(scene, camera);
    };

    const start = async () => {
      if (!('gpu' in navigator) || !navigator.gpu) throw new Error('WebGPU is not available in this browser.');
      renderer = new WebGPURenderer({ canvas, alpha: true, antialias: true, powerPreference: 'high-performance' });
      resize();
      try { await renderer.init(); } catch (error) { release(); throw error; }
      initialized = true;
      if (disposed) { release(); return; }
      onReadyRef.current();
      await renderer.setAnimationLoop(render);
      if (disposed) { await renderer.setAnimationLoop(null); release(); }
    };

    resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    void start().catch((error) => {
      if (!disposed) onErrorRef.current(error);
    });

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      if (initialized && renderer) {
        void renderer.setAnimationLoop(null).finally(release);
      } else if (!renderer) release();
      // An in-flight init owns release until its promise settles.
    };
  }, [domRegistry, motion, hoveredId]);

  return <canvas ref={canvasRef} className={styles.canvas} aria-label="WebGPU 碎玻璃背景" />;
}
