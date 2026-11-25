import assert from 'node:assert/strict';
import {test} from 'node:test';
import {Triangle,Vector3} from '../public/vendor/three.module.js';
import {scalpSurface,insetScalpEnd} from '../public/scalp-inset.mjs';
import {sectionFrames} from '../public/section-frames.mjs';
import {validateSections} from '../public/section-profile.mjs';

test('the inset clears the full cap and preserves the earlier guide samples', () => {
  const a = new Vector3(-.3,-.3,0), b = new Vector3(.3,-.3,0);
  const c = new Vector3(-.3,.3,0), d = new Vector3(.3,.3,0);
  const scalp = scalpSurface([new Triangle(a,b,c),new Triangle(b,d,c)]);
  const card = {shape:'square',seq:Array.from({length:65},(_,i) =>
    [0,i*.003,.010,.012,.015,1,0,0])};
  const outline = [[.006,0],[0,.0075],[-.006,0],[0,-.0075]];
  const shallow = insetScalpEnd(card,outline,scalp,0);
  const deep = insetScalpEnd(card,outline,scalp,3);
  assert.ok(shallow && deep);
  assert.ok(deep.shift > shallow.shift);
  assert.deepEqual(deep.card.seq.slice(0,38),card.seq.slice(0,38));
  assert.deepEqual(deep.offsets[0].map(n => n || 0),[0,0,0]);
  const frame = sectionFrames(deep.card).at(-1);
  for (const [x,y] of outline) {
    const point = frame.center.clone().addScaledVector(frame.width,x).addScaledVector(frame.thick,y);
    assert.ok(scalp.nearest(point).signed < -.003);
  }
  assert.equal(card.seq.at(-1)[2],.010);
  assert.throws(() => validateSections({a:{from:0,to:100,width:100,thickness:100,roundness:45,scalpInset:-1}},[{id:'a'}]),
    /内嵌深度无效/);
});
