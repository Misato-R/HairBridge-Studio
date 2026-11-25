import {t,msg,getLanguage,normalizeLanguage,setLanguageResolver} from '../public/i18n.mjs';
setLanguageResolver(()=>normalizeLanguage(process.env.HAIRBRIDGE_LANG ?? 'en'));
import {createHash} from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';

const [command, projectId, ...args] = process.argv.slice(2);
const address = new URL(process.env.HAIRBRIDGE_URL || 'http://127.0.0.1:8787');
const views = ['front', 'left', 'right', 'back'];
const separationParts = ['head', 'hair'];
const p2Parts = ['coarse', ...separationParts];
const maxImageSize = 20 * 1024 ** 2;
const maxGlbSize = 100 * 1024 ** 2;
const usage = [
  'node scripts/project.mjs status PROJECT_ID',
  'node scripts/project.mjs attach-model PROJECT_ID GLB REQUEST_ID',
  'node scripts/project.mjs show-reference-request PROJECT_ID REQUEST_ID',
  'node scripts/project.mjs attach-views PROJECT_ID REQUEST_ID front=PATH left=PATH right=PATH back=PATH',
  'node scripts/project.mjs show-p2-request PROJECT_ID REQUEST_ID',
  'node scripts/project.mjs attach-p2 PROJECT_ID REQUEST_ID coarse=PATH head=PATH hair=PATH',
  'node scripts/project.mjs show-separation-request PROJECT_ID REQUEST_ID',
  'node scripts/project.mjs attach-separation PROJECT_ID REQUEST_ID head=PATH hair=PATH',
  'node scripts/project.mjs attach-separation PROJECT_ID REQUEST_ID head=PATH  (when the task reuses hair)',
  'node scripts/project.mjs complete-surface-layout PROJECT_ID REQUEST_ID',
  'node scripts/project.mjs complete-surface-fit PROJECT_ID REQUEST_ID REGION_ID',
  'node scripts/project.mjs show-surface-refit-request PROJECT_ID REQUEST_ID REGION_ID MESH_JSON',
  'node scripts/project.mjs attach-surface-refit PROJECT_ID REQUEST_ID REGION_ID RESULT_JSON',
].join('\n');

if (address.protocol !== 'http:' || address.hostname !== '127.0.0.1' || address.username || address.password) {
  throw Error(t('HAIRBRIDGE_URL 需要指向本机工作台，例如 http://127.0.0.1:8787。'));
}
if (!/^[a-f0-9-]{36}$/.test(projectId || '')) throw Error(msg`需要有效项目 ID。\n${usage}`);
const projectRoute = `/api/projects/${projectId}`;

async function request(route, options) {
  let response;
  try {
    response = await fetch(address.origin + route, {...options, headers:{...options?.headers,'Accept-Language':getLanguage()}, redirect: 'error'});
  } catch (error) {
    throw Error(msg`无法请求本机工作台 ${address.origin}。`, {cause: error});
  }
  const result = await response.json();
  if (!response.ok) throw Error(result.error || msg`工作台请求失败（HTTP ${response.status}）。`);
  return result;
}

function referenceRequest(project, requestId) {
  const task = project.referenceRequests?.find(item => item.id === requestId);
  if (!task || !['awaiting_agent', 'registered'].includes(task.status) ||
      task.sourceSha256 !== project.sourceReference?.sha256) {
    throw Error(t('四视图请求已失效。请从当前原图重新创建请求。'));
  }
  return task;
}

function referenceSummary(project, task) {
  const received = task.received ?? [];
  return {
    projectId: project.id, requestId: task.id, status: task.status,
    views: task.views, received, remaining: task.views.filter(view => !received.includes(view)),
  };
}

function viewFiles(entries, task) {
  if (!entries.length) throw Error(usage);
  const files = new Map();
  for (const entry of entries) {
    const separator = entry.indexOf('=');
    const name = entry.slice(0, separator);
    const filename = entry.slice(separator + 1);
    if (separator < 1 || !filename || !views.includes(name) || !task.views.includes(name) || files.has(name)) {
      throw Error(t('请为本次请求的每个视图提供一次「视图=文件路径」，例如 front="C:\\views\\front.png"。'));
    }
    files.set(name, filename);
  }
  return [...files].filter(([view]) => !(task.received ?? []).includes(view));
}

