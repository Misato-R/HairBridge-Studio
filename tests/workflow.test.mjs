import test,{after,before} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {makeProject,validateCards,invalidate,view,stamp,saveResult,approveResult,restoreResult,approvedSeparation,REFERENCE_VIEWS} from '../lib/project.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
process.env.HAIRBRIDGE_DATA=path.join(root,'data','qa',randomUUID());
let server,base;
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5r8AAAAASUVORK5CYII=','base64');
const cards=[{shape:'square',seq:[[0,0,0,.02,.004,1,0,0],[0,.1,0,.01,.002,1,0,0]]}];
function glb(name, buffers) {
  const document=JSON.stringify({asset:{version:'2.0'},nodes:[{name}],buffers});
  const json=Buffer.from(document.padEnd(Math.ceil(document.length / 4) * 4));
  const header=Buffer.alloc(20);
  header.write('glTF');
  header.writeUInt32LE(2,4);
  header.writeUInt32LE(20+json.length,8);
  header.writeUInt32LE(json.length,12);
  header.writeUInt32LE(0x4e4f534a,16);
  return Buffer.concat([header,json]);
}
before(async()=>{const app=await import('../server.mjs');server=await app.start(0);base=`http://127.0.0.1:${server.address().port}`;});
after(async()=>{await new Promise(resolve=>server.close(resolve));});
async function request(route,body,headers={}){const response=await fetch(base+route,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...headers},body:body===undefined?undefined:JSON.stringify(body)});return {status:response.status,data:await response.json()};}
async function create(){return(await request('/api/projects',{name:'QA workflow'})).data;}
async function upload(p,role,name,bytes,extra={}){const params=new URLSearchParams({role,name,...extra});const r=await fetch(`${base}/api/projects/${p.id}/upload?${params}`,{method:'POST',body:bytes});return{status:r.status,data:await r.json()};}
async function readyReference(p) {
  const route=`/api/projects/${p.id}`;
  p=(await upload(p,'reference','source.png',png)).data;
  for(const slot of REFERENCE_VIEWS) {
    p=(await upload(p,'reference-view',`${slot}.png`,png,{view:slot})).data;
    const asset=p.references.find(item=>item.view===slot);
    p=(await request(`${route}/reference-view-review`,{view:slot,assetId:asset.id,approved:true})).data;
  }
  return p;
}

test('fresh-checkout demo and companion download use bundled public files',async()=>{
  const {status,data:p}=await request('/api/demo',{}, {'Accept-Language':'en'});
  assert.equal(status,201);
  assert.equal(p.references.length,4);
  assert.equal(p.cards.count,7);
  assert.ok(p.pointFlowAvailable);
  assert.equal(p.result,null);
  assert.equal(p.approvals.finish,undefined);
  assert.equal((await request(`/api/projects/${p.id}/point-flow`)).status,200);
  const capabilities=(await request('/api/capabilities')).data;
  assert.equal(capabilities.addon,true);
  const response=await fetch(base+'/api/addon');
  assert.equal(response.status,200);
  const downloaded=Buffer.from(await response.arrayBuffer());
  assert.deepEqual(downloaded,await fs.readFile(path.join(root,'installers','hairbridge_studio.zip')));
});
test('English task creation and Chinese viewing preserve task identity and source data',async()=>{
  let p=await create();const route=`/api/projects/${p.id}`;
  p=(await upload(p,'reference','reference.png',png)).data;
  p=(await request(route+'/reference-request',{views:['front']},{'Accept-Language':'en'})).data;
  const task=p.referenceRequests.at(-1);
  assert.match(task.message,/Complete the hairstyle reference views/);
  assert.doesNotMatch(task.message,/[\u3400-\u9fff]/u);
  assert.doesNotMatch(task.message,/[，。；：！？、「」]/u);
  assert.equal(task.message,task.messages.en);
  assert.match(task.message,/attach-views/);
  const chinese=(await request(route,undefined,{'Accept-Language':'zh'})).data;
  assert.equal(chinese.referenceRequests.at(-1).id,task.id);
  assert.equal(chinese.referenceRequests.at(-1).message,task.messages.zh);
  assert.equal(chinese.sourceReference.sha256,p.sourceReference.sha256);
  const english=(await request(route,undefined,{'Accept-Language':'en'})).data;
  assert.equal(english.referenceRequests.at(-1).message,task.messages.en);
});

