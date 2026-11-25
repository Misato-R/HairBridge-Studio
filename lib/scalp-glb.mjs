import {t,msg} from '../public/i18n.mjs';
import {setTaskMessage,withLanguage,requestLanguage,localizeTaskView} from './locale.mjs';
import {readFile} from 'node:fs/promises';
import {BufferAttribute,BufferGeometry,Matrix4,Quaternion,Vector3} from '../public/vendor/three.module.js';
import {meshTriangles,scalpSurface} from '../public/scalp-inset.mjs';

// Read only the static triangle geometry, in the same GLB scene frame as the viewport.
export async function readScalpSurface(file) {
  const {triangles} = readStaticGlb(await readFile(file));
  const surface = scalpSurface(triangles);
  if (!surface) throw Error(t('头皮参考没有可用于内嵌的三角面。'));
  return surface;
}

export function readStaticGlb(bytes, includeUv = false) {
  if (bytes.length < 28 || bytes.toString('ascii',0,4) !== 'glTF' || bytes.readUInt32LE(4) !== 2) {
    throw Error(t('测量参考需要使用 GLB 2.0。'));
  }
  const length = bytes.readUInt32LE(12);
  const chunk = 20+length;
  if (chunk+8 > bytes.length || bytes.toString('ascii',chunk+4,chunk+7) !== 'BIN') {
    throw Error(t('GLB 缺少内嵌网格。'));
  }
  const gltf = JSON.parse(bytes.toString('utf8',20,chunk));
  const binary = chunk+8;
  const read = (index,size) => {
    const item = gltf.accessors[index];
    const view = gltf.bufferViews[item.bufferView];
    const types = {5121:['readUInt8',1],5123:['readUInt16LE',2],5125:['readUInt32LE',4],5126:['readFloatLE',4]};
    const type = types[item.componentType];
    if (!view || view.buffer !== 0 || item.sparse || !type ||
        (size === 3 && item.componentType !== 5126) || (size === 1 && item.componentType === 5126)) {
      throw Error(t('测量需要未压缩的静态网格。'));
    }
    const [method,step] = type;
    const start = binary+(view.byteOffset ?? 0);
    const offset = start+(item.byteOffset ?? 0);
    const stride = view.byteStride ?? size*step;
    if (!Number.isSafeInteger(item.count) || item.count < 1 || stride < size*step || offset < start ||
        offset+(item.count-1)*stride+size*step > Math.min(start+view.byteLength,bytes.length)) {
      throw Error(t('GLB 的网格数据不完整。'));
    }
    const values = new (size > 1 ? Float32Array : Uint32Array)(item.count*size);
    for (let i=0;i<item.count;i++) for (let j=0;j<size;j++) values[i*size+j] = bytes[method](offset+i*stride+j*step);
    return new BufferAttribute(values,size);
  };
  const triangles = [], coordinates = [];
  const collect = (id,parent,depth=0) => {
    if (depth > 128) throw Error(t('GLB 场景层级无效。'));
    const node = gltf.nodes[id];
    const matrix = node.matrix ? new Matrix4().fromArray(node.matrix) : new Matrix4().compose(
      new Vector3(...node.translation ?? [0,0,0]),new Quaternion(...node.rotation ?? [0,0,0,1]),
      new Vector3(...node.scale ?? [1,1,1]));
    matrix.premultiply(parent);
    if (node.mesh !== undefined) for (const primitive of gltf.meshes[node.mesh].primitives) {
      if ((primitive.mode ?? 4) !== 4 || primitive.attributes.POSITION === undefined ||
          primitive.extensions?.KHR_draco_mesh_compression) continue;
      const geometry = new BufferGeometry().setAttribute('position',read(primitive.attributes.POSITION,3));
      if (primitive.indices !== undefined) geometry.setIndex(read(primitive.indices,1));
      const part = meshTriangles(geometry,matrix);
      for (const triangle of part) triangles.push(triangle);
      if (!includeUv) continue;
      const uv = primitive.attributes.TEXCOORD_0;
      const tex = uv === undefined ? null : read(uv,2);
      const accessor = gltf.accessors[uv];
      const scale = accessor?.normalized ? ({5121:255,5123:65535}[accessor.componentType] ?? 1) : 1;
      const indices = geometry.index;
      const order = matrix.determinant() < 0 ? [0,2,1] : [0,1,2];
      for (let k=0;k<part.length;k++) coordinates.push(tex ? order.map(side => {
        const index = indices ? indices.getX(k*3+side) : k*3+side;
        return [tex.getX(index)/scale,tex.getY(index)/scale];
      }) : null);
    }
    for (const child of node.children ?? []) collect(child,matrix,depth+1);
  };
  for (const node of gltf.scenes[gltf.scene ?? 0].nodes ?? []) collect(node,new Matrix4());
  return {triangles,coordinates};
}
