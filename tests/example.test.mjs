import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {installExample} from '../lib/example.mjs';
import {approvedSeparation,stamp,referenceStamp,requireReview} from '../lib/project.mjs';
import {pointFlowAvailable,pointFlowFixture} from '../lib/point-flow.mjs';

test('bundled study installs independent editable projects without the original experiment directory',async()=>{
  const temporary=await fs.mkdtemp(path.join(os.tmpdir(),'hairbridge-example-'));
  try{
    const first=await installExample(temporary),second=await installExample(temporary);
    assert.notEqual(first.id,second.id);
    assert.equal(first.references.length,4);
    assert.ok(first.sourceReference);
    assert.ok(approvedSeparation(first));
    assert.ok(pointFlowAvailable(first));
    assert.ok(pointFlowFixture(first).surfaceMesh);
    assert.equal(first.inputStamp,stamp(first));
    assert.equal(first.separation.review.referenceStamp,referenceStamp(first));
    requireReview(first,'draft');
    assert.equal(first.result,null);
    assert.equal(first.approvals.finish,undefined);
    assert.equal(first.cards.count,7);
    assert.equal(first.jobs.length,0);
    const saved=await fs.readFile(path.join(temporary,'projects',first.id,'project.hairbridge'),'utf8');
    assert.doesNotMatch(saved,/[A-Za-z]:[\\/]|\/Users\/|\/home\//);
    assert.ok(!saved.includes('f46db7b7-c5c4-4274-96cd-fcc7f4eb4349'));
    for(const asset of first.assets)assert.ok((await fs.stat(path.join(temporary,'projects',first.id,asset.file))).size>0);
  }finally{await fs.rm(temporary,{recursive:true,force:true});}
});