test('reject malformed or degenerate guides before passing them to Blender',()=>{
  assert.equal(validateCards(cards).count,1);
  assert.throws(()=>validateCards([{shape:'square',seq:[[0,0,0,1,1,0,0,0],[0,1,0,1,1,1,0,0]]}]));
  assert.throws(()=>validateCards([{shape:'square',seq:[cards[0].seq[0],cards[0].seq[0]]}]));
});
test('new projects retain the chosen image or coarse entry when reopened',async()=>{
  const image=await request('/api/projects',{name:'New image',entryMode:'image'});
  const coarse=await request('/api/projects',{name:'New rough',entryMode:'coarse'});
  assert.equal(image.status,201);
  assert.equal(image.data.referenceMode,'multiview');
  assert.equal(coarse.status,201);
  assert.equal(coarse.data.stage,'reference');
  assert.equal(coarse.data.referenceMode,undefined);
  assert.equal(coarse.data.model,null);
  assert.equal((await request(`/api/projects/${coarse.data.id}`)).data.entryMode,'coarse');
  assert.equal((await request('/api/projects',{entryMode:'invalid'})).status,400);
});
test('imported results do not imply reference approval; changing reference invalidates derived work',()=>{
  const p=makeProject();p.cards={sha256:'old'};assert.equal(view(p).stage,'reference');
  p.approvals={reference:{},draft:{},finish:{}};p.result={};p.model={};invalidate(p,'reference');
  assert.deepEqual(p.approvals,{});assert.equal(p.cards,null);assert.equal(p.model,null);assert.equal(p.result,null);
});
test('HTTP checkpoints, persistent reopening, evidence and project ZIP',async()=>{
  let p=await create();const route=`/api/projects/${p.id}`;
  assert.equal((await request(route+'/review',{step:'draft'})).status,400);
  p=await readyReference(p);
  p=(await request(route+'/review',{step:'reference',note:'QA reference check'})).data;
  assert.equal(p.stage,'draft');
  p=(await upload(p,'cards','cards.json',Buffer.from(JSON.stringify(cards)))).data;
  assert.equal(p.stage,'review');assert.equal(p.cards.count,1);
  p=(await request(route+'/review',{step:'draft',note:'QA guide check'})).data;assert.equal(p.stage,'blender');
  assert.equal((await request(route+'/review',{step:'finish'})).status,400);
  const reopened=(await request(route)).data;assert.equal(reopened.approvals.draft.note,'QA guide check');
  const archive=Buffer.from(await(await fetch(base+route+'/export')).arrayBuffer());assert.equal(archive.readUInt32LE(0),0x04034b50);
  await fs.writeFile(path.join(process.env.HAIRBRIDGE_DATA,'export-test.zip'),archive);
  p=(await upload(p,'reference','replacement.png',png)).data;
  assert.equal(p.cards,null);assert.equal(p.stage,'reference');assert.equal(p.approvals.draft,undefined);
});
test('a reference change supersedes a partially uploaded P2.0 request',async()=>{
  let p=await readyReference(await create());
  const route=`/api/projects/${p.id}`;
  p=(await request(`${route}/review`,{step:'reference'})).data;
  p=(await request(`${route}/studio-request`,{note:'QA only'})).data;
  const requestId=p.studioRequests[0].id;
  const head=await upload(p,'separation-head','head.glb',glb('first head'),{requestId});
  assert.equal(head.status,200);
  assert.equal(head.data.model,null);
  assert.equal(head.data.separation.head,null);
  p=(await upload(p,'reference-view','replacement.png',Buffer.concat([png,Buffer.from([1])]),{view:'left'})).data;
  assert.equal(p.studioRequests[0].status,'superseded');
  assert.equal((await upload(p,'model','late.glb',glb('late candidate'),{requestId})).status,400);
  assert.equal((await upload(p,'separation-hair','late.glb',glb('late hair'),{requestId})).status,400);
  assert.equal((await request(`${route}/register-model`,{requestId})).status,400);
});