async function readImage(view, filename) {
  const name = path.basename(filename);
  const stat = await fs.stat(filename);
  if (!stat.isFile() || stat.size > maxImageSize) throw Error(msg`${view} 需要有效的图片文件，大小限 20 MB。`);
  const bytes = await fs.readFile(filename);
  const ext = path.extname(name).toLowerCase();
  const valid = (ext === '.png' && bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) ||
    (['.jpg', '.jpeg'].includes(ext) && bytes[0] === 255 && bytes[1] === 216) ||
    (ext === '.webp' && bytes.toString('ascii', 0, 4) === 'RIFF' && bytes.toString('ascii', 8, 12) === 'WEBP');
  if (!valid || bytes.length > maxImageSize) throw Error(msg`${view} 需要有效的 PNG、JPEG 或 WebP 图片，大小限 20 MB。`);
  return {view, name, bytes};
}

async function attachViews(project, task, entries) {
  const images = await Promise.all(viewFiles(entries, task).map(([view, filename]) => readImage(view, filename)));
  for (const image of images) {
    const query = new URLSearchParams({role: 'reference-view', view: image.view, name: image.name, requestId: task.id});
    try {
      project = await request(`${projectRoute}/upload?${query}`, {method: 'POST', body: image.bytes});
    } catch (error) {
      throw Error(msg`登记 ${image.view} 失败。${error.message} 请求有效时可以重试同一命令，已登记的视图会跳过。`, {cause: error});
    }
  }
  return referenceSummary(project, referenceRequest(project, task.id));
}

function separationRequest(project, requestId) {
  const task = project.separation?.requests.find(item => item.id === requestId);
  if (!task || !project.model || !['awaiting_agent', 'registered'].includes(task.status) || task.modelId !== project.model.id ||
      task.modelSha256 !== project.model.sha256 || task.referenceStamp !== project.referenceStamp) {
    throw Error(t('拆分任务已失效。请在当前粗模上重新创建请求。'));
  }
  return task;
}

function smartMeshReferences(project, task) {
  const staleViews = t('P2.0 所用的四视图已更换或撤回确认，请重新创建任务。');
  if (project.referenceMode !== 'multiview' || !project.approvals?.reference ||
      !Array.isArray(task.references) || task.references.length !== views.length) throw Error(staleViews);
  return views.map(view => {
    const asset = project.references?.find(item => item.view === view);
    const input = task.references.find(item => item.view === view);
    if (!asset || !input || input.assetId !== asset.id || input.sha256 !== asset.sha256 ||
        project.referenceReviews?.[view]?.assetId !== asset.id) throw Error(staleViews);
    return {view, assetId: asset.id, sha256: asset.sha256, path: path.join(project.localDirectory, asset.file)};
  });
}

function smartMeshInputs(project, task) {
  const references = smartMeshReferences(project, task);
  if (!task.reusedHairId && !task.reusedHairSha256) return {references, reusedHair: null};
  const hair = project.separation?.hair;
  if (!hair || hair.id !== task.reusedHairId || hair.sha256 !== task.reusedHairSha256 ||
      !task.received.includes('hair') || task.assetIds?.hair !== hair.id) {
    throw Error(t('P2.0 任务使用的头发已更换，请重新创建任务。'));
  }
  return {references, reusedHair: {assetId: hair.id, sha256: hair.sha256, path: path.join(project.localDirectory, hair.file)}};
}

function separationSummary(project, task) {
  const method = task.method ?? 'ai-completion';
  return {
    projectId: project.id, requestId: task.id, status: task.status, method,
    received: task.received, remaining: separationParts.filter(part => !task.received.includes(part)),
    modelPath: path.join(project.localDirectory, project.model.file), modelSha256: task.modelSha256,
    referenceStamp: task.referenceStamp, note: task.note, message: task.message,
    ...(method === 'smart-mesh-p2' ? smartMeshInputs(project, task) : {}),
  };
}

function p2Request(project, requestId) {
  const task = project.studioRequests?.find(item => item.id === requestId);
  if (!task || task.method !== 'smart-mesh-p2' || !['awaiting_agent', 'registered'].includes(task.status) ||
      task.referenceStamp !== project.referenceStamp) {
    throw Error(t('P2.0 生成与拆分任务已失效。请用当前四视图重新创建任务。'));
  }
  if (task.status === 'registered' && (!task.assetIds?.coarse || project.model?.id !== task.assetIds.coarse)) {
    throw Error(t('P2.0 任务的整头粗模已更换。请用当前四视图重新创建任务。'));
  }
  return task;
}

