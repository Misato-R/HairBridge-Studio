import {t,h,msg,getLanguage,setLanguage,translateDOM,taskMessage} from './i18n.mjs';
import {initialGuideEdit,PointFlowEditor} from './point-flow-editor.mjs';
import {fitPointFlow} from './point-flow-fit.mjs';
import {cleanSurfaceMask,surfaceTopology} from './surface-mask-cleanup.mjs';
import {createManualGuideFitter,minGuideAnchors,maxGuideAnchors} from './manual-guide.mjs';

const escape = value => String(value ?? '').replace(/[&<>"']/g,ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const liveGroups = state => state.groups ?? [];
const fitted = state => liveGroups(state).filter(group => group.confirmed && group.fitKey).flatMap(group => group.guideRecipes);

export class SurfaceFlowEditor extends PointFlowEditor {
  constructor(fixture, project, onChange, notify) {
    const state = project.surfaceFlow;
    super({...fixture,regions:liveGroups(state).length ? liveGroups(state) : [{id:'pending',strandIds:[]}],
      strands:fitted(state)},project,onChange,notify);
    this.surfaceMode = true;
    this.selectedIds = this.selectedIds.filter(id => this.strands[id]);
    this.drafts = new Map();
    this.history = new Map();
    this.cleanups = new Map();
    this.keys = new Map(liveGroups(state).map(group => [group.id,group.fitKey]));
    this.tool = 'inspect';
    this.radius = 14;
    this.forceMask = false;
    this.sync(project);
  }

  sync(project) {
    this.state = project.surfaceFlow;
    this.fixture.regions = liveGroups(this.state);
    this.fixture.strands = fitted(this.state);
    this.assignments = project.pointFlowRegionAssignments ?? {};
    this.strands = Object.fromEntries(this.fixture.strands.map(guide => [guide.id,guide]));
    if (!this.fixture.regions.some(group => group.id === this.region)) this.region = this.fixture.regions[0]?.id;
    if (this.manualDraft && (!this.group?.confirmed || this.group.fitKey !== this.manualDraft.fitKey)) this.manualDraft = null;
    if (this.group?.refitTask?.status !== 'ready' || this.drafts.has(this.region)) this.refitPreview = false;
    for (const group of this.fixture.regions) {
      const previous = this.keys.get(group.id);
      for (const guide of group.fitKey ? group.guideRecipes : []) {
        if (this.edits[guide.id] && group.fitKey === previous) continue;
        this.edits[guide.id] = initialGuideEdit(guide);
        this.undoStacks[guide.id] = [];
      }
      this.keys.set(group.id,group.fitKey);
    }
    this.selectedIds = this.selectedIds.filter(id => this.strands[id]);
    if (project.pointFlow?.cardsId && project.pointFlow.cardsId !== this.cardsId) {
      for (const id of project.pointFlow.selectedIds ?? []) {
        if (!this.strands[id] || !project.pointFlow.edits[id]) continue;
        this.edits[id] = structuredClone(project.pointFlow.edits[id]);
        this.undoStacks[id] = [];
      }
      this.selectedIds = (project.pointFlow.selectedIds ?? []).filter(id => this.strands[id]);
      this.accepted(project.pointFlow.cardsId);
    }
    if (this.region && !this.groupIds.includes(this.strandId)) {
      this.strandId = this.groupIds[0];
      this.active = this.strandId ? this.nextSlot() : null;
    }
  }

  get reviewingRegion() { return this.forceMask || this.drafts?.has(this.region) || !this.group?.confirmed || !this.group.fitKey || !this.groupIds.length; }
  get viewportLabel() {
    if (this.manualDraft) return '补画导线';
    if (this.refitPreview) return `${this.refitPreview === 'after' ? '新版导线' : '当前导线'} · ${this.refitGuides.length} 条`;
    return this.reviewingRegion ? '粗模选区' : '在发片上标记';
  }
  get refitGuides() {
    const current = this.group.guideRecipes;
    if (this.refitPreview !== 'after') return current;
    return [...this.group.refitTask.proposal.recipes,...current.filter(guide => guide.manual)];
  }
  get viewportInstruction() {
    if (this.manualDraft) return '点击放点 · 拖动编号改点';
    if (this.refitPreview) return '换视角检查发束走向';
    if (!this.reviewingRegion) return '点击发片标记';
    return this.tool === 'inspect' ? '点击颜色区块选区' : '在可见头发表面涂抹';
  }
  get mask() { return this.drafts.get(this.region) ?? this.group?.faces ?? []; }
  get cleanup() { return this.cleanups.get(this.region); }
  get displayedMask() { return this.cleanup?.showAfter ? this.cleanup.faces : this.mask; }

  selectRegion(id,useCamera) {
    this.manualDraft = null;
    this.refitDraftRegion = null;
    this.refitPreview = false;
    this.forceMask = false;
    this.tool = 'inspect';
    super.selectRegion(id,useCamera);
  }

  payload(revision,requestId,priorFlow) {
    const localIds = this.selectedInGroup;
    const retained = (priorFlow?.selectedIds ?? []).filter(id => {
      const source = priorFlow.strandRegions?.[id];
      return source !== this.region && !localIds.includes(id) && this.fixture.regions.some(group => group.id === source);
    });
    return {version:this.fixture.version,revision,requestId,surfaceGroupId:this.region,selectedIds:[...retained,...localIds],
      strands:{...priorFlow?.edits,...Object.fromEntries(localIds.map(id => [id,this.edits[id]]))}};
  }

  changedMask(faces,tool) {
    const mask = new Set(this.mask);
    for (const id of faces) if (tool === 'add') mask.add(id); else mask.delete(id);
    return [...mask].sort((a,b) => a-b);
  }

  setDraft(faces) {
    const saved = this.group.faces;
    if (faces.length === saved.length && faces.every((id,i) => id === saved[i])) this.drafts.delete(this.region);
    else this.drafts.set(this.region,faces);
  }

  commitPaint(faces,tool) {
    this.commitMask(this.changedMask(faces,tool));
  }

  commitMask(next) {
    const original = this.mask;
    if (next.length !== original.length || next.some((id,i) => id !== original[i])) {
      const history = this.history.get(this.region) ?? [];
      history.push(original);
      if (history.length > 30) history.shift();
      this.history.set(this.region,history);
      this.setDraft(next);
    }
    this.change();
  }

  previewCleanup() {
    this.topology ??= surfaceTopology(this.fixture.surfaceMesh);
    const protectedFaces = new Set(this.fixture.regions.filter(group => group !== this.group && group.confirmed)
      .flatMap(group => group.faces));
    const result = cleanSurfaceMask(this.topology,this.mask,protectedFaces);
    if (!result.added && !result.removed) return this.notify(t('当前选区边缘无需清理。'));
    this.tool = 'inspect';
    this.cleanups.set(this.region,{...result,showAfter:true});
    this.change();
  }

  copyTask(task) {
    return task?.status === 'pending' ? `<label class="flow-assignment-field">给 Codex 的任务<textarea id="surfaceTaskText" rows="5" readonly>${escape(taskMessage(task))}</textarea></label>
      <button id="surfaceCopyTask" class="full quiet" type="button">复制任务</button>` : '';
  }

  guideReviewSummary() {
    const {guideRecipes,uncovered,incomplete} = this.group;
    const manual = guideRecipes.filter(guide => guide.manual).length;
    return `<p class="subtle">已拟合 ${guideRecipes.length-manual} 束${manual ? ` · 手动补画 ${manual} 束` : ''}。${uncovered ? `另有 ${uncovered} 个粗模面待辨认。` : ''}${incomplete.length ? `待重新标记 ${escape(incomplete.join('、'))}。` : ''}</p>`;
  }

  guideActions(working) {
    const disabled = working ? ' disabled' : '';
    const current = this.strand;
    const invalid = (this.group.manualGuides ?? []).filter(guide => !this.strands[guide.id]);
    return `<div class="point-actions"><button type="button" class="quiet" id="manualGuideStart"${disabled}>补一条导线</button>
      ${this.group.refitTask || this.refitDraftRegion === this.region ? '' :
        `<button type="button" class="quiet" id="surfaceRefitStart"${disabled}>重新生成导线</button>`}
      ${current?.manual ? `<button type="button" class="quiet" data-remove-manual-guide="${current.id}"${disabled}>移除这条补线</button>` : ''}</div>
      ${invalid.map(guide => `<button type="button" class="quiet" data-remove-manual-guide="${guide.id}"${disabled}>移除「${escape(guide.label)}」</button>`).join('')}
      ${this.refitControls(disabled)}`;
  }

  refitControls(disabled) {
    const request = this.group.refitTask;
    if (request?.status === 'ready') {
      const {recipes,unresolved} = request.proposal;
      const manual = this.group.guideRecipes.filter(guide => guide.manual).length;
      return `<section class="surface-cleanup-review" aria-label="审核重做导线">
        <p class="subtle">新版有 ${recipes.length} 条候选导线${manual ? `，另有 ${manual} 条手动补线` : ''}。</p>
        ${unresolved.length ? `<p class="subtle">待辨认 ${escape(unresolved.join('、'))}</p>` : ''}
        <div class="point-actions" role="group" aria-label="同机位对比导线">
          <button type="button" class="quiet" id="surfaceRefitBefore" aria-pressed="${this.refitPreview === 'before'}">当前导线</button>
          <button type="button" class="quiet" id="surfaceRefitAfter" aria-pressed="${this.refitPreview === 'after'}">查看新版</button></div>
        <div class="point-actions"><button type="button" class="primary" id="surfaceRefitAdopt"${disabled}>采用新版导线</button>
          <button type="button" class="quiet" id="surfaceRefitCancel"${disabled}>放弃新版</button></div>
        ${this.refitPreview ? '<button type="button" class="full quiet" id="surfaceRefitExit">返回区块</button>' : ''}</section>`;
    }
    if (request?.status === 'pending') return `<section class="surface-cleanup-review" aria-label="等待 Codex 重做导线">
      <p class="subtle">把任务复制给 Codex。等待期间仍可查看当前导线。</p>
      ${this.copyTask(request)}<button type="button" class="quiet" id="surfaceRefitCancel"${disabled}>取消重做任务</button></section>`;
    if (this.refitDraftRegion !== this.region) return '';
    return `<form class="surface-cleanup-review" id="surfaceRefitForm" aria-label="准备重做导线任务">
      <label class="flow-assignment-field">希望改哪里<textarea name="note" rows="3" maxlength="1000"
        placeholder="例如：左右外侧有漏束，请沿发梢重新辨认。"${disabled}></textarea></label>
      <div class="point-actions"><button type="submit" class="primary"${disabled}>准备重做任务</button>
        <button type="button" class="quiet" id="surfaceRefitClose"${disabled}>取消</button></div></form>`;
  }

  startManualGuide() {
    this.refitPreview = false;
    const mesh = this.fixture.surfaceMesh;
    this.topology ??= surfaceTopology(mesh);
    const covered = new Set(this.groupIds.flatMap(id => this.strands[id].coverageFaces ??
      this.fixture.selectionHints.find(hint => hint.id === id)?.faceIds ?? []));
    this.manualDraft = {fitKey:this.group.fitKey, anchors:[], history:[], faceIds:new Set(this.group.faces),
      unmatched:{vertices:mesh.vertices,faces:this.group.faces.filter(id => !covered.has(id)).flatMap(id => mesh.faces.slice(id*3,id*3+3))},
      fit:createManualGuideFitter(mesh,this.group.faces,this.topology)};
    this.change();
  }

  manualAnchors(anchors,checkpoint = true) {
    const draft = this.manualDraft;
    if (!draft || draft.saving) return;
    if (checkpoint) draft.history.push(draft.anchors);
    draft.anchors = anchors;
    draft.preview = null;
    draft.error = null;
    if (anchors.length >= 2) {
      try { draft.preview = draft.fit(anchors); }
      catch (error) { draft.error = error.message; }
    }
    this.change();
  }

  manualHit(hit, index) {
    const draft = this.manualDraft;
    if (!draft || draft.saving) return;
    if (!hit) return this.notify(t('请点选当前区块中可见的头发。'));
    if (index == null && draft.anchors.length >= maxGuideAnchors) return this.notify(t('可以拖动已有的点，或撤销后再补点。'));
    const anchors = [...draft.anchors];
    if (index == null) anchors.push(hit);
    else anchors[index] = hit;
    this.manualAnchors(anchors);
  }

  manualBody(working) {
    const draft = this.manualDraft;
    const locked = working || draft.saving;
    const disabled = locked ? ' disabled' : '';
    const count = draft.anchors.length;
    return `<section class="point-editor"><h3>补一条导线 · ${escape(this.group.label)}</h3>
      <p>沿同一片头发依次点 3–5 个点。黄色是待辨认发面，浅蓝是已有导线。</p>
      <p class="subtle" role="status">${draft.error ? escape(draft.error) : count ?
        `已放置 ${count} 个点。可以换视角、拖动编号。确认前检查 1 号是起点，末点是发梢。` : '先点起点或容易辨认的发梢。'}</p>
      <div class="point-actions"><button type="button" id="manualGuideReverse" class="quiet"${count < 2 ? ' disabled' : disabled}>反转起点和发梢</button>
      <button type="button" id="manualGuideUndo" class="quiet" aria-keyshortcuts="Control+Z Meta+Z"${!draft.history.length ? ' disabled' : disabled}>撤销 <kbd>Ctrl+Z</kbd></button></div>
      <button type="button" class="primary" id="manualGuideSave"${!draft.preview || count < minGuideAnchors ? ' disabled' : disabled}>确认并加入本组</button>
      <button type="button" class="full quiet" id="manualGuideCancel"${disabled}>取消补画</button></section>`;
  }

  body(options) {
    const {working} = options;
    const disabled = working ? ' disabled' : '';
    if (this.manualDraft) return this.manualBody(working);
    if (this.refitPreview) return `<section class="point-editor"><h3>审核重做导线 · ${escape(this.group.label)}</h3>
      ${this.refitControls(disabled)}</section>`;
    if (!this.state.groups) return `<section class="point-editor"><h3>准备自动分区</h3>
      <p>让 Codex 根据已审核的头发粗模提出区块。收到建议后，可以逐区修边和确认。</p>
      ${this.state.layoutTask?.status === 'pending' ? this.copyTask(this.state.layoutTask) :
        `<button id="surfaceRequestLayout" class="primary" type="button"${disabled}>准备自动分区任务</button>`}</section>`;
    if (!this.reviewingRegion) return super.body(options);
    const nav = this.fixture.regions.map(group => {
      const status = group.fitKey ? `${group.guideRecipes.length} 束已拟合` : group.confirmed ? '已确认选区' : '待确认选区';
      return `<button class="quiet" type="button" data-surface-region="${group.id}" aria-pressed="${group === this.group}"><span><i style="background:#${group.color.toString(16).padStart(6,'0')}"></i>${escape(group.label)}</span><small>${status}</small></button>`;
    }).join('');
    const manage = `<form id="surfaceAddRegion" class="surface-add-region"><input name="label" placeholder="新区域名称" maxlength="24" required aria-label="新区域名称"${disabled}><button type="submit" class="quiet"${disabled}>新增区块</button></form>`;
    if (!this.group) return `<section class="point-editor"><h3>编辑头发选区</h3>${manage}</section>`;
    if (this.cleanup) return `<section class="point-editor"><h3>编辑头发选区</h3>
      <div class="flow-region-tabs" role="group" aria-label="发型区块">${nav}</div>
      <h4>${escape(this.group.label)}</h4><div class="surface-cleanup-review">
      <p class="subtle" id="surfaceCleanupDelta">建议补选 ${this.cleanup.added} 面，减选 ${this.cleanup.removed} 面。</p>
      <div class="point-actions" role="group" aria-label="比较清理前后">
        <button type="button" id="surfaceCleanupBefore" class="quiet" aria-pressed="${!this.cleanup.showAfter}">清理前</button>
        <button type="button" id="surfaceCleanupAfter" class="quiet" aria-pressed="${this.cleanup.showAfter}">清理后</button>
      </div>
      <div class="point-actions"><button type="button" id="surfaceCleanupApply" class="primary"${disabled}>采用清理结果</button>
        <button type="button" id="surfaceCleanupCancel" class="quiet">取消预览</button></div></div></section>`;
    const tools = [['inspect','巡视'],['add','加选画笔'],['remove','减选画笔']].map(([id,label]) =>
      `<button type="button" class="quiet" data-surface-tool="${id}" aria-pressed="${id===this.tool}"${disabled}>${label}</button>`).join('');
    const laneOptions = this.fixture.selectionHints.map(lane => `<option value="${lane.id}">${escape(lane.label)}</option>`).join('');
    const dirty = this.drafts.has(this.region);
    const pending = this.group.fitTask?.status === 'pending';
    const diagnostics = this.group.fitKey ? this.guideReviewSummary() : '';
    return `<section class="point-editor"><h3>编辑头发选区</h3>
      <div class="flow-region-tabs" role="group" aria-label="发型区块">${nav}</div>${manage}
      <h4>${escape(this.group.label)}</h4><p class="subtle" id="surfaceFaceCount">${this.mask.length} 个选中面${dirty?' · 有未保存修改':''}</p>
      <div class="point-actions" role="group" aria-label="选区画笔">${tools}</div>
      ${this.tool === 'inspect' ? '<p class="subtle">切换视角检查发片边缘，再加选或减选。</p>' :
        `<label class="flow-assignment-field"><span>画笔直径 <output id="surfaceDiameter" for="surfaceRadius">${2*this.radius} px</output></span><input type="range" id="surfaceRadius" min="4" max="32" value="${this.radius}"></label>
         <p class="subtle">画笔作用于可见的头发表面。改用「巡视」可旋转模型。</p>`}
      <button type="button" id="surfaceCleanup" class="full quiet" ${working || !this.mask.length ? 'disabled' : ''}>清理选区边缘</button>
      <details class="part-files"><summary>按发流线索加减选</summary>
        <select id="surfaceLane" aria-label="发流线索">${laneOptions}</select>
        <div class="point-actions"><button type="button" id="surfaceLaneAdd"${disabled}>加选整段</button><button type="button" id="surfaceLaneRemove"${disabled}>减选整段</button></div></details>
      <div class="point-actions"><button type="button" id="surfaceUndo" aria-keyshortcuts="Control+Z Meta+Z" ${working || !(this.history.get(this.region)?.length) ? 'disabled' : ''}>撤销选区修改 <kbd>Ctrl+Z</kbd></button>
      <button type="button" id="surfaceRemoveRegion" class="quiet"${disabled}>移除区块</button></div>
      ${dirty ? `<button type="button" id="surfaceSave" class="full quiet"${disabled}>保存选区草稿</button>` : ''}
      ${!this.group.confirmed || dirty ? `<button type="button" id="surfaceConfirm" class="primary" ${working || !this.mask.length ? 'disabled' : ''}>确认当前选区</button>` :
        this.group.fitKey ? (this.groupIds.length ? `<button type="button" id="surfaceOpenGuides" class="primary">进入本区导线</button>` : '') :
        pending ? this.copyTask(this.group.fitTask) : `<button type="button" id="surfaceFitRequest" class="primary"${disabled}>准备本区导线拟合任务</button>`}
      ${this.group.fitKey && !dirty ? this.guideActions(working) : ''}
      ${diagnostics}</section>`;
  }

  bind(root,options) {
    const bind = (id,fn) => {const control=root.querySelector('#'+id);if(control) control.onclick=fn;};
    const change = (action,payload={}) => options.surfaceAction(action,payload);
    if (this.manualDraft) {
      const draft = this.manualDraft;
      bind('manualGuideReverse',() => this.manualAnchors([...draft.anchors].reverse()));
      bind('manualGuideUndo',() => this.manualAnchors(draft.history.pop(),false));
      bind('manualGuideCancel',() => {this.manualDraft=null;this.change();});
      bind('manualGuideSave',async () => {
        draft.saving = true;
        this.change();
        if (!await change('surface-manual-guide-add',{regionId:this.region,guideId:`manual_${crypto.randomUUID()}`,anchors:draft.anchors})) {
          draft.saving = false;
          this.change();
        }
      });
      return;
    }
    bind('manualGuideStart',() => this.startManualGuide());
    bind('surfaceRefitStart',() => {this.refitDraftRegion=this.region;this.change();});
    bind('surfaceRefitClose',() => {this.refitDraftRegion=null;this.change();});
    const refitForm = root.querySelector('#surfaceRefitForm');
    if (refitForm) refitForm.onsubmit = event => {
      event.preventDefault();
      void change('surface-refit-request',{regionId:this.region,note:new FormData(refitForm).get('note')});
    };
    for (const [id,preview] of [['surfaceRefitBefore','before'],['surfaceRefitAfter','after'],['surfaceRefitExit',false]]) {
      bind(id,() => {this.refitPreview=preview;this.change();});
    }
    for (const [id,action] of [['surfaceRefitAdopt','surface-refit-adopt'],['surfaceRefitCancel','surface-refit-cancel']]) {
      bind(id,() => change(action,{regionId:this.region,taskId:this.group.refitTask.id}));
    }
    if (this.refitPreview) return;
    bind('surfaceCopyTask',async () => {
      const field = root.querySelector('#surfaceTaskText');
      try {await navigator.clipboard.writeText(field.value);this.notify(t('任务已复制。'));}
      catch {field.select();this.notify(t('请复制已选中的任务文字。'));}
    });
    root.querySelectorAll('[data-remove-manual-guide]').forEach(button => {
      button.onclick = () => change('surface-manual-guide-remove',{regionId:this.region,guideId:button.dataset.removeManualGuide});
    });
    if (!this.reviewingRegion) {
      super.bind(root,options);
      root.querySelector('#flowPickRegion').onclick = () => {this.forceMask=true;this.change();};
      return;
    }
    bind('surfaceRequestLayout',() => change('surface-layout-request'));
    root.querySelectorAll('[data-surface-region]').forEach(button => {button.onclick=() => this.selectRegion(button.dataset.surfaceRegion,true);});
    root.querySelectorAll('[data-surface-tool]').forEach(button => {button.onclick=() => {this.tool=button.dataset.surfaceTool;this.change();};});
    const add = root.querySelector('#surfaceAddRegion');
    if (add) add.onsubmit = event => {event.preventDefault();void change('surface-region-add',{label:new FormData(add).get('label')});};
    const radius = root.querySelector('#surfaceRadius');
    if (radius) radius.oninput = () => {
      this.radius = Number(radius.value);
      root.querySelector('#surfaceDiameter').textContent = t(`${2*this.radius} px`);
      this.viewer?.setSurfaceBrushRadius(this.radius);
    };
    bind('surfaceCleanup',() => this.previewCleanup());
    bind('surfaceCleanupBefore',() => {this.cleanup.showAfter=false;this.change();});
    bind('surfaceCleanupAfter',() => {this.cleanup.showAfter=true;this.change();});
    bind('surfaceCleanupCancel',() => {this.cleanups.delete(this.region);this.change();});
    bind('surfaceCleanupApply',() => {
      const faces = this.cleanup.faces;
      this.cleanups.delete(this.region);
      this.commitMask(faces);
    });
    bind('surfaceRemoveRegion',() => change('surface-region-remove',{regionId:this.region}));
    const save = confirm => change('surface-region-save',{regionId:this.region,faces:this.mask,confirm});
    bind('surfaceSave',() => save(false));
    bind('surfaceConfirm',() => save(true));
    bind('surfaceFitRequest',() => change('surface-fit-request',{regionId:this.region}));
    bind('surfaceOpenGuides',() => {this.forceMask=false;this.change();});
    bind('surfaceUndo',() => {this.setDraft(this.history.get(this.region).pop());this.change();});
    for (const [id,tool] of [['surfaceLaneAdd','add'],['surfaceLaneRemove','remove']]) bind(id,() =>
      this.commitPaint(this.fixture.selectionHints.find(lane => lane.id === root.querySelector('#surfaceLane').value).faceIds,tool));
  }

  applied(action,payload) {
    if (action === 'surface-refit-request') this.refitDraftRegion = null;
    if (action === 'surface-refit-adopt') {
      this.forceMask = false;
      this.tool = 'inspect';
    }
    if (action === 'surface-manual-guide-add') {
      this.manualDraft = null;
      this.forceMask = false;
      this.tool = 'inspect';
      this.selectStrand(payload.guideId);
      return;
    }
    if (action === 'surface-region-save' || action === 'surface-region-remove') {
      this.drafts.delete(payload.regionId);
      this.cleanups.delete(payload.regionId);
    }
    if (action === 'surface-region-add') this.selectRegion(this.fixture.regions.at(-1).id,false);
    else this.change();
  }

  show(viewer,working) {
    this.viewer = viewer;
    if (this.manualDraft) {
      const draft = this.manualDraft;
      const pick = index => ({accepts:(_position,triangle) => draft.faceIds.has(triangle),onHit:hit => this.manualHit(hit,index)});
      viewer.setSurfaceBrush(null);
      viewer.showFlowRegions(draft.unmatched.faces.length ? [{id:this.region,surface:draft.unmatched,color:0xf9c879,opacity:.45}] : []);
      viewer.setPointFlow({card:draft.preview?.surfacePath,color:0xffe09f,surface:this.fixture.surfaceMesh,
        others:this.groupIds.map(id => ({seq:this.strands[id].base.seq})),
        markers:draft.anchors.map((mark,i) => ({id:`manual-${i}`,label:`补线点 ${i+1}`,number:i+1,confirmed:true,
          position:mark.position,onClick:working || draft.saving ? null : () => {},
          drop:working || draft.saving ? null : pick(i)})),
        pick:working || draft.saving ? null : pick(null)});
      return;
    }
    if (this.refitPreview) {
      const newVersion = this.refitPreview === 'after';
      const others = this.refitGuides.map(guide => {
        const edit = this.edits[guide.id] ?? initialGuideEdit(guide);
        const versions = fitPointFlow(guide,edit);
        return versions[edit.choice] ?? versions.after;
      });
      viewer.setSurfaceBrush(null);
      viewer.showFlowRegions(null);
      viewer.setPointFlow({card:null,otherColor:newVersion ? 0xffd18a : 0x8dbfe5,
        surface:this.fixture.surfaceMesh,markers:[],others});
      return;
    }
    if (!this.reviewingRegion) {
      viewer.setSurfaceBrush(null);
      return super.show(viewer,working);
    }
    viewer.setPointFlow(null);
    const mesh = this.fixture.surfaceMesh;
    const selectRegion = working || this.tool !== 'inspect' ? null : id => this.selectRegion(id,false);
    const showMask = mask => viewer.showSurfaceRegions(mesh,this.fixture.regions,this.region,mask,selectRegion);
    showMask(this.displayedMask);
    if (this.group && !working && this.tool !== 'inspect' && !this.cleanup) {
      viewer.setSurfaceBrush({surface:mesh,radius:this.radius,tool:this.tool,preview:faces => showMask(this.changedMask(faces,this.tool)),
        finish:faces => this.commitPaint(faces,this.tool)});
    } else viewer.setSurfaceBrush(null);
  }
}