test('one source, four agent views, and single-view redo retain the other reviews',async()=>{
  let p=await create();const route=`/api/projects/${p.id}`;
  p=(await upload(p,'reference','source.png',png)).data;
  const sourceId=p.sourceReference.id;
  assert.equal(p.references.length,0);
  assert.equal((await request(`${route}/review`,{step:'reference'})).status,400);
  p=(await request(`${route}/reference-request`,{})).data;
  const task=p.referenceRequests[0];
  assert.deepEqual(task.views,REFERENCE_VIEWS);
  for(const slot of REFERENCE_VIEWS) {
    p=(await upload(p,'reference-view',`${slot}.png`,png,{view:slot,requestId:task.id})).data;
    const asset=p.references.find(item=>item.view===slot);
    assert.equal(asset.origin,'agent');
    p=(await request(`${route}/reference-view-review`,{view:slot,assetId:asset.id,approved:true})).data;
  }
  assert.equal(p.referenceRequests[0].status,'registered');
  p=(await request(`${route}/review`,{step:'reference'})).data;
  assert.equal(p.stage,'draft');
  p=(await request(`${route}/studio-request`,{})).data;
  for(const file of p.references) assert.ok(p.studioRequests[0].message.includes(path.basename(file.file)));
  const otherIds=p.references.slice(0,3).map(item=>item.id);
  const oldBack=p.references[3].id;
  p=(await request(`${route}/reference-request`,{views:['back'],note:'keep the side part'})).data;
  const redo=p.referenceRequests.at(-1);
  p=(await upload(p,'reference-view','back-redo.png',png,{view:'back',requestId:redo.id})).data;
  assert.equal(p.sourceReference.id,sourceId);
  assert.equal(p.stage,'reference');
  assert.equal(p.studioRequests[0].status,'superseded');
  assert.deepEqual(p.references.slice(0,3).map(item=>item.id),otherIds);
  assert.deepEqual(Object.keys(p.referenceReviews),REFERENCE_VIEWS.slice(0,3));
  assert.equal((await request(`${route}/reference-view-review`,{view:'back',assetId:oldBack,approved:true})).status,400);
  p=(await request(`${route}/reference-request`,{views:['back']})).data;
  const stale=p.referenceRequests.at(-1).id;
  p=(await upload(p,'reference','different-source.png',png)).data;
  assert.equal(p.references.length,0);
  assert.equal((await upload(p,'reference-view','late.png',png,{view:'back',requestId:stale})).status,400);
});
test('reject cross-origin writes and externally referenced GLB resources',async()=>{
  assert.equal((await request('/api/projects',{name:'blocked'},{Origin:'https://example.com'})).status,403);
  const p=await create();
  const remote=glb('remote',[{uri:'https://example.com/private',byteLength:1}]);
  assert.equal((await upload(p,'model','remote.glb',remote)).status,400);
  assert.equal((await upload(p,'separation-head','remote.glb',remote)).status,400);
});

test('historical Tripo separation can finish and remains bound to the approved inputs',async()=>{
  let p=await create();
  const route=`/api/projects/${p.id}`;
  assert.deepEqual(p.separation,{requests:[],head:null,hair:null,review:null});
  assert.equal((await request(`${route}/separation-request`,{})).status,400);
  p=await readyReference(p);
  p=(await upload(p,'model','coarse.glb',glb('coarse'))).data;
  assert.equal((await request(`${route}/separation-request`,{})).status,400);
  p=(await request(`${route}/review`,{step:'reference'})).data;
  const inputs={modelId:p.model.id,referenceStamp:p.referenceStamp};
  const pending={
    id:randomUUID(),status:'awaiting_agent',at:new Date().toISOString(),
    modelSha256:p.model.sha256,...inputs,note:'preserve the ponytail',received:[],assetIds:{},
    message:'Existing Tripo Fill Parts handoff',
  };
  const manifestPath=path.join(p.localDirectory,'project.hairbridge');
  const manifest=JSON.parse(await fs.readFile(manifestPath,'utf8'));
  manifest.separation={...p.separation,requests:[pending]};
  await fs.writeFile(manifestPath,JSON.stringify(manifest));
  assert.equal((await request(`${route}/separation-request`,{method:'ai-completion',...inputs})).status,400);
  assert.deepEqual((await request(route)).data.separation.requests,[pending]);

  const other=(await request('/api/projects',{entryMode:'coarse'})).data;
  const otherWithModel=(await upload(other,'model','same.glb',glb('coarse'))).data;
  assert.equal((await upload(otherWithModel,'separation-head','late.glb',glb('head'),{requestId:pending.id})).status,400);

  p=(await upload(p,'separation-head','head.glb',glb('head'),{requestId:pending.id})).data;
  assert.deepEqual(p.separation.requests[0].received,['head']);
  assert.equal(p.separation.head,null);
  assert.equal((await request(`${route}/separation-review`,{decision:'approved',...inputs})).status,400);
  const previousStamp=stamp(p);
  p=(await upload(p,'separation-hair','hair.glb',glb('hair'),{requestId:pending.id})).data;
  assert.equal(p.separation.requests[0].status,'registered');
  assert.equal(p.separation.head.requestId,pending.id);
  assert.equal(p.separation.hair.requestId,pending.id);
  assert.equal(stamp(p),previousStamp);
  assert.equal((await request(`${route}/separation-review`,{decision:'approved',headId:'stale',...inputs})).status,400);
  p=(await request(`${route}/separation-review`,{decision:'approved',...inputs,headId:p.separation.head.id,hairId:p.separation.hair.id})).data;
  assert.ok(approvedSeparation(p));
  assert.notEqual(stamp(p),previousStamp);
  assert.equal(p.stage,'draft');
  assert.equal(p.cards,null);
  const headDownload=await fetch(base+p.separation.head.url);
  assert.deepEqual(Buffer.from(await headDownload.arrayBuffer()),glb('head'));
  assert.equal((await request(route)).data.separation.review.decision,'approved');

  assert.equal((await request(`${route}/separation-request`,inputs)).status,400);
  assert.equal((await request(route)).data.separation.head.requestId,pending.id);
  p=(await request(`${route}/separation-review`,{decision:'skipped',...inputs})).data;
  assert.equal(p.separation.review.decision,'skipped');
  assert.equal(stamp(p),previousStamp);
  p=(await upload(p,'reference-view','new-front.png',Buffer.concat([png,Buffer.from([1])]),{view:'front'})).data;
  assert.equal(p.separation.head,null);
  assert.equal(p.separation.hair,null);
  assert.equal(p.separation.review,null);
  assert.equal((await upload(p,'separation-head','stale.glb',glb('head'),inputs)).status,400);
});