function p2Summary(project, task) {
  const received = task.received ?? [];
  return {
    projectId: project.id, requestId: task.id, status: task.status, method: task.method,
    received, remaining: p2Parts.filter(part => !received.includes(part)),
    references: smartMeshReferences(project, task),
    referenceStamp: task.referenceStamp, note: task.note, message: task.message,
  };
}

function modelPartFiles(entries, parts) {
  if (!entries.length) throw Error(usage);
  const files = new Map();
  for (const entry of entries) {
    const separator = entry.indexOf('=');
    const part = entry.slice(0, separator);
    const filename = entry.slice(separator + 1);
    if (separator < 1 || !parts.includes(part) || !filename || files.has(part)) {
      throw Error(msg`请为每个部件至多提供一次文件路径。可用参数为 ${parts.map(key => msg`${key}=GLB路径`).join('、')}。`);
    }
    files.set(part, filename);
  }
  return files;
}

async function readGlb(part, filename) {
  const name = path.basename(filename);
  const stat = await fs.stat(filename);
  if (!stat.isFile() || stat.size > maxGlbSize || path.extname(name).toLowerCase() !== '.glb')
    throw Error(msg`${part} 需要有效的 GLB 文件，大小限 100 MB。`);
  const bytes = await fs.readFile(filename);
  if (bytes.length < 20 || bytes.length > maxGlbSize || bytes.toString('ascii', 0, 4) !== 'glTF' ||
      bytes.readUInt32LE(4) !== 2 || bytes.readUInt32LE(8) !== bytes.length)
    throw Error(msg`${part} 需要完整的 GLB 2.0 文件。`);
  return {part, name, bytes};
}

async function attachModelParts(project, task, entries, parts) {
  const received = task.received ?? [];
  const files = [...modelPartFiles(entries, parts)].filter(([part]) => parts === p2Parts || !received.includes(part));
  const models = await Promise.all(files.map(([part, filename]) => readGlb(part, filename)));
  const pending = models.filter(({part, bytes}) => {
    if (!received.includes(part)) return true;
    const staged = project.assets.find(asset => asset.id === task.assetIds?.[part]);
    if (staged?.sha256 !== createHash('sha256').update(bytes).digest('hex')) {
      throw Error(msg`${part} 与已登记的文件不同。请使用同一 P2.0 候选的原文件，或新建任务更换候选。`);
    }
    return false;
  });
  for (const model of pending) {
    const role = model.part === 'coarse' ? 'model' : `separation-${model.part}`;
    const query = new URLSearchParams({role, name: model.name, requestId: task.id});
    try {
      project = await request(`${projectRoute}/upload?${query}`, {method: 'POST', body: model.bytes});
    } catch (error) {
      throw Error(msg`登记 ${model.part} 失败。${error.message} 请求有效时可以重试，已登记的部件会跳过。`, {cause: error});
    }
  }
  return project;
}

