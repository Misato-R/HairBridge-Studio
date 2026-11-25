import {CatmullRomCurve3, Triangle, Vector3} from './vendor/three.module.js';
import {fairAnchoredPath} from './point-flow-fit.mjs';
import {surfaceTopology} from './surface-mask-cleanup.mjs';

export const minGuideAnchors = 3;
export const maxGuideAnchors = 5;
const stationsPerSpan = 16;

export function createManualGuideFitter(mesh, faceIds, topology = surfaceTopology(mesh)) {
  const selected = new Set(faceIds);
  const triangles = new Map();
  const sample = point => new Vector3(...point);
  function face(id) {
    if (!triangles.has(id)) {
      const triangle = new Triangle(...mesh.faces.slice(id*3,id*3+3).map(index =>
        sample(mesh.vertices.slice(index*3,index*3+3))));
      triangles.set(id,{triangle, center:triangle.getMidpoint(new Vector3()), normal:triangle.getNormal(new Vector3())});
    }
    return triangles.get(id);
  }

  function route(start, end) {
    const frontier = new Set([start]);
    const from = new Map(), distance = new Map([[start,0]]);
    const goal = face(end).center;
    while (frontier.size) {
      let next, estimate = Infinity;
      for (const id of frontier) {
        const score = distance.get(id) + face(id).center.distanceTo(goal);
        if (score < estimate) {next = id; estimate = score;}
      }
      if (next === end) {
        const path = [end];
        while (path.at(-1) !== start) path.push(from.get(path.at(-1)));
        return path.reverse();
      }
      frontier.delete(next);
      const a = face(next);
      for (const {id} of topology.neighbors[next]) {
        if (!selected.has(id)) continue;
        const b = face(id);
        const crease = 1 - Math.abs(a.normal.dot(b.normal));
        const cost = distance.get(next) + a.center.distanceTo(b.center) * (1 + 3 * crease);
        if (cost >= (distance.get(id) ?? Infinity)) continue;
        distance.set(id,cost);
        from.set(id,next);
        frontier.add(id);
      }
    }
    throw Error('这两个点之间没有连续的选中发面。请换视角或先检查选区。');
  }

  function anchorsOnSurface(anchors) {
    return anchors.map(mark => {
      if (!selected.has(mark?.triangle) || !Array.isArray(mark.position) ||
          mark.position.length !== 3 || !mark.position.every(Number.isFinite)) throw Error('请把点放在当前选区的可见头发上。');
      const point = sample(mark.position);
      const projected = face(mark.triangle).triangle.closestPointToPoint(point,new Vector3());
      if (point.distanceToSquared(projected) > 1e-8) throw Error('点位已偏离发面，请重新点选。');
      return {triangle:mark.triangle, point:projected};
    });
  }

  function interpolateSpan(start, end) {
    const chord = start.point.distanceTo(end.point);
    if (chord < topology.extent*.002) throw Error('相邻点太近，请拉开一点。');
    const ids = route(start.triangle,end.triangle);
    const chain = [start.point,...ids.slice(1,-1).map(id => face(id).center),end.point];
    const length = chain.slice(1).reduce((sum,point,i) => sum + point.distanceTo(chain[i]),0);
    if (length > chord*2.8) throw Error('这段绕行太远，请在同一片头发的中途补一个点。');
    const softened = chain.map((point,i) => i === 0 || i === chain.length-1 ? point :
      point.clone().multiplyScalar(.5).addScaledVector(chain[i-1],.25).addScaledVector(chain[i+1],.25));
    const curve = new CatmullRomCurve3(softened);
    const corridor = new Set(ids);
    for (const id of ids) for (const neighbor of topology.neighbors[id]) {
      if (selected.has(neighbor.id)) corridor.add(neighbor.id);
    }
    const path = curve.getSpacedPoints(stationsPerSpan).map((point,i) => {
      if (i === 0) return start;
      if (i === stationsPerSpan) return end;
      let nearest, gap = Infinity;
      const projected = new Vector3();
      for (const id of corridor) {
        face(id).triangle.closestPointToPoint(point,projected);
        const error = point.distanceToSquared(projected);
        if (error < gap) {nearest = {triangle:id,point:projected.clone()}; gap = error;}
      }
      return nearest;
    });
    return {path,corridor};
  }

  return anchors => {
    if (!Array.isArray(anchors) || anchors.length < 2 || anchors.length > maxGuideAnchors) {
      throw Error('请沿发束放置起点、经过点和发梢。');
    }
    const marks = anchorsOnSurface(anchors);
    const path = [marks[0]], corridor = new Set();
    for (let i = 1; i < marks.length; i++) {
      const span = interpolateSpan(marks[i-1],marks[i]);
      path.push(...span.path.slice(1));
      for (const id of span.corridor) corridor.add(id);
    }
    const length = path.slice(1).reduce((sum,mark,i) => sum + mark.point.distanceTo(path[i].point),0);
    const width = Math.min(length*.19,topology.extent*.085);
    const seq = path.map(({point,triangle},i) => {
      const tangent = path[Math.min(path.length-1,i+1)].point.clone().sub(path[Math.max(0,i-1)].point).normalize();
      const normal = new Vector3();
      const reference = face(triangle).normal;
      for (const mark of path.slice(Math.max(0,i-2),i+3)) {
        const candidate = face(mark.triangle).normal;
        normal.addScaledVector(candidate,candidate.dot(reference) < 0 ? -1 : 1);
      }
      normal.normalize();
      const axis = new Vector3().crossVectors(tangent,normal).normalize();
      if (axis.lengthSq() < .5) throw Error('这段发面折得太急，请调整附近的点位。');
      const t = i/(path.length-1);
      const taper = Math.min(1,.07+3*(1-t),.68+2*t);
      const thick = width*.42*taper;
      return [...point.clone().addScaledVector(normal,-thick*.38).toArray(),width*taper,thick,...axis.toArray()];
    });
    const surfacePath = fairAnchoredPath(path.map(mark => mark.point.toArray()),marks.map((_,i) => i*stationsPerSpan));
    return {card:{shape:'square',seq}, surfacePath:{seq:surfacePath},
      marks:marks.map(({point,triangle},i) => ({position:point.toArray(), triangle, index:i*stationsPerSpan})),
      faceIds:[...corridor].sort((a,b) => a-b), width};
  };
}