test('one P2.0 request publishes its whole candidate, head and hair together',async()=>{
  let p=await readyReference(await create());
  const route=`/api/projects/${p.id}`;
  assert.equal((await request(`${route}/studio-request`,{})).status,400);
  p=(await request(`${route}/review`,{step:'reference'})).data;
  const first=await request(`${route}/studio-request`,{});
  assert.equal(first.status,200);
  p=first.data;
  const task=p.studioRequests.at(-1);
  assert.equal(task.method,'smart-mesh-p2');
  assert.equal(task.referenceStamp,p.referenceStamp);
  assert.deepEqual(task.references,p.references.map(({view,id:assetId,sha256})=>({view,assetId,sha256})));
  assert.match(task.message,/P2\.0/);
  assert.match(task.message,/25,?000/);
  assert.match(task.message,/同一候选/);
  assert.match(task.messages.en,/same candidate|one candidate/i);
  assert.doesNotMatch(task.messages.en,/[\u3400-\u9fff]/u);
  assert.match(task.message,/attach-p2/);
  assert.doesNotMatch(task.message,/Fill Parts|AI Completion/i);
  assert.deepEqual(task.received,[]);
  assert.equal(task.status,'awaiting_agent');
  assert.equal((await request(`${route}/separation-request`,{})).status,400);

  const trio={coarse:glb('whole P2 candidate'),head:glb('same P2 head'),hair:glb('same P2 hair')};
  for (const [role,slot] of [['model','coarse'],['separation-head','head']]) {
    const saved=await upload(p,role,`${slot}.glb`,trio[slot],{requestId:task.id});
    assert.equal(saved.status,200);
    p=saved.data;
    assert.ok(p.studioRequests.at(-1).received.includes(slot));
    assert.equal(p.studioRequests.at(-1).status,'awaiting_agent');
    assert.equal(p.model,null);
    assert.equal(p.separation.head,null);
    assert.equal(p.separation.hair,null);
  }
  assert.equal((await request(`${route}/register-model`,{requestId:task.id})).status,400);
  assert.equal((await request(`${route}/separation-review`,{decision:'approved'})).status,400);

  const runCli=promisify(execFile);
  const cli=path.join(root,'scripts','project.mjs');
  const cliOptions={env:{...process.env,HAIRBRIDGE_URL:base},windowsHide:true};
  const checked=JSON.parse((await runCli(process.execPath,
    [cli,'show-p2-request',p.id,task.id],cliOptions)).stdout);
  assert.deepEqual(checked.remaining,['hair']);
  assert.deepEqual(checked.references.map(item=>item.view),REFERENCE_VIEWS);
  const hairFile=path.join(p.localDirectory,'p2-hair.glb');
  const mismatchedCoarse=path.join(p.localDirectory,'different-coarse.glb');
  await fs.writeFile(hairFile,trio.hair);
  await fs.writeFile(mismatchedCoarse,glb('different candidate'));
  await assert.rejects(runCli(process.execPath,
    [cli,'attach-p2',p.id,task.id,`hair=${hairFile}`,`coarse=${mismatchedCoarse}`],cliOptions));
  const stillPartial=(await request(route)).data;
  assert.deepEqual(stillPartial.studioRequests.at(-1).received,['coarse','head']);
  assert.equal(stillPartial.model,null);
  const attached=JSON.parse((await runCli(process.execPath,
    [cli,'attach-p2',p.id,task.id,`hair=${hairFile}`],cliOptions)).stdout);
  assert.equal(attached.status,'registered');
  assert.deepEqual(attached.remaining,[]);

  p=(await request(route)).data;
  const published=p.studioRequests.at(-1);
  assert.equal(published.status,'registered');
  assert.deepEqual(published.assetIds,{coarse:p.model.id,head:p.separation.head.id,hair:p.separation.hair.id});
  assert.equal(p.separation.review,null);
  assert.equal(approvedSeparation(p),null);
  const deniedGuides=await upload(p,'cards','guides.json',Buffer.from(JSON.stringify(cards)));
  assert.equal(deniedGuides.status,400);
  assert.match(deniedGuides.data.error,/叠加审核.*头模与头发/);
  const deniedJob=await request(`${route}/job`,{kind:'hairdeck',requestId:randomUUID()});
  assert.equal(deniedJob.status,400);
  assert.match(deniedJob.data.error,/叠加审核.*头模与头发/);
  assert.equal((await request(`${route}/review`,{step:'draft'})).status,400);
  assert.equal((await request(`${route}/separation-review`,{decision:'skipped'})).status,400);
  assert.equal((await request(`${route}/separation-review`,{decision:'approved'})).status,400);
  assert.equal((await upload(p,'separation-head','manual.glb',glb('unpaired head'))).status,400);
  for (const [slot,asset] of Object.entries({coarse:p.model,head:p.separation.head,hair:p.separation.hair})) {
    const download=await fetch(base+asset.url);
    assert.deepEqual(Buffer.from(await download.arrayBuffer()),trio[slot]);
  }
  p=(await request(`${route}/separation-review`,{
    decision:'approved',headId:p.separation.head.id,hairId:p.separation.hair.id,
    modelId:p.model.id,referenceStamp:p.referenceStamp,
  })).data;
  assert.ok(approvedSeparation(p));
  const guideUpload=await upload(p,'cards','guides.json',Buffer.from(JSON.stringify(cards)));
  assert.equal(guideUpload.status,200);

  const approved=guideUpload.data;
  p=(await request(`${route}/studio-request`,{})).data;
  const replacementId=p.studioRequests.at(-1).id;
  p=(await upload(p,'model','other.glb',glb('partial new P2 candidate'),{requestId:replacementId})).data;
  assert.equal(p.model.id,approved.model.id);
  assert.equal(p.separation.head.id,approved.separation.head.id);
  assert.equal(p.separation.hair.id,approved.separation.hair.id);
  assert.deepEqual(p.separation.review,approved.separation.review);
  assert.equal(stamp(p),stamp(approved));

  p=(await upload(p,'separation-hair','next-hair.glb',glb('next candidate hair'),{requestId:replacementId})).data;
  p=(await upload(p,'separation-head','next-head.glb',glb('next candidate head'),{requestId:replacementId})).data;
  assert.notEqual(p.model.id,approved.model.id);
  assert.notEqual(p.separation.head.id,approved.separation.head.id);
  assert.notEqual(p.separation.hair.id,approved.separation.hair.id);
  assert.equal(p.separation.review,null);
  assert.equal(p.cards,null);
});

