import {t,h,msg,getLanguage,setLanguage,translateDOM,taskMessage} from './i18n.mjs';
import {HairViewer} from './viewer.mjs';
import {PointFlowEditor} from './point-flow-editor.mjs';
import {SurfaceFlowEditor} from './surface-flow-editor.mjs';
import {SectionEditor} from './section-editor.mjs';
import {generatedStrands} from './section-profile.mjs';

const $ = selector => document.querySelector(selector);
const escape = value => String(value ?? '').replace(/[&<>"']/g, key => (
  {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[key]
));
const names = {
  reference: '导入参考', draft: '粗模与拆分', guides: '导线生成',
  review: '发流确认', blender: 'Blender 精修', finish: '保存结果',
};
const phases = [
  {label: '准备阶段', steps: ['reference', 'draft']},
  {label: '导线与精修', steps: ['guides', 'review', 'blender', 'finish']},
];
const views = {front: '正面', left: '左侧', right: '右侧', input: '前三分之四', side: '侧面', back: '背面', fit: '自由视角'};
const referenceViewKeys = ['front', 'left', 'right', 'back'];
const decisions = {keep: '保留', adjust: '调整走向', connect: '连接到另一束', split: '拆分'};
const partViews = ['head', 'hair', 'parts'];
const previousHistoryLabels = new Map([
  ['准备 P2.0 生成与拆分任务', '准备粗模生成与拆分任务'],
  ['准备 P2.0 拆分任务', '准备粗模拆分任务'],
  ['准备 P2.0 头模任务', '准备无发头模任务'],
  ['收到 P2.0 三份模型', '收到粗模与拆分结果'],
  ['收到 P2.0 部件', '收到粗模部件'],
]);
const stages = Object.keys(names);
let project = null;
let caps = {};
let stage = 'reference';
let mode = 'guides';
let cards = null;
let cardStamp = null;
let selected = -1;
let region = '';
let referenceView = 'front';
let camera = 'fit';
let comparison = 'after';
let comparisonVersion = '';
const referenceCompare = {split:false,overlay:false,opacity:24};
let uploadTarget;
let toastTimer;
let busy = false;
let drawRequest = 0;
let viewer;
let pointEditor;
let pointSceneKey;
let sectionOpen = false;
let sectionEditor;
let renderedSceneKey;

function toast(text) {
  clearTimeout(toastTimer);
  $('#toast').textContent = t(text);
  $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 6000);
}

async function api(route, options = {}) {
  const response = await fetch(route, {
    ...options,
    headers: {...(options.body instanceof Blob ? {} : {'Content-Type': 'application/json'}), 'Accept-Language': getLanguage(), ...options.headers},
  });
  const value = await response.json();
  if (!response.ok) throw Error(value.error || '请求失败');
  return value;
}

async function act(action, data = {}) {
  if (busy) return false;
  busy = true;
  const id = project.id;
  try {
    const value = await api(`/api/projects/${id}/${action}`, {method: 'POST', body: JSON.stringify(data)});
    if (project?.id !== id) return false;
    project = value;
    await render();
    return true;
  } catch (error) {
    toast(t(error.message));
    return false;
  } finally {
    busy = false;
  }
}

const note = () => $('#reviewNote').value.trim();
const runningJob = () => project?.jobs.find(job => job.status === 'running');
const button = (id, label, disabled = false, primary = false) => (
  `<button id="${id}" class="${primary ? 'primary' : 'full quiet'}"${disabled ? ' disabled' : ''}>${label}</button>`
);
const bind = (id, action) => {
  const element = $("#" + id);
  if (element) element.onclick = () => Promise.resolve(action()).catch(error => toast(t(error.message)));
};
const strandLabel = (strand, index) => strand?.label ?? `发束 ${index + 1}`;
const usesMultiview = () => project.referenceMode === 'multiview';
const importsCoarseModel = () => stage === 'reference' && project?.entryMode === 'coarse';
const stageLabel = (key, entryMode) => key === 'reference' && entryMode === 'coarse' ? '导入粗模' : names[key];
const pendingReferenceTasks = () => (project.referenceRequests ?? []).filter(task => task.status === 'awaiting_agent');
const waitingForView = (tasks, view) => tasks.some(task => task.views.includes(view) && !task.received.includes(view));
const isHairDeckPreviewJob = job => job?.kind === 'hairdeck' && job.options?.previewOnly === true;
const hairDeckPreviewView = () => mode === 'hairdeck' || (mode === 'draft' && !project.flow?.aligned);
const pointPanel = () => stage === 'guides' && project?.pointFlowAvailable && pointEditor;
const pointView = () => pointPanel() && mode === 'guides';
const pointPreview = () => mode === 'result' && project?.pointFlowAvailable && !!project.pointFlow;
const pilotResultCompare = () => stage === 'guides' && pointPreview();
const canCompareReference = () => pointPreview() && !!preview()?.url && !!project.separation?.hair?.url &&
  (comparison !== 'before' || !pilotResultCompare());
const referenceMode = () => {
  if (!canCompareReference()) return 'off';
  return referenceCompare.split ? (referenceCompare.overlay ? 'split-overlay' : 'split')
    : referenceCompare.overlay ? 'overlay' : 'off';
};
const editableSections = () => project?.pointFlowAvailable && project.pointFlow && project.result?.preview &&
  project.result.sourceStamp === project.inputStamp && ['guides', 'blender'].includes(stage);
const canFitSections = () => editableSections() && project.surfaceFlow?.enabled &&
  project.surfaceFlow.groups?.some(group => group.confirmed && group.fitKey &&
    group.guideRecipes.some(({id}) => project.pointFlow.selectedIds?.includes(id)));

function registeredStudioRequest(value) {
  if (!value.model) return null;
  return value.studioRequests.findLast(task => (
    task.status === 'registered' && task.modelSha256 === value.model.sha256 &&
    (task.referenceStamp ? task.referenceStamp === value.referenceStamp : task.referenceSha256 === value.reference?.sha256)
  ));
}

function pendingP2Request() {
  return project.studioRequests.findLast(task => task.method === 'smart-mesh-p2' && task.status === 'awaiting_agent');
}

const hasP2Bundle = () => project.model?.method === 'smart-mesh-p2';

function draftCoarse(value) {
  const task = value.studioRequests.at(-1);
  if (task?.status === 'awaiting_agent' && value.model && task.at <= value.model.createdAt && !registeredStudioRequest(value)) {
    return null;
  }
  return value.model;
}

function separationTask() {
  return project.separation?.requests.findLast(task => task.method === 'smart-mesh-p2' && task.status === 'awaiting_agent');
}

function scalpPreview() {
  const split = project.separation;
  const head = split?.head;
  return head && (head.method === 'smart-mesh-p2' || head.origin === 'user' || split.review?.decision === 'approved')
    ? head : null;
}

function hasPartPreview(view) {
  if (view === 'hair') return !!project.separation?.hair;
  return !!scalpPreview() && (view === 'head' || !!project.separation?.hair);
}

function referenceSlots() {
  const assets = new Map((project.references ?? []).map(asset => [asset.view, asset]));
  return referenceViewKeys.map(view => {
    const asset = assets.get(view);
    const approved = !!asset && project.referenceReviews?.[view]?.assetId === asset.id;
    return {view, label: views[view], asset, approved};
  });
}

function strands() {
  if (project?.flow?.strands?.length) return project.flow.strands;
  if (project?.pointFlow && cards) return generatedStrands(project.pointFlow).map((strand,index) => ({...strand,index}));
  return (cards ?? []).map((_, index) => ({id: String(index), index}));
}

function selectedStrand() {
  return strands().find(strand => strand.index === selected);
}

function filteredStrands() {
  return strands().filter(strand => !region || (strand.regions ?? []).includes(region));
}

function activeVersions() {
  return (project.versions ?? []).filter(version => version.restorable !== false);
}

function beforeOptions() {
  const options = activeVersions().filter(version => version.id !== project.result?.id);
  if (project.flow?.aligned && project.cards?.preview) {
    options.unshift({id: 'draft', preview: project.cards.preview, label: '原始发束初稿'});
  }
  return options;
}

function beforeResult() {
  const options = beforeOptions();
  return options.find(version => version.id === comparisonVersion) ?? options.at(-1) ?? null;
}

function sectionBaseline() {
  return project.result?.fittedSections && beforeOptions().findLast(version => version.preview && !version.fittedSections);
}

function canEnterStage(key) {
  if (key === 'reference') return true;
  if (!project.approvals.reference) return false;
  if (key === 'draft') return true;
  if (key === 'review') return !!project.cards;
  if (key === 'blender') return !!project.approvals.draft;
  if (key === 'finish') return !!project.result;
  if (key !== 'guides') return false;
  const decision = project.separation?.review?.decision;
  return !!project.cards || (decision === 'approved' && hasPartPreview('parts')) ||
    (project.entryMode === 'coarse' ? decision === 'skipped' : !usesMultiview() && !!project.reference);
}

function resumeStage() {
  const job = runningJob();
  if (project.pointFlowAvailable && job && !isHairDeckPreviewJob(job)) return 'guides';
  if (project.surfaceFlow?.enabled && project.stage === 'draft' && !project.surfaceFlow.layoutTask) return 'draft';
  return project.stage === 'draft' && canEnterStage('guides') ? 'guides' : project.stage;
}

function pickStagePreview(key) {
  if (key === 'finish' && project.result) return 'result';
  if (key === 'guides' && project.pointFlowAvailable) return 'guides';
  if (key === 'blender' && project.pointFlowAvailable && project.result) return 'result';
  if (key === 'draft' && (draftCoarse(project) || usesMultiview())) {
    return hasP2Bundle() && hasPartPreview('parts') ? 'parts' : 'coarse';
  }
  if (key === 'guides' && !project.cards) {
    if (project.separation?.review?.decision === 'approved' && hasPartPreview('parts')) return 'parts';
    if (project.model) return 'coarse';
  }
  return 'guides';
}

