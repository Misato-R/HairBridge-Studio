import {t,h,msg,getLanguage,setLanguage,translateDOM,taskMessage} from './i18n.mjs';
import {activeMoveFaces,arcWeight,canPlacePoint,fitPointFlow,guideSegments,pointSlots} from './point-flow-fit.mjs';
import {defaultStrandIds} from './section-profile.mjs';

const versions = {before: '标记前', after: '标记后', hairdeck: 'HairDeck 对照'};
const colors = {before: 0xf2b37f, after: 0xd8b1ff, hairdeck: 0x82e4b5};

export function initialGuideEdit(strand) {
  const points = strand.manual || strand.refit ? Object.fromEntries(strand.points.map(slot => [slot.id,
    {position:slot.suggestion,triangle:slot.triangle,locked:false}])) : {};
  return {points,thirdBend:strand.id === 'curl',choice:'after'};
}

export class PointFlowEditor {
  constructor(fixture, project, onChange, notify) {
    this.fixture = fixture;
    this.key = `hairbridge:point-flow:${project.id}:${fixture.version}:${fixture.modelSha256}`;
    this.change = onChange;
    this.notify = notify;
    this.strands = Object.fromEntries(fixture.strands.map(strand => [strand.id, strand]));
    const defaults = Object.fromEntries(fixture.strands.map(strand => [strand.id,initialGuideEdit(strand)]));
    this.edits = {...defaults, ...structuredClone(project.pointFlow?.edits ?? {})};
    this.undoStacks = Object.fromEntries(fixture.strands.map(strand => [strand.id, []]));
    this.selectedIds = [...(project.pointFlow?.selectedIds ?? defaultStrandIds)];
    try {
      const saved = JSON.parse(localStorage.getItem(this.key));
      if (saved && saved.cardsId === (project.pointFlow?.cardsId ?? null)) {
        this.edits = {...this.edits, ...saved.edits};
        this.undoStacks = {...this.undoStacks, ...saved.undoStacks};
        this.selectedIds = (saved.selectedIds ?? this.selectedIds).filter(id => this.strands[id]);
      } else if (saved && project.surfaceFlow?.enabled && project.pointFlow?.selectedIds) {
        const generated = new Set(project.pointFlow.selectedIds);
        for (const id of Object.keys(this.strands)) {
          if (generated.has(id) || !saved.edits?.[id]) continue;
          this.edits[id] = saved.edits[id];
          this.undoStacks[id] = saved.undoStacks?.[id] ?? [];
        }
      }
    } catch { /* Private sessions can still complete a new draft. */ }
    this.cardsId = project.pointFlow?.cardsId ?? null;
    this.suggestedAssignments = Object.fromEntries(fixture.regions.flatMap(region =>
      (region.strandIds ?? []).map(id => [id,region.id])));
    this.assignments = project.pointFlowRegionAssignments ?? this.suggestedAssignments;
    this.strandPatches = fixture.strandPatches ?? {};
    this.region = fixture.regions[0].id;
    this.strandId = this.groupIds[0];
    this.reviewed = project.pointFlowReviewedRegions ?? [];
    this.pickingRegion = false;
    this.assignmentStrand = null;
    this.assignmentTarget = null;
    this.active = this.strandId ? this.nextSlot() : null;
    this.view = 'after';
  }

  get strand() { return this.strands[this.strandId]; }
  get edit() { return this.edits[this.strandId]; }
  get slots() { return pointSlots(this.strand, this.edit); }
  get curves() { return fitPointFlow(this.strand, this.edit); }
  get segments() { return this.strand?.anchorEditing ? guideSegments(this.strand,this.slots) : []; }
  get group() { return this.fixture.regions.find(region => region.id === this.region); }
  get groupIds() { return this.members(this.region); }
  get selectedInGroup() { return this.selectedIds.filter(id => this.groupIds.includes(id)); }
  get reviewingRegion() { return !!this.assignmentStrand || this.pickingRegion || !this.reviewed.includes(this.region) || !this.groupIds.length; }
  get viewportLabel() {
    if (this.assignmentStrand) return '整束归属预览';
    return this.reviewingRegion ? '粗模分区建议' : '在发片上标记';
  }
  get viewportInstruction() {
    if (this.assignmentStrand) return '点击候选发片选束';
    return this.reviewingRegion ? '点击颜色区块选区' : '点击发片标记';
  }