test('untouched legacy preparation upgrades in place and manual upload supersedes the new request',async()=>{
  let p=await readyReference(await create());
  const route=`/api/projects/${p.id}`;
  p=(await request(`${route}/review`,{step:'reference'})).data;
  const legacy={id:randomUUID(),status:'awaiting_agent',at:new Date().toISOString(),
    referenceSha256:p.reference.sha256,referenceStamp:p.referenceStamp,message:'Legacy rough-model-only request'};
  const manifestPath=path.join(p.localDirectory,'project.hairbridge');
  const manifest=JSON.parse(await fs.readFile(manifestPath,'utf8'));
  await fs.writeFile(manifestPath,JSON.stringify({...manifest,studioRequests:[legacy]}));
  p=(await request(`${route}/studio-request`,{})).data;
  assert.equal(p.studioRequests.length,1);
  assert.equal(p.studioRequests[0].id,legacy.id);
  assert.equal(p.studioRequests[0].method,'smart-mesh-p2');
  assert.equal(p.studioRequests[0].status,'awaiting_agent');

  p=(await upload(p,'model','manual.glb',glb('independent local coarse model'))).data;
  assert.equal(p.studioRequests[0].status,'superseded');
  assert.equal((await upload(p,'separation-head','late.glb',glb('late P2 head'),{requestId:legacy.id})).status,400);
  assert.equal(p.model.name,'manual.glb');
  assert.equal(p.separation.head,null);
});

