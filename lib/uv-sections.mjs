import {Box3,Vector3} from '../public/vendor/three.module.js';
import {sectionFrames} from '../public/section-frames.mjs';
import {defaultSection,sectionOffsets,sectionStations} from '../public/section-profile.mjs';
import {coherentSections} from './section-trend.mjs';

const clamp = (n,min,max) => Math.max(min,Math.min(n,max));
const mix = (a,b,t) => a+(b-a)*t;
const pointKey = point => point.toArray().map(value => Math.round(value*1e6)).join(',');

function guideSite(entry) {
  const stations = sectionStations(entry.card).map(value => value/100);
  const frames = sectionFrames(entry.card);
  const segments = frames.slice(0,-1).map(({center},i) => {
    const delta = frames[i+1].center.clone().sub(center);
    return {center,delta,length:delta.lengthSq(),i};
  }).filter(segment => segment.length > 1e-14);
  const peakWidth = Math.max(...entry.card.seq.map(row => row[3]));
  const site = {stations,frames,segments,peakWidth,faces:[]};
  for (const segment of segments) segment.site = site;
  if (segments.length > 128) site.tree = segmentTree([...segments]);
  return site;
}

function segmentTree(segments) {
  const box = new Box3();
  const end = new Vector3();
  for (const segment of segments) {
    box.expandByPoint(segment.center);
    box.expandByPoint(end.copy(segment.center).add(segment.delta));
  }
  if (segments.length <= 12) return {box,segments};
  const size = box.getSize(new Vector3());
  const axis = size.x >= size.y && size.x >= size.z ? 'x' : size.y >= size.z ? 'y' : 'z';
  segments.sort((a,b) => (a.center[axis]+a.delta[axis]/2)-(b.center[axis]+b.delta[axis]/2));
  const mid = segments.length >> 1;
  return {box,left:segmentTree(segments.slice(0,mid)),right:segmentTree(segments.slice(mid))};
}

function nearestProjection(point,segments,tree,limit) {
  let best = Infinity, v = 0, owner;
  function measure({i,center,delta,length,site}) {
    const x = point.x-center.x, y = point.y-center.y, z = point.z-center.z;
    const along = clamp((x*delta.x+y*delta.y+z*delta.z)/length,0,1);
    const sq = (x-along*delta.x)**2+(y-along*delta.y)**2+(z-along*delta.z)**2;
    if (sq < best && (!limit || sq < Math.max(.012,site.peakWidth*1.4)**2)) {
      best = sq;
      v = mix(site.stations[i],site.stations[i+1],along);
      owner = site;
    }
  }
  if (!tree) {
    for (const segment of segments) measure(segment);
  } else {
    const scratch = new Vector3();
    const distance = node => scratch.copy(point).clamp(node.box.min,node.box.max).distanceToSquared(point);
    function visit(node, bound) {
      if (bound > best) return;
      if (node.segments) {
        for (const segment of node.segments) measure(segment);
        return;
      }
      const a = distance(node.left), b = distance(node.right);
      if (a < b) {visit(node.left,a);visit(node.right,b);}
      else {visit(node.right,b);visit(node.left,a);}
    }
    visit(tree,distance(tree));
  }
  return {v,owner};
}

function assign(mesh, sites) {
  const center = new Vector3();
  const segments = sites.flatMap(site => site.segments);
  const tree = segments.length > 1024 ? segmentTree([...segments]) : null;
  for (const [i,triangle] of mesh.triangles.entries()) {
    triangle.getMidpoint(center);
    // A small fixed margin allows an inner wall to participate in the slice.
    const {owner} = nearestProjection(center,segments,tree,true);
    if (!owner) continue;
    const points = [triangle.a,triangle.b,triangle.c];
    const longitudinal = points.map(point => nearestProjection(point,owner.segments,owner.tree,false).v);
    if (Math.max(...longitudinal)-Math.min(...longitudinal) > .24) continue;
    owner.faces.push({points,longitudinal,uv:mesh.coordinates[i],area:triangle.getArea()});
  }
}

