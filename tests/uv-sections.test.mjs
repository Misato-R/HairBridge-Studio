import assert from 'node:assert/strict';
import {test} from 'node:test';
import {Triangle,Vector3} from '../public/vendor/three.module.js';
import {coherentSections} from '../lib/section-trend.mjs';
import {inferUvSections} from '../lib/uv-sections.mjs';
import {sectionOffsets} from '../public/section-profile.mjs';

function verifyTrend(axis,peak) {
  axis.slice(1).forEach((value,i) => {
    assert.ok((i < peak ? value-axis[i] : axis[i]-value) >= -1e-12);
  });
}

test('rejects a local spike and fits monotone and single-peak section envelopes', () => {
  const patterns = [
    {kind:'decreasing',values:[10,9,8,7,6,5,4,3,2]},
    {kind:'increasing',values:[2,3,4,5,6,7,8,9,10]},
    {kind:'single-peak',values:[2,3,5,7,9,7,5,4,2]},
  ];
  for (const {kind,values} of patterns) {
    const samples = [...values];
    samples[3] = 45;
    const fit = coherentSections(samples,samples,values,values);
    assert.equal(fit.trend,kind);
    assert.equal(fit.rejected,2);
    for (const axis of fit.dimensions) {
      verifyTrend(axis,fit.peak);
      assert.ok(Math.max(...axis)<=10.00001);
      assert.ok(Math.abs(axis[0]-values[0])<1e-8);
      assert.ok(Math.abs(axis.at(-1)-values.at(-1))<1e-8);
    }
  }
});

test('samples a flow-aligned native UV chart and falls back to guide coordinates', () => {
  const card = {shape:'square',seq:Array.from({length:21},(_,i) => {
    const v = i/20;
    return [0,v*.25,0,.036+.024*Math.sin(v*Math.PI),.024,1,0,0];
  })};
  const triangles = [], coordinates = [];
  for (let i=0;i<20;i++) for (let j=0;j<24;j++) {
    const vertex = (k,l) => {
      const v = k/20, u = l/24;
      const w = (card.seq[k][3]/2)*Math.cos(u*Math.PI*2);
      const z = (card.seq[k][4]/2)*Math.sin(u*Math.PI*2);
      return [new Vector3(w,v*.25,z),[u,v]];
    };
    const a=vertex(i,j),b=vertex(i,j+1),c=vertex(i+1,j),d=vertex(i+1,j+1);
    for (const corners of [[a,b,c],[b,d,c]]) {
      triangles.push(new Triangle(...corners.map(([point]) => point)));
      coordinates.push(corners.map(([,uv]) => uv));
    }
  }
  const entry = {id:'strand',card,tipAt:1};
  const native = inferUvSections({triangles,coordinates},[entry]).strand;
  const guide = inferUvSections({triangles,coordinates:[]},[entry]).strand;
  assert.equal(native.data.uvFit.measurement,'mesh-uv');
  assert.equal(guide.data.uvFit.measurement,'guide-uv');
  assert.equal(native.data.uvFit.trend,'single-peak');
  assert.ok(native.data.uvFit.measuredThickness>=18);
  const offsets = sectionOffsets(card,native.setting,1,undefined,native.data);
  assert.deepEqual(offsets[0],sectionOffsets(card,undefined,1)[0]);
  assert.deepEqual(offsets.at(-1),sectionOffsets(card,undefined,1).at(-1));
});