test('existing coarse GLB can skip separation or manually supply parts before the usual guide review',async()=>{
  let p=(await request('/api/projects',{entryMode:'coarse'})).data;
  const route=`/api/projects/${p.id}`;
  assert.equal((await request(`${route}/review`,{step:'reference'})).status,400);
  p=(await upload(p,'model','coarse.glb',glb('first coarse'))).data;
  const inputs={modelId:p.model.id,referenceStamp:p.referenceStamp};
  p=(await request(`${route}/separation-review`,{decision:'skipped',...inputs})).data;
  p=(await request(`${route}/review`,{step:'reference',modelId:p.model.id})).data;
  assert.equal(p.stage,'draft');
  assert.equal((await request(`${route}/studio-request`,{})).status,400);
  assert.equal((await request(`${route}/job`,{kind:'hairdeck',requestId:randomUUID()})).status,400);
  assert.equal((await request(`${route}/separation-request`,{method:'smart-mesh-p2',...inputs})).status,400);
  assert.equal((await request(`${route}/separation-request`,inputs)).status,400);
  assert.deepEqual((await request(route)).data.separation.requests,[]);
  p=(await upload(p,'separation-head','head.glb',glb('head'),inputs)).data;
  assert.equal(p.separation.head.origin,'user');
  p=(await upload(p,'separation-hair','hair.glb',glb('hair'),inputs)).data;
  p=(await request(`${route}/separation-review`,{decision:'approved',...inputs})).data;
  p=(await upload(p,'cards','cards.json',Buffer.from(JSON.stringify(cards)))).data;
  p=(await request(`${route}/review`,{step:'draft'})).data;
  assert.equal(p.stage,'blender');
  assert.ok(approvedSeparation(p));
  p=(await upload(p,'model','another.glb',glb('second coarse'))).data;
  assert.equal(p.stage,'reference');
  assert.equal(p.cards,null);
  assert.equal(p.separation.review,null);
  assert.equal(p.separation.head,null);
  assert.equal((await request(`${route}/review`,{step:'reference',modelId:inputs.modelId})).status,400);
  assert.equal((await upload(p,'separation-hair','old-hair.glb',glb('hair'),inputs)).status,400);
});

test('restoring a version restores its own approval and rejects versions from earlier inputs',()=>{
  const project=makeProject();
  project.reference={sha256:'reference'};
  project.cards={sha256:'draft'};
  project.approvals={reference:{},draft:{}};
  const approval={at:'2026-11-23T12:00:00Z',stamp:stamp(project),note:'confirmed'};
  saveResult(project,{blend:{id:'initial'},sourceStamp:stamp(project)},'初稿');
  project.approvals.finish=approval;
  approveResult(project,approval);
  saveResult(project,{blend:{id:'edit'},sourceStamp:stamp(project)},'精修');
  assert.equal(project.approvals.finish,undefined);
  assert.equal(restoreResult(project,'initial').id,'initial');
  assert.deepEqual(project.approvals.finish,approval);
  assert.equal(restoreResult(project,'edit').id,'edit');
  assert.equal(project.approvals.finish,undefined);
  invalidate(project,'reference');
  project.reference={sha256:'new image'};
  project.approvals.draft={};
  assert.equal(view(project).versions.every(version=>!version.restorable),true);
  assert.throws(()=>restoreResult(project,'initial'),/当前输入/);
});
