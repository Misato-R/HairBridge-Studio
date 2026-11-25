import {t,msg,getLanguage} from './public/i18n.mjs';
import {setTaskMessage,withLanguage,requestLanguage,localizeTaskView,projectPackageInstructions} from './lib/locale.mjs';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawn} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {makeProject,record,stamp,referenceStamp,REFERENCE_VIEWS,VIEW_LABELS,now,hash,validateCards,invalidate,
  requireReview,saveResult,approveResult,restoreResult,versions,coarseOnly,separationState,supersedeSeparationRequests,
  invalidateSeparation,approvedSeparation,view as projectView} from './lib/project.mjs';
import {zip} from './lib/zip.mjs';
import {installExample} from './lib/example.mjs';
import {confirmPointRegion, editSurfaceFlow, fitPointSections, movePointRegionStrand, pointFlowAvailable, pointFlowFixture, pointRegionAssignments, pointSurfaceStageView,
  resolvePointFlow, reviewedPointRegions} from './lib/point-flow.mjs';
import {activeSections, generatedStrands, sectionOffsets, sectionPlan, validateSectionPlan, validateSections} from './public/section-profile.mjs';
import {insetScalpEnd} from './public/scalp-inset.mjs';
import {readScalpSurface,readStaticGlb} from './lib/scalp-glb.mjs';
import {inferUvSections} from './lib/uv-sections.mjs';

export const ROOT = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.resolve(process.env.HAIRBRIDGE_DATA || path.join(ROOT,'data'));
const PROJECTS = path.join(DATA,'projects');
const A2 = path.resolve(ROOT,'../assignment/A2_Hair_Bridge');
const RAIN_PRESET = path.join(A2,'experiments/rain_v3_studio_trial/preset.json');
const running = new Map();
let mutation = Promise.resolve();
const serial = fn => { const r = mutation.then(fn); mutation = r.catch(()=>{}); return r; };
const idOK = id => /^[a-f0-9-]{36}$/.test(id);
const projectDir = id => { if(!idOK(id)) throw Error(t('项目 ID 无效。')); return path.join(PROJECTS,id); };
const closedHair = p => {
  const hair = approvedSeparation(p)?.hair;
  return hair && p.closedHair?.hairId === hair.id && p.closedHair.hairHash === hair.sha256 ? p.closedHair : null;
};
const view = p => localizeTaskView({...projectView(p),localDirectory:projectDir(p.id),pointFlowAvailable:pointFlowAvailable(p),
  closedHair:closedHair(p),
  pointFlowReviewedRegions:reviewedPointRegions(p),pointFlowRegionAssignments:pointRegionAssignments(p),
  ...(p.surfaceFlow?.enabled ? {surfaceFlow:pointSurfaceStageView(p)} : {})});
export const load = async id => JSON.parse(await fs.readFile(path.join(projectDir(id),'project.hairbridge'),'utf8'));
async function save(p) {
  const dir = projectDir(p.id); await fs.mkdir(dir,{recursive:true});
  const target = path.join(dir,'project.hairbridge'), temp = target+'.tmp';
  p.inputStamp = stamp(p);
  await fs.writeFile(temp,JSON.stringify(p,null,2)); await fs.rename(temp,target);
}
async function config() {
  let c = {}; try { c = JSON.parse(await fs.readFile(path.join(ROOT,'local-config.json'),'utf8')); } catch(e) {if(e.code!=='ENOENT')throw e;}
  return {hairdeckRoot:process.env.HAIRDECK_CODE || c.hairdeckRoot || 'D:/Character_Hair/references/HairDeck',
    hairdeckWorkspace:process.env.HAIRDECK_ROOT || c.hairdeckWorkspace || 'D:/Character_Hair/hairdeck_workspace',
    hairdeckPython:process.env.HAIRDECK_PYTHON || c.hairdeckPython || 'D:/Character_Hair/references/HairDeck/.venv/Scripts/python.exe',
    blender:process.env.BLENDER || c.blender || 'D:/Steam/steamapps/common/Blender/blender.exe'};
}
const exists = async p => !!await fs.stat(p).catch(()=>null);
async function capabilities() {
  const c = await config();
  return {hairdeck:await exists(c.hairdeckPython) && await exists(path.join(c.hairdeckRoot,'hairdeck/infer/image.py')),
    hairdeckPreview:true,
    blender:await exists(c.blender), tripo:'studio-agent', port:server.address()?.port,
    addon:await exists(path.join(ROOT,'installers/hairbridge_studio.zip')), rainTripo:await exists(RAIN_PRESET)};
}
function notRunning(p) { if(p.jobs.some(j=>['queued','running'].includes(j.status))) throw Error(t('项目正在处理，请等待完成或先停止任务。')); }
const assetURL = (id,a) => `/api/projects/${id}/assets/${a.id}`;
async function addAsset(p,role,name,bytes) {
  name = path.basename(name.replaceAll('\\','/')).replace(/[^\p{L}\p{N}._ -]/gu,'_').slice(0,120) || 'asset';
  const a = {id:randomUUID(),role,name,file:`assets/${randomUUID()}${path.extname(name).toLowerCase()}`,bytes:bytes.length,sha256:hash(bytes),createdAt:now()};
  await fs.mkdir(path.join(projectDir(p.id),'assets'),{recursive:true});
  await fs.writeFile(path.join(projectDir(p.id),a.file),bytes,{flag:'wx'});
  a.url = assetURL(p.id,a); p.assets.push(a); return a;
}
function validateImage(extension,bytes) {
  const ok=(extension==='.png'&&bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))||
    (['.jpg','.jpeg'].includes(extension)&&bytes[0]===255&&bytes[1]===216)||
    (extension==='.webp'&&bytes.toString('ascii',0,4)==='RIFF'&&bytes.toString('ascii',8,12)==='WEBP');
  if(!ok)throw Error(t('请上传有效的 PNG、JPEG 或 WebP 图片。'));
  if(bytes.length>20*1024**2)throw Error(t('参考图限 20 MB。'));
}

function validateGlb(extension, bytes) {
  if (extension !== '.glb' || bytes.length < 20 || bytes.toString('ascii',0,4) !== 'glTF' ||
      bytes.readUInt32LE(4) !== 2 || bytes.readUInt32LE(8) !== bytes.length) throw Error(t('请上传完整的 GLB 2.0 文件。'));
  const length = bytes.readUInt32LE(12);
  if (bytes.readUInt32LE(16) !== 0x4e4f534a || length > bytes.length - 20) throw Error(t('GLB JSON 数据无效。'));
  const gltf = JSON.parse(bytes.toString('utf8',20,20+length));
  if ([...(gltf.buffers || []), ...(gltf.images || [])].some(x => x.uri && !x.uri.startsWith('data:')))
    throw Error(t('请使用贴图和几何内嵌的 GLB，不支持外部资源链接。'));
}

const separationLabels = {head: t('无发头模'), hair: t('独立头发')};
const p2Method = 'smart-mesh-p2';
const p2Roles = {coarse: 'model', head: 'separation-head', hair: 'separation-hair'};
const p2Labels = {coarse: t('整头粗模'), ...separationLabels};

function requireSeparationInputs(p) {
  if (!p.model) throw Error(t('请先导入或取得当前粗模 GLB。'));
  if (coarseOnly(p)) return;
  if (!p.approvals.reference) throw Error(t('请先确认参考图。'));
  requireReview(p, 'reference');
}

function separationInputs(p) {
  return {modelId: p.model.id, modelSha256: p.model.sha256, referenceStamp: referenceStamp(p)};
}

