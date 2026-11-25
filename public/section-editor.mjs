import {t,h,msg,getLanguage,setLanguage,translateDOM,taskMessage} from './i18n.mjs';
import {activeSections, defaultSection, endSectionValues, generatedStrands, parseSectionPercent,
  profileOffsetLimit, sectionEndRegion, sectionEnds, sectionOffsets, sectionPlan, sectionSliderMax, sectionSources,
  scalpInsetMax, sectionStations, sectionValueMax} from './section-profile.mjs';

const regionPresets = [[0, 34], [32, 70], [66, 100], [0, 100]];
const controls = {
  roundness: '截面圆润度', from: '选区起点', to: '选区终点', width: '局部宽度', thickness: '局部厚度',
  endWidth: '边界宽度', endThickness: '边界厚度',
  ridge:'脊线横向偏移', balance:'上下厚度分配',
};
const editable = ['roundness','width','thickness','endWidth','endThickness'];
const numericHint = '点数值可输入倍率或百分比，例如 3 或 300%。';
const sectionTrends = {'single-peak':'小 → 大 → 小', increasing:'小 → 大', decreasing:'大 → 小'};

export class SectionEditor {
  constructor(root, paint, apply, close) {
    this.root = root;
    this.paint = paint;
    this.apply = apply;
    this.key = null;
    this.active = 'curl';
    this.endSide = 'start';
    this.showEndRange = false;
    this.live = true;
    root.innerHTML = h(`
      <header class="section-heading"><h3 id="sectionTitle" tabindex="-1">截面调整</h3><button type="button" class="quiet" id="sectionClose">收起</button></header>
      <div class="section-toolbar" role="group" aria-label="选择调整的发束">
        <button type="button" class="quiet" id="sectionCompare">查看已生成</button>
      </div>
      <div class="section-toolbar section-source" id="sectionSource" role="group" aria-label="当前发束的截面基准">
        <span>截面基准</span>
        <button type="button" class="quiet" data-section-source="original">原截面</button>
        <button type="button" class="quiet" data-section-source="fitted">拟合截面</button>
      </div>
      <div class="section-outline">
        <label>截面形状
          <select id="sectionProfile"><option value="">沿用基准</option><option value="four">四点</option><option value="ellipse">椭圆</option></select>
        </label>
        <canvas id="sectionProfilePreview" width="144" height="62" role="img" aria-label="当前截面轮廓"></canvas>
      </div>
      <div class="section-controls">
        <div>
          <div class="section-presets" role="group" aria-label="沿发束选择区间">
            ${regionPresets.map((_,i) => `<button type="button" class="quiet" data-section-zone="${i}"></button>`).join('')}
          </div>
          <div class="section-track" aria-hidden="true"><span></span></div>
          <div class="section-ends"><small id="sectionFromLabel"></small><small id="sectionToLabel"></small></div>
          ${this.slider('from', 0, 96)}${this.slider('to', 4, 100)}
          <p class="subtle" id="sectionRangeHelp"></p>
        </div>
        <div>
          <div id="sectionRoundedControls">
            ${this.slider('roundness')}
            <div class="section-ends"><small>收窄肩部</small><small>100% 椭圆 · 上调使肩部更饱满</small></div>
          </div>
          <div id="sectionFourControls" hidden>
            ${this.slider('ridge',-profileOffsetLimit,profileOffsetLimit)}
            ${this.slider('balance',-profileOffsetLimit,profileOffsetLimit)}
          </div>
          ${this.slider('width')}${this.slider('thickness')}
          <p class="subtle" id="sectionNumericHelp" aria-live="polite">${numericHint}</p>
        </div>
      </div>
      <details class="section-end-editor" id="sectionEndEditor">
        <summary>选区两端截面</summary>
        <div class="section-toolbar" role="group" aria-label="选择选区边界">
          ${sectionEnds.map(side => `<button type="button" class="quiet" data-section-end="${side}"></button>`).join('')}
        </div>
        ${this.slider('endWidth')}${this.slider('endThickness')}
        <label class="section-end-shape">边界轮廓
          <select id="sectionEndOutline"><option value="inherit">沿用基准</option><option value="block">块状圆角</option><option value="round">椭圆</option></select>
        </label>
        <p class="subtle">以选区内侧的截面为 100%，修改在边界附近渐变。</p>
        <div class="section-toolbar">
          <button type="button" class="quiet" id="sectionEndPreset">扎点收紧 · 头皮端加宽</button>
          <button type="button" class="quiet" id="sectionEndReset">恢复这端</button>
        </div>
      </details>
      <div class="section-end-editor" id="scalpInsetControls" hidden>
        <label class="scalp-inset-toggle"><input type="checkbox" id="scalpInsetEnabled">贴头皮端内嵌</label>
        <div class="section-slider" id="scalpInsetDepthControls" hidden>
          <label for="scalpInsetDepth">附加内嵌深度</label><output id="scalpInsetValue"></output>
          <input id="scalpInsetDepth" type="range" min="0" max="${scalpInsetMax}" step="1">
        </div>
        <p class="subtle">以藏住端面为起点，深度以毫米计。位移向前平滑过渡。</p>
      </div>
      <div class="section-footer">
        <button type="button" class="quiet" id="sectionReset" aria-label="恢复这束的四点截面">恢复四点截面</button>
        <button type="button" class="primary" id="sectionApply">后台生成 SHP</button>
      </div>
      <p id="sectionStatus" class="subtle" role="status"></p>`);
    root.querySelector('#sectionClose').onclick = close;
    root.querySelector('#sectionCompare').onclick = () => { this.live = !this.live; this.refresh(); };
    root.querySelectorAll('[data-section-source]').forEach(button => {
      button.onclick = () => {
        this.plan.sources[this.active] = button.dataset.sectionSource;
        this.live = true;
        this.refresh();
      };
    });
    root.querySelectorAll('[data-section-zone]').forEach(button => {
      button.onclick = () => { this.setRange(...regionPresets[Number(button.dataset.sectionZone)]); };
    });
    for (const key of Object.keys(controls)) {
      root.querySelector(`#section-${key}`).oninput = event => this.adjust(key, Number(event.target.value));
    }
    for (const key of editable) {
      const field = root.querySelector(`#section-result-${key}`);
      field.onfocus = () => field.select();
      field.onkeydown = event => {
        if (event.key === 'Enter') {
          event.preventDefault();
          field.blur();
        } else if (event.key === 'Escape') {
          field.value = field.dataset.saved;
          field.blur();
        }
      };
      field.onblur = () => {
        const previous = field.dataset.saved;
        if (field.value !== previous && !this.working) {
          const amount = parseSectionPercent(field.value);
          if (amount !== null) {
            root.querySelector('#sectionNumericHelp').textContent = t(numericHint);
            if (previous !== `${amount}%`) this.adjust(key,amount);
          } else {
            root.querySelector('#sectionNumericHelp').textContent =
              t(`请输入 0% 到 ${sectionValueMax}% 之间的数值。例如 3 或 300%。`);
          }
        }
        field.value = field.dataset.saved;
      };
    }
    root.querySelector('#sectionEndEditor').ontoggle = event => {
      this.showEndRange = event.target.open;
      this.refresh();
    };
    root.querySelectorAll('[data-section-end]').forEach(button => {
      button.onclick = () => {
        this.endSide = button.dataset.sectionEnd;
        this.showEndRange = this.live = true;
        this.refresh();
      };
    });
    root.querySelector('#sectionEndOutline').onchange = event => this.editEnd('outline',event.target.value);
    root.querySelector('#scalpInsetEnabled').onchange = event => this.adjustInset(event.target.checked ? 2 : undefined);
    root.querySelector('#scalpInsetDepth').oninput = event => this.adjustInset(Number(event.target.value));
    root.querySelector('#sectionProfile').onchange = event => {
      const profile = event.target.value;
      const setting = this.settingForEdit();
      if (profile) {
        setting.profile = profile;
        if (profile === 'ellipse' && setting.roundness === this.baseline.roundness) setting.roundness = 100;
      } else {
        delete setting.profile;
        if (this.source === 'original' && setting.roundness === 0) setting.originalOutline = true;
      }
      this.plan.overrides[this.source][this.active] = setting;
      this.live = true;
      this.refresh();
    };
    root.querySelector('#sectionEndReset').onclick = () => this.resetEnd();
    root.querySelector('#sectionEndPreset').onclick = () => {
      const setting = this.settingForEdit();
      setting.endsAtSelection = true;
      setting.ends = {
        start:{width:40,thickness:55,outline:'inherit'},
        end:{width:85,thickness:95,outline:'block'},
      };
      this.plan.overrides[this.source][this.active] = setting;
      this.endSide = 'end';
      this.showEndRange = this.live = true;
      this.refresh();
    };
    root.querySelector('#sectionReset').onclick = () => {
      this.plan.overrides[this.source][this.active] = null;
      this.live = true;
      this.refresh();
    };
    root.querySelector('#sectionApply').onclick = () => this.apply(structuredClone(this.plan));
  }

