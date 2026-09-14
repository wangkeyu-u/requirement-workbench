'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import { AnimatePresence, motion as motionElement, useReducedMotion } from 'motion/react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import { X } from 'lucide-react';
import type { Settings, Thread, ThreadStatus } from '../../lib/api';
import { categoryLabel, STATUS_LABELS } from '../../lib/i18n';
import styles from './SpatialWorkspace.module.css';
import { WebGPUField } from './WebGPUField';

const CARD_WIDTH_WORLD = 3.62;
const CARD_HEIGHT_WORLD = 2.42;
const GRID_SPACING_X = 4.12;
const GRID_SPACING_Y = 3.12;
const GRID_COLUMNS = 5;
const GRID_ROWS = 3;
const WRAP_WIDTH = GRID_COLUMNS * GRID_SPACING_X;
const WRAP_HEIGHT = GRID_ROWS * GRID_SPACING_Y;
const FRACTURE_SHARDS = Array.from({ length: 12 }, (_, index) => index);

const SLOT_COORDINATES = [
  [0, 0],
  [1, 0],
  [-1, 0],
  [2, 0],
  [-2, 0],
  [0, 1],
  [0, -1],
  [1, 1],
  [-1, 1],
  [1, -1],
  [-1, -1],
  [2, 1],
  [-2, -1],
] as const;

const STATUS_TONE: Record<ThreadStatus, string> = {
  waiting_for_me: '#a7bca3',
  ready: '#d1c5a3',
  replied: '#8d9d9a',
  no_action: '#787c74',
  do_not_reply: '#c7a591',
};

const LIQUID_VERTEX_SHADER = /* glsl */ `
  uniform float uTime;
  uniform float uHover;
  uniform float uFocus;
  varying vec2 vUv;
  varying float vDepth;

  void main() {
    vUv = uv;
    vec3 transformed = position;
    float edge = smoothstep(0.05, 0.92, length(uv * 2.0 - 1.0));
    float waveA = sin(uv.x * 8.0 + uTime * 0.48) * 0.012;
    float waveB = cos(uv.y * 7.0 - uTime * 0.34) * 0.009;
    transformed.z += (waveA + waveB) * (0.6 + uHover * 0.8) * (1.0 - edge * 0.42);
    transformed.z += uFocus * 0.018 * (1.0 - edge);
    vDepth = transformed.z;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(transformed, 1.0);
  }
`;