function checkSeparationInputs(p, expected) {
  const current = separationInputs(p);
  if (Object.keys(current).some(key => expected[key] != null && expected[key] !== current[key]))
    throw Error(t('当前粗模或参考图已更换，请重新核对拆分。'));
  return current;
}

function resetSeparationResult(p, previousStamp) {
  if (stamp(p) === previousStamp) return;
  p.versions = versions(p);
  p.result = null;
  delete p.approvals.finish;
}

function confirmedP2Views(p) {
  if (p.referenceMode !== 'multiview' || !p.approvals.reference) throw Error(t('生成粗模需要四张已确认的参考图。'));
  requireReview(p, 'reference');
  return REFERENCE_VIEWS.map(view => p.references.find(asset => asset.view === view));
}

function supersedeP2Requests(p) {
  for (const task of p.studioRequests) {
    if (task.method === p2Method && task.status === 'awaiting_agent') task.status = 'superseded';
  }
}

function createP2Request(p, payload) {
  const references = confirmedP2Views(p);
  const currentStamp = referenceStamp(p);
  const previous = !p.model && p.studioRequests.findLast(task =>
    !task.method && task.status === 'awaiting_agent' && task.referenceStamp === currentStamp);
  const task = {
    id: previous?.id ?? randomUUID(), status: 'awaiting_agent', at: now(), method: p2Method,
    referenceStamp: currentStamp, referenceSha256: p.reference.sha256,
    references: references.map(({view, id: assetId, sha256}) => ({view, assetId, sha256})),
    note: String(payload.note ?? previous?.note ?? '').slice(0,1000), received: [], assetIds: {}};
  const directory = projectDir(p.id);
  const cli = path.join(ROOT, 'scripts/project.mjs');
  const base = `http://127.0.0.1:${server.address().port}`;
  setTaskMessage(task,()=>[
    msg`请为 HairBridge 项目 ${p.name} 在 Tripo Studio 生成并拆分一批粗模候选。`,
    msg`项目 ${p.id} · 任务 ${task.id}`,
    msg`项目文件 ${path.join(directory, 'project.hairbridge')}`,
    t('用本项目已确认的四视图，左右以角色自身为准。'),
    ...references.map(asset => `${t(VIEW_LABELS[asset.view])} ${path.join(directory, asset.file)} · SHA-256 ${asset.sha256}`),
    t('在用户已登录的 Tripo Studio 选择 Private、Smart Mesh P2.0 和 Quad New，目标每个 25,000 面，在已授权范围内提交一批四个带发候选。保留原始 FBX、实际面数和候选编号。'),
    t('逐个检查头皮和发型。选择头顶到后颈弧度自然，且刘海、两鬓、发际线、马尾扎点与尖梢保留完整的同一个候选。'),
    t('从选中的候选分出无发头模和整套独立头发。优先识别原网格连通部件，必要时用 Custom · By Part。可用提示 “Separate the complete hairstyle, including the bangs, side locks, crown, nape hair, and ponytail, from the head, ears, neck, and existing scalp.”'),
    t('为同一候选保存拆分前的整头粗模 GLB，再分别导出无发头模和独立头发 GLB，含内嵌资源。三份沿用该候选的原点、比例和朝向，保持在同一坐标系。独立部件沿用原位置，无需跨模型配准。'),
    t('叠加检查发际线、耳后和后颈的贴合，核对眼眶与颈底开口。若该候选缺头皮或发束不完整，就检查本批其他候选。只有同一候选的三份文件齐全且可叠加时才登记，并记录选中的编号与缺项。'),
    task.note ? msg`本轮要求 ${task.note}` : '',
    msg`先在 PowerShell 设置 $env:HAIRBRIDGE_URL='${base}'，再核对请求`,
    `node "${cli}" show-p2-request ${p.id} ${task.id}`,
    t('三份 GLB 回填后交由用户叠加确认，再进入导线生成。'),
    msg`node "${cli}" attach-p2 ${p.id} ${task.id} "coarse=整头粗模GLB绝对路径" "head=无发头模GLB绝对路径" "hair=独立头发GLB绝对路径"`,
  ].filter(Boolean).join('\n'),false);
  for (const other of p.studioRequests) {
    if (other !== previous && other.status === 'awaiting_agent') other.status = 'superseded';
  }
  if (p.separation) supersedeSeparationRequests(p.separation);
  if (previous) Object.assign(previous, task);
  else p.studioRequests.push(task);
  record(p, t('准备粗模生成与拆分任务'), t('一批候选，交回同一候选的三份 GLB。'));
}

function requirePreparedP2(p) {
  if (p.model?.method === p2Method && !approvedSeparation(p)) throw Error(t('请先叠加审核并确认头模与头发。'));
}

async function attachP2(p, task, slot, name, bytes) {
  const references = confirmedP2Views(p);
  if (!['awaiting_agent', 'registered'].includes(task.status) || task.referenceStamp !== referenceStamp(p) ||
      !Array.isArray(task.references) || task.references.length !== references.length ||
      references.some((asset, index) => task.references[index]?.view !== asset.view ||
        task.references[index].assetId !== asset.id || task.references[index].sha256 !== asset.sha256) ||
      (task.status === 'registered' && p.model?.id !== task.assetIds.coarse)) {
    throw Error(t('粗模任务已失效，请检查当前参考图和模型。'));
  }
  if (task.received.includes(slot)) {
    const existing = p.assets.find(asset => asset.id === task.assetIds[slot]);
    if (existing?.sha256 === hash(bytes)) return view(p);
    throw Error(t('这份文件已登记，若需更换请准备一条新的粗模任务。'));
  }
  const asset = await addAsset(p, p2Roles[slot], name, bytes);
  Object.assign(asset, {method: p2Method, origin: 'agent', requestId: task.id, referenceStamp: task.referenceStamp});
  task.received.push(slot);
  task.assetIds[slot] = asset.id;
  if (Object.keys(p2Roles).every(part => task.received.includes(part))) {
    const findPart = (part) => p.assets.find(item => item.id === task.assetIds[part]);
    const coarse = findPart('coarse'), head = findPart('head'), hair = findPart('hair');
    invalidate(p, 'model');
    p.cards = null;
    p.model = coarse;
    Object.assign(head, separationInputs(p));
    Object.assign(hair, separationInputs(p));
    const separation = p.separation ??= separationState();
    Object.assign(separation, {head, hair, review: null});
    task.status = 'registered';
    task.modelSha256 = coarse.sha256;
    record(p, t('收到粗模与拆分结果'), t('整头粗模、头模和头发已就绪，等待叠加审核。'));
  } else {
    record(p, t('收到粗模部件'), `${p2Labels[slot]} · ${asset.name}`);
  }
  await save(p);
  return view(p);
}