  members(regionId) {
    return this.fixture.strands.filter(strand => this.assignments[strand.id] === regionId).map(strand => strand.id);
  }

  selectAssignment(strandId) {
    this.assignmentStrand = strandId;
    this.assignmentTarget = this.assignments[strandId];
    this.change();
  }

  nextSlot() { return this.slots.find(slot => !this.edit.points[slot.id])?.id ?? null; }

  counts(strand) {
    const state = this.edits[strand.id];
    const slots = pointSlots(strand, state);
    return {done: slots.filter(slot => state.points[slot.id]).length, total: slots.length};
  }

  complete(ids) {
    return !!ids.length && ids.every(id => {
      const strand = this.strands[id];
      const {done, total} = this.counts(strand);
      return done === total;
    });
  }

  store() {
    try { localStorage.setItem(this.key, JSON.stringify({cardsId: this.cardsId,
      edits: this.edits, undoStacks: this.undoStacks, selectedIds:this.selectedIds})); } catch { /* Server saves the confirmed draft. */ }
  }

  accepted(cardsId) {
    this.cardsId = cardsId;
    this.store();
  }

  payload(revision, requestId, priorFlow, groupOnly) {
    const payload = {version: this.fixture.version, revision, requestId, strands:this.edits, selectedIds:this.selectedIds};
    if (!groupOnly) return payload;
    const group = this.groupIds;
    const retained = (priorFlow?.selectedIds ?? (priorFlow ? defaultStrandIds : [])).filter(id => !group.includes(id));
    const selected = this.selectedInGroup;
    return {...payload, selectedIds:[...retained,...selected], strands:{...priorFlow?.edits,
      ...Object.fromEntries(selected.map(id => [id,this.edits[id]]))}};
  }

  selectStrand(id, frame = null) {
    this.arcSegment = null;
    this.strandId = id;
    this.active = id ? this.nextSlot() : null;
    this.view = 'after';
    this.pickingRegion = false;
    this.change(frame);
  }

  selectRegion(id, useCamera) {
    const sameRegion = this.region === id;
    this.region = id;
    this.selectStrand(sameRegion ? this.strandId : this.groupIds[0], useCamera ? this.group.camera : null);
  }

  useSuggestions(ids = [this.strandId]) {
    for (const id of ids) {
      const edit = this.edits[id];
      const missing = pointSlots(this.strands[id],edit).filter(slot => !edit.points[slot.id]);
      if (missing.length) this.checkpoint(id);
      for (const slot of missing) edit.points[slot.id] = {position:slot.suggestion, triangle:slot.triangle, locked:false};
    }
    this.active = null;
    this.pickingRegion = false;
    this.view = 'after';
    this.store();
    this.change();
  }

  checkpoint(id = this.strandId) {
    const stack = this.undoStacks[id];
    stack.push(structuredClone(this.edits[id]));
    if (stack.length > 40) stack.shift();
  }

  editPoint(slot) {
    const mark = this.edit.points[slot.id];
    if (mark?.locked) return this.notify(t('请先解锁这个点，再去模型上重定位。'));
    this.arcSegment = null;
    this.active = slot.id;
    this.pickingRegion = false;
    this.view = 'after';
    this.change();
  }

