import {Vector3} from '../public/vendor/three.module.js';
import {sectionFrames} from '../public/section-frames.mjs';
import {sectionStations} from '../public/section-profile.mjs';

const clamp = (value,min,max) => Math.min(max,Math.max(min,value));
const mix = (first,second,weight) => first + (second-first)*weight;
const percentile = (values,fraction) => {
  const sorted = [...values].sort((a,b) => a-b);
  const index = (sorted.length-1)*fraction;
  return mix(sorted[Math.floor(index)],sorted[Math.ceil(index)],index%1);
};

function guideSites(card) {
  const frames = sectionFrames(card);
  const bins = frames.map(() => []);
  return {frames,bins};
}

function assignFaces(triangles, faceIds, sites) {
  const center = new Vector3();
  for (const id of faceIds) {
    const triangle = triangles[id];
    triangle.getMidpoint(center);
    let best = Infinity, owner, station;
    for (const site of sites) for (const [i,frame] of site.frames.entries()) {
      const distance = center.distanceToSquared(frame.center);
      if (distance < best) {
        best = distance;
        owner = site;
        station = i;
      }
    }
    owner.bins[station].push(triangle);
  }
}

function sectionSamples(triangles, frame, reach) {
  const samples = [], delta = new Vector3(), normal = new Vector3();
  for (const tri of triangles) {
    const corners = [tri.a,tri.b,tri.c];
    const lengths = corners.map(point => delta.subVectors(point,frame.center).dot(frame.tangent));
    const crossings = corners.flatMap((point,i) => {
      const j = (i+1)%3;
      if ((lengths[i] < 0) === (lengths[j] < 0)) return [];
      return [point.clone().lerp(corners[j],lengths[i]/(lengths[i]-lengths[j])).sub(frame.center)];
    });
    if (crossings.length !== 2) continue;
    tri.getNormal(normal);
    const segment = crossings[0].distanceTo(crossings[1]);
    if (segment < 1e-8) continue;
    const count = clamp(Math.ceil(segment/(reach*.045)),2,12);
    for (let i=0;i<count;i++) {
      const point = crossings[0].clone().lerp(crossings[1],(i+.5)/count);
      const x = point.dot(frame.width), y = point.dot(frame.thick);
      if (Math.abs(x) <= reach && Math.abs(y) <= reach*.65) {
        samples.push({x,y,nx:normal.dot(frame.width),ny:normal.dot(frame.thick),weight:segment/count});
      }
    }
  }
  return samples;
}

function inferRing(samples,row,peak) {
  const [width,thick] = row.slice(3,5);
  const prior = [width/2,width/2,thick/2,thick/2,0];
  if (samples.length < 4) return {ring:prior,estimated:false};

  // Follow the exposed face near the guide. The opposite wall is often fused
  // with another lock or absent from the approved surface selection.
  const normals = samples.filter(s => Math.abs(s.x) < Math.max(width*.32,peak*.13) && Math.abs(s.ny) > .5);
  const sign = Math.sign(normals.reduce((sum,s) => sum+s.ny*s.weight,0)) || 1;
  const angles = normals.filter(s => s.ny*sign > 0).map(s => Math.atan2(-s.nx*sign,s.ny*sign));
  const angle = angles.length ? clamp(percentile(angles,.5),-.35,.35)*.72 : 0;
  const cos = Math.cos(angle), sin = Math.sin(angle);
  const local = samples.map(s => ({x:s.x*cos+s.y*sin,y:-s.x*sin+s.y*cos,ny:s.ny}));
  const lateral = local.map(s => s.x);
  const minHalf = width*.36, maxHalf = Math.max(width*1.2,peak*.57);
  const left = clamp(-percentile(lateral,.015)*1.07,minHalf,maxHalf);
  const right = clamp(percentile(lateral,.985)*1.07,minHalf,maxHalf);
  const visible = local.filter(s => s.ny*sign>.35 && Math.abs(s.x) < Math.max(left,right)*.65);
  const measured = visible.length >= 4 ? percentile(visible.map(s => s.y*sign),.80) : thick*.5;
  const outside = clamp(measured,thick*.36,Math.max(thick*.85,peak*.13));
  const inside = thick*.42;
  return {ring:[left,right,sign<0 ? outside : inside,sign>0 ? outside : inside,angle],estimated:true};
}

export function inferCoarseSections(triangles,faceIds,entries) {
  if (!faceIds.length || !entries.length) return {};
  const sites = entries.map(({card}) => guideSites(card));
  assignFaces(triangles,faceIds,sites);
  return Object.fromEntries(entries.flatMap(({id,card,tipAt=1,include},guideIndex) => {
    if (!include) return [];
    const {frames,bins} = sites[guideIndex];
    const peak = Math.max(...card.seq.map(row => row[3]));
    const estimates = frames.map((frame,i) => {
      const slice = bins.slice(Math.max(0,i-8),i+9).flat();
      return inferRing(sectionSamples(slice,frame,peak*1.35),card.seq[i],peak);
    });
    const limited = estimates.filter(item => !item.estimated).length;
    if (limited > frames.length*.55) return [];
    const weights = [1,2,3,4,5,4,3,2,1];
    const stations = sectionStations(card);
    const rings = estimates.map(({ring},i) => ring.map((value,axis) => {
      let sum = 0, total = 0;
      for (const [j,weight] of weights.entries()) {
        const sample = estimates[i+j-4];
        if (!sample) continue;
        sum += sample.ring[axis]*weight;
        total += weight;
      }
      const smoothed = mix(sum/total,value,.12);
      if (axis === 4) return smoothed;
      const fromTip = tipAt === 0 ? stations[i] : 100-stations[i];
      const t = clamp(fromTip/11,0,1);
      // A transverse slice cannot see the round termination along the guide.
      const terminal = card.seq[i][axis < 2 ? 3 : 4]/2;
      return mix(terminal,smoothed,t*t*(3-2*t));
    }));
    return [[id,{rings,roundness:58,limited}]];
  }));
}
