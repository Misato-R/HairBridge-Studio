import assert from 'node:assert/strict';
import {test} from 'node:test';
import {Triangle,Vector3} from '../public/vendor/three.module.js';
import {createManualGuideFitter} from '../public/manual-guide.mjs';
import {canPlacePoint,fairAnchoredPath,fitPointFlow,guideSegments} from '../public/point-flow-fit.mjs';
import {editableAnchorRecipe} from '../lib/surface-flow.mjs';

test('fairing reduces mesh zigzags while preserving every anchor', () => {
  const anchors = [0,16,32,48,64];
  const path = Array.from({length:65},(_,i) => [i,Math.sin(i/12)+(i%2 ? .6 : -.6),0]);
  const result = fairAnchoredPath(path,anchors);
  for (const i of anchors) assert.deepEqual(result[i],path[i]);
  const roughness = points => points.slice(1,-1).reduce((sum,p,i) =>
    sum+(points[i][1]-2*p[1]+points[i+2][1])**2,0);
  assert.ok(roughness(result) < roughness(path)*.1);
});

test('a segment adjustment preserves its anchors and every neighboring position', () => {
  const points = [0,16,32].map(index => ({id:`anchor${index}`,index,suggestion:[index*.01,0,0]}));
  const seq = Array.from({length:33},(_,index) => [index*.01,0,0,.06,.025,0,1,0]);
  const strand = {refit:true,points,base:{shape:[],seq}};
  const [segment] = guideSegments(strand,points);
  const delta = [0,.006,.002];
  const original = fitPointFlow(strand,{points:{}}).after.seq;
  const edited = fitPointFlow(strand,{points:{},arcs:{[segment.id]:delta}}).after.seq;

  assert.deepEqual(edited[0].slice(0,3),original[0].slice(0,3));
  assert.deepEqual(edited.slice(16).map(row => row.slice(0,3)),original.slice(16).map(row => row.slice(0,3)));
  assert.deepEqual(edited[segment.mid].slice(1,3),delta.slice(1));
});

test('the root can extend on connected cap faces while retaining saved face indices', () => {
  const vertices = [], faces = [], selected = [];
  const columns = 5, rows = 22;
  for (let y=0;y<=rows;y++) for (let x=0;x<=columns;x++) vertices.push(x,y,0);
  for (let y=0;y<rows;y++) for (let x=0;x<columns;x++) {
    const a=y*(columns+1)+x, b=a+columns+1;
    if (y>=3 && y<=20) selected.push(faces.length/3,faces.length/3+1);
    faces.push(a,a+1,b,b,a+1,b+1);
  }
  const end = vertices.length/3;
  vertices.push(2.1,2.7,.1,2.4,2.7,.1,2.1,2.9,.1);
  faces.push(end,end+1,end+2);
  const mesh = {vertices,faces};
  const triangles = Array.from({length:faces.length/3},(_,i) => new Triangle(...faces.slice(i*3,i*3+3)
    .map(v => new Vector3(...vertices.slice(v*3,v*3+3)))));
  const marks = [4,12,20].map(y => ({triangle:y*columns*2+4,position:[2.3,y+.3,0]}));
  const fit = createManualGuideFitter(mesh,selected)(marks);
  const source = {manual:true,id:'test',base:fit.card,coverageFaces:fit.faceIds,
    points:fit.marks.map(mark => ({index:mark.index,suggestion:mark.position,
      triangle:fit.faceIds.indexOf(mark.triangle),moveFaces:[fit.faceIds.indexOf(mark.triangle)]}))};
  const result = editableAnchorRecipe({mesh,triangles},{faces:selected,fitKey:'test'},source);
  const root = result.points[0];
  const allowed = root.moveFaces.map(i => result.surface.faces.slice(i*3,i*3+3)
    .map(v => result.surface.vertices.slice(v*3,v*3+3)));

  assert.equal(root.triangle,source.points[0].triangle);
  assert.ok(root.moveFaces.includes(source.points[0].triangle));
  assert.ok(allowed.some(corners => corners.every(([,y]) => y<=3)));
  assert.ok(!allowed.some(corners => corners.some(([, ,z]) => z===.1)));
  const tip = {...result.points.at(-1),id:'tip'};
  assert.ok(tip.extraMoveFaces.length);
  const extra = tip.extraMoveFaces.find(i => result.surface.faces.slice(i*3,i*3+3)
    .some(v => result.surface.vertices[v*3+1]===22));
  assert.ok(Number.isInteger(extra));
  assert.equal(canPlacePoint(tip,tip.suggestion,extra),false);
  assert.equal(canPlacePoint(tip,tip.suggestion,extra,{expanded:{tip:true}}),true);
});