async function attachSeparation(p, slot, name, bytes, {requestId, ...expected}) {
  requireSeparationInputs(p);
  if (p.model.method === p2Method) throw Error(t('请通过同一条粗模任务一起登记整头粗模、头模和头发。'));
  const inputs = checkSeparationInputs(p, expected);
  const separation = p.separation ??= separationState();
  const task = requestId ? separation.requests.find(candidate => candidate.id === requestId) : null;
  if (requestId && (!task || !['awaiting_agent', 'registered'].includes(task.status) ||
      Object.keys(inputs).some(key => task[key] !== inputs[key]))) throw Error(t('拆分任务已失效，请检查当前粗模。'));
  if (task?.reusedHairId && (separation.hair?.id !== task.reusedHairId ||
      separation.hair.sha256 !== task.reusedHairSha256)) throw Error(t('当前头发已更换，请重新准备拆分任务。'));
  if (task?.received.includes(slot)) {
    const existing = p.assets.find(asset => asset.id === task.assetIds[slot]);
    if (existing?.sha256 === hash(bytes)) return view(p);
    throw Error(t('这个部件已登记。请上传手动替换或新建拆分任务。'));
  }
  const previousStamp = stamp(p);
  const asset = await addAsset(p, `separation-${slot}`, name, bytes);
  Object.assign(asset, inputs, {origin: task ? 'agent' : 'user', requestId: task?.id ?? null});
  if (slot === 'head' && task?.method === 'smart-mesh-p2') asset.method = task.method;
  if (task) {
    task.received.push(slot);
    task.assetIds[slot] = asset.id;
    if (task.received.length === 2) {
      task.status = 'registered';
      separation.head = p.assets.find(candidate => candidate.id === task.assetIds.head);
      separation.hair = p.assets.find(candidate => candidate.id === task.assetIds.hair);
      separation.review = null;
    }
  } else {
    supersedeP2Requests(p);
    supersedeSeparationRequests(separation);
    separation[slot] = asset;
    separation.review = null;
  }
  resetSeparationResult(p, previousStamp);
  record(p, t('登记拆分部件'), `${separationLabels[slot]} · ${asset.name}`);
  await save(p);
  return view(p);
}

function reviewSeparation(p, payload) {
  requireSeparationInputs(p);
  const inputs = checkSeparationInputs(p, payload);
  const {decision, headId, hairId} = payload;
  if (!['approved', 'skipped'].includes(decision)) throw Error(t('请选择确认拆分或使用整头粗模。'));
  if (p.model.method === p2Method && (decision !== 'approved' ||
      payload.modelId !== inputs.modelId || payload.referenceStamp !== inputs.referenceStamp || !headId || !hairId)) {
    throw Error(t('请查看并确认当前整头粗模、头模和头发。'));
  }
  const separation = p.separation ??= separationState();
  if ((headId !== undefined && headId !== (separation.head?.id ?? null)) ||
      (hairId !== undefined && hairId !== (separation.hair?.id ?? null))) throw Error(t('拆分部件已更换，请查看当前版本后再确认。'));
  if (decision === 'approved' && (!separation.head || !separation.hair)) throw Error(t('请先登记无发头模与独立头发两个 GLB。'));
  const previousStamp = stamp(p);
  if (decision === 'skipped') supersedeSeparationRequests(separation);
  separation.review = {decision, at: now(), note: String(payload.note ?? '').slice(0,1000), ...inputs,
    headId: separation.head?.id ?? null, hairId: separation.hair?.id ?? null};
  resetSeparationResult(p, previousStamp);
  record(p, decision === 'approved' ? t('确认头发与头部拆分') : t('使用整头粗模继续'), separation.review.note);
}

function liveStudioRequest(p,id) {
  const request=p.studioRequests.find(item=>item.id===id);
  const matching=request?.referenceStamp ? request.referenceStamp===referenceStamp(p) : request?.referenceSha256===p.reference?.sha256;
  return request?.status==='awaiting_agent' && p.approvals.reference && matching ? request : null;
}

async function attachReferenceView(p,name,bytes,slot,requestId) {
  if(p.referenceMode!=='multiview' || !p.sourceReference || !REFERENCE_VIEWS.includes(slot))
    throw Error(t('请先添加一张原图，再选择要补齐的视图。'));
  const request=requestId ? p.referenceRequests.find(item=>item.id===requestId) : null;
  if(requestId && (!request || request.status!=='awaiting_agent' || request.sourceSha256!==p.sourceReference.sha256 ||
      !request.views.includes(slot) || request.received.includes(slot))) throw Error(t('这个补图任务已失效或该视图已登记。'));
  const asset=await addAsset(p,'reference-view',name,bytes);
  invalidate(p,'reference-view');
  delete p.referenceReviews[slot];
  p.references=[...p.references.filter(item=>item.view!==slot),{...asset,view:slot,origin:request?'agent':'user'}]
    .sort((a,b)=>REFERENCE_VIEWS.indexOf(a.view)-REFERENCE_VIEWS.indexOf(b.view));
  p.reference=p.references.find(item=>item.view==='front') ?? null;
  if(request) {
    request.received.push(slot);
    if(request.views.every(view=>request.received.includes(view))) request.status='registered';
  } else {
    for(const pending of p.referenceRequests) {
      if(pending.status==='awaiting_agent' && pending.views.includes(slot)) pending.status='superseded';
    }
  }
  record(p,request?t('收到补图'):t('添加或替换视图'),`${VIEW_LABELS[slot]} · ${asset.name}`);
  await save(p);
  return view(p);
}

async function attach(p,role,name,bytes,params=new URLSearchParams()) {
  notRunning(p);
  const ext=path.extname(name).toLowerCase();
  const requestId = params.get('requestId');
  const p2Slot = Object.keys(p2Roles).find(slot => p2Roles[slot] === role);
  if (requestId && p2Slot) {
    const task = p.studioRequests.find(item => item.id === requestId && item.method === p2Method);
    if (task) {
      validateGlb(ext, bytes);
      return attachP2(p, task, p2Slot, name, bytes);
    }
  }
  if(role==='reference' || role==='reference-view') validateImage(ext,bytes);
  else if(role==='cards') {
    requirePreparedP2(p);
    validateCards(JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/,'')));
  }
  else if(role==='model') {
    if(requestId && !liveStudioRequest(p,requestId)) throw Error(t('Tripo 请求已失效。'));
    validateGlb(ext, bytes);
  } else if (['separation-head', 'separation-hair'].includes(role)) {
    validateGlb(ext, bytes);
    return attachSeparation(p, role.slice('separation-'.length), name, bytes, {
      requestId, modelId: params.get('modelId'), modelSha256: params.get('modelSha256'),
      referenceStamp: params.get('referenceStamp'),
    });
  } else throw Error(t('不支持的素材类型。'));
  if(role==='reference-view') return attachReferenceView(p,name,bytes,params.get('view'),requestId);
  const hadPreset = !!p.flow;
  if (role === 'model') supersedeP2Requests(p);
  invalidate(p,role);
  if (hadPreset && role==='model') p.cards=null;
  const original=role==='reference' && p.referenceMode==='multiview';
  const a=await addAsset(p,original?'source-reference':role,name,bytes);
  if(original) p.sourceReference=a;
  else p[role]=a;
  if(role==='cards')p.cards.count=validateCards(JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/,''))).count;
  record(p,t('添加素材'),`${role}: ${name}`); await save(p); return view(p);
}

