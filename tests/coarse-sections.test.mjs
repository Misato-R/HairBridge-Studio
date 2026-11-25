import assert from 'node:assert/strict';
import {test} from 'node:test';
import {Triangle,Vector3} from '../public/vendor/three.module.js';
import {inferCoarseSections} from '../lib/coarse-sections.mjs';
import {activeSections,defaultSection,endSectionValues,parseSectionPercent,sectionOffsets,
  sectionEndRegion,sectionPlan,sectionSeamKnots,validateSectionPlan,validateSections} from '../public/section-profile.mjs';

test('selection ends follow internal boundaries while older plans keep physical ends', () => {
  const card = {shape:'square',seq:Array.from({length:101},(_,i)=>[0,i,0,2,1])};
  const range = {from:35,to:65};
  const setting = {...defaultSection,...range,originalOutline:true,ends:{start:{width:170},end:{thickness:60}}};
  const legacy = sectionOffsets(card,setting,1);
  const current = {...setting,endsAtSelection:true};
  const rings = sectionOffsets(card,current,1);
  assert.equal(validateSections({a:current},[{id:'a'}]).a.endsAtSelection,true);
  assert.equal(sectionEndRegion(range,'start').boundary,35);
  assert.equal(sectionEndRegion(range,'end').boundary,65);
  assert.equal(endSectionValues(card,current,null,'start',range).width,170);
  assert.equal(legacy[0][0][0],1.7);
  assert.equal(rings[0][0][0],1);
  assert.equal(rings[35][0][0],1.7);
  assert.equal(rings[65][1][1],.3);
  assert.equal(rings[50][0][0],1);
  assert.equal(rings[70][1][1],.5);
  assert.equal(rings[100][1][1],.5);
});

test('typed multipliers and percentages can exceed the slider range', () => {
  assert.equal(parseSectionPercent('3'),300);
  assert.equal(parseSectionPercent('300%'),300);
  assert.equal(parseSectionPercent('1.25'),125);
  assert.equal(parseSectionPercent('0'),0);
  assert.equal(parseSectionPercent('2.3x'),null);
  const setting = {...defaultSection,width:0,thickness:300,roundness:300};
  assert.deepEqual(validateSections({a:setting},[{id:'a'}]),{a:setting});
});

test('joint section edits affect each side independently and preserve the physical end rings', () => {
  const card = {shape:'square',seq:Array.from({length:101},(_,i)=>[0,i,0,2,1])};
  const settings = {...defaultSection,profile:'four'};
  const seamFit = sectionSeamKnots.map(percent => percent === 47 ? [120,90] : [100,100]);
  const fit = {rings:card.seq.map(() => [1,1,.5,.5,Math.PI/2])};
  const before = sectionOffsets(card,settings,1,undefined,fit);
  const after = sectionOffsets(card,{...settings,seamFit},1,undefined,fit);
  assert.deepEqual(after[0],before[0]);
  assert.deepEqual(after.at(-1),before.at(-1));
  assert.equal(after[47][0][1],.9);
  assert.equal(after[47][2][1],-1.2);
  assert.deepEqual(after[47][1],before[47][1]);
  assert.ok(after[39][0][1] > .9 && after[39][0][1] < 1);
  assert.deepEqual(validateSections({a:{...settings,seamFit}},[{id:'a'}]).a.seamFit,seamFit);
  assert.throws(() => validateSections({a:{...settings,seamFit:[[99,100],...seamFit.slice(1)]}},[{id:'a'}]),/边缘/);
});

test('explicit shape selection changes the ring while leaving guide dimensions and fitted angle available', () => {
  const card = {shape:'square',seq:[[0,0,0,2,1],[0,1,0,2,1]]};
  const four = {...defaultSection,profile:'four',ridge:25,balance:20};
  const oval = {...defaultSection,profile:'ellipse',roundness:100};
  assert.deepEqual(validateSections({a:four},[{id:'a'}]).a,four);
  assert.throws(() => validateSections({a:{...four,ridge:41}},[{id:'a'}]),/偏移/);
  const fitted = {rings:Array.from({length:2},() => [1,1,.5,.5,0])};
  const ring = sectionOffsets(card,four,1,undefined,fitted)[0];
  assert.deepEqual(ring,[[1,0],[.25,.6],[-1,0],[-.25,-.4]]);
  const smooth = sectionOffsets(card,oval,1,undefined,fitted)[0];
  assert.equal(smooth.length,16);
  assert.ok(Math.abs(smooth[2][0]-Math.SQRT1_2)<1e-9);
});