  slider(key,min=0,max=sectionSliderMax) {
    const value = editable.includes(key)
      ? `<input class="section-value" id="section-result-${key}" type="text" inputmode="decimal" aria-label="${controls[key]}数值" autocomplete="off" spellcheck="false" title="输入倍率或百分比，例如 3 或 300%">`
      : `<output id="section-result-${key}"></output>`;
    return `<div class="section-slider">
      <label id="section-label-${key}" for="section-${key}">${controls[key]}</label>${value}
      <input id="section-${key}" type="range" min="${min}" max="${max}" step="1">
    </div>`;
  }

  setProject(project) {
    const key = `${project.id}:${project.result.id}`;
    if (key === this.key) return;
    this.live = this.key === null;
    this.key = key;
    this.strands = generatedStrands(project.pointFlow);
    if (!this.strands.some(item => item.id === this.active)) this.active = this.strands[0].id;
    this.root.querySelectorAll('[data-section-strand]').forEach(button => button.remove());
    const compare = this.root.querySelector('#sectionCompare');
    for (const strand of this.strands) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'quiet';
      button.dataset.sectionStrand = strand.id;
      button.textContent = t(strand.label);
      button.append(document.createElement('small'));
      button.onclick = () => { this.active = strand.id; this.live = true; this.refresh(); };
      compare.before(button);
    }
    this.fitted = project.result.fittedSections ?? {};
    this.saved = sectionPlan(this.strands,project.result);
    this.plan = structuredClone(this.saved);
    this.ranges = Object.fromEntries(sectionSources.map(source => [source,Object.fromEntries(this.strands.map(({id}) => {
      const {from,to} = this.plan.overrides[source][id] ?? defaultSection;
      return [id,{from,to}];
    }))]));
  }

  get source() { return this.plan.sources[this.active]; }
  get setting() { return this.plan.overrides[this.source][this.active]; }
  get range() { return this.ranges[this.source][this.active]; }
  get previewRange() {
    if (!this.showEndRange) return this.range;
    return sectionEndRegion(this.range,this.endSide);
  }
  get dirty() { return JSON.stringify(this.plan) !== JSON.stringify(this.saved); }
  get activeSections() { return activeSections(this.strands,this.plan.sources,this.plan.overrides,this.fitted); }
  get baseline() {
    const fit = this.source === 'fitted' ? this.fitted[this.active] : null;
    return {...defaultSection,roundness:fit?.roundness ?? 0};
  }

  useOriginal(project) {
    this.setProject(project);
    for (const {id} of this.strands) this.plan.sources[id] = 'original';
    this.live = true;
  }

  setRange(from,to) {
    const moved = this.range.from !== from || this.range.to !== to;
    this.ranges[this.source][this.active] = {from,to};
    if (this.setting) {
      Object.assign(this.setting,this.range);
      if (moved && this.setting.ends) this.setting.endsAtSelection = true;
    }
    this.live = true;
    this.refresh();
  }

  adjust(key, value) {
    if (key === 'endWidth' || key === 'endThickness') {
      return this.editEnd(key === 'endWidth' ? 'width' : 'thickness',value);
    }
    const {from,to} = this.range;
    if (key === 'from') return this.setRange(Math.min(value,to - 4),to);
    if (key === 'to') return this.setRange(from,Math.max(value,from + 4));
    const setting = {...(this.setting ?? this.baseline), ...this.range, [key]:value};
    if (this.source === 'original') {
      if (setting.roundness === 0 && (!this.setting || this.setting.originalOutline || key === 'roundness')) {
        setting.originalOutline = true;
      } else delete setting.originalOutline;
    }
    this.plan.overrides[this.source][this.active] = setting;
    this.showEndRange = false;
    this.live = true;
    this.refresh();
  }

  settingForEdit() {
    return {...this.baseline,...(!this.setting && this.source === 'original' ? {originalOutline:true} : {}),
      ...this.setting,...this.range};
  }

  editEnd(key,value) {
    const setting = this.settingForEdit();
    setting.endsAtSelection = true;
    setting.ends = {...setting.ends,[this.endSide]:{...setting.ends?.[this.endSide],[key]:value}};
    this.plan.overrides[this.source][this.active] = setting;
    this.showEndRange = this.live = true;
    this.refresh();
  }

  resetEnd() {
    const setting = {...this.setting,ends:{...this.setting?.ends}};
    delete setting.ends[this.endSide];
    if (!Object.keys(setting.ends).length) {
      delete setting.ends;
      delete setting.endsAtSelection;
    }
    const baseline = this.baseline;
    const original = this.source !== 'original' || setting.originalOutline === true;
    this.plan.overrides[this.source][this.active] = !setting.ends && !setting.profile && !setting.seamFit &&
      setting.scalpInset === undefined && original &&
      ['width','thickness','roundness'].every(key => setting[key] === baseline[key]) ? null : setting;
    this.showEndRange = this.live = true;
    this.refresh();
  }

  adjustInset(depth) {
    const setting = this.settingForEdit();
    if (depth === undefined) delete setting.scalpInset;
    else setting.scalpInset = depth;
    this.plan.overrides[this.source][this.active] = setting;
    this.live = true;
    this.refresh();
  }

  drawProfile(card,strand,fit) {
    const canvas = this.root.querySelector('#sectionProfilePreview');
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const {width,height} = canvas;
    const stations = sectionStations(card);
    const {from,to} = this.range;
    const target = this.showEndRange ? this.previewRange.boundary : (from+to)/2;
    const index = stations.reduce((best,t,i) => Math.abs(t-target) < Math.abs(stations[best]-target) ? i : best,0);
    const ring = sectionOffsets(card,this.setting,strand.tipAt,stations,fit)[index];
    const span = Math.max(...ring.map(([x,y]) => Math.max(Math.abs(x),Math.abs(y)*width/height)),.00001);
    const scale = (width/2-10)/span;
    const points = ring.map(([x,y]) => [width/2+x*scale,height/2-y*scale]);
    ctx.clearRect(0,0,width,height);
    ctx.strokeStyle = '#4b405a';
    ctx.beginPath();
    ctx.moveTo(6,height/2); ctx.lineTo(width-6,height/2);
    ctx.moveTo(width/2,5); ctx.lineTo(width/2,height-5);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(...points[0]);
    points.slice(1).forEach(point => ctx.lineTo(...point));
    ctx.closePath();
    ctx.fillStyle = '#8263ad88';
    ctx.strokeStyle = '#d1b9f6';
    ctx.fill();
    ctx.stroke();
    if (points.length === 4) for (const point of points) {
      ctx.beginPath();
      ctx.arc(...point,2.6,0,Math.PI*2);
      ctx.fillStyle = '#eadbff';
      ctx.fill();
    }
  }

  refresh() {
    if (this.root.hidden) return;
    const strand = this.strands.find(item => item.id === this.active);
    const fit = this.source === 'fitted' ? this.fitted[this.active] : null;
    const card = this.cards[this.strands.indexOf(strand)];
    const end = endSectionValues(card,this.setting,fit,this.endSide,this.range);
    const state = {...(this.setting ?? this.baseline), ...this.range};
    state.endWidth = end.width;
    state.endThickness = end.thickness;
    state.ridge ??= 0;
    state.balance ??= 0;
    const whole = state.from === 0 && state.to === 100;
    const back = strand.region === 'back';
    const endLabels = back ? ['扎点端','贴头皮端'] : strand.ends;
    const zoneLabels = [...(back ? ['扎点附近','中段','贴头皮附近'] : strand.zones), '整体'];
    const hasFit = Object.keys(this.fitted).length > 0;
    const $ = selector => this.root.querySelector(selector);
    const shape = this.setting?.profile ?? '';
    $('#sectionProfile').value = shape;
    $('#sectionProfile').disabled = this.working;
    $('#sectionFourControls').hidden = shape !== 'four';
    $('#sectionRoundedControls').hidden = shape === 'four';
    $('#section-label-roundness').textContent = t(shape === 'ellipse' ? '椭圆饱满度' : controls.roundness);
    for (const key of Object.keys(controls)) {
      const input = $(`#section-${key}`);
      input.value = Math.min(Number(input.max),state[key]);
      input.disabled = this.working;
      input.setAttribute('aria-valuetext',`${state[key]}%`);
      const field = $(`#section-result-${key}`);
      if (editable.includes(key)) {
        field.disabled = this.working;
        field.dataset.saved = `${state[key]}%`;
        if (field !== document.activeElement) field.value = field.dataset.saved;
      } else field.textContent = t(`${state[key]}%`);
    }
    this.root.querySelectorAll('[data-section-strand]').forEach(button => {
      const id = button.dataset.sectionStrand;
      button.setAttribute('aria-pressed', String(id === this.active));
      const status = button.querySelector('small');
      status.hidden = !hasFit;
      status.textContent = t(this.plan.sources[id] === 'fitted' ? '拟合截面' : '原截面');
    });
    $('#sectionSource').hidden = !hasFit;
    this.root.querySelectorAll('[data-section-source]').forEach(button => {
      const source = button.dataset.sectionSource;
      button.disabled = this.working || (source === 'fitted' && !this.fitted[this.active]);
      button.setAttribute('aria-pressed',String(source === this.source));
    });
    this.root.querySelectorAll('[data-section-zone]').forEach((button, i) => {
      button.textContent = t(zoneLabels[i]);
      button.disabled = this.working;
      button.setAttribute('aria-pressed', String(state.from === regionPresets[i][0] && state.to === regionPresets[i][1]));
    });
    const bar = $('.section-track span');
    bar.style.left = state.from + '%';
    bar.style.width = (state.to - state.from) + '%';
    $('#sectionFromLabel').textContent = t('0% · ' + endLabels[0]);
    $('#sectionToLabel').textContent = t('100% · ' + endLabels[1]);
    $('#sectionRangeHelp').textContent = t(whole ? '宽厚作用于当前整束。' : '青色高亮表示宽厚的作用范围，区间边缘会渐变。');
    $('#section-label-width').textContent = t(whole ? '整体宽度' : controls.width);
    $('#section-label-thickness').textContent = t(whole ? '整体厚度' : controls.thickness);
    $('#sectionCompare').textContent = t(this.live ? '查看已生成' : '查看滑块预览');
    this.root.querySelectorAll('[data-section-end]').forEach((button,i) => {
      button.textContent = t(i === 0 ? `选区起点 · ${state.from}%` : `选区终点 · ${state.to}%`);
      button.disabled = this.working;
      button.setAttribute('aria-pressed',String(button.dataset.sectionEnd === this.endSide));
    });
    $('#sectionEndOutline').value = end.outline;
    $('#sectionEndOutline').disabled = this.working;
    $('#sectionEndPreset').hidden = !back || !whole;
    $('#sectionEndPreset').disabled = this.working;
    $('#sectionEndReset').disabled = this.working || (!whole && !this.setting?.endsAtSelection) ||
      !this.setting?.ends?.[this.endSide];
    const depth = this.setting?.scalpInset;
    $('#scalpInsetControls').hidden = !back || !this.hasScalp;
    $('#scalpInsetEnabled').checked = depth !== undefined;
    $('#scalpInsetEnabled').disabled = this.working;
    $('#scalpInsetDepthControls').hidden = depth === undefined;
    $('#scalpInsetDepth').disabled = this.working;
    $('#scalpInsetDepth').value = depth ?? 2;
    $('#scalpInsetValue').textContent = t(`${depth ?? 2} mm`);
    $('#sectionReset').textContent = t(fit ? '恢复拟合截面' : '恢复四点截面');
    $('#sectionReset').setAttribute('aria-label',t($('#sectionReset').textContent));
    $('#sectionReset').disabled = this.working || !this.setting;
    $('#sectionApply').disabled = this.working || !this.dirty || !this.ready;
    $('#sectionStatus').textContent = t(this.working ? 'Blender 正在后台生成。' : this.dirty
      ? '当前方案尚未生成，可与上一次 SHP 结果对照。'
      : this.setting?.seamFit ? '已联合拟合发束两侧。可继续微调宽度、厚度与截面形状。'
      : fit?.uvFit ? `测量基准为${fit.uvFit.measurement === 'mesh-uv' ? '网格 UV' : '沿导线取样'}。截面趋势为 ${sectionTrends[fit.uvFit.trend]}。`
      : fit ? `宽厚 100% 以粗模拟合尺寸为准。${fit.limited ? '发面样本不足的位置沿用基础估值。' : ''}`
      : this.setting ? '宽厚 100% 以原截面尺寸为准。' : '当前是原始四点截面。可以调整宽度、厚度和圆润度。');
    this.drawProfile(card,strand,fit);
    this.paint();
  }

  show(project, {working,ready,cards}) {
    this.cards = cards;
    this.hasScalp = project.separation?.review?.decision === 'approved' && !!project.separation.head;
    this.setProject(project);
    this.working = working;
    this.ready = ready;
    this.root.hidden = false;
    this.refresh();
  }
}
