/** 三维机制地图：把真实 10×7 坐标映射成节点，状态控制高度/颜色，点击选择证据。
 * 按需渲染限制后台 GPU 负担；不使用随机装饰点或远程模型，WebGL 不可用时回到二维。
 */
import { Component, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CanvasTexture, SRGBColorSpace, CubicBezierCurve3, Vector3 } from 'three';
import type { Cell, Result } from './control-types';

const colors = { active: '#dcf58b', measured: '#44d7b6', rejected: '#d69972', pending: '#2c6568' };

/** 管理轨道控制生命周期；输入复位版本，返回空节点，视角不影响研究状态。 */
function Controls({ reset }: { reset: number }) {
  const { camera, gl, invalidate } = useThree();
  useEffect(() => {
    camera.position.set(10.5, 12.5, 14);
    const controls = new OrbitControls(camera, gl.domElement);
    controls.target.set(0, 0, 0);
    controls.minDistance = 10; controls.maxDistance = 30;
    controls.minPolarAngle = .15; controls.maxPolarAngle = Math.PI / 2.15;
    controls.enablePan = false;
    const onChange = () => invalidate();
    controls.addEventListener('change', onChange);
    controls.update(); invalidate();
    return () => { controls.removeEventListener('change', onChange); controls.dispose(); };
  }, [camera, gl, invalidate, reset]);
  return null;
}

/** 用本地画布绘制坐标标签；输入文本，返回纹理，避免字体网络依赖。 */
function Label({ text, position }: { text: string; position: [number, number, number] }) {
  const texture = useMemo(() => {
    const canvas = document.createElement('canvas'); canvas.width = 128; canvas.height = 64;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('无法创建坐标标签');
    context.fillStyle = '#c4ded0'; context.font = '500 30px monospace'; context.textAlign = 'center';
    context.fillText(text, 64, 43);
    const result = new CanvasTexture(canvas); result.colorSpace = SRGBColorSpace; return result;
  }, [text]);
  useEffect(() => () => texture.dispose(), [texture]);
  return <mesh position={position} rotation={[-Math.PI / 2, 0, 0]}><planeGeometry args={[.9, .45]} /><meshBasicMaterial map={texture} transparent depthWrite={false} /></mesh>;
}

/** 提供有选择状态的模型节点；输入研究坐标，返回可点击网格柱。 */
function Node({ cell, selected, onSelect }: { cell: Cell; selected: boolean; onSelect: (id: string) => void }) {
  const [hover, setHover] = useState(false);
  const x = (cell.form - 4) * 1.22, z = (Number(cell.family.slice(1)) - 5.5) * 1.13;
  const height = { active: 1.85, measured: 1.05, rejected: .5, pending: .22 }[cell.display_state];
  const color = selected || hover ? '#edffb9' : colors[cell.display_state];
  return <group position={[x, 0, z]}>
    <mesh position={[0, height / 2, 0]} onClick={e => { e.stopPropagation(); onSelect(cell.id); }}
      onPointerOver={e => { e.stopPropagation(); setHover(true); }} onPointerOut={() => setHover(false)}>
      <boxGeometry args={[.84, height, .76]} /><meshStandardMaterial color={color} roughness={.35} metalness={.4}
        emissive={color} emissiveIntensity={selected || cell.display_state === 'active' ? .35 : .035} />
    </mesh>
    <mesh position={[0, .014, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <ringGeometry args={[.47, .49, 4]} /><meshBasicMaterial color={color} transparent opacity={selected ? 1 : .25} />
    </mesh>
    {(selected || cell.display_state === 'active') && <mesh position={[0, height + .18, 0]} rotation={[0, Math.PI / 4, 0]}>
      <octahedronGeometry args={[.11]} /><meshBasicMaterial color="#efffc4" /></mesh>}
  </group>;
}

/** 连接实际父子结构；输入可定位的两个研究坐标，输出上拱曲线，绝不生成假谱系。 */
function LineageLink({ source, target, donor }: { source: Cell; target: Cell; donor: boolean }) {
  const curve = useMemo(() => {
    const start = new Vector3((source.form - 4) * 1.22, 1.2, (Number(source.family.slice(1)) - 5.5) * 1.13);
    const end = new Vector3((target.form - 4) * 1.22, 1.2, (Number(target.family.slice(1)) - 5.5) * 1.13);
    const same = source.id === target.id;
    return new CubicBezierCurve3(start, start.clone().add(new Vector3(same ? 1 : 0, 2.3, -.8)),
      end.clone().add(new Vector3(same ? -1 : 0, 2.3, .8)), end);
  }, [source.id, source.form, source.family, target.id, target.form, target.family]);
  return <mesh><tubeGeometry args={[curve, 40, .023, 6, false]} /><meshBasicMaterial color={donor ? '#75bcda' : '#d6ed8c'} transparent opacity={.8} /></mesh>;
}

/** 捕获 GPU 创建或上下文丢失；输入备用视图，异常时保留可访问的二维地图。 */
class SceneBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

/** 渲染实时地图；输入坐标与选择回调，返回三维场景或诚实的降级提示。 */
export default function ResearchScene({ cells, rows, selected, onSelect, reset, fallback }: {
  cells: Cell[]; rows: Result[]; selected?: string; onSelect: (id: string) => void; reset: number; fallback: ReactNode;
}) {
  return <SceneBoundary fallback={fallback}><Canvas frameloop="demand" dpr={[1, 1.5]}
    camera={{ position: [12, 14, 16], fov: 40 }} gl={{ antialias: true, alpha: true }} fallback={fallback}>
    <ambientLight intensity={1.3} /><directionalLight position={[5, 14, 8]} intensity={3} color="#dcfff0" />
    <pointLight position={[-6, 5, -5]} intensity={45} color="#57a9c3" />
    <group rotation={[0, -.08, 0]}>
      <mesh position={[0, -.28, 0]}><boxGeometry args={[10.3, .5, 13]} /><meshStandardMaterial color="#11272b" metalness={.5} roughness={.35} /></mesh>
      <gridHelper args={[13, 26, '#255354', '#183b3d']} position={[0, -.018, 0]} />
      {cells.map(cell => <Node key={cell.id} cell={cell} selected={cell.id === selected} onSelect={onSelect} />)}
      {rows.flatMap(row => [row.spec.lineage.parent, row.spec.lineage.donor].map((id, i) => {
        const parent = rows.find(candidate => candidate.id === id);
        const source = cells.find(cell => cell.family === parent?.family && cell.form === parent?.form);
        const target = cells.find(cell => cell.family === row.family && cell.form === row.form);
        return source && target ? <LineageLink key={row.id + '-' + i} source={source} target={target} donor={i === 1} /> : null;
      }))}
      {Array.from({ length: 10 }, (_, i) => <Label key={'m' + i} text={'M' + (i + 1)} position={[-4.85, .04, (i - 4.5) * 1.13]} />)}
      {Array.from({ length: 7 }, (_, i) => <Label key={'f' + i} text={'F' + (i + 1)} position={[(i - 3) * 1.22, .04, 6.05]} />)}
    </group><Controls reset={reset} />
  </Canvas></SceneBoundary>;
}