test('endpoint sections are sized from the nearby body and fade into the existing profile', () => {
  const card = {shape:'square',seq:Array.from({length:101},(_,i) =>
    [0,i,0,i === 100 ? .07 : 1,i === 100 ? .035 : .5])};
  const setting = {...defaultSection,roundness:0,originalOutline:true,
    ends:{start:{width:40},end:{width:85,thickness:95,outline:'block'}}};
  const rings = sectionOffsets(card,setting,1);
  assert.equal(endSectionValues(card,null,null,'end').width,7);
  assert.deepEqual(validateSections({a:setting},[{id:'a'}]).a.ends,setting.ends);
  assert.ok(Math.abs(rings[0][0][0]-.2)<1e-9);
  assert.ok(Math.abs(rings[50][0][0]-.5)<1e-9);
  assert.ok(Math.abs(rings[100][0][0]-.425)<1e-9);
  assert.equal(rings.every(ring=>ring.length === 16),true);
  const round = sectionOffsets(card,{...defaultSection,roundness:100},1)[50];
  const fuller = sectionOffsets(card,{...defaultSection,roundness:300},1)[50];
  assert.ok(fuller[2][0]>round[2][0]);
});

test('per-strand sources retain their own edits and the original outline can be resized', () => {
  const strands = [{id:'a'},{id:'b'}];
  const fittedSections = {a:{roundness:58},b:{roundness:58}};
  const fittedEdit = {...defaultSection,width:94};
  const originalEdit = {...defaultSection,roundness:0,from:0,to:100,width:125,originalOutline:true};
  const plan = sectionPlan(strands,{fittedSections,sectionSettings:{a:fittedEdit}});
  plan.sources.a = 'original';
  plan.overrides.original.a = originalEdit;
  const validated = validateSectionPlan(plan,strands,fittedSections);
  const active = activeSections(strands,validated.sources,validated.overrides,fittedSections);
  assert.deepEqual(active, {settings:{a:originalEdit,b:null},fitted:{b:fittedSections.b}});
  assert.deepEqual(validated.overrides.fitted.a,fittedEdit);
  assert.throws(() => validateSectionPlan(plan,strands,{}), /可用的截面基准/);
  const card = {shape:'square',seq:[[0,0,0,2,1],[0,1,0,2,1]]};
  assert.deepEqual(sectionOffsets(card,active.settings.a,1)[0],[[1.25,0],[0,.5],[-1.25,0],[0,-.5]]);
});

test('coarse fitting measures assigned face slices, retains a tapered tip, and supports slider overrides', () => {
  const triangles = [];
  for (let i=0;i<16;i++) for (let j=0;j<16;j++) {
    const x = -.48+.06*i, y = .0625*j;
    const a = new Vector3(x,y,.045), b = new Vector3(x+.06,y,.045);
    const c = new Vector3(x,y+.0625,.045), d = new Vector3(x+.06,y+.0625,.045);
    triangles.push(new Triangle(a,b,c),new Triangle(b,d,c));
  }
  const makeCard = x => ({shape:'square',seq:Array.from({length:17},(_,i) =>
    [x,.02+.06*i,0,i === 16 ? .04 : .35,.10,1,0,0])});
  const card = makeCard(-.20);
  const faces = triangles.map((_,i) => i);
  const fit = inferCoarseSections(triangles,faces,[
    {id:'selected',card,include:true},{id:'adjacent',card:makeCard(.20),include:false},
  ]);
  assert.deepEqual(Object.keys(fit),['selected']);
  const fitted = fit.selected;
  assert.equal(fitted.rings.length,card.seq.length);
  assert.ok(fitted.rings[8][0] > fitted.rings[8][1]);
  assert.deepEqual(fitted.rings.at(-1).slice(0,4),[.02,.02,.05,.05]);
  const plain = sectionOffsets(card,null,1);
  const inferred = sectionOffsets(card,null,1,undefined,fitted);
  const widened = sectionOffsets(card,{...defaultSection,from:0,to:100,width:120},1,undefined,fitted);
  assert.equal(plain[8].length,4);
  assert.equal(inferred[8].length,16);
  const width = ring => Math.max(...ring.map(([x])=>x)) - Math.min(...ring.map(([x])=>x));
  assert.ok(Math.abs(width(widened[8])/width(inferred[8])-1.2) < 1e-8);
});