function setStage(key) {
  if (!canEnterStage(key)) return;
  stage = key;
  mode = pickStagePreview(key);
  return render();
}

async function home() {
  project = null;
  pointEditor = null;
  sectionOpen = false;
  location.hash = '';
  viewer?.clear();
  delete $('#viewport').dataset.asset;
  $('#workspace').hidden = true;
  $('#welcome').hidden = false;
  $('#projectName').textContent = '发型工作台';
  $('#saveProject').disabled = true;
  const projects = await api('/api/projects');
  $('#recentProjects').innerHTML = h(projects.length
    ? projects.map(item => (
      `<button class="recent-card" data-project="${escape(item.id)}"><span>${escape(item.name)}</span><small>${stageLabel(item.stage, item.entryMode)} · ${new Date(item.updatedAt).toLocaleDateString(getLanguage()==='zh'?'zh-CN':'en-GB')}</small></button>`
    )).join('')
    : '<p class="subtle">你的项目会保存在本机，下次打开可以继续。</p>');
  document.querySelectorAll('[data-project]').forEach(element => {
    element.onclick = () => open(element.dataset.project);
  });
}

async function open(id) {
  const value = await api(`/api/projects/${id}`);
  project = value;
  pointEditor = null;
  sectionOpen = false;
  stage = resumeStage();
  mode = pickStagePreview(stage);
  camera = value.pointFlowAvailable ? 'right' : value.flow?.camera?.input ? 'input' : 'fit';
  cardStamp = null;
  cards = null;
  selected = -1;
  region = '';
  referenceView = 'front';
  comparison = 'after';
  comparisonVersion = '';
  Object.assign(referenceCompare,{split:false,overlay:false,opacity:24});
  $('#reviewNote').value = '';
  $('#coarseOverlay').checked = true;
  $('#markOverlay').checked = true;
  $('#showAll').checked = true;
  $('#showNeighbors').checked = false;
  location.hash = id;
  await render();
}

function renderReference() {
  if (project.entryMode === 'coarse') {
    $('#referencePanel').innerHTML = h(project.model
      ? `<div class="reference-meta">${escape(project.model.name)}</div><p class="subtle">粗模已保存</p>`
      : '<p class="subtle">尚未上传粗模。</p>');
    return;
  }
  const options = project.references?.length ? project.references : [];
  const reference = options.find(asset => asset.view === referenceView) ?? project.reference;
  if (usesMultiview() && stage === 'reference') {
    const source = project.sourceReference;
    $('#referencePanel').innerHTML = h(source
      ? `<span class="reference-source-label">原图</span><div class="reference-frame"><img src="${escape(source.url)}" alt="用户上传的原图"></div><div class="reference-meta">${escape(source.name)}</div>${button('changeReference', '更换原图')}`
      : '<p class="subtle">尚未上传原图。</p>');
    bind('changeReference', () => choose('reference'));
    return;
  }
  if (stage === 'reference') {
    const count = options.length || Number(Boolean(reference));
    $('#referencePanel').innerHTML = h(`<div class="reference-meta">${count ? `已载入 ${count} 张参考图` : '尚未添加参考图'}</div>${button('changeReference', reference ? '更换参考图' : '添加参考图')}`);
    bind('changeReference', () => choose('reference'));
    return;
  }
  const image = reference
    ? `<img src="${escape(reference.url)}" alt="${escape(reference.name)}">`
    : '<div class="reference-empty">添加角色参考图<br>PNG / JPEG / WebP</div>';
  const tabs = options.length > 1
    ? `<div class="reference-views" role="group" aria-label="参考视图">${options.map(asset => (
      `<button data-reference-view="${escape(asset.view)}" aria-pressed="${asset.id === reference?.id}">${escape(views[asset.view] ?? asset.view)}</button>`
    )).join('')}</div>` : '';
  $('#referencePanel').innerHTML = h(`<div class="reference-frame">${image}</div>${tabs}
    <div class="reference-meta">${reference ? escape(reference.name) : '尚未添加参考图'}</div>
    ${button('changeReference', usesMultiview() ? '更换原图' : reference ? '更换参考图' : '添加参考图')}`);
  bind('changeReference', () => choose('reference'));
  document.querySelectorAll('[data-reference-view]').forEach(element => {
    element.onclick = () => { referenceView = element.dataset.referenceView; renderReference(); };
  });
}

function showReferenceGallery() {
  const gallery = $('#referenceGallery');
  if (importsCoarseModel()) {
    gallery.classList.add('single');
    gallery.setAttribute('aria-label', t('上传 Tripo 粗模'));
    gallery.innerHTML = h('<div class="reference-upload-empty"><h2>从已有 Tripo 粗模开始</h2><p class="subtle">上传一个 GLB 文件，即可旋转查看粗模。</p><button class="primary" id="uploadCoarseModel">上传 GLB</button></div>');
    bind('uploadCoarseModel', () => choose('model'));
    return;
  }
  gallery.setAttribute('aria-label', t('参考图对照'));
  if (usesMultiview()) {
    const source = project.sourceReference;
    gallery.classList.toggle('single', !source);
    if (!source) {
      gallery.innerHTML = h(`<div class="reference-upload-empty"><h2>从一张原图开始</h2><p class="subtle">上传一张 PNG、JPEG 或 WebP 图片。</p><button class="primary" id="uploadOriginalImage">上传原图</button></div>`);
      bind('uploadOriginalImage', () => choose('reference'));
      return;
    }
    const tasks = pendingReferenceTasks();
    gallery.innerHTML = h(referenceSlots().map(({view, label, asset, approved}) => {
      const waiting = waitingForView(tasks, view);
      const content = asset
        ? `<button class="reference-tile-image" type="button" data-preview-reference="${view}" aria-label="放大${label}参考图"><img src="${escape(asset.url)}" alt="${label}参考图"></button>`
        : `<div class="reference-tile-placeholder"><p>${waiting ? '等待补图' : '待补全'}</p><button type="button" data-upload-reference="${view}" aria-label="上传${label}参考图">上传图片</button></div>`;
      const actions = asset
        ? `<div class="reference-tile-actions"><button class="quiet" type="button" data-upload-reference="${view}" aria-label="替换${label}参考图">替换</button>
          <button class="quiet" type="button" data-request-reference="${view}" aria-label="重新补${label}参考图">重补</button>
          <button class="${approved ? 'quiet' : 'primary'}" type="button" data-approve-reference="${view}" aria-label="${approved ? '取消确认' : '确认'}${label}参考图">${approved ? '取消确认' : '确认'}</button></div>`
        : '';
      const status = asset && waiting ? '等待重补' : approved ? '已确认' : '';
      return `<figure class="reference-tile" data-reference-slot="${view}">${content}<figcaption class="reference-tile-caption"><span>${label}${status ? `<span class="reference-state ${waiting ? 'pending' : ''}">${status}</span>` : ''}</span>${actions}</figcaption></figure>`;
    }).join(''));
    for (const {view, label, asset, approved} of referenceSlots()) {
      const upload = gallery.querySelector(`[data-upload-reference="${view}"]`);
      upload.onclick = () => choose('reference-view', view);
      if (!asset) continue;
      gallery.querySelector(`[data-preview-reference="${view}"]`).onclick = () => showReferenceImage(label, asset);
      gallery.querySelector(`[data-request-reference="${view}"]`).onclick = () => void prepareReferenceTask([view]);
      gallery.querySelector(`[data-approve-reference="${view}"]`).onclick = () => void act('reference-view-review', {
        view, assetId: asset.id, approved: !approved,
      });
    }
    return;
  }
  const assets = project.references?.length ? project.references : project.reference ? [project.reference] : [];
  gallery.classList.toggle('single', assets.length <= 1);
  gallery.innerHTML = h(assets.length ? assets.map(asset => {
    const label = views[asset.view] ?? asset.name;
    return `<figure class="reference-tile"><img src="${escape(asset.url)}" alt="${escape(label)}参考图"><figcaption>${escape(label)}</figcaption></figure>`;
  }).join('') : '<div class="reference-empty">添加参考图后在这里查看。</div>');
}

function renderProjectLists() {
  const currentIndex = stages.indexOf(resumeStage());
  $('#steps').innerHTML = h(phases.map(({label, steps}) => (
    `<section class="step-phase" aria-label="${label}">
      <span class="step-phase-label" aria-hidden="true">${label}</span>
      <div class="step-phase-track">${steps.map(key => {
        const index = stages.indexOf(key);
        const current = stage === key;
        const done = index < currentIndex;
        return `<button class="step ${current ? 'current' : ''} ${done ? 'done' : ''}" data-step="${key}"${current ? ' aria-current="step"' : ''}${canEnterStage(key) ? '' : ' disabled'}><span class="step-index" aria-hidden="true">${done ? '✓' : index + 1}</span>${stageLabel(key, project.entryMode)}</button>`;
      }).join('')}</div></section>`
  )).join(''));
  document.querySelectorAll('[data-step]').forEach(element => {
    element.onclick = () => void setStage(element.dataset.step).catch(error => toast(t(error.message)));
  });
  const assets = [project.cards, project.model, scalpPreview(), project.separation?.hair, project.result?.blend].filter(Boolean);
  $('#assetList').innerHTML = h(assets.length ? assets.map(asset => (
    `<div class="asset-row"><span class="asset-icon">${asset.role === 'cards' ? '⌁' : '◇'}</span><div>
    <strong>${escape(asset.name)}</strong><small>${asset.role === 'cards' ? `${asset.count} 束导线` : `${(asset.bytes / 1024 ** 2).toFixed(1)} MB`} · 已保存</small></div></div>`
  )).join('') : '<p class="subtle">生成或导入后，素材会出现在这里。</p>');
  $('#capabilities').innerHTML = h(`<div class="capability"><span>HairDeck 本地模型</span><span>${caps.hairdeck ? '可用' : '待配置'}</span></div>
    <div class="capability"><span>Blender</span><span>${caps.blender ? '可用' : '待配置'}</span></div>
    <div class="capability"><span>Tripo Studio</span><span>网页 + agent</span></div>`);
}

