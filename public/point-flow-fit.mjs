const position = row => row.slice(0, 3);
const subtract = (a, b) => a.map((value, axis) => value - b[axis]);
const add = (a, b) => a.map((value, axis) => value + b[axis]);
const distance = (a, b) => Math.hypot(...subtract(a, b));
const length = path => path.slice(1).reduce((total, point, i) => total + distance(point, path[i]), 0);
const multiply = (a, scale) => a.map(value => value * scale);
const mix = (a, b, fraction) => add(a, multiply(subtract(b, a), fraction));
const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);

export function pointSlots(strand, state) {
  return strand.points.filter(slot => slot.id !== 'bend3' || state.thirdBend);
}

export function activeMoveFaces(slot, state) {
  if (slot && state?.expanded?.[slot.id] === true && slot.extraMoveFaces?.length) {
    return [...slot.moveFaces,...slot.extraMoveFaces];
  }
  return slot?.moveFaces;
}

export function canPlacePoint(slot, point, triangle, state) {
  if (!Array.isArray(point) || point.length !== 3 || !point.every(Number.isFinite)) return false;
  if (slot.moveFaces) return activeMoveFaces(slot,state).includes(triangle);
  return distance(point, slot.suggestion) <= slot.maxMove ||
    !!slot.extension && nearestOnRail(slot.extension.rail, point).gap <= slot.extension.radius;
}

function nearestOnRail(rail, point) {
  let nearest = {gap: Infinity};
  let offset = 0;
  for (let index = 0; index < rail.length - 1; index++) {
    const start = rail[index], edge = subtract(rail[index + 1], start);
    const span = Math.hypot(...edge);
    if (!span) continue;
    const fraction = Math.min(1, Math.max(0, dot(subtract(point, start), edge) / span ** 2));
    const gap = distance(point, add(start, multiply(edge, fraction)));
    if (gap < nearest.gap) nearest = {gap, index, offset: offset + span * fraction};
    offset += span;
  }
  return nearest;
}

function evenlySample(path, stations) {
  const points = path.filter((point, i) => !i || distance(point, path[i - 1]) > 1e-9);
  const spans = [0];
  for (let i = 1; i < points.length; i++) spans.push(spans[i - 1] + distance(points[i], points[i - 1]));
  let end = 1;
  return Array.from({length: stations}, (_, i) => {
    const arc = spans.at(-1) * i / (stations - 1);
    while (end < spans.length - 1 && spans[end] < arc) end++;
    return mix(points[end - 1], points[end], (arc - spans[end - 1]) / (spans[end] - spans[end - 1]));
  });
}

function extendForehead(rows, slot, hit, route) {
  const join = 16;
  const surfaceInset = subtract(position(rows[0]), slot.suggestion);
  const leading = slot.extension.rail.slice(1, route.index + 1).reverse();
  const front = [hit, ...leading.map(point => add(point, multiply(surfaceInset, .75))),
    ...rows.slice(0, join + 1).map(position)];
  const sampled = evenlySample(front, join + 1);
  return [...sampled.map((point, i) => [...point, ...rows[i].slice(3)]), ...rows.slice(join + 1)];
}

function interpolate(knots, station) {
  const end = knots.findIndex(knot => knot.index >= station);
  if (end === 0) return knots[0].delta;
  const left = knots[end - 1], right = knots[end];
  const fraction = (station - left.index) / (right.index - left.index);
  const weight = fraction * fraction * (3 - 2 * fraction);
  return left.delta.map((value, axis) => value + weight * (right.delta[axis] - value));
}

export function fairAnchoredPath(path, anchors) {
  // Suppress the small bends introduced by the triangulated surface first.
  // A smooth correction restores the exact control positions across the whole curve.
  let smooth = path;
  for (let pass = 0; pass < 14; pass++) {
    const current = smooth;
    smooth = current.map((point,index) => index === 0 || index === current.length-1 ? point :
      point.map((value,axis) => .5*value+.25*(current[index-1][axis]+current[index+1][axis])));
  }
  const knots = anchors.map(index => ({index,delta:subtract(path[index],smooth[index])}));
  const pinned = new Set(anchors);
  return smooth.map((point,index) => pinned.has(index) ? path[index] : add(point,interpolateCorrection(knots,index)));
}

