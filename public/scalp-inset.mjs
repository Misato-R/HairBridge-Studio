import {Box3,Triangle,Vector3} from './vendor/three.module.js';
import {sectionFrames} from './section-frames.mjs';
import {sectionStations} from './section-profile.mjs';

function buildTree(faces) {
  const box = new Box3();
  for (const {triangle} of faces) for (const point of [triangle.a,triangle.b,triangle.c]) box.expandByPoint(point);
  if (faces.length <= 18) return {box,faces};
  const size = box.getSize(new Vector3());
  const axis = size.x >= size.y && size.x >= size.z ? 'x' : size.y >= size.z ? 'y' : 'z';
  faces.sort((a,b) => a.center[axis]-b.center[axis]);
  const mid = faces.length>>1;
  return {box,left:buildTree(faces.slice(0,mid)),right:buildTree(faces.slice(mid))};
}

export function scalpSurface(triangles) {
  const items = triangles.flatMap(triangle => {
    const normal = triangle.getNormal(new Vector3());
    return normal.lengthSq() ? [{triangle,normal,center:triangle.getMidpoint(new Vector3())}] : [];
  });
  if (!items.length) return null;
  const tree = buildTree(items);
  const hit = new Vector3(), delta = new Vector3();
  const boxDistance = (box,point) => delta.copy(point).clamp(box.min,box.max).distanceToSquared(point);
  return {
    extent:tree.box.getSize(new Vector3()).length(),
    nearest(point) {
      let distance = Infinity, signed, normal;
      function search(node, lower) {
        if (lower > distance) return;
        if (node.faces) {
          for (const face of node.faces) {
            face.triangle.closestPointToPoint(point,hit);
            const gap = hit.distanceToSquared(point);
            if (gap < distance) {
              distance = gap;
              normal = face.normal;
              signed = delta.subVectors(point,hit).dot(normal);
            }
          }
          return;
        }
        const a = boxDistance(node.left.box,point), b = boxDistance(node.right.box,point);
        if (a < b) { search(node.left,a); search(node.right,b); }
        else { search(node.right,b); search(node.left,a); }
      }
      search(tree,0);
      return {distance:Math.sqrt(distance), signed, normal};
    },
  };
}

export function meshTriangles(geometry, matrix) {
  const position = geometry.getAttribute('position'), index = geometry.getIndex();
  const count = index?.count ?? position.count;
  const vertex = i => new Vector3().fromBufferAttribute(position,index ? index.getX(i) : i).applyMatrix4(matrix);
  const flipped = matrix.determinant() < 0;
  const result = [];
  for (let i=0;i+2<count;i+=3) result.push(new Triangle(vertex(i),vertex(i+(flipped ? 2 : 1)),vertex(i+(flipped ? 1 : 2))));
  return result;
}

function ringSamples(frame, outline) {
  const {center,width,thick} = frame;
  const ring = outline.map(([u,v]) => center.clone().addScaledVector(width,u).addScaledVector(thick,v));
  return [center,...ring,...ring.flatMap((point,i) => {
    const mid = point.clone().lerp(ring[(i+1)%ring.length],.5);
    return [mid,center.clone().lerp(mid,.5)];
  })];
}

// Keep the confirmed guide as the source. Only the generated copy approaches
// the head, with zero displacement and slope at the start of the blend.
export function insetScalpEnd(card, outline, surface, depth) {
  if (!surface) return null;
  const stations = sectionStations(card);
  const initial = sectionFrames(card).at(-1);
  const contact = surface.nearest(initial.center);
  if (contact.distance > surface.extent*.15) return null;
  const direction = contact.normal.clone();
  for (const point of ringSamples(initial,outline)) {
    const {normal} = surface.nearest(point);
    if (normal.dot(contact.normal) > .6) direction.add(normal);
  }
  direction.normalize().negate();
  const length = card.seq.slice(1).reduce((sum,row,i) =>
    sum+Math.hypot(...row.slice(0,3).map((value,axis)=>value-card.seq[i][axis])),0);
  const limit = Math.min(surface.extent*.12,length*.25);
  // The editable Bézier fit may differ slightly from the samples.
  const target = -(depth/1000+.0018);
  function probe(shift) {
    const span = Math.min(57,Math.max(16,230*shift/length));
    const offsets = stations.map(percent => {
      const t = Math.max(0,1-(100-percent)/span);
      return direction.clone().multiplyScalar(shift*t*t*(3-2*t)).toArray();
    });
    const seq = card.seq.map((row,i) => [
      ...row.slice(0,3).map((value,axis)=>value+offsets[i][axis]),...row.slice(3),
    ]);
    const adjusted = {...card,seq};
    const points = ringSamples(sectionFrames(adjusted).at(-1),outline);
    return {card:adjusted,offsets,edge:Math.max(...points.map(point=>surface.nearest(point).signed)),shift,span};
  }
  const initialProbe = probe(0);
  if (initialProbe.edge <= target) return initialProbe;
  let low = 0, high, result;
  for (let i=1;i<=12;i++) {
    const tested = probe(limit*i/12);
    if (tested.edge <= target) { high = tested.shift; result = tested; break; }
    low = tested.shift;
  }
  if (!result) return null;
  for (let i=0;i<10;i++) {
    const tested = probe((low+high)/2);
    if (tested.edge <= target) { high = tested.shift; result = tested; }
    else low = tested.shift;
  }
  return result;
}