function fitUvAxis(faces, axis) {
  const chartSeams = new Map();
  let weight = 0, cx = 0, cy = 0, xx = 0, yy = 0, xy = 0, seams = 0;
  for (const face of faces) {
    if (!face.uv || !face.area) continue;
    for (const [i,point] of face.points.entries()) {
      const u = face.uv[i][axis], v = face.longitudinal[i], area = face.area;
      const key = pointKey(point), previous = chartSeams.get(key);
      if (previous !== undefined && Math.abs(u-previous) > .015) seams++;
      chartSeams.set(key,u);
      weight += area; cx += area*u; cy += area*v;
      xx += area*u*u; yy += area*v*v; xy += area*u*v;
    }
  }
  if (weight <= 0 || seams > chartSeams.size*.035) return null;
  const vx = xx-cx*cx/weight, vy = yy-cy*cy/weight, cov = xy-cx*cy/weight;
  if (vx <= 0 || vy <= 0) return null;
  const slope = cov/vx, intercept = (cy-slope*cx)/weight;
  const correlation = Math.abs(cov/Math.sqrt(vx*vy));
  if (correlation < .92) return null;
  let low = Infinity, high = -Infinity;
  for (const {uv} of faces) for (const pair of uv ?? []) {
    const level = pair[axis]*slope+intercept;
    low = Math.min(low,level);
    high = Math.max(high,level);
  }
  if (low > .14 || high < .86) return null;
  return {axis,slope,intercept,correlation};
}

function stationSamples(site, native) {
  const samples = site.stations.map(() => []);
  for (const face of site.faces) {
    if (native && !face.uv) continue;
    const levels = native ? face.uv.map(pair => pair[native.axis]*native.slope+native.intercept) : face.longitudinal;
    const low = Math.min(...levels), high = Math.max(...levels);
    if (high-low > .26) continue;
    let start = 0, end = site.stations.length;
    while (start < end) {
      const mid = (start+end)>>1;
      if (site.stations[mid] < low) start = mid+1;
      else end = mid;
    }
    for (let i=start; i<site.stations.length && site.stations[i]<high; i++) {
      const t = site.stations[i];
      const crossing = face.points.flatMap((point,j) => {
        const k = (j+1)%3;
        if ((levels[j] <= t) === (levels[k] <= t)) return [];
        return [point.clone().lerp(face.points[k],(t-levels[j])/(levels[k]-levels[j]))];
      });
      if (crossing.length !== 2) continue;
      for (const point of crossing) samples[i].push(point);
    }
  }
  return samples;
}

function percentile(sorted,fraction) {
  const index = (sorted.length-1)*fraction;
  return mix(sorted[Math.floor(index)],sorted[Math.ceil(index)],index%1);
}

function dimensions(points,{center,tangent,width,thick},[left,right,bottom,top,angle]) {
  const c = Math.cos(angle), s = Math.sin(angle);
  const window = Math.max(left+right,.006);
  const height = Math.max(top+bottom,.003);
  const samples = points.flatMap(point => {
    const distance = point.clone().sub(center);
    const x = distance.dot(width), y = distance.dot(thick);
    const u = x*c+y*s, v = -x*s+y*c;
    if (Math.abs(u) > window || Math.abs(v) > Math.max(height*1.8,window*.56) ||
        Math.abs(distance.dot(tangent)) > Math.max(.006,window*.32)) return [];
    return [[u,v]];
  });
  if (samples.length < 8) return [null,null];
  const xs = samples.map(value => value[0]).sort((a,b) => a-b);
  const ys = samples.map(value => value[1]).sort((a,b) => a-b);
  const a = percentile(xs,.06), b = percentile(xs,.94);
  const lo = percentile(ys,.06), hi = percentile(ys,.94);
  return [a < -.12*window && b > .12*window ? b-a : null,
    lo < -.12*height && hi > .12*height ? hi-lo : null];
}