const LIQUID_FRAGMENT_SHADER = /* glsl */ `
  precision highp float;

  uniform float uTime;
  uniform float uHover;
  uniform float uFocus;
  uniform float uMotion;
  uniform vec3 uAccent;
  varying vec2 vUv;
  varying float vDepth;

  float roundedBoxSdf(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
  }

  float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 345.45));
    p += dot(p, p + 34.345);
    return fract(p.x * p.y);
  }

  float softNoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
  }

  vec3 fieldColor(vec2 uv) {
    float drift = sin(uTime * 0.13 + uv.x * 3.4) * 0.5 + 0.5;
    float grain = softNoise(uv * 4.4 + uTime * 0.025);
    vec3 deep = vec3(0.045, 0.062, 0.055);
    vec3 moss = vec3(0.11, 0.16, 0.13);
    vec3 paper = vec3(0.23, 0.23, 0.19);
    vec3 field = mix(deep, moss, smoothstep(0.1, 0.92, uv.y + drift * 0.18));
    field = mix(field, paper, smoothstep(0.56, 1.0, uv.x * 0.36 + uv.y * 0.46) * 0.24);
    return field + grain * 0.018;
  }

  void main() {
    vec2 p = vUv * 2.0 - 1.0;
    float distanceToEdge = roundedBoxSdf(p, vec2(0.95, 0.92), 0.12);
    float alpha = 1.0 - smoothstep(0.0, 0.012, distanceToEdge);
    if (alpha < 0.02) discard;

    float bevelWidth = 0.28;
    float edge = clamp(1.0 + distanceToEdge / bevelWidth, 0.0, 1.0);
    float height = pow(max(1.0 - pow(edge, 2.0), 0.0), 0.5);
    float stepX = 0.008;
    float stepY = 0.008;
    float leftHeight = pow(max(1.0 - pow(clamp(1.0 + roundedBoxSdf(p - vec2(stepX, 0.0), vec2(0.95, 0.92), 0.12) / bevelWidth, 0.0, 1.0), 2.0), 0.0), 0.5);
    float rightHeight = pow(max(1.0 - pow(clamp(1.0 + roundedBoxSdf(p + vec2(stepX, 0.0), vec2(0.95, 0.92), 0.12) / bevelWidth, 0.0, 1.0), 2.0), 0.0), 0.5);
    float downHeight = pow(max(1.0 - pow(clamp(1.0 + roundedBoxSdf(p - vec2(0.0, stepY), vec2(0.95, 0.92), 0.12) / bevelWidth, 0.0, 1.0), 2.0), 0.0), 0.5);
    float upHeight = pow(max(1.0 - pow(clamp(1.0 + roundedBoxSdf(p + vec2(0.0, stepY), vec2(0.95, 0.92), 0.12) / bevelWidth, 0.0, 1.0), 2.0), 0.0), 0.5);
    vec3 normal = normalize(vec3((rightHeight - leftHeight) * 1.8, (upHeight - downHeight) * 1.8, 1.0));

    vec2 refractedUv = vUv + normal.xy * (0.032 + uHover * 0.024 + uMotion * 0.006);
    refractedUv += vec2(
      sin(vUv.y * 10.0 + uTime * 0.3),
      cos(vUv.x * 9.0 - uTime * 0.24)
    ) * 0.008;
    vec3 refracted = fieldColor(refractedUv);

    float fresnel = pow(1.0 - max(dot(normal, vec3(0.0, 0.0, 1.0)), 0.0), 3.1);
    vec3 reflection = mix(vec3(0.31, 0.38, 0.31), vec3(0.82, 0.76, 0.62), vUv.y);
    reflection += uAccent * (0.18 + uHover * 0.25);

    float rim = smoothstep(0.075, -0.008, distanceToEdge);
    vec3 rimColor = mix(vec3(0.68, 0.75, 0.64), vec3(0.88, 0.78, 0.56), vUv.y);
    vec3 color = mix(refracted + uAccent * 0.16, reflection, fresnel * (0.72 + uFocus * 0.16));
    color += rimColor * rim * (0.1 + fresnel * 0.6 + uHover * 0.18);
    color += vec3(0.9, 0.88, 0.78) * smoothstep(0.06, -0.01, distanceToEdge) * 0.07;
    color += uAccent * height * 0.045;

    float innerShade = smoothstep(0.93, 0.35, length(p));
    color *= 0.82 + innerShade * 0.22;
    gl_FragColor = vec4(color, alpha * (0.73 + uFocus * 0.12));
  }
`;

export type WorkspaceMotion = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  pointerDown: boolean;
  pointerId: number | null;
  lastX: number;
  lastY: number;
  lastTime: number;
  dragDistance: number;
  justDragged: boolean;
};

export type DomRegistry = React.MutableRefObject<Record<string, HTMLDivElement | null>>;

export type WorkbenchShellProps = {
  threadId: string;
  onClose: () => void;
  onUpdated?: () => void;
};

export type SpatialWorkspaceProps = {
  threads: Thread[];
  settings: Settings;
  connection: 'demo' | 'live';
  onAutoReplyChange: (enabled: boolean) => Promise<void> | void;
  onSyncMail?: () => Promise<void> | void;
  autoReplyPending?: boolean;
  mailSyncPending?: boolean;
  autoReplyError?: string | null;
  WorkbenchShell?: ComponentType<WorkbenchShellProps>;
  onUpdated?: () => void;
};

function wrap(value: number, range: number) {
  const half = range / 2;
  return ((((value + half) % range) + range) % range) - half;
}