  place(slot, hit) {
    if (!slot || !hit || !canPlacePoint(slot, hit.position, hit.triangle,this.edit)) {
      if (slot?.moveFaces) {
        if (this.active !== slot.id) this.editPoint(slot);
        const color = this.edit.expanded?.[slot.id] ? '青色或黄色' : '青色';
        this.notify(t(`请把「${slot.label}」放在可见的${color}发面上。遮住时可以换个角度。`));
        return;
      }
      this.notify(t(slot?.extension ? '请点这片头发或靠近它的额前尖端。' :
        '这个位置超出了当前点的发片范围。请在这束头发上点选。'));
      return;
    }
    if (this.edit.points[slot.id]?.locked) return this.notify(t('这个点已锁定。'));
    this.checkpoint();
    this.arcSegment = null;
    this.edit.points[slot.id] = {...hit, locked: false};
    this.active = this.nextSlot() ?? (this.strand.anchorEditing ? slot.id : null);
    this.view = 'after';
    if (this.edit.choice === 'hairdeck' && !this.curves.hairdeck) {
      this.edit.choice = 'after';
      this.notify(t('当前点位与 HairDeck 候选偏差较大，已采用标记后导线。'));
    }
    this.store();
    this.change();
  }

  toggleLock(slot) {
    const point = this.edit.points[slot.id];
    if (!point) return;
    this.checkpoint();
    point.locked = !point.locked;
    if (point.locked && this.active === slot.id) this.active = this.nextSlot();
    this.store();
    this.change();
  }

  toggleThirdBend() {
    if (this.edit.points.bend3?.locked) return this.notify(t('请先解锁第三弯，再改用两个弯位。'));
    this.checkpoint();
    this.edit.thirdBend = !this.edit.thirdBend;
    if (!this.edit.thirdBend) delete this.edit.points.bend3;
    this.active = this.nextSlot();
    this.view = 'after';
    this.store();
    this.change();
  }

  undo() {
    const snapshot = this.undoStacks[this.strandId].pop();
    if (!snapshot) return;
    this.edits[this.strandId] = snapshot;
    this.active = this.nextSlot() ?? this.active;
    this.view = 'after';
    this.store();
    this.change();
  }

  togglePointRange(slot) {
    if (!slot?.extraMoveFaces?.length) return;
    const mark = this.edit.points[slot.id];
    if (mark?.locked) return;
    const expanded = {...this.edit.expanded};
    if (expanded[slot.id]) {
      if (mark && !canPlacePoint(slot,mark.position,mark.triangle)) {
        return this.notify(t('这个点在扩大范围内。先把它移回原范围，或撤销上次移动。'));
      }
      delete expanded[slot.id];
    } else expanded[slot.id] = true;
    this.checkpoint();
    if (Object.keys(expanded).length) this.edit.expanded = expanded;
    else delete this.edit.expanded;
    this.store();
    this.change();
  }

  selectArc(id) {
    this.arcSegment = id;
    this.active = null;
    this.view = 'after';
    this.change();
  }

  setArc(segment, displacement) {
    const previous = this.edit.arcs?.[segment.id] ?? [0,0,0];
    const weight = arcWeight(segment,segment.mid);
    const offset = displacement ? displacement.map((d,i) => previous[i]+d/weight) : [0,0,0];
    const size = Math.hypot(...offset);
    this.checkpoint();
    const arcs = {...this.edit.arcs};
    if (size > 1e-9) arcs[segment.id] = offset.map(d => d * Math.min(1,segment.limit/size));
    else delete arcs[segment.id];
    if (Object.keys(arcs).length) this.edit.arcs = arcs;
    else delete this.edit.arcs;
    this.store();
    this.change();
  }