function createReferenceRequest(p,payload) {
  if(p.referenceMode!=='multiview' || !p.sourceReference) throw Error(t('请先上传一张原图。'));
  const targets=payload.views ?? REFERENCE_VIEWS.filter(view=>!p.references.some(asset=>asset.view===view));
  if(!Array.isArray(targets) || targets.length===0 || targets.some(view=>!REFERENCE_VIEWS.includes(view)) ||
      new Set(targets).size!==targets.length) throw Error(t('请选择需要补齐或重做的视图。'));
  for(const pending of p.referenceRequests) {
    if(pending.status==='awaiting_agent' && pending.views.some(view=>targets.includes(view))) pending.status='superseded';
  }
  const task={id:randomUUID(),status:'awaiting_agent',at:now(),sourceSha256:p.sourceReference.sha256,
    views:targets,received:[],note:String(payload.note || '').slice(0,1000)};
  const directory=projectDir(p.id), cli=path.join(ROOT,'scripts/project.mjs');
  const base=`http://127.0.0.1:${server.address().port}`;
  const supplied=p.references.filter(asset=>!targets.includes(asset.view));
  const otherViews=supplied.map(asset=>`${t(VIEW_LABELS[asset.view])} ${path.join(directory,asset.file)}`).join('\n');
  const args=targets.map(view=>msg`"${view}=对应输出图片的绝对路径"`).join(' ');
  setTaskMessage(task,()=>msg`请在 HairBridge Studio 用原图补齐发型参考图。\n项目 ${p.id}\n任务 ${task.id}\n工作台 ${base}\n原图 ${path.join(directory,p.sourceReference.file)}\n待补 ${targets.map(view=>t(VIEW_LABELS[view])).join(getLanguage()==='en'?', ':'、')}。左右以角色自身为准。\n${otherViews?msg`已存视图供保持一致\n${otherViews}\n`:''}每张只画一个视角，保持同一角色、同一发型、发饰、分缝和不对称细节。统一头颈构图、正交机位、比例、光线和中性背景。补全看不见的发面时保留符合原图发流的结构。\n${task.note?msg`本轮修改 ${task.note}\n`:''}在生成前确认任务和原图仍有效。PowerShell 中设置 $env:HAIRBRIDGE_URL='${base}'，再运行\nnode "${cli}" show-reference-request ${p.id} ${task.id}\n完成后按视图分别保存图片，再登记\nnode "${cli}" attach-views ${p.id} ${task.id} ${args}\n只登记此任务的视图，交回工作台供用户逐张确认。`,false);
  p.referenceRequests.push(task);
  record(p,t('准备四视图补图任务'),targets.map(view=>t(VIEW_LABELS[view])).join(getLanguage()==='en'?', ':'、'));
}

function reviewReferenceView(p,payload) {
  if(p.referenceMode!=='multiview') throw Error(t('当前项目没有独立的四视图审核。'));
  const {view:slot,assetId,approved}=payload;
  const asset=p.references.find(item=>item.view===slot);
  if(!asset || asset.id!==assetId || typeof approved!=='boolean') throw Error(t('视图已更换，请查看当前图片后再确认。'));
  if(approved) p.referenceReviews[slot]={assetId:asset.id,at:now()};
  else {
    const previousStamp = stamp(p);
    delete p.referenceReviews[slot];
    delete p.approvals.reference;
    delete p.approvals.draft;
    delete p.approvals.finish;
    for(const request of p.studioRequests) {
      if(request.status==='awaiting_agent') request.status='superseded';
    }
    invalidateSeparation(p);
    resetSeparationResult(p, previousStamp);
  }
  record(p,approved?t('确认一张参考图'):t('撤回视图确认'),VIEW_LABELS[slot]);
}
async function listProjects() {
  await fs.mkdir(PROJECTS,{recursive:true}); const names=await fs.readdir(PROJECTS);
  const projects=await Promise.all(names.filter(idOK).map(id=>load(id).catch(()=>null)));
  return projects.filter(Boolean).map(p=>({id:p.id,name:p.name,updatedAt:p.updatedAt,stage:view(p).stage,
    entryMode:p.entryMode})).sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt));
}
async function demo() {
  if(await exists(path.join(ROOT,'examples/rain-study/project.hairbridge')))return view(await installExample(DATA));
  const base=path.resolve(ROOT,'../assignment/A2_Hair_Bridge/rain_v3');
  if(!await exists(path.join(base,'inference/cards_seed0.json')))throw Error(t('本机 Rain 示例未找到。可新建项目并导入自己的参考图和 cards JSON。'));
  const p=makeProject(t('Rain · 已有成果演示')); await save(p);
  await attach(p,'reference','Rain.png',await fs.readFile(path.join(base,'reference_input.png')));
  await attach(p,'cards','cards_seed0.json',await fs.readFile(path.join(base,'inference/cards_seed0.json')));
  const model=await addAsset(p,'draft-model','hair_seed0.glb',await fs.readFile(path.join(base,'inference/hair_seed0.glb')));
  p.cards.preview=model;
  if(await exists(path.join(base,'rain_comparison.png')))
    await addAsset(p,'evidence','Rain_existing_comparison.png',await fs.readFile(path.join(base,'rain_comparison.png')));
  record(p,t('导入已有成果'),t('复用此前的 Rain HairDeck 输出；本次没有重新推理或调用 Tripo。待用户审核。'));
  await save(p); return view(p);
}

async function rainTripo() {
  const preset = JSON.parse(await fs.readFile(RAIN_PRESET,'utf8'));
  const directory = path.dirname(RAIN_PRESET);
  async function source(relative, extension) {
    if (typeof relative !== 'string') throw Error(t('Rain 试跑素材清单不完整。'));
    const file = await fs.realpath(path.resolve(directory,relative));
    if (!file.toLowerCase().startsWith(path.resolve(A2).toLowerCase()+path.sep) || path.extname(file).toLowerCase()!==extension)
      throw Error(t('Rain 试跑素材路径无效。'));
    const data = await fs.readFile(file);
    return {name:path.basename(file),data};
  }
  const refs = await Promise.all(preset.references.map(async reference => ({view:reference.view,...await source(reference.path,'.png')})));
  if (new Set(refs.map(reference=>reference.view)).size!==4 || !['front','left','right','back'].every(view=>refs.some(reference=>reference.view===view)))
    throw Error(t('Rain 试跑需正面、左右侧面和背面参考。'));
  const specs = {model:['.glb','model'], cards:['.json','cards'], preparedBlend:['.blend','prepared-blend'],
    head:['.glb','review-context'], preview:['.glb','draft-model'], markMesh:['.glb','flow-marks']};
  const pieces = await Promise.all(Object.entries(specs)
    .filter(([key])=>key!=='markMesh' || preset.markMesh)
    .map(async ([key,[ext,role]])=>[key,{role,...await source(preset[key],ext)}]));
  const count = validateCards(JSON.parse(pieces.find(([key])=>key==='cards')[1].data)).count;
  if (!Array.isArray(preset.strands) || preset.strands.length!==count ||
      !preset.strands.every((strand,index)=>strand.index===index && typeof strand.objectName==='string' && /^[a-z0-9_-]+$/i.test(strand.id)) ||
      new Set(preset.strands.map(strand=>strand.id)).size!==count || typeof preset.scene!=='string')
    throw Error(t('Rain 导线清单与初稿不匹配。'));
  const p = makeProject(t('Rain v3 · Tripo 发流试跑'));
  p.references = [];
  for (const ref of refs) p.references.push({...await addAsset(p,'reference',ref.name,ref.data),view:ref.view});
  p.reference = p.references.find(asset=>asset.view==='front');
  const assets = {};
  for (const [key,asset] of pieces) assets[key] = await addAsset(p,asset.role,asset.name,asset.data);
  p.model = assets.model;
  p.cards = {...assets.cards,count,preview:assets.preview};
  p.flow = {strands:preset.strands,reviews:{},aligned:true,head:assets.head,markMesh:assets.markMesh,
    camera:preset.camera,preparedBlend:assets.preparedBlend,scene:preset.scene};
  record(p,t('建立 Rain 试跑项目'),t('载入四视图、已对齐的 Tripo 粗模、发流标记和两束导线初稿，等待人工确认。'));
  await save(p);
  return view(p);
}

