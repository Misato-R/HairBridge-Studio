import assert from 'node:assert/strict';
import test from 'node:test';
import {cleanSurfaceMask,surfaceTopology} from '../public/surface-mask-cleanup.mjs';

function grid(width,height) {
  const vertices = [], faces = [];
  for (let y=0;y<=height;y++) for (let x=0;x<=width;x++) vertices.push(x,y,0);
  for (let y=0;y<height;y++) for (let x=0;x<width;x++) {
    const a = y*(width+1)+x, b = a+1, c = a+width+1, d = c+1;
    faces.push(a,b,d,a,d,c);
  }
  return {topology:surfaceTopology({vertices,faces}),cell:(x,y) => [2*(y*width+x),2*(y*width+x)+1]};
}

test('clean small selection specks and holes without clipping a long separate strand',() => {
  const {topology,cell} = grid(64,48);
  const chosen = new Set();
  for (let y=8;y<25;y++) for (let x=7;x<28;x++) for (const id of cell(x,y)) chosen.add(id);
  const hole = cell(17,16);
  const speck = cell(37,9);
  const longStrand = Array.from({length:11},(_,index) => cell(46,8+index)).flat();
  const [edgeTooth] = cell(10,25);
  for (const id of hole) chosen.delete(id);
  for (const id of [...speck,...longStrand,edgeTooth]) chosen.add(id);

  const input = [...chosen].sort((a,b)=>a-b);
  const cleaned = cleanSurfaceMask(topology,input);
  const selected = new Set(cleaned.faces);
  assert.ok(hole.every(id => selected.has(id)));
  assert.ok(speck.every(id => !selected.has(id)));
  assert.ok(longStrand.every(id => selected.has(id)));
  assert.equal(selected.has(edgeTooth),false);
  assert.equal(cleaned.added,2);
  assert.equal(cleaned.removed,3);
  assert.ok(hole.every(id => !input.includes(id)));
});

test('leave faces in a confirmed neighboring region and retain a small standalone selection',() => {
  const {topology,cell} = grid(64,48);
  const [protectedFace,otherFace] = cell(16,10);
  const chosen = [];
  for (let y=7;y<22;y++) for (let x=8;x<28;x++) for (const id of cell(x,y)) {
    if (id !== protectedFace && id !== otherFace) chosen.push(id);
  }
  assert.equal(cleanSurfaceMask(topology,chosen,new Set([protectedFace])).faces.includes(protectedFace),false);
  const small = cell(38,5);
  assert.deepEqual(cleanSurfaceMask(topology,small),{faces:small,added:0,removed:0});
});