  body({working, ready, reviewed, generated, assignments}) {
    this.reviewed = reviewed;
    this.assignments = assignments ?? this.suggestedAssignments;
    if (!this.groupIds.includes(this.strandId)) {
      this.strandId = this.groupIds[0];
      this.active = this.strandId ? this.nextSlot() : null;
    }
    const blocks = this.fixture.regions.map(block => {
      const members = this.members(block.id);
      const count = members.filter(id => generated.includes(id)).length;
      const status = members.length ? `${count}/${members.length} 束已生成` : '待提取导线';
      return `<button type="button" class="quiet" data-flow-region="${block.id}" aria-pressed="${block.id === this.region}">
        <span><i style="background:#${block.color.toString(16).padStart(6,'0')}"></i>${block.label}</span>
        <small>${this.reviewed.includes(block.id) ? status : '待确认'}</small></button>`;
    }).join('');
    const regionNav = `<div class="flow-region-tabs" role="group" aria-label="自动分区">${blocks}</div>`;
    if (this.assignmentStrand) {
      const selectedId = this.assignmentStrand;
      const current = this.assignments[selectedId];
      const options = this.fixture.regions.map(block => `<option value="${block.id}"${block.id === this.assignmentTarget ? ' selected' : ''}>${block.label}</option>`).join('');
      const candidates = this.fixture.strands.filter(strand => this.strandPatches[strand.id]?.faces.length)
        .map(strand => `<option value="${strand.id}"${strand.id === selectedId ? ' selected' : ''}>${strand.label}</option>`).join('');
      return `<section class="point-editor" aria-labelledby="pointFlowTitle">
        <h3 id="pointFlowTitle">调整发束归属</h3>
        <p class="subtle">点模型上的发片或从列表选择。黄色显示这一束会一起移动的范围。</p>
        <label class="flow-assignment-field">发束<select id="assignmentStrand">${candidates}</select></label>
        <p class="subtle">当前区块 · ${this.fixture.regions.find(block => block.id === current).label}</p>
        <label class="flow-assignment-field">目标区块<select id="assignmentRegion">${options}</select></label>
        <button type="button" class="primary" id="savePointAssignment" ${working || current === this.assignmentTarget ? 'disabled' : ''}>整束移到目标区块</button>
        <div class="point-actions"><button type="button" class="quiet" id="closePointAssignment">返回分区确认</button></div>
      </section>`;
    }
    if (this.reviewingRegion) {
      const reviewedGroup = this.reviewed.includes(this.region);
      return `<section class="point-editor" aria-labelledby="pointFlowTitle">
        <h3 id="pointFlowTitle">确认自动分区</h3>${regionNav}
        <h4>${this.group.label}</h4>
        <p class="subtle">点选模型上的颜色区块或切换视角，检查当前高亮范围。</p>
        ${Object.keys(this.strandPatches).length ? `<div class="point-actions"><button type="button" class="quiet" id="editPointAssignment" ${working ? 'disabled' : ''}>调整发束归属</button></div>` : ''}
        ${this.groupIds.length ? `<p class="subtle">本区已拟合 ${this.groupIds.length} 束导线。</p>` :
          '<p class="subtle">本区块已划出范围，导线尚待提取。</p>'}
        ${!reviewedGroup ? `<button type="button" class="primary" id="confirmPointRegion" ${working ? 'disabled' : ''}>确认「${this.group.label}」区块</button>` :
          this.groupIds.length ? '<button type="button" class="primary" id="enterPointRegion">进入本组导线</button>' : '<p class="subtle">区块已确认。请选择下一组。</p>'}
      </section>`;
    }
    const curves = this.curves;
    const controls = Object.entries(versions).map(([key, label]) =>
      `<button type="button" class="quiet" data-flow-version="${key}" aria-pressed="${key === this.view}"
        ${curves[key] ? '' : 'disabled'}>${label}</button>`).join('');
    const strands = this.groupIds.map(id => {
      const strand = this.strands[id];
      const {done, total} = this.counts(strand);
      return `<div class="flow-candidate"><button type="button" data-flow-strand="${strand.id}" aria-pressed="${this.strandId === strand.id}">
        ${strand.label}<small>${done}/${total} 个点</small></button><label>
        <input type="checkbox" data-flow-include="${strand.id}" aria-label="将${strand.label}加入 SHP"
          ${this.selectedIds.includes(strand.id) ? 'checked' : ''} ${working ? 'disabled' : ''}>加入 SHP</label></div>`;
    }).join('');
    const rows = this.slots.map((slot, index) => {
      const point = this.edit.points[slot.id];
      return `<li><button type="button" class="point-target quiet" data-flow-target="${slot.id}"
          aria-pressed="${this.active === slot.id}" ${working ? 'disabled' : ''}>
          <span class="point-number">${index + 1}</span><span>${slot.label}<small>${point ?
            (point.locked ? '已锁定' : '已标记 · 可重定位') : '待标记'}</small></span></button>
        <button type="button" class="quiet point-lock" data-flow-lock="${slot.id}"
          aria-label="${point?.locked ? '解锁' : '锁定'}${slot.label}" ${working || !point ? 'disabled' : ''}>${point?.locked ? '解锁' : '锁定'}</button></li>`;
    }).join('');
    const selectedSlot = this.slots.find(slot => slot.id === this.active);
    const expanded = selectedSlot && this.edit.expanded?.[selectedSlot.id] === true;
    const segment = this.segments.find(item => item.id === this.arcSegment);
    const help = selectedSlot
      ? `青色是「${selectedSlot.label}」的可移动发面。${expanded ? '黄色是这次扩大的范围。' : ''}点选新位置或拖动编号。`
      : segment ? `拖动线上的菱形，调整 ${segment.label} 段的弧度。`
      : this.groupIds.length > 1 ? '浅蓝线是同组的其他发束。点当前发束的编号可查看移动范围。'
      : '点编号可查看移动范围。可以拖动未锁定的点，或点击新位置。';
    const count = this.selectedIds.length;
    const groupCount = this.selectedInGroup.length;
    return `<section class="point-editor" aria-labelledby="pointFlowTitle">
      <h3 id="pointFlowTitle">按组确认发流</h3>
      ${regionNav}
      <div class="point-actions"><button id="flowPickRegion" type="button" class="quiet" ${working ? 'disabled' : ''}>查看分区</button></div>
      <p class="point-help subtle" role="status">${help}</p>
      ${selectedSlot?.extraMoveFaces?.length ? `<button type="button" id="flowPointRange" class="quiet" aria-pressed="${expanded}" ${working || this.edit.points[selectedSlot.id]?.locked ? 'disabled' : ''}>${expanded ? '恢复原范围' : '扩大可拖范围'}</button>` : ''}
      ${this.segments.length ? `<div class="point-actions"><label for="flowArcSegment">调整弧度</label>
        <select id="flowArcSegment" ${working ? 'disabled' : ''}><option value="">选一段导线</option>
        ${this.segments.map(item => `<option value="${item.id}" ${item.id === segment?.id ? 'selected' : ''}>${item.label} 段</option>`).join('')}</select>
        ${segment && this.edit.arcs?.[segment.id] ? `<button id="flowArcReset" type="button" class="quiet" ${working ? 'disabled' : ''}>恢复本段弧度</button>` : ''}</div>` : ''}
      <p class="subtle">勾选要加入 SHP 的发束，再点「生成本组 SHP」。</p>
      <div class="point-strands" role="group" aria-label="区域候选发束">${strands}</div>
      ${this.guideReviewSummary?.() ?? ''}
      ${this.guideActions?.(working) ?? ''}
      <p class="subtle">本组勾选 ${groupCount}/${this.groupIds.length} 束 · 共勾选 ${count} 束</p>
      <div class="point-actions"><button id="flowGroupSuggestions" type="button" class="quiet" ${working ? 'disabled' : ''}>勾选本组候选并采用建议点</button></div>
      <ol class="point-targets">${rows}</ol>
      <div class="point-actions">
        ${this.nextSlot() ? `<button id="flowSuggestions" type="button" class="quiet" ${working ? 'disabled' : ''}>采用这束建议点</button>` : ''}
        ${this.strandId === 'curl' ? `<button id="flowThirdBend" type="button" class="quiet" ${working ? 'disabled' : ''}>${this.edit.thirdBend ? '改用两个弯位' : '加入第三弯'}</button>` : ''}
        <button id="flowUndo" type="button" class="quiet" ${working || !this.undoStacks[this.strandId].length ? 'disabled' : ''}>撤销</button>
      </div>
      <div class="point-compare">
        <div class="point-actions" role="group" aria-label="导线对比">${controls}</div>
        ${this.view === 'hairdeck' || this.edit.choice === 'hairdeck' ?
          `<button id="flowChoice" type="button" class="quiet" ${working ? 'disabled' : ''}>${this.edit.choice === 'hairdeck' ?
            '采用标记后导线' : '采用 HairDeck 参考'}</button>` : ''}
        <p class="subtle">${this.edit.choice === 'hairdeck' ? '生成时采用 HairDeck 参考。' : !curves.hairdeck ?
          (this.strand.hairdeck ? '当前点位与已有 HairDeck 候选偏差过大。' :
            this.strandId === 'nape' ? '这束试跑使用粗模导线。' : '这束没有通过匹配的 HairDeck 候选。') :
          '切换对照时保留机位和缩放。'}</p>
      </div>
      <button type="button" class="primary" id="flowGenerateGroup" ${!this.complete(this.selectedInGroup) || working || !ready ? 'disabled' : ''}>
        ${working ? '正在后台生成 SHP…' : `生成本组 SHP${groupCount ? ` · ${groupCount} 束` : ''}`}</button>
      <p class="subtle">${this.complete(this.selectedInGroup) ? '生成本组时保留其他组上次确认的发束。' :
        '勾选本组的发束并标好点，就可以生成。'}</p>
      ${this.surfaceMode ? '' : `<button type="button" class="full quiet" id="flowGenerate" ${!this.complete(this.selectedIds) || working || !ready ? 'disabled' : ''}>
        ${count ? `生成勾选的 ${count} 束 SHP` : '生成勾选发束'}</button>`}
    </section>`;
  }