function saveFlowDecision(p, payload) {
  const {strandId,decision,targetId,direction='as-fitted'} = payload;
  const strand = p.flow?.strands.find(item=>item.id===strandId);
  if (!p.approvals.reference || !strand || !['keep','connect','split','adjust'].includes(decision) ||
      !['as-fitted','reverse'].includes(direction)) throw Error(t('请选择当前项目的发束和有效的发流决定。'));
  if (decision==='connect' && (targetId===strandId || !p.flow.strands.some(item=>item.id===targetId)))
    throw Error(t('请选择要连接的另一束。'));
  const note = String(payload.note || '').slice(0,1000);
  p.flow.reviews[strandId] = {decision,direction,note,at:now(),...(decision==='connect'?{targetId}:{})};
  delete p.approvals.draft;
  delete p.approvals.finish;
  record(p,t('记录发流决定'),`${strand.label} · ${note || {keep:t('保留'),connect:t('待连接'),split:t('待拆分'),adjust:t('待调整')}[decision]}`);
}
let scalpCache;

async function startJob(p,kind,requestId,options={}) {
  if(!idOK(requestId))throw Error(t('请求 ID 无效。'));
  const duplicate=p.jobs.find(j=>j.requestId===requestId);
  if(duplicate)return view(p);
  notRunning(p);
  if(!p.approvals.reference)throw Error(t('请先确认参考图。'));
  if(!['hairdeck','blender','hair-closure'].includes(kind))throw Error(t('未知任务。'));
  const hairdeckPreviewOnly = kind === 'hairdeck' && options.previewOnly === true;
  if (!hairdeckPreviewOnly) requirePreparedP2(p);
  if(kind==='hairdeck'&&!p.reference)throw Error(t('HairDeck 需要已确认的参考图。'));
  if (kind==='hairdeck' && !hairdeckPreviewOnly && p.flow) throw Error(t('请在普通项目中生成 HairDeck 导线。'));
  if(kind==='blender'&&(!p.cards||!p.approvals.draft))throw Error(t('请先审核导线并确认进入 Blender。'));
  if(kind==='hairdeck'&&running.size)throw Error(t('已有生成任务运行，请稍后再试。'));
  const c=await config();
  const exe=kind==='hairdeck'?c.hairdeckPython:c.blender;
  if(!await exists(exe))throw Error(msg`${kind} 未配置。请编辑 local-config.json 指定本机路径。`);
  const job={id:randomUUID(),requestId,kind,status:'running',createdAt:now(),inputStamp:stamp(p),log:'',options};
  const dir=path.join(projectDir(p.id),'runs',job.id);await fs.mkdir(dir,{recursive:true});
  job.directory=`runs/${job.id}`;
  const params={uiLanguage:getLanguage(),projectId:p.id,jobId:job.id,output:dir,hairdeckRoot:c.hairdeckRoot,
    reference:p.reference?path.join(projectDir(p.id),p.reference.file):null,cards:p.cards?path.join(projectDir(p.id),p.cards.file):null,
    model:p.model?path.join(projectDir(p.id),p.model.file):null,seed:Math.max(0,Math.min(2147483646,Math.trunc(Number(options.seed)||0))),
    bridge:path.join(ROOT,'addon/hairbridge_studio'),projectFile:path.join(projectDir(p.id),'project.hairbridge'),inputStamp:job.inputStamp,
    studioUrl:`http://127.0.0.1:${server.address().port}`};
  const separation = kind !== 'hairdeck' ? approvedSeparation(p) : null;
  if (kind === 'hair-closure') {
    if (!separation) throw Error(t('请先确认当前粗模的独立头发和头皮。'));
    params.sourceHair = path.join(projectDir(p.id),separation.hair.file);
  }
  if (separation) params.separation = {
    head:path.join(projectDir(p.id),separation.head.file),hair:path.join(projectDir(p.id),separation.hair.file),
  };
  let fittedSections, savedSections, hasFitted;
  const editingPointFlow = !!(p.pointFlow && pointFlowAvailable(p));
  if (kind === 'blender' && (editingPointFlow || options.fitUv || p.result?.fittedSections && !p.flow)) {
    const strands = editingPointFlow ? generatedStrands(p.pointFlow) :
      Array.from({length:p.cards.count},(_,i) => ({id:`guide-${i+1}`,label:msg`导线 ${i+1}`,tipAt:1}));
    params.strandIds = strands.map(({id}) => id);
    if (p.cards.count !== strands.length) throw Error(t('本次勾选列表与导线文件不匹配。'));
    const stored = options.baseVersionId ? versions(p).find(version =>
      version.id === options.baseVersionId && version.sourceStamp === stamp(p)) : (p.result ?? p.pointFlow);
    if (!stored) throw Error(t('选定的截面基准与当前导线不匹配。'));
    if (options.sectionPlan || options.sections || options.fitCoarse || options.fitUv || stored.fittedSections ||
        stored.sectionSettings || stored.sectionSources) {
      const cards = JSON.parse(await fs.readFile(params.cards,'utf8'));
      if (validateCards(cards).count !== strands.length) throw Error(t('截面设置与已确认的导线不匹配。'));
      let inferred = options.fitCoarse ? fitPointSections(p,cards,strands) : (stored.fittedSections ?? {});
      if (options.fitCoarse === 'requested' && !Object.keys(inferred).length) {
        throw Error(t('当前选区内没有足够的发面可拟合截面。'));
      }
      const plan = options.sectionPlan ? validateSectionPlan(options.sectionPlan,strands,inferred) :
        sectionPlan(strands,{...stored,fittedSections:inferred});
      if (options.fitUv) {
        const meshSource = closedHair(p);
        if (!meshSource) throw Error(t('请先生成当前独立头发的闭合粗模。'));
        const mesh = readStaticGlb(await fs.readFile(path.join(projectDir(p.id),meshSource.asset.file)),true);
        const current = activeSections(strands,plan.sources,plan.overrides,inferred);
        const fits = inferUvSections(mesh,strands.map((strand,i) => ({...strand,card:cards[i],
          fitted:current.fitted[strand.id],setting:current.settings[strand.id]})));
        if (!Object.keys(fits).length) throw Error(t('现有导线附近没有足够的截面样本。请检查导线与闭合粗模是否贴合。'));
        inferred = {...inferred};
        params.uvSectionFit = {closedAssetId:meshSource.asset.id,closureMethod:meshSource.report.method,
          baseVersionId:stored.id,measured:{},untouched:[]};
        for (const strand of strands) {
          const fit = fits[strand.id];
          if (!fit) {
            params.uvSectionFit.untouched.push(strand.id);
            continue;
          }
          inferred[strand.id] = fit.data;
          plan.sources[strand.id] = 'fitted';
          plan.overrides.fitted[strand.id] = fit.setting;
          params.uvSectionFit.measured[strand.id] = fit.data.uvFit;
        }
      }
      if (options.sections) {
        const settings = validateSections(options.sections,strands);
        for (const {id} of strands) plan.overrides[plan.sources[id]][id] = settings[id];
      }
      const {settings,fitted} = activeSections(strands,plan.sources,plan.overrides,inferred);
      hasFitted = Object.keys(fitted).length > 0;
      if (Object.keys(inferred).length) fittedSections = inferred;
      const profiles = strands.map(({id,tipAt}, index) => settings[id] || fitted[id]
        ? sectionOffsets(cards[index],settings[id],tipAt,undefined,fitted[id]) : null);
      if (profiles.some(Boolean)) params.sectionProfiles = profiles;
      if (strands.some(({id}) => settings[id]?.scalpInset !== undefined)) {
        if (!params.separation || p.flow) throw Error(t('贴头皮端内嵌需要已审核的独立头皮网格。'));
        if (scalpCache?.sha !== separation.head.sha256) {
          scalpCache = {sha:separation.head.sha256,surface:await readScalpSurface(params.separation.head)};
        }
        params.scalpInsets = strands.map(({id,label,region},i) => {
          const depth = settings[id]?.scalpInset;
          if (depth === undefined) return null;
          if (region !== 'back') throw Error(t('请选择具有贴头皮端的后脑发束。'));
          const inset = insetScalpEnd(cards[i],profiles[i].at(-1),scalpCache.surface,depth);
          if (!inset) throw Error(msg`${label}的末端未找到可内嵌的头皮，请检查端点或减小深度。`);
          const {offsets,shift,span} = inset;
          return {offsets,shift,span,depth};
        });
      }
      savedSections = {sectionSettings:settings,sectionSources:plan.sources,sectionOverrides:plan.overrides};
    }
  }
  if (kind==='blender' && p.flow) params.prepared = {file:path.join(projectDir(p.id),p.flow.preparedBlend.file),
    scene:p.flow.scene,strands:p.flow.strands,reviews:p.flow.reviews};
  await fs.writeFile(path.join(dir,'job.json'),JSON.stringify(params,null,2));
  if(kind==='hairdeck' && !hairdeckPreviewOnly) {
    p.versions = versions(p);
    delete p.approvals.draft;delete p.approvals.finish;p.result=null;
  }
  const jobLabel = hairdeckPreviewOnly ? t('HairDeck 初稿对照') : kind;
  p.jobs.push(job);record(p,t('启动任务'),jobLabel);await save(p);
  const args=kind==='hairdeck'?[path.join(ROOT,'scripts/hairdeck_worker.py'),path.join(dir,'job.json')]:
    ['--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',
      path.join(ROOT,kind==='hair-closure' ? 'scripts/blender_close_hair.py' : 'scripts/blender_build.py'),
      '--',path.join(dir,'job.json')];
  const child=spawn(exe,args,{shell:false,windowsHide:true,cwd:ROOT,env:{...process.env,PYTHONUTF8:'1',PYTHONUNBUFFERED:'1',
    HAIRDECK_ROOT:c.hairdeckWorkspace,HAIRDECK_OFFLOAD:'on',HF_HUB_OFFLINE:'1',TRANSFORMERS_OFFLINE:'1',
    HF_HOME:path.join(c.hairdeckWorkspace,'cache/huggingface'),TORCH_HOME:path.join(c.hairdeckWorkspace,'cache/torch'),
    TRITON_CACHE_DIR:path.join(c.hairdeckWorkspace,'cache/triton'),GRADIO_ANALYTICS_ENABLED:'False'}});
  let output='',settled=false;
  const collect=chunk=>{output=(output+chunk.toString()).slice(-12000);};
  child.stdout.on('data',collect);child.stderr.on('data',collect);running.set(job.id,{child,project:p.id,getLog:()=>output});
  const timer=setTimeout(()=>{output+=t('\n任务超时，已停止。');child.kill();},20*60*1000);timer.unref();
  async function finish(code,error) {
    if(settled)return;settled=true;clearTimeout(timer);running.delete(job.id);
    await fs.writeFile(path.join(dir,'run.log'),output).catch(()=>{});
    await serial(async()=>{
      const latest=await load(p.id), saved=latest.jobs.find(j=>j.id===job.id);
      if(saved.status==='cancelled')return;
      saved.finishedAt=now();saved.log=output.slice(-6000);
      try {
        if(error||code!==0)throw Error(error?.message||output.slice(-1500)||msg`进程退出：${code}`);
        const result=JSON.parse(await fs.readFile(path.join(dir,'result.json'),'utf8'));
        if(!result.success)throw Error(result.error||t('任务未通过检查。'));
        if(stamp(latest)!==job.inputStamp)throw Error(t('输入已经改变，请重做此阶段。'));
        if (hairdeckPreviewOnly) {
          const previewPath = path.join(dir, 'preview.glb');
          if (!await exists(previewPath)) throw Error(t('HairDeck 未输出初稿预览。'));
          const bytes = await fs.readFile(previewPath);
          validateGlb('.glb', bytes);
          latest.hairdeckPreview = await addAsset(latest, 'draft-model', 'HairDeck_preview.glb', bytes);
        } else if(kind==='hairdeck') {
          const cards=await fs.readFile(path.join(dir,'cards.json'));const stats=validateCards(JSON.parse(cards));
          latest.cards=await addAsset(latest,'cards','cards.json',cards);latest.cards.count=stats.count;
          if(await exists(path.join(dir,'preview.glb'))) {
            latest.cards.preview=await addAsset(latest,'draft-model','HairDeck_preview.glb',await fs.readFile(path.join(dir,'preview.glb')));
            delete latest.hairdeckPreview;
          }
        } else if (kind==='hair-closure') {
          const bytes=await fs.readFile(path.join(dir,'closed-hair.glb'));
          validateGlb('.glb',bytes);
          const asset=await addAsset(latest,'closed-hair',t('闭合测量粗模.glb'),bytes);
          latest.closedHair={asset,hairId:separation.hair.id,hairHash:separation.hair.sha256,report:result};
          record(latest,t('登记闭合测量粗模'),result.method === 'tripo' ? t('Tripo 快速封口') : t('本地生成'));
        } else {
          const blend=await addAsset(latest,'blend','hairbridge.blend',await fs.readFile(path.join(dir,'hairbridge.blend')));
          const preview=await addAsset(latest,'result-model','hairbridge.glb',await fs.readFile(path.join(dir,'hairbridge.glb')));
          if (savedSections && editingPointFlow) {
            for (const key of ['sectionSettings','sectionSources']) {
              latest.pointFlow[key] = {...latest.pointFlow[key],...savedSections[key]};
            }
            const prior = latest.pointFlow.sectionOverrides;
            latest.pointFlow.sectionOverrides = {
              original:{...prior?.original,...savedSections.sectionOverrides.original},
              fitted:{...prior?.fitted,...savedSections.sectionOverrides.fitted},
            };
          }
          if (params.uvSectionFit) result.uv_section_fit=params.uvSectionFit;
          saveResult(latest,{blend,preview,report:result,createdAt:now(),sourceStamp:stamp(latest),
            ...savedSections, ...(fittedSections ? {fittedSections} : {})},
            options.fitUv ? (params.uvSectionFit.closureMethod === 'tripo' ? t('Tripo 封口 · UV 平滑截面') :
              t('沿 UV 测量与平滑截面')) : options.sections || options.sectionPlan ? options.sectionLabel || t('截面调整') :
              hasFitted ? t('粗模拟合截面') : t('Blender 初稿'));
        }
        saved.status='succeeded';record(latest,t('任务完成'),jobLabel);
      } catch(e) { saved.status='failed';saved.error=e.message;record(latest,t('任务失败'),`${jobLabel}：${e.message}`); }
      await save(latest);
    }).catch(e=>console.error('Job record:',e.message));
  }
  child.on('error',e=>{void finish(null,e);});child.on('close',code=>{void finish(code);});
  return view(p);
}
const types={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8',
  '.json':'application/json','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.glb':'model/gltf-binary','.svg':'image/svg+xml','.zip':'application/zip'};
