import assert from 'node:assert/strict';
import {test} from 'node:test';
import {SurfaceFlowEditor} from '../public/surface-flow-editor.mjs';

test('refit review binds comparison and approval without point editing controls', () => {
  const group = {id:'back',refitTask:{id:'request',status:'ready'}};
  let redraws = 0;
  const actions = [];
  const editor = Object.assign(Object.create(SurfaceFlowEditor.prototype),{
    region:'back',fixture:{regions:[group]},refitPreview:'after',change:() => {redraws++;},
  });
  const ids = ['surfaceRefitBefore','surfaceRefitAfter','surfaceRefitExit','surfaceRefitAdopt','surfaceRefitCancel'];
  const buttons = Object.fromEntries(ids.map(id => [id,{}]));
  const review = {
    querySelector: selector => buttons[selector.slice(1)] ?? null,
    querySelectorAll: () => [],
  };
  editor.bind(review,{surfaceAction:(...args) => actions.push(args)});

  buttons.surfaceRefitBefore.onclick();
  assert.equal(editor.refitPreview,'before');
  buttons.surfaceRefitAfter.onclick();
  assert.equal(editor.refitPreview,'after');
  buttons.surfaceRefitAdopt.onclick();
  buttons.surfaceRefitExit.onclick();
  assert.equal(editor.refitPreview,false);
  assert.equal(redraws,3);
  assert.deepEqual(actions,[['surface-refit-adopt',{regionId:'back',taskId:'request'}]]);
});
