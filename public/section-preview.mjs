import * as THREE from 'three';
import {regionWeight, sectionOffsets, sectionStations} from './section-profile.mjs';
import {sectionFrames} from './section-frames.mjs';
import {insetScalpEnd} from './scalp-inset.mjs';

function intervalRing(rings, stations, position) {
  const end = stations.findIndex(value => value >= position);
  if (end <= 0) return rings[end < 0 ? rings.length - 1 : 0];
  const mix = (position - stations[end - 1]) / (stations[end] - stations[end - 1]);
  return rings[end - 1].map((point, i) => point.clone().lerp(rings[end][i], mix));
}

export function sectionScene(cards, settings, active, range, strands, fitted, scalp) {
  const layer = new THREE.Group();
  const teal = new THREE.Color(0x5bd6bd);
  const purple = new THREE.Color(0xb491cb);
  const muted = new THREE.Color(0x7f6d90);
  for (const [index, strand] of strands.entries()) {
    const card = cards[index], setting = settings[strand.id], chosen = strand.id === active;
    const stations = sectionStations(card);
    const fit = fitted?.[strand.id];
    const offsets = sectionOffsets(card, setting, strand.tipAt, stations, fit);
    const inset = setting?.scalpInset === undefined ? null : insetScalpEnd(card,offsets.at(-1),scalp,setting.scalpInset);
    const basis = sectionFrames(inset?.card ?? card);
    const rings = offsets.map((ring, i) => {
      const {center, width, thick} = basis[i];
      return ring.map(([x,y]) => center.clone().addScaledVector(width, x).addScaledVector(thick, y));
    });
    const positions = [], colors = [], faces = [];
    const count = rings[0].length;
    for (const [i,ring] of rings.entries()) {
      const inRange = stations[i] >= range.from && stations[i] <= range.to;
      const weight = chosen && inRange ? .45 + .55 * regionWeight(stations[i], range.from, range.to) : 0;
      const color = chosen ? purple.clone().lerp(teal, weight) : muted;
      for (const [j,point] of ring.entries()) {
        positions.push(...point.toArray());
        colors.push(color.r, color.g, color.b);
        if (i) {
          const a = (i - 1) * count + j, b = (i - 1) * count + (j + 1) % count;
          faces.push(a + count, a, b + count, b, b + count, a);
        }
      }
    }
    const last = (rings.length - 1) * count;
    for (let i = 1; i < count - 1; i++) faces.push(0,i+1,i,last,last+i,last+i+1);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions,3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors,3));
    geometry.setIndex(faces);
    geometry.computeVertexNormals();
    layer.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      vertexColors:true, roughness:.66, flatShading:count === 4, side:THREE.DoubleSide,
    })));
    const boundaries = range.boundary === undefined ? [range.from,range.to] : [range.boundary];
    if (chosen) for (const [i,boundary] of boundaries.entries()) {
      const ring = intervalRing(rings,stations,boundary);
      const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(ring),
        new THREE.LineBasicMaterial({color:i || range.boundary !== undefined ? 0xf4d8a8 : 0xa1f9e7, depthTest:false, depthWrite:false}));
      line.renderOrder = 4;
      layer.add(line);
    }
  }
  return layer;
}