function priorProfiles(entry) {
  const {card,setting,fitted,tipAt} = entry;
  return sectionOffsets(card,setting,tipAt,undefined,fitted).map((outline,i) => {
    const angle = fitted?.rings[i]?.[4] ?? 0;
    const c = Math.cos(angle), s = Math.sin(angle);
    const x = outline.map(([u,v]) => u*c+v*s), y = outline.map(([u,v]) => -u*s+v*c);
    return [-Math.min(...x),Math.max(...x),-Math.min(...y),Math.max(...y),angle];
  });
}

function fitStrand(entry, site) {
  const prior = priorProfiles(entry);
  const width = prior.map(([a,b]) => a+b);
  const height = prior.map(([, ,a,b]) => a+b);
  if (width.some(value => value < 1e-7) || height.some(value => value < 1e-7)) return null;
  const native = [fitUvAxis(site.faces,1),fitUvAxis(site.faces,0)].filter(Boolean)
    .sort((a,b) => b.correlation-a.correlation)[0];
  let samples = stationSamples(site,native);
  let measurement = native ? 'mesh-uv' : 'guide-uv';
  if (native && samples.filter(points => points.length>=8).length < site.stations.length*.55) {
    samples = stationSamples(site,null);
    measurement = 'guide-uv';
  }
  const observations = samples.map((points,i) => dimensions(points,site.frames[i],prior[i]));
  const confidence = measurement === 'mesh-uv' ? [.65,.55] : [.27,.34];
  const fit = coherentSections(observations.map(value => value[0]),observations.map(value => value[1]),
    width,height,confidence);
  if (fit.retained[0] < Math.max(3,site.stations.length*.37)) return null;
  const last = prior.length-1;
  const rings = prior.map(([left,right,bottom,top,angle],i) => {
    if (i === 0 || i === last) return prior[i];
    const [w,h] = fit.dimensions.map(axis => axis[i]);
    // Preserve the handedness and roll of the user's section, but soften local
    // variation in the left/right and inner/outer split.
    const neighbors = prior.slice(Math.max(0,i-5),i+6);
    const lateral = neighbors.reduce((sum,[a,b]) => sum+a/(a+b),0)/neighbors.length;
    const depth = neighbors.reduce((sum, [, ,a,b]) => sum+a/(a+b),0)/neighbors.length;
    const weight = Math.min(1,i/6,(last-i)/6);
    const x = mix(left/(left+right),lateral,weight);
    const y = mix(bottom/(bottom+top),depth,weight);
    return [w*x,w*(1-x),h*y,h*(1-y),angle];
  });
  const existing = entry.setting;
  const setting = {...defaultSection,from:0,to:100,
    roundness:existing?.roundness ?? entry.fitted?.roundness ?? 0,
    profile:existing?.profile ?? (entry.fitted || (existing && !existing.originalOutline) ? undefined : 'four')};
  if (setting.profile === undefined) delete setting.profile;
  if (existing?.ridge !== undefined) setting.ridge = existing.ridge;
  if (existing?.scalpInset !== undefined) setting.scalpInset = existing.scalpInset;
  if (existing?.ends) {
    const ends = Object.fromEntries(Object.entries(existing.ends)
      .filter(([,end]) => end.outline && end.outline !== 'inherit')
      .map(([key,end]) => [key,{outline:end.outline}]));
    if (Object.keys(ends).length) {
      setting.ends = ends;
      if (existing.endsAtSelection) {
        setting.endsAtSelection = true;
        setting.from = existing.from;
        setting.to = existing.to;
      }
    }
  }
  const data = {rings,roundness:setting.roundness,limited:site.stations.length-fit.retained[1],
    uvFit:{measurement,trend:fit.trend,peakPercent:Math.round(site.stations[fit.peak]*100),
      rejected:fit.rejected,stations:site.stations.length,measuredWidth:fit.retained[0],measuredThickness:fit.retained[1]}};
  return {data,setting};
}

export function inferUvSections(mesh, entries) {
  const sites = entries.map(guideSite);
  assign(mesh,sites);
  return Object.fromEntries(entries.flatMap((entry,i) => {
    if (entry.include === false) return [];
    const fit = fitStrand(entry,sites[i]);
    return fit ? [[entry.id,fit]] : [];
  }));
}