  bind(root, options) {
    root.querySelectorAll('[data-flow-strand]').forEach(button => {
      button.onclick = () => this.selectStrand(button.dataset.flowStrand);
    });
    root.querySelectorAll('[data-flow-region]').forEach(button => {
      button.onclick = () => this.selectRegion(button.dataset.flowRegion,true);
    });
    root.querySelectorAll('[data-flow-include]').forEach(input => {
      input.onchange = () => {
        const id = input.dataset.flowInclude;
        this.selectedIds = input.checked ? [...this.selectedIds,id] : this.selectedIds.filter(value => value !== id);
        this.store();
        this.change();
      };
    });
    root.querySelectorAll('[data-flow-version]').forEach(button => {
      button.onclick = () => { this.view = button.dataset.flowVersion; this.change(); };
    });
    for (const slot of this.reviewingRegion ? [] : this.slots) {
      root.querySelector(`[data-flow-target="${slot.id}"]`).onclick = () => this.editPoint(slot);
      root.querySelector(`[data-flow-lock="${slot.id}"]`).onclick = () => this.toggleLock(slot);
    }
    const bind = (id, callback) => { const button = root.querySelector('#' + id); if (button) button.onclick = callback; };
    bind('flowPickRegion', () => { this.pickingRegion = true; this.change(); });
    bind('editPointAssignment', () => this.selectAssignment(this.strandId ?? this.fixture.strands[0].id));
    bind('closePointAssignment', () => { this.assignmentStrand = null; this.pickingRegion = true; this.change(); });
    bind('savePointAssignment', () => options.assignStrand(this.assignmentStrand,this.assignmentTarget));
    const candidateSelect = root.querySelector('#assignmentStrand');
    const regionSelect = root.querySelector('#assignmentRegion');
    if (candidateSelect) candidateSelect.onchange = event => this.selectAssignment(event.target.value);
    if (regionSelect) regionSelect.onchange = event => {
      this.assignmentTarget = event.target.value;
      root.querySelector('#savePointAssignment').disabled = this.assignmentTarget === this.assignments[this.assignmentStrand];
    };
    bind('confirmPointRegion', () => options.confirmRegion(this.region));
    bind('enterPointRegion', () => { this.pickingRegion = false; this.change(); });
    bind('flowSuggestions', () => this.useSuggestions());
    bind('flowGroupSuggestions', () => {
      this.selectedIds = [...new Set([...this.selectedIds,...this.groupIds])];
      this.useSuggestions(this.groupIds);
    });
    bind('flowThirdBend', () => this.toggleThirdBend());
    bind('flowUndo', () => this.undo());
    bind('flowPointRange', () => this.togglePointRange(this.slots.find(slot => slot.id === this.active)));
    bind('flowArcReset', () => this.setArc(this.segments.find(item => item.id === this.arcSegment),null));
    const arcSelect = root.querySelector('#flowArcSegment');
    if (arcSelect) arcSelect.onchange = event => this.selectArc(event.target.value || null);
    bind('flowChoice', () => {
      this.checkpoint();
      this.edit.choice = this.edit.choice === 'hairdeck' ? 'after' : 'hairdeck';
      this.view = this.edit.choice;
      this.store();
      this.change();
    });
    bind('flowGenerateGroup', () => options.generate(true));
    bind('flowGenerate', () => options.generate(false));
  }