async function bytes(req,max=100*1024**2) { let n=0,chunks=[];for await(const c of req){n+=c.length;if(n>max)throw Error(t('文件过大（限 100 MB）。'));chunks.push(c);}return Buffer.concat(chunks); }
const body=async req=>JSON.parse((await bytes(req,1024**2)).toString()||'{}');
const send=(res,status,p)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(p));};
async function file(res,p,name) {
  const data=await fs.readFile(p);res.writeHead(200,{'Content-Type':types[path.extname(p)]||'application/octet-stream','Content-Length':data.length,
    'X-Content-Type-Options':'nosniff',...(name?{'Content-Disposition':`attachment; filename*=UTF-8''${encodeURIComponent(name)}`}:{})});res.end(data);
}
const server=http.createServer((req,res)=>withLanguage(requestLanguage(req),async()=>{
  try {
    const host=req.headers.host;
    if(!host||!/^127\.0\.0\.1:\d+$/.test(host)||req.headers.origin&&req.headers.origin!==`http://${host}`)return send(res,403,{error:t('仅接受本机同源访问。')});
    const u=new URL(req.url,`http://${host}`), route=u.pathname;
    if(route==='/api/capabilities'&&req.method==='GET')return send(res,200,await capabilities());
    if(route==='/api/projects'&&req.method==='GET')return send(res,200,await listProjects());
    if(route==='/api/projects'&&req.method==='POST') {
      const b=await body(req);
      const entryMode=b.entryMode ?? 'image';
      if(!['image','coarse'].includes(entryMode))throw Error(t('请选择从图片或已有粗模开始。'));
      return send(res,201,await serial(async()=>{
        const p=makeProject(b.name);
        p.entryMode=entryMode;
        if(entryMode==='image')Object.assign(p,{referenceMode:'multiview',sourceReference:null,references:[],
          referenceReviews:{},referenceRequests:[]});
        record(p,t('创建项目'),entryMode==='image'?t('从一张图片开始'):t('从已有 Tripo 粗模开始'));
        await save(p);return view(p);
      }));
    }
    if(route==='/api/demo'&&req.method==='POST')return send(res,201,await serial(demo));
    if(route==='/api/rain-tripo'&&req.method==='POST')return send(res,201,await serial(rainTripo));
    if(route==='/api/addon'&&req.method==='GET')return await file(res,path.join(ROOT,'installers/hairbridge_studio.zip'),'hairbridge_studio.zip');
    const m=route.match(/^\/api\/projects\/([a-f0-9-]{36})(?:\/(.*))?$/);
    if(m) {
      const id=m[1],action=m[2]||'';
      if(req.method==='GET') {
        const p=await load(id);
        if(!action){for(const j of p.jobs)if(running.has(j.id))j.log=running.get(j.id).getLog();return send(res,200,view(p));}
        if(action==='point-flow')return send(res,200,pointFlowFixture(p));
        if(action==='manifest')return await file(res,path.join(projectDir(id),'project.hairbridge'),'project.hairbridge');
        if(action==='export') {
          const entries=[['project.hairbridge',Buffer.from(JSON.stringify(p,null,2))]];
          for(const a of p.assets)entries.push([a.file,await fs.readFile(path.join(projectDir(id),a.file))]);
          entries.push(['OPEN_ME.txt',Buffer.from(projectPackageInstructions(),'utf8')]);
          const archive=zip(entries);res.writeHead(200,{'Content-Type':'application/zip','Content-Disposition':`attachment; filename="hairbridge-${id.slice(0,8)}.zip"`,'Content-Length':archive.length});res.end(archive);return;
        }
        if(action.startsWith('assets/')) {const a=p.assets.find(x=>x.id===action.slice(7));if(!a)return send(res,404,{error:t('素材不存在。')});return await file(res,path.join(projectDir(id),a.file),u.searchParams.has('download')?a.name:null);}
      }
      if(req.method==='POST') {
        if(action==='upload') {
          const data=await bytes(req);
          const params=u.searchParams;
          return send(res,200,await serial(async()=>attach(await load(id),params.get('role'),params.get('name')||'asset',
            data,params)));
        }
        const b=await body(req);
        const result=await serial(async()=>{
          const p=await load(id);
          if (action.startsWith('surface-')) {
            notRunning(p);
            const change = editSurfaceFlow(p,action,b,{
              file: asset => path.join(projectDir(p.id),asset.file),
              command: msg`在 PowerShell 设置 $env:HAIRBRIDGE_URL='http://127.0.0.1:${server.address().port}'，再运行\nnode "${path.join(ROOT,'scripts/project.mjs')}"`,
            });
            if (change) {record(p,...change);await save(p);}
            return view(p);
          }
          if(action==='point-region-confirm') {
            notRunning(p);
            const region = confirmPointRegion(p,b);
            if (region) {record(p,t('确认发流区块'),region.label);await save(p);}
            return view(p);
          }
          if(action==='point-region-move-strand') {
            notRunning(p);
            const move = movePointRegionStrand(p,b);
            if (move) {
              record(p,t('调整发束归属'),`${move.strand.label} → ${move.destination.label}`);
              await save(p);
            }
            return view(p);
          }
          if(action==='point-flow-confirm') {
            if (p.jobs.some(job=>job.requestId===b.requestId)) return view(p);
            if (!idOK(b.requestId)) throw Error(t('请求 ID 无效。'));
            notRunning(p);
            if (!await exists((await config()).blender)) throw Error(t('请先配置本机 Blender。'));
            const {cards, edits, selectedIds, version, modelSha256, hairSha256, acceptedRecipes, strandRegions,customStrands} = resolvePointFlow(p,b);
            const sectionSettings = {...p.pointFlow?.sectionSettings,...p.result?.sectionSettings};
            const sectionSources = {...p.pointFlow?.sectionSources,...p.result?.sectionSources};
            const sectionOverrides = p.result?.sectionOverrides ? {
              original:{...p.pointFlow?.sectionOverrides?.original,...p.result.sectionOverrides.original},
              fitted:{...p.pointFlow?.sectionOverrides?.fitted,...p.result.sectionOverrides.fitted},
            } : p.pointFlow?.sectionOverrides;
            const encoded = Buffer.from(JSON.stringify(cards));
            if (p.cards?.sha256 !== hash(encoded)) {
              invalidate(p,'cards');
              p.cards = await addAsset(p,'cards','point-flow-guides.json',encoded);
              p.cards.count = cards.length;
            }
            p.pointFlow = {version, modelSha256, hairSha256, cardsId:p.cards.id, edits, selectedIds,
              ...(Object.keys(sectionSettings).length ? {sectionSettings} : {}),
              ...(Object.keys(sectionSources).length ? {sectionSources} : {}),
              ...(sectionOverrides ? {sectionOverrides} : {}), ...(strandRegions ? {strandRegions} : {}),
              ...(customStrands?.length ? {customStrands} : {})};
            if (acceptedRecipes) p.surfaceFlow.generatedRecipes = acceptedRecipes;
            const labels = generatedStrands(p.pointFlow).map(({label}) => label).join('、');
            p.approvals.draft = {at:now(),stamp:stamp(p),note:labels};
            record(p,t('确认勾选发束'),labels);
            await save(p);
            return startJob(p,'blender',b.requestId,p.surfaceFlow?.enabled ? {fitCoarse:true} : {});
          }
          if(action==='point-section-fit') {
            if (p.jobs.some(job=>job.requestId===b.requestId)) return view(p);
            notRunning(p);
            if (!p.surfaceFlow?.enabled || !pointFlowAvailable(p) || !p.pointFlow ||
                p.cards?.id !== b.cardsId || p.result?.id !== b.resultId ||
                p.result?.sourceStamp !== stamp(p) || p.revision !== b.revision) {
              throw Error(t('项目或导线已更新，请刷新后重试。'));
            }
            return startJob(p,'blender',b.requestId,{fitCoarse:'requested'});
          }
          if (action === 'hair-closure') {
            const hair = approvedSeparation(p)?.hair;
            if (!hair || b.hairId !== hair.id) throw Error(t('独立头发已更新，请刷新后再生成闭合粗模。'));
            if (b.tripoClosure !== undefined) throw Error(t('当前工作台提供本地闭合，请刷新页面后继续。'));
            return startJob(p,'hair-closure',b.requestId);
          }
          if (action === 'uv-section-fit') {
            if (p.flow || !p.cards || p.cards.id !== b.cardsId || !p.result || p.result.id !== b.resultId ||
                p.result.sourceStamp !== stamp(p) || p.revision !== b.revision ||
                closedHair(p)?.asset.id !== b.closedAssetId) {
              throw Error(t('请刷新项目，并确认已有导线、SHP 初稿和对应的闭合测量粗模。'));
            }
            return startJob(p,'blender',b.requestId,{fitUv:true,baseVersionId:b.baseVersionId});
          }
          if(action==='point-section-preview') {
            if (p.jobs.some(job=>job.requestId===b.requestId)) return view(p);
            notRunning(p);
            if (!pointFlowAvailable(p) || !p.pointFlow || p.cards?.id !== b.cardsId ||
                !p.approvals.draft || !p.result?.id || p.result.id !== b.resultId ||
                p.result.sourceStamp !== stamp(p)) throw Error(t('请先生成当前勾选发束的 SHP 预览。'));
            const strands = generatedStrands(p.pointFlow);
            const options = b.plan === undefined ? {sections:validateSections(b.settings,strands)} :
              {sectionPlan:validateSectionPlan(b.plan,strands,p.result.fittedSections)};
            if (typeof b.label === 'string') options.sectionLabel = b.label.trim().slice(0,64);
            return startJob(p,'blender',b.requestId,options);
          }
          if(action==='review') {
            notRunning(p);if(!['reference','draft','finish'].includes(b.step))throw Error(t('未知审核阶段。'));requireReview(p,b.step);
            if (b.step === 'draft') requirePreparedP2(p);
            if (b.step === 'reference' && coarseOnly(p) && b.modelId !== undefined && b.modelId !== p.model.id)
              throw Error(t('粗模已更换，请查看当前模型后再确认。'));
            p.approvals[b.step]={at:now(),stamp:stamp(p),note:String(b.note||'').slice(0,1000)};
            if(b.step==='finish')approveResult(p,p.approvals.finish);
            record(p,t('用户确认'),`${b.step}: ${p.approvals[b.step].note}`);await save(p);return view(p);
          }
          if(action==='flow-review') {notRunning(p);saveFlowDecision(p,b);await save(p);return view(p);}
          if(action==='reference-request') {notRunning(p);createReferenceRequest(p,b);await save(p);return view(p);}
          if(action==='reference-view-review') {notRunning(p);reviewReferenceView(p,b);await save(p);return view(p);}
          if(action==='separation-request') throw Error(t('请在「粗模与拆分」准备一条粗模生成与拆分任务。'));
          if(action==='separation-review') {notRunning(p);reviewSeparation(p,b);await save(p);return view(p);}
          if(action==='restore-version') {
            notRunning(p);const version=restoreResult(p,b.versionId);
            record(p,t('恢复成果版本'),version.label);await save(p);return view(p);
          }
          if(action==='job')return startJob(p,b.kind,b.requestId,b.options);
          if(action==='cancel') {
            const j=p.jobs.find(x=>x.id===b.jobId),run=j&&running.get(j.id);if(!run)throw Error(t('任务已结束。'));
            j.status='cancelled';j.finishedAt=now();j.log=run.getLog();record(p,t('停止任务'),j.kind);await save(p);run.child.kill();return view(p);
          }
          if(action==='note') {record(p,t('用户记录'),String(b.note||'').slice(0,2000));await save(p);return view(p);}
          if(action==='review-return') {
            notRunning(p);
            if(typeof b.folder!=='string'||!/^[0-9]{8}_[0-9]{6}_[a-f0-9]{6}$/.test(b.folder))throw Error(t('审核目录无效。'));
            const dir=path.join(projectDir(id),'reviews',b.folder),report=JSON.parse(await fs.readFile(path.join(dir,'review.json'),'utf8'));
            if(report.project_id!==id||report.source_stamp!==stamp(p))throw Error(t('精修副本基于旧的输入，请检查项目再返回。'));
            const key=`review:${b.folder}`;if(p.jobs.some(j=>j.requestId===key))return view(p);
            const blend=await addAsset(p,'blend','edited.blend',await fs.readFile(path.join(dir,'edited.blend')));
            const preview=await addAsset(p,'result-model','edited.glb',await fs.readFile(path.join(dir,'edited.glb')));
            saveResult(p,{blend,preview,report,createdAt:now(),sourceStamp:stamp(p)},t('Blender 精修'));
            p.jobs.push({id:randomUUID(),requestId:key,kind:'blender',status:'succeeded',createdAt:now(),finishedAt:now(),log:t('Blender 插件已返回人工精修副本。')});
            record(p,t('接收 Blender 精修'),msg`导线 ${report.guides} 束；等待用户审核。`);await save(p);return view(p);
          }
          if(action==='studio-request') {
            notRunning(p);
            createP2Request(p,b);await save(p);return view(p);
          }
          if(action==='register-model') {
            notRunning(p);const request=liveStudioRequest(p,b.requestId);
            if(!request)throw Error(t('Tripo 请求已失效。'));
            if(request.method===p2Method)throw Error(t('请使用 attach-p2 登记同一候选的三份 GLB。'));
            if(!p.model)throw Error(t('请先上传 GLB。'));request.status='registered';request.modelSha256=p.model.sha256;
            record(p,t('登记 Tripo 结果'),p.model.name);await save(p);return view(p);
          }
          throw Error(t('未知操作。'));
        });return send(res,200,result);
      }
      return send(res,404,{error:t('操作不存在。')});
    }
    if(req.method==='GET') {
      const relative=route==='/'?'index.html':decodeURIComponent(route.slice(1));
      const publicRoot=path.join(ROOT,'public'),target=path.resolve(publicRoot,relative);
      if(!target.startsWith(publicRoot+path.sep))return send(res,403,{error:t('路径无效。')});
      return await file(res,target);
    }
    send(res,404,{error:'Not found'});
  }catch(e){send(res,e.code==='ENOENT'?404:400,{error:e.code==='ENOENT'?t('文件或项目不存在。'):e.message});}
}));
export async function start(port=Number(process.env.PORT||8787)) {
  await fs.mkdir(PROJECTS,{recursive:true});
  // Bind first: launching a second instance must not rewrite the active server's job records.
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});
  for(const item of await listProjects()) {const p=await load(item.id);let changed=false;for(const j of p.jobs)if(['running','queued'].includes(j.status)){j.status='failed';j.error=t('服务中断；请检查已有输出后重试。');changed=true;}if(changed){record(p,t('恢复项目'),t('中断任务已标记，可检查输出后重试。'));await save(p);}}
  console.log(`HairBridge Studio: http://127.0.0.1:${server.address().port}`);return server;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  await start();
  for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{for(const task of running.values())task.child.kill();server.close(()=>process.exit(0));setTimeout(()=>process.exit(0),1500).unref();});
}