function flowReviewBody() {
  if (!project.flow?.strands) {
    return '<p>选择发束，检查发根、发梢与跨区走向。需要修正的地方可以记在备注里。</p>';
  }
  const reviews = project.flow.reviews ?? {};
  const statusList = strands().map(strand => (
    `<li><button type="button" data-pick-strand="${strand.index}">${escape(strand.label)}</button><span class="flow-status">${reviews[strand.id] ? escape(decisions[reviews[strand.id].decision]) : '待确认'}</span></li>`
  )).join('');
  return `<ul class="flow-checks" aria-label="发束确认进度">${statusList}</ul><div id="flowForm"></div>`;
}

function renderFlowForm() {
  const content = $('#flowForm');
  if (!content) return;
  const strand = selectedStrand();
  if (!strand) {
    content.innerHTML = h('<p class="subtle">选中发束后，核对多机位中的走向，再记录处理方案。</p>');
    return;
  }
  const saved = project.flow.reviews?.[strand.id];
  const status = saved?.decision ?? 'keep';
  const other = strands().filter(item => item.id !== strand.id);
  const options = Object.entries(decisions).filter(([key]) => key !== 'connect' || other.length);
  content.innerHTML = h(`<form id="flowDecisionForm" class="flow-fields">
    <label>发流方向<select id="flowDirection"><option value="as-fitted">沿现有根梢方向</option>
      <option value="reverse"${saved?.direction === 'reverse' ? ' selected' : ''}>交换根梢</option></select></label>
    <label>处理方案<select id="flowDecision">${options.map(([key, title]) => (
      `<option value="${key}"${key === status ? ' selected' : ''}>${title}</option>`
    )).join('')}</select></label>
    <label id="flowTargetField"${status === 'connect' ? '' : ' hidden'}>目标发束<select id="flowTarget">${other.map(item => (
      `<option value="${escape(item.id)}"${item.id === saved?.targetId ? ' selected' : ''}>${escape(item.label)}</option>`
    )).join('')}</select></label>
    <label>发束备注<textarea id="flowNote" rows="2" maxlength="1000" placeholder="例如，耳上中段向外移少许">${escape(saved?.note)}</textarea></label>
    <button type="submit"${runningJob() ? ' disabled' : ''}>保存这束的确认</button>
    <p class="subtle">连接、拆分和交换根梢作为精修决定保存，在 Blender 中执行。</p>
  </form>`);
  $('#flowDecision').onchange = event => { $('#flowTargetField').hidden = event.target.value !== 'connect'; };
  $('#flowDirection').onchange = syncViewerSelection;
  $('#flowDecisionForm').onsubmit = async event => {
    event.preventDefault();
    const decision = $('#flowDecision').value;
    if (await act('flow-review', {
      strandId: String(strand.id), decision, direction: $('#flowDirection').value,
      targetId: decision === 'connect' ? $('#flowTarget').value : undefined, note: $('#flowNote').value.trim(),
    })) toast(t(`已保存${strand.label}的发流确认。`));
  };
}

function restoreOptions() {
  const choices = activeVersions().filter(version => version.id !== project.result?.id);
  if (!choices.length) return '';
  const suggested = choices.findLast(version => version.approved) ?? choices.at(-1);
  return `<div class="flow-fields"><label>恢复保存版本<select id="restoreChoice">${choices.map(version => (
    `<option value="${escape(version.id)}"${version.id === suggested.id ? ' selected' : ''}>${escape(versionLabel(version))}</option>`
  )).join('')}</select></label>${button('restoreVersion', '将所选版本设为当前', !!runningJob())}</div>`;
}