  show(viewer, working) {
    if (this.assignmentStrand) {
      viewer.setPointFlow(null);
      viewer.showFlowRegions(Object.entries(this.strandPatches).map(([id,surface]) => ({id,surface,
        color:id === this.assignmentStrand ? 0xffda86 : 0x9c9ed0, opacity:id === this.assignmentStrand ? .86 : .35,
      })), working ? null : id => this.selectAssignment(id));
      return;
    }
    if (this.reviewingRegion) {
      viewer.setPointFlow(null);
      const patches = this.fixture.regions.flatMap(block => [block.surface,...this.members(block.id).map(id => this.strandPatches[id])]
        .filter(surface => surface?.faces.length)
        .map(surface => ({...block,surface,opacity:block.id === this.region ? .68 : .30})));
      viewer.showFlowRegions(patches, working ? null : id => this.selectRegion(id,false));
      return;
    }
    viewer.showFlowRegions(null);
    const isEditing = this.view !== 'before' && !working;
    const selected = this.slots.find(slot => slot.id === this.active);
    const curves = this.curves;
    const card = curves[this.view] ?? curves.after;
    const pick = slot => ({
      accepts: (point, triangle) => canPlacePoint(slot, point, triangle,this.edit),
      snap: slot.extension?.edgeSnaps ?? slot.edgeSnaps,
      snapDistance: slot.edgeSnaps ? 12 : undefined,
      onHit: hit => this.place(slot, hit),
    });
    const markers = this.slots.map((slot, index) => {
      const mark = this.edit.points[slot.id];
      return {id: slot.id, label: slot.label, number: index + 1, confirmed: !!mark,
        locked: !!mark?.locked, active: selected?.id === slot.id,
        position: card.seq[slot.index].slice(0, 3),
        drop: isEditing && !mark?.locked ? pick(slot) : null,
        onClick: isEditing ? () => mark ? this.editPoint(slot) : this.place(slot,
          {position: slot.suggestion, triangle: slot.triangle}) : null};
    });
    const segment = isEditing && this.segments.find(item => item.id === this.arcSegment);
    if (segment) markers.push({id:'arc',label:`调整 ${segment.label} 段弧度`,number:'◆',confirmed:true,active:true,
      position:card.seq[segment.mid].slice(0,3),onClick:() => {},dragPlane:delta => this.setArc(segment,delta)});
    const others = this.groupIds.filter(id => id !== this.strandId).map(id => {
      const curves = fitPointFlow(this.strands[id],this.edits[id]);
      return curves[this.edits[id].choice] ?? curves.after;
    });
    viewer.setPointFlow({
      card, color: colors[this.view], surface: this.strand.surface, markers, others, moveFaces:isEditing ? selected?.moveFaces : null,
      extraMoveFaces:isEditing && activeMoveFaces(selected,this.edit) !== selected?.moveFaces ? selected?.extraMoveFaces : null,
      pick: isEditing && selected ? pick(selected) : null,
    });
  }
}