function interpolateCorrection(knots, station) {
  const end = knots.findIndex(knot => knot.index >= station);
  if (end === 0) return knots[0].delta;
  const left = knots[end-1], right = knots[end];
  const fraction = (station-left.index)/(right.index-left.index);
  const weight = fraction**3*(10-15*fraction+6*fraction**2);
  return mix(left.delta,right.delta,weight);
}

export function guideSegments(strand, slots) {
  return slots.slice(0,-1).flatMap((slot,i) => {
    const right = slots[i+1];
    if (right.index-slot.index < 4) return [];
    const first = strand.base.seq[slot.index];
    const last = strand.base.seq[right.index];
    const limit = Math.min((first[3]+last[3])*.32,distance(position(first),position(last))*.33);
    return [{id:slot.id,label:`${i+1}–${i+2}`,start:slot.index,end:right.index,mid:Math.floor((slot.index+right.index)/2),limit}];
  });
}

export function arcWeight(segment,index) {
  const t = (index-segment.start)/(segment.end-segment.start);
  return (4*t*(1-t))**3;
}

function fairAnchoredCard(card, slots, strand, state) {
  const points = fairAnchoredPath(card.seq.map(position),slots.map(slot => slot.index));
  if (state.arcs) for (const segment of guideSegments(strand,slots)) {
    const delta = state.arcs[segment.id];
    if (!delta) continue;
    for (let i=segment.start+1;i<segment.end;i++) points[i] = add(points[i],multiply(delta,arcWeight(segment,i)));
  }
  return {...card,seq:card.seq.map((row,index) => {
    const tangent = subtract(points[Math.min(points.length-1,index+1)],points[Math.max(0,index-1)]);
    const axis = row.slice(5);
    const lengthSquared = dot(tangent,tangent);
    const aligned = lengthSquared > 1e-12 ? subtract(axis,multiply(tangent,dot(axis,tangent)/lengthSquared)) : axis;
    const size = Math.hypot(...aligned);
    return [...points[index],row[3],row[4],...(size > 1e-6 ? multiply(aligned,1/size) : axis)];
  })};
}

// Start with the measured Tripo curve. Move its centerline by the user's
// surface displacement so a click does not pull the section center to the skin.
export function fitPointFlow(strand, state) {
  const slots = pointSlots(strand, state);
  const base = strand.fittingWithoutThirdBend && !state.thirdBend
    ? strand.fittingWithoutThirdBend : strand.base;
  const start = slots[0];
  const hit = state.points[start.id]?.position;
  const route = hit && start.extension ? nearestOnRail(start.extension.rail, hit) : null;
  const extending = route && route.gap <= start.extension.radius && route.offset >= .022;
  const marks = slots.map(slot => ({index: slot.index,
    delta: subtract(extending && slot === start ? slot.suggestion :
      state.points[slot.id]?.position ?? slot.suggestion, slot.suggestion)}));
  const displaced = base.seq.map((row, i) => [...add(position(row), interpolate(marks, i)), ...row.slice(3)]);
  const after = {shape: base.shape, seq: extending ? extendForehead(displaced, start, hit, route) : displaced};
  if (strand.manual || strand.refit) return {before:strand.raw,after:fairAnchoredCard(after,slots,strand,state),hairdeck:null};
  let hairdeck = null;
  if (!strand.hairdeck) return {before: strand.raw, after, hairdeck};
  const target = after.seq.map(position);
  const hint = strand.hairdeckSource;
  const ratio = length(hint) / length(target);
  const errors = target.map((point, i) => distance(point, hint[i]) / strand.headSpan);
  if (ratio < .75 || ratio > 1.25 || errors.reduce((sum, n) => sum + n, 0) / errors.length > .09 ||
      Math.max(errors[0], errors.at(-1)) > .16) return {before: strand.raw, after, hairdeck};
  const detail = strand.hairdeck.seq.map((row, i) => subtract(position(row), position(base.seq[i])));
  const offsetsAtAnchors = slots.map(slot => ({index: slot.index, delta: detail[slot.index]}));
  hairdeck = {shape: after.shape, seq: after.seq.map((row, i) => [
    ...add(position(row), subtract(detail[i], interpolate(offsetsAtAnchors, i))), ...row.slice(3),
  ])};
  return {before: strand.raw, after, hairdeck};
}