function versionLabel(version) {
  const time = version.createdAt
    ? new Date(version.createdAt).toLocaleString('zh-CN', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'})
    : '';
  return [version.label || 'Blender 版本', version.approved ? '已确认' : '', time].filter(Boolean).join(' · ');
}

function separationBody(working) {
  const split = project.separation;
  const combined = hasP2Bundle();
  const task = combined ? null : separationTask();
  const hasPair = hasPartPreview('parts');
  const decision = split?.review?.decision;
  const canSkip = !combined && project.entryMode === 'coarse';
  const prepared = decision === 'approved' || (canSkip && decision === 'skipped');
  const files = [['head', '无发头模'], ['hair', '独立头发']].map(([slot, label]) => {
    const asset = slot === 'head' ? scalpPreview() : split?.hair;
    return `${combined ? '' : button(`uploadPart-${slot}`, `${asset ? '更换' : '导入'}${label} GLB`, working)}
      ${asset ? `<a class="button full quiet" href="${escape(asset.url)}?download">下载${label} GLB</a>` : ''}`;
  }).join('');
  return `<section class="draft-source" aria-labelledby="separationTitle">
    <h4 id="separationTitle">审核头模和头发</h4>
    ${prepared ? `<p class="check-row">${decision === 'approved' ? '头皮与头发已确认。准备阶段完成。' : '已选整头粗模作为导线参考。准备阶段完成。'}</p>
      ${button('toGuides', '进入导线生成', working, true)}`
      : hasPair ? `<p>对照${combined ? '四视图和' : ''}整头粗模，检查头顶、后脑、刘海和马尾。叠加查看发际线、耳后和后颈的贴合。</p>`
      : '<p>导入与当前粗模坐标一致的无发头模和独立头发 GLB，再叠加检查贴合。</p>'}
    ${hasPartPreview('head') || hasPartPreview('hair') ? `<div class="part-previews" role="group" aria-label="查看拆分结果">
      ${hasPartPreview('head') ? button('viewHead', '查看无发头模') : ''}
      ${hasPartPreview('hair') ? button('viewHair', '查看独立头发') : ''}
      ${hasPair ? button('viewParts', '叠加查看') : ''}</div>` : ''}
    ${hasPair && decision !== 'approved' ? button('approveSeparation', '确认头皮和头发', working, true) : ''}
    ${task ? button('showSeparation', '查看已生成的拆分任务') : ''}
    ${canSkip && !prepared ? button('skipSeparation', '使用整头粗模继续', working) : ''}
    <details class="part-files"><summary>${combined ? '下载拆分文件' : '手动导入或下载拆分文件'}</summary>
      ${files}</details>
    </section>${decision === 'approved' ? closedHairBody(working) : ''}`;
}

function closedHairBody(working, measurement = false) {
  const closed = project.closedHair;
  const canMeasure = measurement && project.result?.sourceStamp === project.inputStamp && !project.flow;
  const fit = project.result?.report?.uv_section_fit;
  return `<details class="draft-source part-files"${measurement ? ' open' : ''}>
    <summary>闭合粗模与 UV 截面</summary>
    ${closed ? `<p class="check-row">${closed.report.method === 'tripo' ? 'Tripo 快速封口' : '闭合测量粗模'}已就绪。</p>
      ${button('viewClosedHair', '查看闭合粗模')}
      <a class="button full quiet" href="${escape(closed.asset.url)}?download">下载闭合粗模 GLB</a>` :
      '<p>用已确认的独立头发生成闭合副本，供逐段测量。</p>'}
    ${button('closeHairMesh', closed ? '重新生成闭合副本' : '生成闭合粗模', working || !caps.blender)}
    ${canMeasure ? button('fitUvSections', '沿 UV 测量与平滑截面', working || !closed || !caps.blender) : ''}
    ${canMeasure && closed ? '<p class="subtle">沿发流逐段测量，宽度和厚度拟合为单调或单峰。缺少可用 UV 时按导线建立测量坐标。</p>' : ''}
    ${fit && canMeasure ? `<p class="subtle">已测量 ${Object.keys(fit.measured).length} 束。${fit.untouched.length ?
      `${fit.untouched.length} 束样本不足，沿用当前截面。` : ''}</p>` : ''}
  </details>`;
}

function guidePreparationBody(working) {
  if (pointPanel() && project.surfaceFlow?.enabled) pointEditor.sync(project);
  if (pointPanel()) return pointEditor.body({working, ready: !!caps.blender, reviewed:project.pointFlowReviewedRegions ?? [],
    generated:project.result?.report?.generated_strands ?? [], assignments:project.pointFlowRegionAssignments}) +
    (project.result ? `${button('pointResult', '查看 SHP 预览')}
    ${editableSections() ? button('pointSections', '调整截面') : ''}
    ${canFitSections() ? button('fitSections', '按粗模拟合截面', working || !caps.blender) : ''}
    ${project.separation?.review?.decision === 'approved' ? closedHairBody(working,true) : ''}
    <a class="button full quiet" href="${escape(project.result.blend.url)}?download">下载 Blender 工程</a>
    ${button('pointContinue', '进入 Blender 精修')}` : '');
  const decision = project.separation?.review?.decision;
  const canFit = !!project.model && !!decision;
  const canRunHairDeck = !!project.reference && !project.flow;
  return `<section class="draft-source" aria-labelledby="fitGuidesTitle">
    <h3 id="fitGuidesTitle">拟合发束导线</h3>
    <p>${project.cards ? '已有导线。可以进入「发流确认」检查走向。' : decision === 'approved' ?
      '用已确认的头发拟合发束走向，用头皮检查发根贴合。收到结果后导入导线 JSON。' :
      canFit ? '在粗模坐标系内拟合主导线，收到结果后导入导线 JSON。' :
      '生成 HairDeck 导线，或导入已有的导线 JSON。'}</p>
    ${canFit ? button('prepareGuideFit', '准备导线拟合任务', working, !project.cards) : ''}
    ${canRunHairDeck ? `${canFit ? '<details class="part-files"><summary>从图片生成 HairDeck 导线</summary>' : ''}
      <p>HairDeck 从单张参考图预测发流，结果可能与 Tripo 粗模差异较大。</p>
      <label>生成种子<input id="seed" type="number" min="0" max="2147483646" value="0"></label>
      ${button('generate', '生成 HairDeck 导线', !caps.hairdeck || working, !canFit && !project.cards)}
      ${canFit ? '</details>' : ''}` : ''}
    ${button('importDraftGuides', '导入导线 JSON', working)}
    ${project.cards ? button('toReview', '进入发流确认', working, true) : ''}
    </section>`;
}

function stageBody() {
  const working = !!runningJob();
  if (importsCoarseModel()) {
    return project.model
      ? `<h3>检查已上传的粗模</h3><p>切换机位检查发际线、两侧和后脑，确认粗模是否可用。</p>
      ${button('approveReference', '确认粗模，继续准备', working, true)}
      ${button('replaceCoarseModel', '更换 GLB', working)}`
      : '<h3>先上传粗模</h3><p>选择从 Tripo 导出的 GLB 文件。</p>';
  }
  if (stage === 'reference' && usesMultiview()) {
    if (!project.sourceReference) return `<h3>先上传原图</h3><p>从一张图补全正面、左侧、右侧和背面，检查后再生成发型。</p>`;
    const slots = referenceSlots();
    const present = slots.filter(slot => slot.asset).length;
    const approved = slots.filter(slot => slot.approved).length;
    const tasks = pendingReferenceTasks();
    const missing = slots.some(slot => !slot.asset && !waitingForView(tasks, slot.view));
    return `<h3>补全并确认四视图</h3>
      <p>${present < 4 ? '让 Codex 补齐缺少的视图，或在对应位置上传你已有的图。' : '对照发际线、分缝和两侧轮廓。点击图片可放大检查，再逐张确认。'}</p>
      <ul class="action-list"><li>已备齐 ${present}/4 张</li><li>已确认 ${approved}/4 张</li></ul>
      ${tasks.map(task => `<button class="full quiet" data-open-reference-task="${escape(task.id)}">查看补图任务${tasks.length > 1 ? ` · ${task.views.map(view => views[view]).join('、')}` : ''}</button>`).join('')}
      ${missing ? button('prepareReferenceTask', '准备补图任务', working, true) : ''}
      ${button('approveReference', '确认四视图，准备粗模', approved !== 4 || working, approved === 4)}`;
  }
  if (stage === 'reference') return `<h3>确认发型参考</h3>
    <p>${project.references?.length > 1 ? '对照四张参考图，检查发际线、两侧和后脑。' : '添加一张能看清发型的参考图。'}</p>
    <ul class="action-list"><li>${project.reference ? '✓' : '○'} 参考图已添加</li>
    <li>${project.approvals.reference ? '✓' : '○'} 已确认参考</li></ul>
    ${button('approveReference', project.flow?.aligned ? '确认参考，查看粗模' : '确认参考，继续准备', !project.reference || working, true)}`;
  if (stage === 'draft') {
    const coarse = draftCoarse(project);
    if (project.flow?.aligned) return `<h3>复核 Tripo 粗模与拟合初稿</h3>
      <p>项目包含已对齐的粗模、发流标记和 ${project.cards.count} 束拟合导线。可切换粗模和导线，检查耳上、额前和扎点。</p>
      ${button('toReview', '进入发流确认', !project.approvals.reference || working, true)}`;
    const combined = hasP2Bundle();
    const coarseReview = coarse ? `<h3>${combined ? '粗模与拆分结果' : '带发粗模'}</h3>
      ${combined ? '<p>整头粗模、无发头模和独立头发来自同一个候选，可在原坐标中叠加查看。</p>' : ''}
      <div class="part-previews">${button('viewCoarse', '查看整头粗模')}
      <a class="button full quiet" href="${escape(coarse.url)}?download">下载整头粗模 GLB</a></div>
      ${separationBody(working)}` : '';
    if (!usesMultiview()) return coarseReview || (canEnterStage('guides')
      ? `<h3>参考图已确认</h3>${button('toGuides', '进入导线生成', working, true)}` : '');
    const pending = pendingP2Request();
    const tripo = `<div class="draft-source">
      ${pending ? `<p class="check-row">等待回填整头粗模、无发头模和独立头发。</p>
        ${button('showStudio', '查看待执行的粗模任务', false, !coarse)}` :
        '<p>用已确认的四视图生成一批粗模候选，从同一个候选导出整头粗模、无发头模和独立头发。</p>'}
      ${!pending || coarse ? button('studioRequest', coarse ? '准备新的粗模任务' : '准备粗模生成与拆分任务',
        working, !coarse) : ''}
      </div>`;
    return coarse ? `${coarseReview}<details class="draft-source part-files"${pending ? ' open' : ''}>
      <summary>更换粗模候选</summary>${tripo}</details>` :
      '<h3>生成并拆分粗模</h3>' + tripo;
  }
  if (stage === 'guides') return guidePreparationBody(working);
  if (stage === 'review') {
    const pending = project.flow?.strands?.filter(strand => !project.flow.reviews?.[strand.id])?.length ?? 0;
    return `<h3>确认发束走向</h3>
      <div class="check-row">${project.cards ? `已准备 ${project.cards.count} 束导线。` : '尚未准备导线。'}
      ${project.flow?.aligned ? '<br>粗模已对齐。紫线为拟合导线，虚线为原始发流标记。' : ''}</div>
      ${flowReviewBody()}
      ${button('approveDraft', '确认发流，进入 Blender', !project.cards || !project.approvals.reference || !!pending || working, true)}
      ${pending ? `<p class="subtle">还有 ${pending} 束待确认。</p>` : ''}
      ${button('toGuides', '返回导线生成')}`;
  }
  if (stage === 'blender') return `<h3>生成和精修发束</h3>
    <p>${project.flow?.aligned ? '工程包含两束可编辑导线和同一组检查机位。用 HairBridge 面板编辑所选发束并返回审核副本。' :
      project.separation?.review?.decision === 'approved' ? '工程包含可编辑导线和已确认的头皮、头发参考。在 Blender 大纲视图分别显示参考，检查发根贴合与穿插。' :
      '生成独立的 Blender 工程进行精修。使用来自其他模型的几何做表面修正时，先核对位置、比例和朝向。'}</p>
    ${button('build', project.result ? '重新生成 Blender 项目' : '生成 Blender 项目', !project.approvals.draft || working || !caps.blender, true)}
    ${editableSections() ? button('pointSections', '调整截面') : ''}
    ${canFitSections() ? button('fitSections', '按粗模拟合截面', working || !caps.blender) : ''}
    ${project.separation?.review?.decision === 'approved' ? closedHairBody(working,true) : ''}
    ${editableSections() ? button('toGuides', '按区域重新选发束') : ''}
    ${project.result ? `<a class="button full" href="${escape(project.result.blend.url)}?download">下载当前 Blender 工程</a>` : ''}
    <a class="button full quiet" href="/api/addon">下载 Blender 插件</a>
    ${button('copyProjectPath', '复制项目文件路径')}
    ${project.result ? button('toFinish', '同机位比较和审核') : ''}`;
  return `<h3>确认和保存结果</h3>
    <p>在同一机位切换修改前后，检查发际线、覆盖和相邻发束的搭接。</p>
    ${project.result ? `<ul class="action-list"><li>✓ Blender 工程已保存</li>
    <li>${project.approvals.finish ? '✓' : '○'} 已确认当前版本</li></ul>` : '<p>请先生成或返回 Blender 成果。</p>'}
    ${button('approveFinish', '确认当前成果', !project.result || working || !!project.approvals.finish, true)}
    ${restoreOptions()}${button('exportProject', '保存项目包', !project.result)}
    ${button('backBlender', '继续 Blender 精修')}`;
}

function renderActions() {
  $('#stageActions').innerHTML = h(`<div class="action-card">${stageBody()}</div>`);
  bind('replaceCoarseModel', () => choose('model'));
  bind('prepareReferenceTask', () => {
    const tasks = pendingReferenceTasks();
    return prepareReferenceTask(referenceSlots().filter(slot => !slot.asset && !waitingForView(tasks, slot.view)).map(slot => slot.view));
  });
  document.querySelectorAll('[data-open-reference-task]').forEach(element => {
    element.onclick = () => showReferenceTask(pendingReferenceTasks().find(task => task.id === element.dataset.openReferenceTask));
  });
  bind('approveReference', async () => {
    const modelId = project.entryMode === 'coarse' ? project.model?.id : undefined;
    if (await act('review', {step: 'reference', note: note(), modelId}) && project.approvals.reference) await setStage('draft');
  });
  bind('generate', () => act('job', {
    kind: 'hairdeck', requestId: crypto.randomUUID(), options: {seed: Number($('#seed').value)},
  }));
  bind('studioRequest', async () => { if (await act('studio-request', {note: note()})) showStudio(); });
  bind('showStudio', showStudio);
  for (const [id, view] of [['viewCoarse', 'coarse'], ['viewHead', 'head'], ['viewHair', 'hair'], ['viewParts', 'parts']]) {
    bind(id, () => {
      mode = view;
      $('#viewport').scrollIntoView({block: 'nearest'});
      return draw();
    });
  }
  bind('showSeparation', showSeparation);
  bind('approveSeparation', () => reviewSeparation('approved'));
  bind('skipSeparation', () => reviewSeparation('skipped'));
  bind('uploadPart-head', () => choose('separation-head'));
  bind('uploadPart-hair', () => choose('separation-hair'));
  bind('prepareGuideFit', showGuideFit);
  bind('importDraftGuides', () => choose('cards'));
  bind('toGuides', () => setStage('guides'));
  bind('toReview', () => setStage('review'));
  bind('approveDraft', async () => {
    if (await act('review', {step: 'draft', note: note()}) && project.approvals.draft) await setStage('blender');
  });
  bind('build', () => act('job', {kind: 'blender', requestId: crypto.randomUUID()}));
  if (pointPanel()) pointEditor.bind($('#stageActions'), {
    surfaceAction: async (action,payload) => {
      const success = await act(action,{...payload,revision:project.revision});
      if (success) pointEditor.applied(action,payload);
      return success;
    },
    assignStrand: async (strandId, regionId) => {
      if (await act('point-region-move-strand', {strandId,regionId,revision:project.revision})) {
        pointEditor.assignmentStrand = null;
        pointEditor.selectRegion(regionId,false);
      }
    },
    confirmRegion: async regionId => {
      if (await act('point-region-confirm', {regionId, revision:project.revision})) {
        pointEditor.pickingRegion = false;
        updatePointEditor();
      }
    },
    generate: async groupOnly => {
      if (await act('point-flow-confirm', pointEditor.payload(project.revision, crypto.randomUUID(), project.pointFlow, groupOnly))) {
        pointEditor.accepted(project.cards.id);
      }
    },
  });
  bind('pointResult', () => { mode = 'result'; comparison = 'after'; return draw(); });
  bind('pointSections', openSectionControls);
  bind('viewClosedHair', () => { mode = 'closed'; return draw(); });
  bind('closeHairMesh', () => act('hair-closure',{requestId:crypto.randomUUID(),
    hairId:project.separation.hair.id}));
  bind('fitUvSections', async () => {
    if (await act('uv-section-fit',{requestId:crypto.randomUUID(),revision:project.revision,cardsId:project.cards.id,
      resultId:project.result.id,closedAssetId:project.closedHair.asset.id})) {
      mode = 'result';
      comparison = 'after';
      await draw();
    }
  });
  bind('fitSections', async () => {
    if (await act('point-section-fit',{requestId:crypto.randomUUID(),revision:project.revision,
      cardsId:project.cards.id,resultId:project.result.id})) {
      mode = 'result';
      comparison = 'after';
      await draw();
    }
  });
  bind('pointContinue', () => setStage('blender'));
  bind('copyProjectPath', async () => {
    await navigator.clipboard.writeText(`${project.localDirectory}\\project.hairbridge`);
    toast(t('项目路径已复制。'));
  });
  bind('toFinish', () => setStage('finish'));
  bind('approveFinish', () => act('review', {step: 'finish', note: note()}));
  bind('backBlender', () => setStage('blender'));
  bind('exportProject', exportProject);
  bind('restoreVersion', async () => {
    if (await act('restore-version', {versionId: $('#restoreChoice').value})) {
      comparison = 'after';
      await draw();
      toast(t('已恢复所选版本。'));
    }
  });
  document.querySelectorAll('[data-pick-strand]').forEach(element => {
    element.onclick = () => {
      if (!filteredStrands().some(item => item.index === Number(element.dataset.pickStrand))) region = '';
      select(Number(element.dataset.pickStrand));
    };
  });
  renderFlowForm();
}

function renderJobsAndHistory() {
  const latest = project.jobs.at(-1);
  $('#jobPanel').hidden = !latest;
  $('#jobPanel').dataset.status = latest?.status ?? '';
  if (latest) {
    const status = {running: '正在处理', succeeded: '已完成', failed: '处理失败', cancelled: '已停止'}[latest.status];
    $('#jobPanel').innerHTML = h(`<h3>${isHairDeckPreviewJob(latest) ? 'HairDeck 初稿对照' : latest.kind === 'hairdeck' ? 'HairDeck 本地推理' :
      latest.kind === 'hair-closure' ? '闭合测量粗模' : 'Blender 发片生成'}</h3>
      <div class="job-status">${status}</div>${latest.error ? `<p class="error-text">${escape(latest.error)}</p>` : ''}
      <details${latest.status === 'running' ? ' open' : ''}><summary class="subtle">运行记录</summary>
      <pre>${escape(latest.log || '正在启动处理进程…')}</pre></details>
      ${latest.status === 'running' ? button('cancelJob', '停止此任务') : ''}`);
    bind('cancelJob', () => act('cancel', {jobId: latest.id}));
  }
  $('#historyCount').textContent = t(`${project.history.length} 条`);
  $('#historyList').innerHTML = h(project.history.slice(-5).reverse().map(item => (
    `<div class="history-row"><time>${new Date(item.at).toLocaleTimeString(getLanguage()==='zh'?'zh-CN':'en-GB', {hour: '2-digit', minute: '2-digit'})}</time>
    <div><strong>${escape(previousHistoryLabels.get(item.action) ?? item.action)}</strong><small data-i18n-preserve="${['用户记录','用户确认','User note','User approval'].includes(item.action)}">${escape(item.detail)}</small></div></div>`
  )).join(''));
}

async function loadCards() {
  const {id, cards: asset} = project;
  const stamp = asset?.sha256 ?? '';
  if (stamp === cardStamp) return true;
  const value = asset ? await api(asset.url) : null;
  if (project?.id !== id || (project.cards?.sha256 ?? '') !== stamp) return false;
  cards = value;
  cardStamp = stamp;
  selected = -1;
  region = '';
  return true;
}

async function render() {
  if (!project) return;
  if (!canEnterStage(stage)) {
    stage = resumeStage();
    mode = pickStagePreview(stage);
  }
  if (stage !== 'reference' && !await loadCards()) return;
  if (stage === 'guides' && project.pointFlowAvailable && !pointEditor) {
    const id = project.id;
    const fixture = await api(`/api/projects/${id}/point-flow`);
    if (project?.id !== id) return;
    const Editor = project.surfaceFlow?.enabled ? SurfaceFlowEditor : PointFlowEditor;
    pointEditor = new Editor(fixture, project, updatePointEditor, toast);
  }
  const sourceStage = stage === 'reference';
  const coarseImport = importsCoarseModel();
  const showCoarse = coarseImport && !!project.model;
  const showSourceGallery = sourceStage && !showCoarse;
  if (coarseImport) mode = 'coarse';
  if (partViews.includes(mode) && !hasPartPreview(mode)) mode = project.model ? 'coarse' : 'guides';
  if (mode === 'hairdeck' && !project.flow?.aligned) mode = 'draft';
  $('[data-view="draft"]').textContent = t(project.flow?.aligned ? '拟合初稿' : 'HairDeck 初稿');
  $('[data-view="hairdeck"]').hidden = !project.flow?.aligned;
  for (const view of partViews) $(`[data-view="${view}"]`).hidden = !hasPartPreview(view);
  $('#welcome').hidden = true;
  $('#workspace').hidden = false;
  $('#referenceGallery').hidden = !showSourceGallery;
  $('#threeDPreview').hidden = showSourceGallery;
  $('#selectionBar').hidden = coarseImport || !!pointView();
  for (const id of ['previewTabs', 'geometryHeading', 'assetList', 'uploadModel', 'uploadCards']) {
    $(`#${id}`).hidden = sourceStage;
  }
  $('#uploadModel').hidden = sourceStage || usesMultiview();
  $('#uploadCards').hidden = !canEnterStage('guides');
  $('#projectName').textContent = project.name;
  $('#saveProject').disabled = false;
  $('#saved').textContent = t('已保存在本机');
  $('#stageTitle').textContent = t(stageLabel(stage, project.entryMode));
  $('#stageStatus').textContent = t(coarseImport ? (showCoarse ? '已上传' : '待上传')
    : runningJob() ? '处理中' : project.approvals.finish ? '已审核' : '用户审核');
  renderProjectLists();
  renderReference();
  renderActions();
  renderJobsAndHistory();
  if (showSourceGallery) {
    renderSectionEditor();
    showReferenceGallery();
    const viewport = $('#viewport');
    if (viewport.dataset.asset !== 'reference') {
      drawRequest++;
      viewer?.clear();
      viewport.dataset.asset = 'reference';
    }
    return;
  }
  renderSelection();
  const key = drawKey();
  if ($('#viewport').dataset.asset !== key) await draw();
  else {
    renderSectionEditor();
    renderHairDeckPreview();
  }
  viewer?.resize();
}

function renderHairDeckPreview() {
  const panel = $('#hairdeckPreviewPanel');
  panel.hidden = !hairDeckPreviewView();
  if (panel.hidden) return;
  const job = runningJob();
  const latest = project.jobs.findLast(item => isHairDeckPreviewJob(item) && item.inputStamp === project.inputStamp);
  const hasReference = !!project.reference && !!project.approvals.reference;
  const control = $('#generateHairDeckPreview');
  control.disabled = !!job || !hasReference || !caps.hairdeck || !caps.hairdeckPreview;
  control.textContent = t(isHairDeckPreviewJob(job) ? '正在生成 HairDeck 初稿…' :
    preview() ? '重新生成 HairDeck 初稿' : '生成 HairDeck 初稿');
  const status = $('#hairdeckPreviewStatus');
  const message = !hasReference ? '请先添加并确认参考图。' :
    !caps.hairdeckPreview ? '请重启 HairBridge Studio 服务以启用初稿对照。' :
    !caps.hairdeck ? '此电脑尚未配置 HairDeck 本地模型。' :
    isHairDeckPreviewJob(job) ? '本地推理进行中，完成后会在这里显示预览。' :
    job ? '请等待当前任务完成。' :
    latest?.status === 'failed' ? '初稿生成失败，可在右侧查看原因或重试。' : '';
  if (status.textContent !== message) status.textContent = t(message);
  status.hidden = !message;
}

function preview() {
  if (hairDeckPreviewView()) return project.hairdeckPreview ?? (!project.flow?.aligned ? project.cards?.preview : null);
  if (mode === 'draft') return project.cards?.preview;
  if (mode === 'coarse') return project.model;
  if (mode === 'head') return scalpPreview();
  if (mode === 'closed') return project.closedHair?.asset;
  if (mode === 'hair' || mode === 'parts') return project.separation?.hair;
  if (mode === 'result') {
    if (comparison === 'baseline') return sectionBaseline()?.preview ?? project.result?.preview;
    if (comparison === 'before') return pilotResultCompare() ? project.separation?.hair : beforeResult()?.preview;
    return project.result?.preview;
  }
  return null;
}

function drawKey() {
  return JSON.stringify([
    project.id, mode, cardStamp, preview()?.url, project.flow?.head?.id, project.model?.id,
    mode === 'parts' ? scalpPreview()?.id : null,
    !!pointView(), project.pointFlowAvailable,
    pointView() && project.surfaceFlow?.enabled ? project.revision : null,
    $('#coarseOverlay').checked, $('#markOverlay').checked,
    referenceMode(), referenceMode() === 'off' ? null : project.separation.hair.url,
  ]);
}

function renderComparison() {
  const usePointCompare = pilotResultCompare() && !!project.result?.preview;
  const options = mode === 'result' ? beforeOptions() : [];
  const chosen = options.length ? beforeResult() : null;
  const baseline = pointPreview() && sectionBaseline();
  const fitted = Object.keys(project.result?.fittedSections ?? {}).filter(id =>
    project.result.sectionSources?.[id] !== 'original').length;
  $('#comparePanel').hidden = mode !== 'result' || !project.result?.preview;
  $('#viewBefore').textContent = t(usePointCompare ? '粗模原发型' : '修改前');
  $('#viewAfter').textContent = t(pointPreview() && fitted ?
    (fitted < project.cards.count ? '混合截面 SHP' : '拟合截面 SHP') :
    usePointCompare ? `SHP · ${project.cards.count} 束` : '当前结果');
  $('#viewBefore').disabled = !chosen && !usePointCompare;
  $('#showSectionEditor').hidden = !editableSections() || mode !== 'result';
  $('#viewBefore').setAttribute('aria-pressed', String(comparison === 'before'));
  $('#viewAfter').setAttribute('aria-pressed', String(comparison === 'after' &&
    ($('#sectionEditor').hidden || !sectionEditor.live)));
  $('#viewSectionBaseline').hidden = !baseline;
  $('#viewSectionBaseline').setAttribute('aria-pressed', String(!!baseline && comparison === 'baseline'));
  $('#referenceCompareControl').hidden = !canCompareReference();
  $('#referenceSplit').setAttribute('aria-pressed',String(referenceCompare.split));
  $('#referenceOverlay').setAttribute('aria-pressed',String(referenceCompare.overlay));
  $('#referenceOpacityControl').hidden = !referenceCompare.overlay;
  $('#referenceOpacity').value = referenceCompare.opacity;
  $('#referenceOpacityValue').textContent = t(`${referenceCompare.opacity}%`);
  $('#viewport').dataset.reference = referenceMode();
  $('#beforeVersion').disabled = !chosen;
  $('#beforeVersion').hidden = usePointCompare;
  $('#comparePanel label').hidden = usePointCompare;
  $('#beforeVersion').innerHTML = h(options.map(version => (
    `<option value="${escape(version.id)}"${version.id === chosen?.id ? ' selected' : ''}>${escape(versionLabel(version))}</option>`
  )).join('') || '<option>暂无上一版本</option>');
  $('#comparisonText').textContent = t(baseline ? '两版 SHP 使用同一组导线。切换时保留机位和缩放。' :
    pointPreview() && fitted ? `已按粗模拟合 ${fitted}/${project.cards.count} 束截面。` :
    usePointCompare ? '在同一机位检查原发型和本次勾选的发片。' : chosen
    ? `${comparison === 'before' ? versionLabel(chosen) : versionLabel(project.result)} · 切换版本时保留机位和缩放`
    : '再保存一版精修成果即可对照。');
}

function syncViewerSelection() {
  const strand = selectedStrand();
  const edges = strand?.neighbors ?? [];
  const neighborIds = edges.map(item => String(item?.id ?? item));
  const connected = $('#showNeighbors').checked
    ? strands().filter(item => neighborIds.includes(String(item.id))).map(item => item.index) : [];
  const reversed = $('#flowDirection')?.value === 'reverse' ||
    !$('#flowDirection') && project.flow?.reviews?.[strand?.id]?.direction === 'reverse';
  viewer?.select(selected, $('#showAll').checked, connected, filteredStrands().map(item => item.index), reversed);
}

function renderSelection() {
  const all = strands();
  const regions = [...new Set(all.flatMap(strand => strand.regions ?? []))];
  const matching = filteredStrands();
  const strand = selectedStrand();
  const isGuideView = mode === 'guides';
  const isAligned = !!project.flow?.aligned;
  const customSelection = isGuideView || mode === 'result' && isAligned;
  const regionsVisible = regions.length > 0 && customSelection;
  $('#regionControl').hidden = !regionsVisible;
  $('#strandRegion').innerHTML = h('<option value="">全部</option>' + regions.map(value => (
    `<option value="${escape(value)}"${region === value ? ' selected' : ''}>${escape(value)}</option>`
  )).join(''));
  $('#strandSelect').disabled = !all.length || !customSelection;
  $('#strandSelect').innerHTML = h('<option value="-1">全部</option>' + matching.map(item => (
    `<option value="${item.index}"${item.index === selected ? ' selected' : ''}>${escape(strandLabel(item, item.index))}</option>`
  )).join(''));
  const card = cards?.[selected];
  $('#selectionText').textContent = t(strand
    ? [strandLabel(strand, selected), (strand.regions ?? []).join(' → '), card ? `${card.seq.length} 个采样点` : ''].filter(Boolean).join(' · ')
    : all.length ? `${matching.length} 束` : '尚未准备导线');
  $('#viewOptions').hidden = !all.length || !customSelection || !!pointView();
  $('#neighborControl').hidden = !strand?.neighbors?.length;
  $('#coarseOverlayControl').hidden = !(isGuideView && isAligned && project.model);
  $('#markOverlayControl').hidden = !(isGuideView && (project.flow?.markMesh || all.some(item => Object.keys(item.marks ?? {}).length)));
  $('#endpointLegend').hidden = !(isGuideView && strand);
  const activeMark = strand ? Object.keys(strand.marks ?? {}).length : all.some(item => Object.keys(item.marks ?? {}).length);
  $('#markLegend').hidden = !(isGuideView && activeMark && $('#markOverlay').checked);
  syncViewerSelection();
  renderComparison();
}

function renderCameraControls() {
  for (const preset of document.querySelectorAll('[data-camera]')) {
    preset.setAttribute('aria-pressed', String(preset.dataset.camera === camera));
  }
  const help = camera === 'fit' ? '拖动旋转 · 滚轮缩放' : '右键拖动平移 · 滚轮缩放';
  $('#viewportHelp').textContent = t(pointView() ? `${help} · ${pointEditor.viewportInstruction}` :
    mode === 'guides' ? `${help} · 点击导线选束` : help);
}

function updatePointEditor(view) {
  renderActions();
  if (view) camera = view;
  if (!pointView()) {
    mode = 'guides';
    void draw();
    return;
  }
  renderCameraControls();
  if (viewer && pointSceneKey === drawKey()) {
    if (view) viewer.cameraView(camera);
    pointEditor.show(viewer, !!runningJob());
    $('#previewBadge').textContent = t(pointEditor.viewportLabel);
  }
}

function paintSectionDraft() {
  if (!viewer || renderedSceneKey !== drawKey()) return;
  const live = !$('#sectionEditor').hidden && sectionEditor.live;
  viewer.showSectionDraft(live ? {cards,...sectionEditor.activeSections,strand:sectionEditor.active,
    range:sectionEditor.previewRange,strands:sectionEditor.strands} : null);
  if (pointPreview() && comparison === 'after') {
    $('#viewAfter').setAttribute('aria-pressed',String(!live));
    previewBadge(live ? '截面预览 · 局部高亮' : $('#viewAfter').textContent);
  }
}

function previewBadge(label) {
  const reference = referenceMode();
  const right = $('#splitResultBadge');
  right.hidden = !reference.startsWith('split');
  right.textContent = t(reference === 'split-overlay' ? '发片 · 金色对照' :
    label.startsWith('截面预览') ? '截面预览' : label);
  right.title = t(label);
  $('#previewBadge').textContent = t(reference.startsWith('split') ? '粗模参考' :
    reference === 'overlay' ? `${label} · 金色为粗模` : label);
}

function renderSectionEditor() {
  const show = !!(sectionOpen && editableSections() && pointPreview() && comparison === 'after' && cards?.length);
  $('#workspace').classList.toggle('section-adjusting', show);
  $('#stageActions').hidden = show;
  if (show) {
    sectionEditor.show(project, {working:!!runningJob(), ready:!!caps.blender,cards});
  } else {
    $('#sectionEditor').hidden = true;
    paintSectionDraft();
  }
}

async function openSectionControls() {
  if (comparison === 'baseline' || comparison === 'before' && !pilotResultCompare() && beforeResult() &&
      !beforeResult().fittedSections) sectionEditor.useOriginal(project);
  sectionOpen = true;
  mode = 'result';
  comparison = 'after';
  if (renderedSceneKey === drawKey()) renderSectionEditor();
  else await draw();
  if ($('#sectionEditor').hidden) return;
  const viewport = $('#viewport');
  const {top,height} = viewport.getBoundingClientRect();
  if (!matchMedia('(min-width:820px)').matches) $('#sectionEditor').scrollIntoView({block:'start'});
  else if (top < 0 || innerHeight - top < Math.min(320,height)) viewport.scrollIntoView({block:'start'});
  $('#sectionTitle').focus({preventScroll:true});
}

async function draw() {
  if (!project || (stage === 'reference' && !importsCoarseModel())) return;
  if (mode === 'guides') sectionOpen = false;
  const request = ++drawRequest;
  pointSceneKey = null;
  renderedSceneKey = null;
  renderSectionEditor();
  const viewport = $('#viewport');
  viewport.dataset.asset = drawKey();
  for (const tab of document.querySelectorAll('[data-view]')) {
    tab.classList.toggle('active', tab.dataset.view === mode);
    tab.setAttribute('aria-pressed', String(tab.dataset.view === mode));
  }
  renderCameraControls();
  renderSelection();
  renderHairDeckPreview();
  const asset = preview();
  const editingPoints = !!pointView();
  const pointResult = pointPreview();
  const reference = referenceMode();
  $('#selectionBar').hidden = importsCoarseModel() || editingPoints || pointResult || hairDeckPreviewView();
  const isGuideView = mode === 'guides';
  const isCoarseView = mode === 'coarse' || mode === 'closed' || partViews.includes(mode);
  const hasAsset = editingPoints || (isGuideView ? !!cards : !!asset);
  const empty = $('#viewportEmpty');
  empty.hidden = hasAsset;
  const emptyLabels = {
    guides: '准备导线后，在这里确认发流。', draft: '尚无初稿预览。', hairdeck: '尚无 HairDeck 初稿预览。',
    coarse: usesMultiview() ? '粗模任务完成后，这里会显示整头粗模及拆分结果。' : '导入已有粗模 GLB。',
    result: '在 Blender 阶段生成发片结果。',
    head: '等待无发头模 GLB。', hair: '等待独立头发 GLB。', parts: '头模和头发就绪后可叠加查看。',
    closed: '请先生成闭合测量粗模。',
  };
  const labels = {
    guides: '发流导线', draft: project.flow?.aligned ? '拟合导线的初稿' : 'HairDeck 初稿', hairdeck: 'HairDeck 初稿',
    coarse: '整头粗模',
    head: '无发头模', hair: '独立头发', parts: '头皮与头发叠加', closed: '闭合测量粗模',
    result: comparison === 'baseline' ? '原参数 SHP' : comparison === 'before' ? '同机位修改前' : '当前发片结果',
  };
  empty.textContent = t(emptyLabels[mode]);
  previewBadge(editingPoints ? pointEditor.viewportLabel :
    pilotResultCompare() && comparison === 'before' ? '粗模原发型' : labels[mode]);
  if (!viewer) return;
  if (!hasAsset) return viewer.clear();
  const aligned = !!project.flow?.aligned && !isCoarseView && !hairDeckPreviewView();
  const onCoarse = aligned && isGuideView && $('#coarseOverlay').checked && !!project.model;
  const comparisonKey = editingPoints || pointResult ? `${project.id}:${project.model.id}:point-flow`
    : mode === 'result' ? `${project.id}:${cardStamp}:result`
    : isCoarseView && project.model ? `${project.id}:${project.model.id}:coarse`
    : aligned ? `${project.id}:${cardStamp}:aligned` : null;
  try {
    const loaded = await viewer.show({
      cards: isGuideView && !editingPoints ? cards : [],
      strands: strands(),
      headUrl: editingPoints || pointResult ? scalpPreview()?.url : aligned && !onCoarse ? project.flow.head?.url : null,
      meshUrl: asset?.url,
      referenceHairUrl: reference === 'off' ? null : project.separation.hair.url,
      referenceMode:reference,
      referenceOpacity:referenceCompare.opacity/100,
      coarseUrl: editingPoints ? project.separation.hair.url :
        mode === 'parts' ? scalpPreview()?.url : onCoarse ? project.model.url : null,
      markMeshUrl: onCoarse && $('#markOverlay').checked ? project.flow.markMesh?.url : null,
      useMarks: isGuideView && $('#markOverlay').checked,
      comparisonKey,
      cameras: project.flow?.aligned && !hairDeckPreviewView() ? project.flow.camera : null,
      camera,
      preserveFrame: !!comparisonKey,
      preserveMaterial: aligned,
      framing: editingPoints || pointResult ? .79 : 1,
    });
    if (loaded && request === drawRequest) {
      renderedSceneKey = drawKey();
      viewer.setReferenceOpacity(referenceCompare.opacity/100);
      if (viewer.view !== camera) viewer.cameraView(camera);
      if (editingPoints && pointView()) {
        pointSceneKey = drawKey();
        pointEditor.show(viewer, !!runningJob());
        $('#previewBadge').textContent = t(pointEditor.viewportLabel);
        renderCameraControls();
      }
      paintSectionDraft();
    }
  } catch (error) {
    if (request === drawRequest) {
      empty.hidden = false;
      empty.textContent = t('预览加载失败：' + error.message);
    }
  }
}

function select(index) {
  selected = Number(index);
  if (!filteredStrands().some(strand => strand.index === selected)) selected = -1;
  renderFlowForm();
  renderSelection();
}

function choose(role, view) {
  if (busy || runningJob()) return toast(t('请等待当前任务完成。'));
  uploadTarget = {id: project.id, role, view, ...(role.startsWith('separation-') ? {coarse: coarseIdentity()} : {})};
  const input = $('#fileInput');
  input.accept = role === 'reference' || role === 'reference-view' ? '.png,.jpg,.jpeg,.webp' : role === 'cards' ? '.json' : '.glb';
  input.value = '';
  input.click();
}

function showReferenceImage(label, asset) {
  $('#referencePreviewTitle').textContent = t(`${label}参考图`);
  const image = $('#referencePreviewImage');
  image.alt = `${label}参考图`;
  image.src = asset.url;
  $('#referencePreviewDialog').showModal();
}

function showReferenceTask(request = project.referenceRequests?.at(-1)) {
  if (!request?.message) return;
  $('#referenceTaskMessage').value = taskMessage(request);
  $('#referenceTaskDialog').showModal();
}

async function prepareReferenceTask(views) {
  if (await act('reference-request', {views, note: note()})) showReferenceTask();
}

function showStudio() {
  const request = pendingP2Request();
  if (!request) return;
  $('#studioMessage').value = taskMessage(request);
  $('#studioDialog').showModal();
}

function coarseIdentity() {
  return {modelId: project.model.id, referenceStamp: project.referenceStamp};
}

function reviewSeparation(decision) {
  return act('separation-review', {
    ...coarseIdentity(), note: note(), decision,
    headId: project.separation?.head?.id ?? null, hairId: project.separation?.hair?.id ?? null,
  });
}

let coarseTaskKind = 'guide';
function showCoarseTask(title, help, message, usesStudio = false) {
  coarseTaskKind = usesStudio ? 'separation' : 'guide';
  $('#coarseTaskTitle').textContent = t(title);
  $('#coarseTaskHelp').textContent = t(help);
  $('#coarseTaskMessage').value = message;
  $('#coarseTaskStudio').hidden = !usesStudio;
  $('#coarseTaskDialog').showModal();
}

function showSeparation() {
  const task = separationTask();
  if (!task) return;
  const review = task.reusedHairId ? '收到无发头模后，和已有头发叠加检查。' :
    '收到头模和头发 GLB 后，在工作台叠加检查。';
  showCoarseTask('拆分头模和头发',
    `首次使用请在 agent 操作的浏览器中登录 Tripo。将任务贴到当前 Codex 对话。${review}`,
    taskMessage(task), true);
}

function showGuideFit() {
  const split = project.separation;
  const useParts = split?.review?.decision === 'approved' && split.head && split.hair;
  const combined = hasP2Bundle();
  const directory = project.localDirectory;
  const separator = directory.includes('\\') ? '\\' : '/';
  const projectFile = `${directory}${separator}project.hairbridge`;
  const file = asset => `${directory}${separator}${asset.file.replaceAll('/', separator)}`;
  const message = [
    t('请在 HairBridge Studio 为当前项目拟合发束主导线。'),
    msg`项目 ${project.id} · ${projectFile}`,
    `${combined ? t('整头粗模') : t('粗模')} ${file(project.model)} · GLB SHA-256 ${project.model.sha256}`,
    ...(useParts ? [
      msg`已确认无发头模 ${file(split.head)} · GLB SHA-256 ${split.head.sha256}`,
      msg`已确认独立头发 ${file(split.hair)} · GLB SHA-256 ${split.hair.sha256}`,
      ...(combined ? [t('三份 GLB 来自同一个粗模候选，沿用该候选的坐标、比例和朝向。')] : []),
      t('用头发网格识别发束区域和走向。用头皮核对发根贴合与穿插，保留卷发和翘起发梢的离头弧度。'),
    ] : [t('以整头粗模为参考，先标记发束区域、起止位置及关键转折，再拟合连贯的主导线。')]),
    t('生成前核对当前清单和用户已确认的版本。沿用粗模的坐标、比例和朝向。先拟合走向明确的主束，核对发根、发梢和扎点，再估计宽厚。'),
    t('请保存 HairBridge 可导入的导线 JSON，采用 HairDeck cards 数组。每束包含 shape（square 或 triangle）和 seq。每个采样点为 [x, y, z, width, thickness, dx, dy, dz]，位置使用 GLB 的坐标。交回用户导入并确认发流。'),
    ...(note() ? [msg`本轮备注 ${note()}`] : []),
  ].join('\n');
  showCoarseTask(t('拟合发束导线'),
    t('将任务贴到当前 Codex 对话。收到导线 JSON 后，点「导入导线 JSON」并进入「发流确认」。'), message);
}

function exportProject() {
  location.href = `/api/projects/${project.id}/export`;
}

async function startPreset(endpoint, control, message) {
  control.disabled = true;
  try {
    const value = await api(endpoint, {method: 'POST', body: '{}'});
    await open(value.id);
    toast(t(message));
  } finally {
    control.disabled = false;
  }
}

bind('newProject', () => $('#newDialog').showModal());
bind('closeDialog', () => $('#newDialog').close());
$('#newForm').onsubmit = async event => {
  event.preventDefault();
  const entryMode = event.submitter?.value;
  if (entryMode !== 'image' && entryMode !== 'coarse') return;
  const choices = event.currentTarget.querySelectorAll('[name="entryMode"]');
  for (const choice of choices) choice.disabled = true;
  try {
    const value = await api('/api/projects', {method: 'POST', body: JSON.stringify({name: $('#newName').value, entryMode})});
    $('#newDialog').close();
    await open(value.id);
  } catch (error) { toast(t(error.message)); }
  finally { for (const choice of choices) choice.disabled = false; }
};
bind('rainTripoProject', () => startPreset('/api/rain-tripo', $('#rainTripoProject'), 'Rain 项目已准备，请先确认四视图。'));
bind('demoProject', () => startPreset('/api/demo', $('#demoProject'), '已载入此前保存的 Rain HairDeck 成果。'));
bind('homeButton', home);
bind('uploadModel', () => choose('model'));
bind('uploadCards', () => choose('cards'));
$('#fileInput').onchange = async () => {
  const file = $('#fileInput').files[0];
  const target = uploadTarget;
  uploadTarget = null;
  if (!file || !target || project?.id !== target.id || busy) return;
  const {id, role, view, coarse} = target;
  if (coarse && (coarse.modelId !== project.model?.id || coarse.referenceStamp !== project.referenceStamp)) {
    return toast(t('当前粗模或参考图已更换，请重新选择文件。'));
  }
  const query = new URLSearchParams({role, name: file.name});
  if (view) query.set('view', view);
  if (coarse) for (const [key, value] of Object.entries(coarse)) query.set(key, value);
  busy = true;
  try {
    const value = await api(`/api/projects/${id}/upload?${query}`, {
      method: 'POST', body: file,
    });
    if (project?.id !== id) return;
    project = value;
    if (role === 'reference' || role === 'reference-view') stage = 'reference';
    if (role === 'model' && stage === 'draft') mode = 'coarse';
    if (role === 'cards' && stage === 'guides') mode = 'guides';
    if (coarse) mode = hasPartPreview('parts') ? 'parts' : role.slice('separation-'.length);
    await render();
    toast(t('素材已保存到当前项目。'));
  } catch (error) { toast(t(error.message)); }
  finally { busy = false; }
};
bind('saveNote', () => act('note', {note: note()}));
bind('saveProject', exportProject);
bind('generateHairDeckPreview', async () => {
  $('#generateHairDeckPreview').disabled = true;
  await act('job', {kind: 'hairdeck', requestId: crypto.randomUUID(), options: {previewOnly: true}});
  if (project) renderHairDeckPreview();
});
document.addEventListener('keydown', event => {
  if (event.defaultPrevented || event.isComposing || event.repeat || event.altKey || event.shiftKey ||
      !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z') return;
  if (busy || runningJob() || !pointView() || $('dialog[open]')) return;
  const target = event.target;
  if (target.isContentEditable || target.closest?.('textarea, select, input:not([type="range"])')) return;
  const undo = $('#manualGuideUndo') ?? $('#surfaceUndo');
  if (!undo || undo.disabled) return;
  event.preventDefault();
  undo.click();
});
$('#strandRegion').onchange = event => { region = event.target.value; select(selected); };
$('#strandSelect').onchange = event => select(event.target.value);
$('#showAll').onchange = syncViewerSelection;
$('#showNeighbors').onchange = syncViewerSelection;
$('#coarseOverlay').onchange = draw;
$('#markOverlay').onchange = draw;
bind('viewBefore', () => { comparison = 'before'; return draw(); });
bind('viewAfter', () => {
  if (sectionOpen) sectionEditor.live = false;
  comparison = 'after';
  return draw();
});
bind('viewSectionBaseline', () => { comparison = 'baseline'; return draw(); });
bind('referenceSplit', () => { referenceCompare.split = !referenceCompare.split; return draw(); });
bind('referenceOverlay', () => { referenceCompare.overlay = !referenceCompare.overlay; return draw(); });
$('#referenceOpacity').oninput = event => {
  referenceCompare.opacity = Number(event.target.value);
  $('#referenceOpacityValue').textContent = t(`${referenceCompare.opacity}%`);
  viewer?.setReferenceOpacity(referenceCompare.opacity/100);
};
bind('showSectionEditor', openSectionControls);
$('#beforeVersion').onchange = event => { comparisonVersion = event.target.value; comparison = 'before'; return draw(); };
document.querySelectorAll('[data-view]').forEach(element => {
  element.onclick = () => { mode = element.dataset.view; void draw(); };
});
document.querySelectorAll('[data-camera]').forEach(element => {
  element.onclick = () => {
    camera = element.dataset.camera;
    renderCameraControls();
    viewer?.cameraView(camera);
  };
});
bind('closeStudio', () => $('#studioDialog').close());
bind('closeCoarseTask', () => $('#coarseTaskDialog').close());
bind('closeReferenceTask', () => $('#referenceTaskDialog').close());
bind('closeReferencePreview', () => $('#referencePreviewDialog').close());
bind('copyReferenceTask', async () => {
  await navigator.clipboard.writeText($('#referenceTaskMessage').value);
  toast(t('补图任务已复制。'));
});
bind('copyStudio', async () => {
  await navigator.clipboard.writeText($('#studioMessage').value);
  $('#studioDialog').close();
  toast(t('Tripo 任务已复制，请粘贴到当前 Codex 对话。'));
});
bind('copyCoarseTask', async () => {
  await navigator.clipboard.writeText($('#coarseTaskMessage').value);
  $('#coarseTaskDialog').close();
  toast(t('任务已复制，请粘贴到当前 Codex 对话。'));
});
try {
  viewer = new HairViewer($('#scene'), select);
} catch (error) {
  toast(t('三维预览不可用：' + error.message));
}
sectionEditor = new SectionEditor($('#sectionEditor'), paintSectionDraft, plan => {
  void act('point-section-preview', {requestId:crypto.randomUUID(), cardsId:project.cards.id,
    resultId:project.result.id, plan});
}, () => {
  sectionOpen = false;
  renderSectionEditor();
  $('#pointSections')?.focus({preventScroll:true});
});

// Language changes are presentation-only: keep project, selection and local edits.
document.querySelectorAll('[data-language]').forEach(button=>button.addEventListener('click',()=>setLanguage(button.dataset.language)));
let localeReady=false;
document.addEventListener('hairbridge:language',async()=>{
  if(!localeReady)return;
  const values=[...document.querySelectorAll('input,textarea,select')]
    .filter(el=>!el.readOnly && el.type!=='file' && el.id!=='newName').map(el=>{
      const parent=el.parentElement?.closest('[id]');
      const selector=el.id ? `#${CSS.escape(el.id)}` :
        `${parent ? '#'+CSS.escape(parent.id)+' ' : ''}${el.tagName.toLowerCase()}${el.name ? '[name="'+CSS.escape(el.name)+'"]' : ''}`;
      return [selector,[...document.querySelectorAll(selector)].indexOf(el),el.value,el.checked];
    });
  try {
    if(project){project=await api(`/api/projects/${project.id}`);await render();}
    else await home();
    for(const [selector,index,value,checked] of values){const el=document.querySelectorAll(selector)[index];if(el){el.value=value;if(el.type==='checkbox')el.checked=checked;}}
    if($('#newName').value=== '我的发型'||$('#newName').value==='My hairstyle')$('#newName').value=t('我的发型');
    if($('#referenceTaskDialog')?.open)showReferenceTask();
    if($('#studioDialog')?.open)showStudio();
    if($('#coarseTaskDialog')?.open){if(coarseTaskKind==='separation')showSeparation();else showGuideFit();}
  }catch(error){toast(error.message);}
});
translateDOM(document);
setLanguage(getLanguage());
$('#newName').value=t('我的发型');

try {
  caps = await api('/api/capabilities');
  $('#rainTripoProject').disabled = caps.rainTripo === false;
  const id = location.hash.slice(1);
  if (/^[a-f0-9-]{36}$/.test(id)) await open(id);
  else await home();
  localeReady=true;
} catch (error) { toast(t(error.message)); }

setInterval(async () => {
  if (!project || busy) return;
  const existing = project;
  try {
    const next = await api(`/api/projects/${existing.id}`);
    if (project !== existing || busy) return;
    const previous = existing.jobs.at(-1)?.status;
    if (next.revision === existing.revision && previous !== 'running') return;
    project = next;
    const latest = next.jobs.at(-1);
    if (previous === 'running' && latest?.status === 'succeeded') {
      if (isHairDeckPreviewJob(latest)) {
        toast(t('HairDeck 初稿已就绪，可在「HairDeck 初稿」查看。'));
      } else if (latest.kind === 'hair-closure') {
        mode = 'closed';
        toast(t('闭合测量粗模已就绪。'));
      } else {
        if (!(stage === 'guides' && next.pointFlowAvailable)) stage = resumeStage();
        mode = next.result ? 'result' : 'guides';
        comparison = 'after';
        toast(t('处理完成，请审核结果。'));
      }
    } else if (stage === 'draft') {
      const returned = registeredStudioRequest(next);
      const split = next.separation;
      if (returned && returned.id !== registeredStudioRequest(existing)?.id) $('#studioDialog').close();
      if (hasPartPreview('parts') && (split.head.id !== existing.separation?.head?.id ||
        split.hair.id !== existing.separation?.hair?.id)) {
        mode = 'parts';
        $('#coarseTaskDialog').close();
        toast(t(hasP2Bundle() ? '粗模及拆分结果已返回，请叠加审核头模和头发。' : '拆分结果已返回，请检查头皮与头发。'));
      } else if (returned && returned.id !== registeredStudioRequest(existing)?.id) {
        mode = 'coarse';
        toast(t('粗模已返回，请对照参考图检查轮廓。'));
      }
    }
    await render();
  } catch (error) {
    $('#saved').textContent = t('正在重连');
  }
}, 2500);