async function main() {
  if (!['status', 'attach-model', 'show-reference-request', 'attach-views',
    'show-p2-request', 'attach-p2', 'show-separation-request', 'attach-separation',
    'complete-surface-layout','complete-surface-fit','show-surface-refit-request','attach-surface-refit'].includes(command))
    throw Error(usage);
  const project = await request(projectRoute);
  if (command === 'status') return project;
  if (command === 'attach-model') {
    const [filename, requestId] = args;
    const pending = project.studioRequests.find(item => item.id === requestId);
    if (pending?.method === 'smart-mesh-p2') {
      throw Error(t('此 P2.0 任务请使用 attach-p2 登记同一候选的整头、无发头模和独立头发。'));
    }
    if (!pending || pending.status !== 'awaiting_agent' || pending.referenceSha256 !== project.reference?.sha256) {
      throw Error(t('请求已失效，不能登记。'));
    }
    const query = new URLSearchParams({role: 'model', name: path.basename(filename), requestId});
    await request(`${projectRoute}/upload?${query}`, {method: 'POST', body: await fs.readFile(filename)});
    const result = await request(`${projectRoute}/register-model`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({requestId}),
    });
    return {id: result.id, model: result.model.name, requestId, status: 'registered'};
  }
  const [requestId, ...entries] = args;
  if (command === 'show-surface-refit-request' || command === 'attach-surface-refit') {
    const [regionId, filename] = entries;
    if (!filename || !path.isAbsolute(filename)) throw Error(t('请提供 JSON 文件的绝对路径。'));
    const region = project.surfaceFlow?.groups?.find(group => group.id === regionId);
    const task = region?.refitTask;
    const selectionHash = region && createHash('sha256').update(JSON.stringify(region.faces)).digest('hex');
    if (!region?.confirmed || task?.status !== 'pending' || task.id !== requestId ||
        task.modelSha256 !== project.model?.sha256 || task.hairSha256 !== project.separation?.hair?.sha256 ||
        task.selectionHash !== selectionHash) throw Error(t('当前重做任务已失效，请重新准备。'));
    if (command === 'attach-surface-refit') {
      const proposal = JSON.parse((await fs.readFile(filename,'utf8')).replace(/^\uFEFF/,''));
      const updated = await request(`${projectRoute}/surface-refit-submit`, {method:'POST',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({regionId,taskId:requestId,revision:project.revision,proposal})});
      const result = updated.surfaceFlow.groups.find(group => group.id === regionId).refitTask;
      return {projectId,requestId,regionId,status:result.status,guides:result.proposal.recipes.map(guide => guide.label),unresolved:result.proposal.unresolved};
    }
    const fixture = await request(`${projectRoute}/point-flow`);
    if (fixture.meshStamp !== task.meshStamp) throw Error(t('当前网格已变化，请重新准备。'));
    const {vertices,faces} = fixture.surfaceMesh;
    const triangles = region.faces.map(id => ({id,corners:faces.slice(id*3,id*3+3).map(vertex => vertices.slice(vertex*3,vertex*3+3))}));
    const existingGuides = region.guideRecipes.map(({id,label,manual,base}) => ({id,label,manual:!!manual,path:base.seq.map(row => row.slice(0,3))}));
    await fs.writeFile(filename,JSON.stringify({taskId:requestId,meshStamp:task.meshStamp,selectionHash,triangles,existingGuides}),{flag:'wx'});
    return {projectId,requestId,regionId,meshFile:filename,triangleCount:triangles.length,note:task.note};
  }
  if (command === 'complete-surface-layout' || command === 'complete-surface-fit') {
    const fitting = command === 'complete-surface-fit';
    const region = fitting ? project.surfaceFlow?.groups?.find(group => group.id === entries[0]) : null;
    const task = fitting ? region?.fitTask : project.surfaceFlow?.layoutTask;
    if (task?.status !== 'pending' || task.id !== requestId || task.modelSha256 !== project.model?.sha256 ||
        task.hairSha256 !== project.separation?.hair?.sha256) throw Error(t('当前模型和选区的任务已失效。'));
    const result = await request(`${projectRoute}/surface-${fitting ? 'fit' : 'layout'}-complete`, {
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({taskId:requestId,regionId:region?.id}),
    });
    return {projectId,taskId:requestId,regions:result.surfaceFlow.groups.map(group => ({id:group.id,label:group.label,
      faces:group.faces.length,confirmed:group.confirmed,guideCount:group.fitKey ? group.guideRecipes.length : 0}))};
  }
  if (command === 'show-p2-request' || command === 'attach-p2') {
    const task = p2Request(project, requestId);
    const summary = p2Summary(project, task);
    if (command === 'show-p2-request') return summary;
    const updated = await attachModelParts(project, task, entries, p2Parts);
    return p2Summary(updated, p2Request(updated, requestId));
  }
  if (['show-separation-request', 'attach-separation'].includes(command)) {
    const task = separationRequest(project, requestId);
    const summary = separationSummary(project, task);
    if (command === 'show-separation-request') return summary;
    const updated = await attachModelParts(project, task, entries, separationParts);
    return separationSummary(updated, separationRequest(updated, requestId));
  }
  const task = referenceRequest(project, requestId);
  if (command === 'attach-views') return attachViews(project, task, entries);
  return {
    ...referenceSummary(project, task),
    sourcePath: path.join(project.localDirectory, project.sourceReference.file),
    sourceSha256: task.sourceSha256, note: task.note, message: task.message,
  };
}

try {
  console.log(JSON.stringify(await main(), null, 2));
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
