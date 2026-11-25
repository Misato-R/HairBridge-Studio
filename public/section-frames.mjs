import {Quaternion, Vector3} from './vendor/three.module.js';

const stencil = [-1/12, 2/3, 0, -2/3, 1/12];

// Match the transported width axis used when Blender builds the SHP profile.
export function sectionFrames(card) {
  const centers = card.seq.map(row => new Vector3(...row.slice(0,3)));
  const tangents = centers.map((_, i) => {
    if (centers.length < 5) return centers.at(-1).clone().sub(centers[0]).normalize();
    const start = Math.min(Math.max(i - 2, 0), centers.length - 5);
    return stencil.reduce((value, weight, j) => value.addScaledVector(centers[start + j], weight),
      new Vector3()).normalize();
  });
  const axis = new Vector3(...card.seq[0].slice(5,8));
  return centers.map((center, i) => {
    const tangent = tangents[i];
    if (i) axis.applyQuaternion(new Quaternion().setFromUnitVectors(tangents[i-1], tangent));
    axis.addScaledVector(tangent, -axis.dot(tangent)).normalize();
    return {center,tangent,width:axis.clone(),thick:new Vector3().crossVectors(axis,tangent)};
  });
}