function relativeTime(timestamp: string) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(timestamp).getTime()) / 60000));
  if (minutes < 2) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.round(hours / 24)} 天前`;
}

function CardCopy({ thread, index }: { thread: Thread; index: number }) {
  return (
    <>
      <div className={styles.cardTop}>
        <span className={styles.cardIndex}>{String(index + 1).padStart(2, '0')}</span>
        <span className={styles.cardCategory}>{categoryLabel(thread.category)}</span>
      </div>
      <div className={styles.cardMiddle}>
        <h2 className={styles.cardTitle}>{thread.title}</h2>
        <p className={styles.cardSender}>{thread.sender}</p>
      </div>
      <div className={styles.cardBottom}>
        <span className={styles.cardStatus} data-status={thread.status}>
          <span className={styles.cardStatusDot} aria-hidden="true" />
          {STATUS_LABELS[thread.status]}
        </span>
        <span className={styles.cardCompleteness}>
          {thread.completeness}<span>%</span>
        </span>
      </div>
    </>
  );
}

function LiquidCardMesh({
  thread,
  index,
  meshRefs,
  materialRefs,
}: {
  thread: Thread;
  index: number;
  meshRefs: React.MutableRefObject<Record<string, THREE.Mesh | null>>;
  materialRefs: React.MutableRefObject<Record<string, THREE.ShaderMaterial | null>>;
}) {
  const accent = useMemo(() => new THREE.Color(STATUS_TONE[thread.status]), [thread.status]);
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uHover: { value: 0 },
      uFocus: { value: 0 },
      uMotion: { value: 0 },
      uAccent: { value: accent },
    }),
    [accent],
  );

  return (
    <mesh
      ref={(node) => {
        meshRefs.current[thread.id] = node;
      }}
      geometry={undefined}
      frustumCulled={false}
      userData={{ threadId: thread.id, index }}
    >
      <planeGeometry args={[CARD_WIDTH_WORLD, CARD_HEIGHT_WORLD, 28, 22]} />
      <shaderMaterial
        ref={(node) => {
          materialRefs.current[thread.id] = node;
        }}
        vertexShader={LIQUID_VERTEX_SHADER}
        fragmentShader={LIQUID_FRAGMENT_SHADER}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

function SceneContents({
  threads,
  motion,
  focusId,
  hoveredId,
  domRegistry,
  reducedMotion,
}: {
  threads: Thread[];
  motion: React.MutableRefObject<WorkspaceMotion>;
  focusId: string | null;
  hoveredId: React.MutableRefObject<string | null>;
  domRegistry: DomRegistry;
  reducedMotion: boolean;
}) {
  const { camera, size } = useThree();
  const meshRefs = useRef<Record<string, THREE.Mesh | null>>({});
  const materialRefs = useRef<Record<string, THREE.ShaderMaterial | null>>({});
  const lastSize = useRef({ width: size.width, height: size.height });
  const targetPosition = useMemo(() => new THREE.Vector3(), []);
  const targetRotation = useMemo(() => new THREE.Euler(), []);
  const targetScale = useMemo(() => new THREE.Vector3(), []);
  const projected = useMemo(() => new THREE.Vector3(), []);

  useEffect(() => {
    lastSize.current = { width: size.width, height: size.height };
  }, [size.width, size.height]);

  useFrame(({ clock }, delta) => {
    const state = motion.current;
    const safeDelta = Math.min(delta, 0.05);

    if (!state.pointerDown) {
      state.x += state.vx * safeDelta;
      state.y += state.vy * safeDelta;
      const friction = Math.exp(-(reducedMotion ? 13 : 5.2) * safeDelta);
      state.vx *= friction;
      state.vy *= friction;
      if (Math.abs(state.vx) < 0.0004) state.vx = 0;
      if (Math.abs(state.vy) < 0.0004) state.vy = 0;
    }

    const viewWidth = Math.max(lastSize.current.width, 1);
    const viewHeight = Math.max(lastSize.current.height, 1);
    if (camera instanceof THREE.PerspectiveCamera) {
      camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan((viewHeight / 720) * Math.tan(THREE.MathUtils.degToRad(19))));
      camera.updateProjectionMatrix();
    }
    const focusActive = Boolean(focusId);
    const responsiveScale = viewWidth < 640 ? 0.76 : viewWidth < 980 ? 0.9 : 1;
    const verticalSpacing = viewWidth < 640 ? 2.72 : GRID_SPACING_Y;
    const verticalWrap = GRID_ROWS * verticalSpacing;

    threads.forEach((thread, index) => {
      const mesh = meshRefs.current[thread.id];
      const material = materialRefs.current[thread.id];
      const dom = domRegistry.current[thread.id];
      if (!mesh || !material) return;

      const slot = SLOT_COORDINATES[index % SLOT_COORDINATES.length];
      const unwrappedX = slot[0] * GRID_SPACING_X + state.x;
      const unwrappedY = slot[1] * verticalSpacing + state.y;
      const x = wrap(unwrappedX, WRAP_WIDTH);
      const y = wrap(unwrappedY, verticalWrap);
      const curvedDistance = Math.sqrt(x * x + y * y);
      const curveX = x * (1 + Math.min(Math.abs(x) / WRAP_WIDTH, 0.46) * 0.08);
      const curveY = y * (1 + Math.min(Math.abs(y) / WRAP_HEIGHT, 0.46) * 0.1);
      const curvedZ = -0.035 * x * x - 0.062 * y * y;
      const spatialScale = THREE.MathUtils.clamp(1.03 - curvedDistance * 0.04, 0.66, 1.04);
      const isFocused = focusId === thread.id;
      const isHovered = hoveredId.current === thread.id;

      if (isFocused) {
        targetPosition.set(0, 0, 2.05);
        targetRotation.set(0, 0, 0);
        targetScale.set(1.13 * responsiveScale, 1.13 * responsiveScale, 1.13 * responsiveScale);
      } else if (focusActive) {
        targetPosition.set(curveX * 1.52, curveY * 1.52, curvedZ - 3.7 - curvedDistance * 0.15);
        targetRotation.set(curveY * -0.035, curveX * 0.04, 0);
        targetScale.set(spatialScale * 0.53 * responsiveScale, spatialScale * 0.53 * responsiveScale, spatialScale * 0.53 * responsiveScale);
      } else {
        const drift = reducedMotion || state.pointerDown ? 0 : Math.sin(clock.elapsedTime * 0.8 + index * 1.7) * 0.14;
        targetPosition.set(curveX, curveY + drift, curvedZ + drift * 0.65 + (isHovered ? 0.48 : 0));
        targetRotation.set(curveY * -0.072, curveX * 0.075, curveX * curveY * 0.006);
        targetScale.set(spatialScale * responsiveScale, spatialScale * responsiveScale, spatialScale * responsiveScale);
      }

      const ease = 1 - Math.exp(-(reducedMotion ? 18 : isFocused ? 8 : 11) * safeDelta);
      mesh.position.lerp(targetPosition, ease);
      mesh.rotation.x = THREE.MathUtils.lerp(mesh.rotation.x, targetRotation.x, ease);
      mesh.rotation.y = THREE.MathUtils.lerp(mesh.rotation.y, targetRotation.y, ease);
      mesh.rotation.z = THREE.MathUtils.lerp(mesh.rotation.z, targetRotation.z, ease);
      mesh.scale.lerp(targetScale, ease);
      mesh.updateMatrixWorld();

      material.uniforms.uTime.value = reducedMotion ? 0 : clock.elapsedTime;
      material.uniforms.uHover.value = THREE.MathUtils.damp(
        material.uniforms.uHover.value,
        isHovered ? 1 : 0,
        8,
        safeDelta,
      );
      material.uniforms.uFocus.value = THREE.MathUtils.damp(
        material.uniforms.uFocus.value,
        isFocused ? 1 : 0,
        7,
        safeDelta,
      );
      material.uniforms.uMotion.value = Math.min(Math.abs(state.vx) + Math.abs(state.vy), 1.5);

      if (dom) {
        projected.setFromMatrixPosition(mesh.matrixWorld).project(camera);
        const left = (projected.x * 0.5 + 0.5) * viewWidth;
        const top = (-projected.y * 0.5 + 0.5) * viewHeight;
        const distance = Math.max(camera.position.z - mesh.position.z, 1);
        const fov = 'fov' in camera ? camera.fov : 38;
        const pixelsPerWorldUnit = viewHeight / (2 * Math.tan(THREE.MathUtils.degToRad(fov / 2)) * distance);
        const opacity = focusActive ? (isFocused ? 1 : 0) : THREE.MathUtils.clamp(0.52 + spatialScale * 0.58, 0.72, 1);
        dom.style.width = `${(CARD_WIDTH_WORLD * mesh.scale.x * pixelsPerWorldUnit).toFixed(2)}px`;
        dom.style.height = `${(CARD_HEIGHT_WORLD * mesh.scale.y * pixelsPerWorldUnit).toFixed(2)}px`;
        dom.style.transform = `translate3d(${left.toFixed(2)}px, ${top.toFixed(2)}px, 0) translate(-50%, -50%) rotateX(${targetRotation.x.toFixed(4)}rad) rotateY(${targetRotation.y.toFixed(4)}rad) rotateZ(${targetRotation.z.toFixed(4)}rad)`;
        dom.style.opacity = String(opacity);
        dom.style.zIndex = String(Math.round((mesh.position.z + 10) * 10));
        dom.dataset.focused = String(isFocused);
        dom.dataset.hovered = String(isHovered);
        dom.setAttribute('aria-hidden', focusActive && !isFocused ? 'true' : 'false');
      }
    });
  });

  return (
    <group>
      {threads.map((thread, index) => (
        <LiquidCardMesh
          key={thread.id}
          thread={thread}
          index={index}
          meshRefs={meshRefs}
          materialRefs={materialRefs}
        />
      ))}
    </group>
  );
}

function CardOverlay({
  thread,
  index,
  domRegistry,
  motion,
  hoveredId,
  onSelect,
}: {
  thread: Thread;
  index: number;
  domRegistry: DomRegistry;
  motion: React.MutableRefObject<WorkspaceMotion>;
  hoveredId: React.MutableRefObject<string | null>;
  onSelect: (id: string) => void;
}) {
  return (
    <div
      ref={(node) => {
        domRegistry.current[thread.id] = node;
      }}
      className={styles.card}
      style={{ transform: 'translate3d(-200vw, -200vh, 0)', opacity: 0 }}
      onMouseEnter={() => {
        hoveredId.current = thread.id;
        const node = domRegistry.current[thread.id];
        if (node) node.dataset.hovered = 'true';
      }}
      onMouseLeave={() => {
        if (hoveredId.current === thread.id) hoveredId.current = null;
        const node = domRegistry.current[thread.id];
        if (node) node.dataset.hovered = 'false';
      }}
      onClick={(event) => {
        event.stopPropagation();
        if (motion.current.justDragged || motion.current.dragDistance > 8) return;
        onSelect(thread.id);
      }}
      role="button"
      tabIndex={0}
      aria-label={`打开需求：${thread.title}`}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect(thread.id);
        }
      }}
    >
      <CardCopy thread={thread} index={index} />
    </div>
  );
}

function FallbackSpatialGrid({
  threads,
  motion,
  onSelect,
}: {
  threads: Thread[];
  motion: React.MutableRefObject<WorkspaceMotion>;
  onSelect: (id: string) => void;
}) {
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    let animationFrame = 0;
    let last = performance.now();

    const tick = (now: number) => {
      const delta = Math.min((now - last) / 1000, 0.05);
      last = now;
      const state = motion.current;
      if (!state.pointerDown) {
        state.x += state.vx * delta;
        state.y += state.vy * delta;
        const friction = Math.exp(-5.2 * delta);
        state.vx *= friction;
        state.vy *= friction;
      }
      threads.forEach((thread, index) => {
        const node = cardRefs.current[thread.id];
        if (!node) return;
        const slot = SLOT_COORDINATES[index % SLOT_COORDINATES.length];
        const x = wrap(slot[0] * GRID_SPACING_X + state.x, WRAP_WIDTH);
        const verticalSpacing = window.innerWidth < 640 ? 2.72 : GRID_SPACING_Y;
        const verticalWrap = GRID_ROWS * verticalSpacing;
        const y = wrap(slot[1] * verticalSpacing + state.y, verticalWrap);
        const scale = THREE.MathUtils.clamp(1.03 - Math.sqrt(x * x + y * y) * 0.04, 0.68, 1.03);
        node.style.transform = `translate(calc(50% + ${x * 84}px), calc(50% + ${y * 84}px)) translate(-50%, -50%) rotate(${(x * 0.85).toFixed(2)}deg) scale(${scale.toFixed(3)})`;
      });
      animationFrame = requestAnimationFrame(tick);
    };

    animationFrame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animationFrame);
  }, [motion, threads]);

  return (
    <div className={styles.fallbackGrid} aria-label="二维空间工作台降级视图">
      {threads.map((thread, index) => (
        <div
          key={thread.id}
          ref={(node) => {
            cardRefs.current[thread.id] = node;
          }}
          className={styles.fallbackCard}
          onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(thread.id); } }}
          style={{ transform: 'translate(-50%, -50%)' }}
          onClick={() => {
            if (!motion.current.justDragged && motion.current.dragDistance <= 8) onSelect(thread.id);
          }}
          role="button"
          tabIndex={0}
          aria-label={`打开需求：${thread.title}`}
        >
          <div className={styles.fallbackBadge}>
            <span>{categoryLabel(thread.category)}</span>
            <span>{thread.completeness}%</span>
          </div>
          <h2>{thread.title}</h2>
          <p>{STATUS_LABELS[thread.status]} · {thread.sender}</p>
        </div>
      ))}
    </div>
  );
}

function DetailFallback({ thread, onClose }: { thread: Thread; onClose: () => void }) {
  return (
    <div className={styles.detailFallback} role="dialog" aria-modal="true" aria-label={`需求详情：${thread.title}`}>
      <div className={styles.detailHeader}>
        <div>
          <div className={styles.detailKicker}>{categoryLabel(thread.category)} / 需求完成度 {thread.completeness}%</div>
          <h1 className={styles.detailTitle}>{thread.title}</h1>
        </div>
        <button className={styles.closeButton} type="button" onClick={onClose} aria-label="关闭需求详情">
          <X size={16} strokeWidth={1.4} />
        </button>
      </div>
      <p className={styles.detailNote}>只读预览 · 连接本地服务后即可查看完整邮件、回答问题并导出需求。</p>
      <div className={styles.detailGrid}>
        <section>
          <div className={styles.detailPanelLabel}>最新动态</div>
          <p className={styles.detailPreview}>{thread.preview}</p>
        </section>
        <section>
          <div className={styles.detailPanelLabel}>线程信息</div>
          <ul className={styles.detailMetaList}>
            <li><span>提出人</span><strong>{thread.sender}</strong></li>
            <li><span>状态</span><strong>{STATUS_LABELS[thread.status]}</strong></li>
            <li><span>未读</span><strong>{thread.unread_count ? `${thread.unread_count} 条消息` : '已全部读完'}</strong></li>
            <li><span>最近更新</span><strong>{relativeTime(thread.updated_at)}</strong></li>
          </ul>
        </section>
      </div>
    </div>
  );
}

export function InfiniteWorkspace({
  threads,
  settings,
  connection,
  onAutoReplyChange,
  onSyncMail,
  autoReplyPending = false,
  mailSyncPending = false,
  autoReplyError = null,
  WorkbenchShell,
  onUpdated,
}: SpatialWorkspaceProps) {
  const reducedMotion = Boolean(useReducedMotion());
  const [rendererMode, setRendererMode] = useState<'checking' | 'webgpu' | 'webgl' | 'fallback'>('checking');
  const [rendererLabel, setRendererLabel] = useState('正在检测图形能力');
  const [isDragging, setIsDragging] = useState(false);
  const [transitionId, setTransitionId] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [returning, setReturning] = useState(false);
  const motion = useRef<WorkspaceMotion>({
    x: 0,
    y: 0,
    vx: 0,
    vy: 0,
    pointerDown: false,
    pointerId: null,
    lastX: 0,
    lastY: 0,
    lastTime: 0,
    dragDistance: 0,
    justDragged: false,
  });
  const hoveredId = useRef<string | null>(null);
  const domRegistry = useRef<Record<string, HTMLDivElement | null>>({});
  const transitionTimer = useRef<number | null>(null);
  const returnTimer = useRef<number | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!detailId) return;
    const previous = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    return () => { previous?.focus(); };
  }, [detailId]);

  useEffect(() => {
    let cancelled = false;
    const canvas = document.createElement('canvas');
    const available = Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
    if (!available) {
      setRendererMode('fallback');
      setRendererLabel('CSS / 2D 降级视图');
      return () => {
        cancelled = true;
        canvas.width = 1;
        canvas.height = 1;
      };
    }

    const gpu = (navigator as Navigator & {
      gpu?: { requestAdapter: () => Promise<unknown | null> };
    }).gpu;

    if (!gpu) {
      setRendererMode('webgl');
      setRendererLabel('WebGL2 / 着色器');
    } else {
      const adapterTimeout = new Promise<null>((resolve) => {
        window.setTimeout(() => resolve(null), 1400);
      });
      void Promise.race([gpu.requestAdapter(), adapterTimeout]).then((adapter) => {
        if (cancelled) return;
        if (adapter) {
          setRendererMode('webgpu');
          setRendererLabel('WebGPU / TSL');
        } else {
          setRendererMode('webgl');
          setRendererLabel('WebGL2 / 着色器');
        }
      }).catch(() => {
        if (cancelled) return;
        setRendererMode('webgl');
        setRendererLabel('WebGL2 / 着色器');
      });
    }

    return () => {
      cancelled = true;
      canvas.width = 1;
      canvas.height = 1;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (transitionTimer.current) window.clearTimeout(transitionTimer.current);
      if (returnTimer.current) window.clearTimeout(returnTimer.current);
    };
  }, []);

  const selectedThread = detailId ? threads.find((thread) => thread.id === detailId) ?? null : null;
  const focusId = transitionId ?? (returning ? null : detailId);

  const handleSelect = useCallback((id: string) => {
    if (transitionId || detailId || motion.current.justDragged) return;
    setTransitionId(id);
    transitionTimer.current = window.setTimeout(() => {
      setTransitionId(null);
      setDetailId(id);
    }, reducedMotion ? 40 : 680);
  }, [detailId, reducedMotion, transitionId]);

  const handleClose = useCallback(() => {
    if (!detailId || returning) return;
    setReturning(true);
    returnTimer.current = window.setTimeout(() => {
      setDetailId(null);
      setReturning(false);
    }, reducedMotion ? 20 : 450);
  }, [detailId, reducedMotion, returning]);

  const handlePointerDown = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const target = event.target as HTMLElement;
    if (detailId || target.closest('button, a, input, textarea, [data-no-drag]')) return;
    const state = motion.current;
    state.pointerDown = true;
    state.pointerId = event.pointerId;
    state.lastX = event.clientX;
    state.lastY = event.clientY;
    state.lastTime = performance.now();
    state.dragDistance = 0;
    state.justDragged = false;
    setIsDragging(true);
  }, [detailId]);

  const handlePointerMove = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const state = motion.current;
    if (!state.pointerDown || state.pointerId !== event.pointerId) return;
    const now = performance.now();
    const deltaMs = Math.max(now - state.lastTime, 8);
    const dx = event.clientX - state.lastX;
    const dy = event.clientY - state.lastY;
    state.x += dx * 0.009;
    state.y += dy * 0.009;
    state.vx = (dx * 0.009) / (deltaMs / 1000);
    state.vy = (dy * 0.009) / (deltaMs / 1000);
    state.dragDistance += Math.hypot(dx, dy);
    state.lastX = event.clientX;
    state.lastY = event.clientY;
    state.lastTime = now;
    if (state.dragDistance > 8) state.justDragged = true;
    event.preventDefault();
  }, []);

  const handlePointerUp = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const state = motion.current;
    if (!state.pointerDown || state.pointerId !== event.pointerId) return;
    state.pointerDown = false;
    state.pointerId = null;
    setIsDragging(false);
    window.setTimeout(() => {
      state.justDragged = false;
      state.dragDistance = 0;
    }, 140);
  }, []);

  return (
    <div
      className={styles.shell}
      data-reduced-motion={reducedMotion}
      data-renderer={rendererMode}
      data-dragging={isDragging}
      onPointerDownCapture={handlePointerDown}
      onPointerMoveCapture={handlePointerMove}
      onPointerUpCapture={handlePointerUp}
      onPointerCancelCapture={handlePointerUp}
    >
      <div className={styles.fractureField} aria-hidden="true">
        {FRACTURE_SHARDS.map((shard) => <span className={styles.fractureShard} key={shard} />)}
      </div>
      <header className={styles.topbar} inert={Boolean(detailId)}>
        <div className={styles.brand}>
          <div className={styles.brandMark} aria-hidden="true" />
          <div>
            <div className={styles.brandName}>需求工作台</div>
            <div className={styles.brandSub}>把邮件整理成清晰、可执行的需求</div>
          </div>
        </div>
        <div className={styles.topbarActions}>
          <div className={styles.signal} title={connection === 'live' ? '已连接本地服务' : '正在使用本地演示数据'}>
            <span className={styles.signalDot} aria-hidden="true" />
            {connection === 'live' ? (settings.mail_provider === 'mock' ? '演示邮箱已连接' : '真实邮箱已连接') : '离线演示'}
          </div>
          {onSyncMail ? (
            <button
              className={styles.syncMail}
              type="button"
              onClick={() => { void onSyncMail(); }}
              disabled={mailSyncPending || connection !== 'live'}
              aria-busy={mailSyncPending}
            >
              {mailSyncPending ? '同步中……' : '同步邮件'}
            </button>
          ) : null}
          <button
            className={styles.autoReply}
            type="button"
            data-enabled={settings.auto_reply}
            onClick={() => { void onAutoReplyChange(!settings.auto_reply); }}
            aria-pressed={settings.auto_reply}
            disabled={autoReplyPending}
            aria-busy={autoReplyPending}
          >
            自动回复 <span className={styles.autoReplyIndicator} aria-hidden="true" />
          </button>
          {autoReplyError ? <div className={styles.autoReplyError} role="alert">{autoReplyError}</div> : null}
        </div>
      </header>

      <nav className={styles.threadIndex} inert={Boolean(detailId)} data-no-drag aria-label="全部邮件线程">
        <details><summary>邮件线程 <span>{String(threads.length).padStart(2, '0')}</span></summary>
          <div>{threads.map(thread => <button key={thread.id} onClick={() => handleSelect(thread.id)}><span>{thread.title}</span><small>{STATUS_LABELS[thread.status]}</small></button>)}</div>
        </details>
      </nav>
      <section className={styles.stage} inert={Boolean(detailId)} aria-label="无限需求工作台">
        {rendererMode === 'webgpu' ? (
          <>
            <WebGPUField
              threads={threads}
              motion={motion}
              focusId={focusId}
              hoveredId={hoveredId}
              domRegistry={domRegistry}
              reducedMotion={reducedMotion}
              onReady={() => setRendererLabel('WebGPU / TSL')}
              onError={() => {
                setRendererMode('webgl');
                setRendererLabel('WebGL2 / 着色器');
              }}
            />
            <div className={styles.gestureSurface} aria-hidden="true" />
            <div className={styles.cardLayer}>
              {threads.map((thread, index) => (
                <CardOverlay
                  key={thread.id}
                  thread={thread}
                  index={index}
                  domRegistry={domRegistry}
                  motion={motion}
                  hoveredId={hoveredId}
                  onSelect={handleSelect}
                />
              ))}
            </div>
          </>
        ) : rendererMode === 'webgl' ? (
          <>
            <Canvas
              className={styles.canvas}
              dpr={[1, 1.8]}
              camera={{ position: [0, 0, 12], fov: 38, near: 0.1, far: 100 }}
              gl={{ alpha: true, antialias: true, powerPreference: 'high-performance' }}
              onCreated={({ gl }) => {
                setRendererLabel(gl.capabilities.isWebGL2 ? 'WebGL2 / 着色器' : 'WebGL / 着色器');
              }}
            >
              <SceneContents
                threads={threads}
                motion={motion}
                focusId={focusId}
                hoveredId={hoveredId}
                domRegistry={domRegistry}
                reducedMotion={reducedMotion}
              />
            </Canvas>
            <div className={styles.gestureSurface} aria-hidden="true" />
            <div className={styles.cardLayer}>
              {threads.map((thread, index) => (
                <CardOverlay
                  key={thread.id}
                  thread={thread}
                  index={index}
                  domRegistry={domRegistry}
                  motion={motion}
                  hoveredId={hoveredId}
                  onSelect={handleSelect}
                />
              ))}
            </div>
          </>
        ) : rendererMode === 'fallback' || rendererMode === 'checking' ? (
          <FallbackSpatialGrid threads={threads} motion={motion} onSelect={handleSelect} />
        ) : null}

        <div className={styles.workspaceMeta}>
          <div className={styles.eyebrow}>无限需求工作台</div>
          <h1 className={styles.workspaceTitle}>留一点空间，<br /><em>想清楚再行动。</em></h1>
          <p className={styles.workspaceNote}>把散落在邮件里的信息，整理成可以执行的需求。</p>
          <div className={styles.workspaceCount}>{threads.length} 条线程 · {threads.filter(thread => thread.status === 'waiting_for_me').length} 条需要你确认</div>
        </div>

        <div className={styles.footerRail}>
          <div className={styles.gestureHint}>
            <span className={styles.gestureIcon} aria-hidden="true" />
            拖动探索 <span aria-hidden="true">/</span> 点击进入
          </div>
          <div className={styles.legend} aria-label="线程状态图例">
            <span className={styles.legendItem}><span className={styles.legendDot} /> 需要你处理</span>
            <span className={styles.legendItem}><span className={styles.legendDot} data-tone="ready" /> 可以回复</span>
            <span className={styles.legendItem}><span className={styles.legendDot} data-tone="replied" /> 已闭环</span>
          </div>
        </div>

        <div className={styles.rendererNote} aria-live="polite">
          <span>{rendererLabel}</span>
          <span aria-hidden="true">·</span>
          <span>{reducedMotion ? '已减少动态' : '实时材质'}</span>
        </div>
      </section>

      <AnimatePresence>
        {selectedThread ? (
          <motionElement.div
            key={selectedThread.id}
            className={styles.detailBackdrop}
            ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label={selectedThread.title}
            onKeyDown={(event) => { if (event.key === 'Escape') handleClose(); }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reducedMotion ? 0.02 : 0.42, ease: [0.22, 1, 0.36, 1] }}
            onPointerDown={(event) => {
              if (event.target === event.currentTarget) handleClose();
            }}
          >
            <motionElement.div
              className={styles.workbenchShell}
              initial={{ opacity: 0, y: reducedMotion ? 0 : 64, scale: reducedMotion ? 1 : 0.92 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: reducedMotion ? 0 : 18, scale: reducedMotion ? 1 : 0.985 }}
              transition={{ duration: reducedMotion ? 0.02 : 0.68, delay: reducedMotion ? 0 : 0.08, ease: [0.22, 1, 0.36, 1] }}
            >
              {WorkbenchShell && connection === 'live' ? (
                <WorkbenchShell threadId={selectedThread.id} onClose={handleClose} onUpdated={onUpdated} />
              ) : (
                <DetailFallback thread={selectedThread} onClose={handleClose} />
              )}
            </motionElement.div>
          </motionElement.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
