// Work on shared mesh edges so nearby overlapping hair does not join the mask.
export function surfaceTopology({vertices,faces}) {
  const count = faces.length / 3;
  const neighbors = Array.from({length:count}, () => []);
  const areas = new Float64Array(count);
  const normals = new Float64Array(faces.length);
  const edges = new Map();
  const low = [Infinity,Infinity,Infinity], high = [-Infinity,-Infinity,-Infinity];
  for (let i = 0; i < vertices.length; i++) {
    const axis = i % 3;
    low[axis] = Math.min(low[axis],vertices[i]);
    high[axis] = Math.max(high[axis],vertices[i]);
  }
  for (let id = 0; id < count; id++) {
    const triangle = faces.slice(id*3,id*3+3);
    const [a,b,c] = triangle.map(index => vertices.slice(index*3,index*3+3));
    const ab = b.map((value,i) => value-a[i]), ac = c.map((value,i) => value-a[i]);
    const cross = [ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0]];
    const doubleArea = Math.hypot(...cross);
    areas[id] = doubleArea/2;
    if (doubleArea) normals.set(cross.map(value => value/doubleArea),id*3);
    for (let j = 0; j < 3; j++) {
      const from = triangle[j], to = triangle[(j+1)%3];
      if (from === to) continue;
      const key = from < to ? `${from}:${to}` : `${to}:${from}`;
      const edge = edges.get(key);
      if (edge) edge.ids.push(id);
      else edges.set(key,{ids:[id],length:Math.hypot(...[0,1,2].map(i => vertices[from*3+i]-vertices[to*3+i]))});
    }
  }
  for (const {ids,length} of edges.values()) {
    if (ids.length !== 2 || ids[0] === ids[1]) continue;
    const [a,b] = ids;
    const alignment = Math.min(1,Math.abs(normals[a*3]*normals[b*3]+normals[a*3+1]*normals[b*3+1]+normals[a*3+2]*normals[b*3+2]));
    // Along a crease it costs less to keep the existing boundary.
    const cost = length*(.34+.66*alignment**4);
    neighbors[a].push({id:b,cost});
    neighbors[b].push({id:a,cost});
  }
  const ordered = [...areas].filter(area => area > 0).sort((a,b) => a-b);
  return {vertices,faces,neighbors,areas,faceArea:ordered[Math.floor(ordered.length/2)] ?? 0,
    extent:Math.hypot(...high.map((value,i) => value-low[i]))};
}

function components(mask, value, topology) {
  const {neighbors,areas,vertices,faces} = topology;
  const labels = new Int32Array(mask.length).fill(-1);
  const sets = [];
  for (let start = 0; start < mask.length; start++) {
    if (mask[start] !== value || labels[start] !== -1) continue;
    const ids = [start], label = sets.length;
    labels[start] = label;
    let area = 0, open = false;
    const low = [Infinity,Infinity,Infinity], high = [-Infinity,-Infinity,-Infinity];
    for (let i = 0; i < ids.length; i++) {
      const id = ids[i];
      area += areas[id];
      open ||= neighbors[id].length !== 3;
      for (let j = 0; j < 3; j++) {
        const vertex = faces[id*3+j];
        for (let axis = 0; axis < 3; axis++) {
          const coord = vertices[vertex*3+axis];
          low[axis] = Math.min(low[axis],coord);
          high[axis] = Math.max(high[axis],coord);
        }
      }
      for (const edge of neighbors[id]) if (mask[edge.id] === value && labels[edge.id] === -1) {
        labels[edge.id] = label;
        ids.push(edge.id);
      }
    }
    sets.push({ids,area,open,span:Math.hypot(...high.map((value,i) => value-low[i]))});
  }
  return {labels,sets};
}

export function cleanSurfaceMask(topology, input, protectedFaces = new Set()) {
  const {areas,neighbors,faceArea,extent} = topology;
  if (!input.length || !faceArea) return {faces:[...input],added:0,removed:0};
  const original = new Uint8Array(neighbors.length);
  for (const id of input) original[id] = 1;
  const mask = original.slice();
  const initial = components(mask,1,topology).sets;
  const largest = initial.reduce((best,item) => item.area > best.area ? item : best,initial[0]);
  // Keep isolated intentional selections and limit cleanup to small spots.
  if (largest.ids.length < 12) return {faces:[...input],added:0,removed:0};
  const areaLimit = Math.min(26*faceArea,largest.area*.02);
  const spanLimit = Math.min(extent*.038,Math.sqrt(faceArea)*10);
  const small = part => part.ids.length <= 64 && part.area <= areaLimit && part.span <= spanLimit;
  for (const part of initial) if (part !== largest && small(part)) {
    for (const id of part.ids) mask[id] = 0;
  }

  const {labels} = components(mask,1,topology);
  for (const hole of components(mask,0,topology).sets) {
    if (hole.open || !small(hole) || hole.ids.some(id => protectedFaces.has(id))) continue;
    const bordering = new Set(hole.ids.flatMap(id => neighbors[id].filter(edge => mask[edge.id]).map(edge => labels[edge.id])));
    if (bordering.size === 1) for (const id of hole.ids) mask[id] = 1;
  }

  // One pass clips little teeth and fills small notches without walking the
  // boundary across the mesh or merging two separately selected pieces.
  const snapshot = mask.slice();
  const merged = components(snapshot,1,topology).labels;
  const corrected = [];
  for (let id = 0; id < snapshot.length; id++) {
    if (neighbors[id].length !== 3 || areas[id] > 2.3*faceArea || (!snapshot[id] && protectedFaces.has(id))) continue;
    if (mask[id] !== original[id]) continue;
    const opposite = neighbors[id].filter(edge => snapshot[edge.id] !== snapshot[id]);
    if (opposite.length < 2) continue;
    const oldCost = opposite.reduce((sum,edge) => sum+edge.cost,0);
    const newCost = neighbors[id].reduce((sum,edge) => snapshot[edge.id] === snapshot[id] ? sum+edge.cost : sum,0);
    if (oldCost <= newCost*1.65) continue;
    if (!snapshot[id] && new Set(opposite.map(edge => merged[edge.id])).size !== 1) continue;
    corrected.push(id);
  }
  // Adjacent opposite flips would just swap a noisy boundary back and forth.
  const changes = new Set(corrected);
  for (const id of corrected) if (!neighbors[id].some(edge => changes.has(edge.id) && snapshot[id] !== snapshot[edge.id])) {
    mask[id] = 1-snapshot[id];
  }
  const faces = [];
  let added = 0, removed = 0;
  for (let id = 0; id < mask.length; id++) {
    if (mask[id]) {faces.push(id);if (!original[id]) added++;}
    else if (original[id]) removed++;
  }
  return {faces,added,removed};
}
