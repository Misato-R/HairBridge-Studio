import {t,msg} from '../public/i18n.mjs';
import {setTaskMessage,withLanguage,requestLanguage,localizeTaskView} from './locale.mjs';
import {randomUUID} from 'node:crypto';
import {Triangle, Vector3} from '../public/vendor/three.module.js';
import {createManualGuideFitter,minGuideAnchors} from '../public/manual-guide.mjs';
import {surfaceTopology} from '../public/surface-mask-cleanup.mjs';
import {hash} from './project.mjs';

const groups = [
  ['bangs',t('刘海'),'input',0xe0a9f6], ['left',t('左侧发束'),'left',0x88acef],
  ['right',t('右侧发束'),'right',0x8dd6aa], ['crown',t('头顶'),'top',0xefb27d],
  ['back',t('后脑'),'back',0xe47989], ['tail',t('马尾'),'right',0xa8a0f1],
];
const groupDefinition = ([id,label,camera,color]) => ({id,label,camera,color,faces:[],confirmed:false});
const maskHash = faces => hash(JSON.stringify(faces));
const uniqueSorted = values => [...new Set(values)].sort((a,b) => a-b);
const colorOf = index => [0x97d0dc,0xe8cb78,0xdca0b0,0xa9cf91][index % 4];

export function prepareSurfaceMesh(fixture) {
  if (!fixture?.surfaceFit) return null;
  const vertices = [], faces = [], faceKeys = new Map(), vertexKeys = new Map(), owners = [];
  function indexSurface(surface, owner) {
    const remap = [];
    for (let i = 0; i < surface.vertices.length; i += 3) {
      const point = surface.vertices.slice(i,i+3);
      const key = point.join(',');
      if (!vertexKeys.has(key)) {vertexKeys.set(key,vertices.length/3);vertices.push(...point);}
      remap.push(vertexKeys.get(key));
    }
    const picked = [];
    for (let i = 0; i < surface.faces.length; i += 3) {
      const tri = surface.faces.slice(i,i+3).map(index => remap[index]);
      const key = [...tri].sort((a,b) => a-b).join(',');
      if (!faceKeys.has(key)) {
        if (!owner) throw Error(t('拟合范围超出了当前头发网格。'));
        faceKeys.set(key,faces.length/3);faces.push(...tri);owners.push(owner);
      }
      picked.push(faceKeys.get(key));
    }
    return uniqueSorted(picked);
  }
  for (const block of fixture.regions) indexSurface(block.surface,block.id);
  for (const [id,surface] of Object.entries(fixture.strandPatches)) {
    indexSurface(surface,{curl:'bangs',sweep:'right',nape:'back',nape_opposite:'back',ponytail:'tail'}[id]);
  }
  const mesh = {vertices,faces};
  const triangles = [];
  for (let i = 0; i < faces.length; i += 3) triangles.push(new Triangle(...faces.slice(i,i+3)
    .map(index => new Vector3(...vertices.slice(index*3,index*3+3)))));
  const hints = [...fixture.strands,...fixture.surfaceFit.extraGuides].map(strand => {
    const faceIds = indexSurface(fixture.surfaceFit.patches[strand.id]);
    const points = strand.base.seq.map(row => new Vector3(...row));
    const bins = Array.from({length:5},() => []);
    for (const id of faceIds) {
      const center = triangles[id].getMidpoint(new Vector3());
      let nearest = 0;
      for (let i=1;i<points.length;i++) if (center.distanceToSquared(points[i]) < center.distanceToSquared(points[nearest])) nearest=i;
      bins[Math.min(4,Math.floor(nearest*5/points.length))].push(id);
      if (strand.id === 'nape_center') owners[id] = 'back';
    }
    return {strand,faceIds,points,bins};
  });
  return {mesh,triangles,hints,owners,stamp:hash(JSON.stringify(mesh))};
}

function clearConfirmation(group) {
  group.confirmed = false;
  group.fitTask = null;
  group.fitKey = null;
  delete group.refitTask;
}

function checkFaces(values, model) {
  if (!Array.isArray(values) || values.length > model.triangles.length ||
      values.some(id => !Number.isInteger(id) || id < 0 || id >= model.triangles.length)) throw Error(t('选区包含无效的网格面。'));
  return uniqueSorted(values);
}

function propose(model) {
  const list = groups.map(groupDefinition);
  const byId = Object.fromEntries(list.map(group => [group.id,group]));
  model.owners.forEach((owner,id) => {
    if (owner === 'front') owner = model.triangles[id].getMidpoint(new Vector3()).x >= 0 ? 'left' : 'right';
    byId[owner].faces.push(id);
  });
  return list;
}

function nearestHit(model, ids, point) {
  let face = -1, gap = Infinity, hit;
  const candidate = new Vector3();
  for (const id of ids) {
    model.triangles[id].closestPointToPoint(point,candidate);
    const error = candidate.distanceToSquared(point);
    if (error < gap) {face=id;gap=error;hit=candidate.clone();}
  }
  return {face,hit,gap};
}

function patchSurface(model, ids) {
  const map = new Map(), vertices = [], faces = [];
  for (const id of ids) for (const vertex of model.mesh.faces.slice(id*3,id*3+3)) {
    if (!map.has(vertex)) {map.set(vertex,vertices.length/3);vertices.push(...model.mesh.vertices.slice(vertex*3,vertex*3+3));}
    faces.push(map.get(vertex));
  }
  return {vertices,faces};
}

function anchoredRecipe(model, region, guide) {
  if (!Array.isArray(guide.anchors) || guide.anchors.length < minGuideAnchors) throw Error(t('请至少标记三个点。'));
  model.topology ??= surfaceTopology(model.mesh);
  const {card,marks,faceIds,width} = createManualGuideFitter(model.mesh,region.faces,model.topology)(guide.anchors);
  const points = marks.map(({position,triangle,index},i) => {
    const point = new Vector3(...position), closest = new Vector3();
    const moveFaces = faceIds.flatMap((id,local) => model.triangles[id].closestPointToPoint(point,closest)
      .distanceToSquared(point) <= width**2 ? [local] : []);
    return {id:`anchor${i+1}`,index,label:i === 0 ? t('起点') : i === marks.length-1 ? t('发梢') : msg`经过点 ${i}`,
      suggestion:position,triangle:faceIds.indexOf(triangle),moveFaces};
  });
  return {id:guide.id,label:guide.label,base:card,raw:card,points,
    surface:patchSurface(model,faceIds),coverageFaces:faceIds};
}

export function editableAnchorRecipe(model, region, recipe) {
  if (!model || !(recipe.manual || recipe.refit) || !recipe.coverageFaces?.length || recipe.anchorEditing) return recipe;
  model.anchorEdits ??= new Map();
  const key = `${region.fitKey}:${recipe.id}`;
  const cached = model.anchorEdits.get(key);
  if (cached) return cached;
  model.topology ??= surfaceTopology(model.mesh);
  const selected = new Set(region.faces);
  const domain = new Set(recipe.coverageFaces);
  const width = Math.max(...recipe.base.seq.map(row => row[3]));
  const startDirection = new Vector3(...recipe.points[0].suggestion)
    .sub(new Vector3(...recipe.base.seq[8].slice(0,3))).normalize();
  const tipDirection = new Vector3(...recipe.points.at(-1).suggestion)
    .sub(new Vector3(...recipe.base.seq.at(-9).slice(0,3))).normalize();
  const closest = new Vector3(), offset = new Vector3(), aNormal = new Vector3(), bNormal = new Vector3();
  function reachableFaces(slot,index,expanded) {
    const root = index === 0;
    const tip = index === recipe.points.length-1;
    const direction = root ? startDirection : tip ? tipDirection : null;
    const radius = width * (root ? (expanded ? 3 : 2.15) : (expanded ? 1.65 : .86));
    const anchor = new Vector3(...slot.suggestion);
    const seed = recipe.coverageFaces[slot.triangle];
    const reachable = [seed], seen = new Set(reachable);
    for (let i=0;i<reachable.length;i++) {
      const id = reachable[i];
      model.triangles[id].getNormal(aNormal);
      for (const edge of model.topology.neighbors[id]) {
        const next = edge.id;
        const onSelection = selected.has(next);
        if (seen.has(next) || (!onSelection && !(root || tip && expanded))) continue;
        const triangle = model.triangles[next];
        if (aNormal.dot(triangle.getNormal(bNormal)) < .35) continue;
        triangle.closestPointToPoint(anchor,closest);
        offset.subVectors(closest,anchor);
        if (offset.lengthSq() > radius**2) continue;
        if (root || tip && expanded) {
          const forward = offset.dot(direction);
          const lateral = offset.lengthSq()-forward**2;
          const lateralLimit = expanded ? (onSelection ? 1.05 : .72) : (onSelection ? .8 : .62);
          if (forward < (onSelection ? -width*.48 : 0) || lateral > (width*lateralLimit)**2) continue;
        }
        seen.add(next);
        reachable.push(next);
        domain.add(next);
      }
    }
    return [...new Set([...reachable,...slot.moveFaces.map(local => recipe.coverageFaces[local])])];
  }
  const allowances = recipe.points.map((slot,index) => reachableFaces(slot,index,false));
  const expanded = recipe.points.map((slot,index) => reachableFaces(slot,index,true));
  // Keep the original face order as a prefix so saved point marks retain their face IDs.
  const faces = [...domain];
  const map = new Map(faces.map((id,index) => [id,index]));
  const points = recipe.points.map((slot,i) => {
    const normal = new Set(allowances[i]);
    return {...slot,moveFaces:allowances[i].map(id => map.get(id)),
      extraMoveFaces:expanded[i].filter(id => !normal.has(id)).map(id => map.get(id))};
  });
  const updated = {...recipe,points,anchorEditing:true,surface:patchSurface(model,faces)};
  if (model.anchorEdits.size >= 128) model.anchorEdits.clear();
  model.anchorEdits.set(key,updated);
  return updated;
}

function fitHint(model, hint, selected) {
  const ids = hint.faceIds.filter(id => selected.has(id));
  const coverage = ids.length / hint.faceIds.length;
  if (coverage < .12) return null;
  if (coverage < .64 || hint.bins.some(bin => bin.length && bin.filter(id => selected.has(id)).length / bin.length < .35)) {
    return {incomplete:hint.strand.label};
  }
  const recipe = structuredClone(hint.strand);
  // Re-sample the confirmed surface along the full lane, keeping the original
  // inward section offset relative to the measured surface.
  const offsets = hint.points.map(point => {
    const original = nearestHit(model,hint.faceIds,point).hit;
    return nearestHit(model,ids,point).hit.sub(original);
  });
  recipe.base.seq = recipe.base.seq.map((row,i) => {
    const near = offsets.slice(Math.max(0,i-3),i+4);
    const offset = near.reduce((sum,delta) => sum.add(delta),new Vector3()).multiplyScalar(1/near.length);
    return [...hint.points[i].clone().add(offset).toArray(),...row.slice(3)];
  });
  recipe.surface = patchSurface(model,ids);
  recipe.points = recipe.points.map(slot => {
    const {hit,face} = nearestHit(model,ids,new Vector3(...slot.suggestion));
    const moveFaces = ids.flatMap((id,index) => model.triangles[id].closestPointToPoint(hit,new Vector3()).distanceToSquared(hit)
      <= slot.maxMove**2 ? [index] : []);
    return {id:slot.id,label:slot.label,index:slot.index,suggestion:hit.toArray(),triangle:ids.indexOf(face),maxMove:slot.maxMove,moveFaces};
  });
  // The precomputed HairDeck alternative used a different surface constraint.
  delete recipe.hairdeck;
  delete recipe.hairdeckSource;
  return {recipe};
}

function unmatchedFaces(model, group, recipes) {
  const fitted = new Set(recipes.map(recipe => recipe.id));
  const covered = new Set(model.hints.filter(hint => fitted.has(hint.strand.id)).flatMap(hint => hint.faceIds));
  for (const recipe of recipes) for (const id of recipe.coverageFaces ?? []) covered.add(id);
  return group.faces.filter(id => !covered.has(id)).length;
}

function fitGroup(model, group) {
  const mask = new Set(group.faces);
  const results = model.hints.map(hint => fitHint(model,hint,mask)).filter(Boolean);
  for (const manual of group.manualGuides ?? []) {
    try { results.push({recipe:{...anchoredRecipe(model,group,manual),manual:true}}); }
    catch { results.push({incomplete:manual.label}); }
  }
  const guideRecipes = results.flatMap(item => item.recipe ? [item.recipe] : []);
  return {guideRecipes,incomplete:results.flatMap(item => item.incomplete ? [item.incomplete] : []),
    uncovered:unmatchedFaces(model,group,guideRecipes)};
}

export function surfaceStageView(project, model) {
  const state = project.surfaceFlow;
  if (!state?.enabled) return null;
  const {generatedRecipes,...visible} = state;
  if (model && visible.groups) visible.groups = visible.groups.map(group => !group.fitKey ? group : ({...group,
    guideRecipes:group.guideRecipes.map(recipe => editableAnchorRecipe(model,group,recipe)),
  }));
  return visible;
}

export function changeSurfaceStage(project, model, action, payload, location) {
  const state = project.surfaceFlow;
  if (!state?.enabled || !model) throw Error(t('当前项目没有可编辑的头发网格。'));
  const systemAction = ['surface-layout-complete','surface-fit-complete'].includes(action);
  if (!systemAction && payload.revision !== project.revision) throw Error(t('项目已更新，请刷新后重试。'));
  const region = state.groups?.find(group => group.id === payload.regionId);
  const task = (type, extra) => ({id:randomUUID(),type,meshStamp:model.stamp,modelSha256:project.model.sha256,
    hairSha256:project.separation.hair.sha256, status:'pending',...extra});
  const referenceInputs = (project.references ?? []).map(asset => `${asset.view} ${location.file(asset)}`).join('\n');
  const instructions = (pending, goal, command) => msg`${goal}\n项目 ${project.id}\n任务 ${pending.id}\n头发 ${location.file(project.separation.hair)}\n${referenceInputs}\n网格编号校验 ${model.stamp}\n保持同一坐标系。仅处理此任务的输入。\n${location.command} ${command} ${project.id} ${pending.id}`;
  if (action === 'surface-layout-request') {
    if (state.groups) throw Error(t('当前项目已有分区。'));
    if (state.layoutTask?.status === 'pending') return null;
    state.layoutTask = task('layout',{});
    setTaskMessage(state.layoutTask,()=>instructions(state.layoutTask,
      t('请按完整发片和发流为这份已审核的独立头发提出分区。左右以角色自身为准，跨区的长束尽量完整归入一个区块。可新增或删去不适用的区域。'),
      'complete-surface-layout'),false);
    return [t('准备自动分区任务'),''];
  }
  if (action === 'surface-layout-complete') {
    const pending = state.layoutTask;
    if (pending?.status !== 'pending' || pending.id !== payload.taskId || pending.meshStamp !== model.stamp) throw Error(t('分区任务已经更新。'));
    state.groups = propose(model);
    pending.status = 'completed';
    return [t('收到自动分区建议'),msg`${state.groups.length} 个区块`];
  }
  if (!state.groups) throw Error(t('请先完成自动分区。'));
  if (action === 'surface-region-add') {
    const label = String(payload.label ?? '').trim();
    if (!/^[\p{L}\p{N} _-]{1,24}$/u.test(label) || state.groups.length >= 20 || state.groups.some(group => group.label === label)) {
      throw Error(t('请输入 1–24 字的唯一区块名称。'));
    }
    state.groups.push(groupDefinition([`region_${randomUUID()}`,label,'fit',colorOf(state.groups.length)]));
    return [t('新建区块'),label];
  }
  if (!region) throw Error(t('请选择有效的区块。'));
  if (action.startsWith('surface-refit-')) {
    if (!region.confirmed || region.fitKey !== maskHash(region.faces)) throw Error(t('请先确认选区并完成本区导线拟合。'));
    const current = region.refitTask;
    if (action === 'surface-refit-request') {
      if (current) throw Error(t('本区已有重做任务，请先处理或取消。'));
      const note = String(payload.note ?? '').trim().slice(0,1000);
      const previous = region.guideRecipes.filter(guide => !guide.manual).map(({id,label}) => `${label} (${id})`);
      const refit = task('refit',{regionId:region.id,selectionHash:maskHash(region.faces),note});
      setTaskMessage(refit,()=>instructions(refit,
        msg`请重新辨认「${region.label}」选区内的各束发流。依据粗模、四视图和已确认网格选区，沿完整发片从根到梢布置新的导线。\n` +
        msg`现有自动导线 ${previous.length ? previous.join('、') : t('无')}。待辨认面 ${region.uncovered}。\n` +
        msg`用户反馈 ${note || t('检查漏束和走向，按实际可辨认发片调整。')}\n` +
        t('先导出任务网格，检查发梢和斜视角。为每条新增或重画导线提供 3–5 个沿发片排列的 3D 锚点。可以保留走向正确的候选。记录仍无法分离的发流。'),
        'show-surface-refit-request'),false);
      const suffix = msg` ${region.id} "选区网格JSON绝对路径"`;
      setTaskMessage(refit,()=>msg`${suffix}\n选区校验 ${refit.selectionHash}\n` +
        t('方案 JSON 格式 {"taskId":"任务ID","meshStamp":"网格编号校验","selectionHash":"选区校验","retain":["保留的导线ID"],"guides":[{"label":"发束名称","anchors":[{"triangle":全局三角面编号,"position":[x,y,z]}]}],"unresolved":["仍无法分离的发流"]}。\n') +
        t('登记新版供用户对照。\n') + location.command + msg` attach-surface-refit ${project.id} ${refit.id} ${region.id} "重做方案JSON绝对路径"`,true);
      region.refitTask = refit;
      return [t('准备重做导线任务'),region.label];
    }
    if (current?.id !== payload.taskId || !current || current.meshStamp !== model.stamp ||
        current.selectionHash !== maskHash(region.faces) || current.modelSha256 !== project.model.sha256 ||
        current.hairSha256 !== project.separation.hair.sha256) throw Error(t('重做任务已失效，请重新准备。'));
    if (action === 'surface-refit-cancel') {
      delete region.refitTask;
      return [t('取消重做导线'),region.label];
    }
    if (action === 'surface-refit-submit') {
      const {taskId,meshStamp,selectionHash,retain,guides,unresolved = []} = payload.proposal ?? {};
      if (current.status !== 'pending' || taskId !== current.id || meshStamp !== model.stamp ||
          selectionHash !== current.selectionHash) throw Error(t('方案与当前重做任务或选区不匹配。'));
      const original = new Map(region.guideRecipes.filter(guide => !guide.manual).map(guide => [guide.id,guide]));
      if (!Array.isArray(retain) || new Set(retain).size !== retain.length || retain.some(id => !original.has(id)) ||
          !Array.isArray(guides) || !guides.length || guides.length > 50 || !Array.isArray(unresolved) ||
          unresolved.length > 50 || unresolved.some(item => typeof item !== 'string' || !item.trim() || item.length > 120)) {
        throw Error(t('请核对保留导线、新锚点方案和待辨认记录。'));
      }
      const recipes = retain.map(id => original.get(id));
      const labels = new Set([...recipes,...region.guideRecipes.filter(guide => guide.manual)].map(guide => guide.label));
      for (const [index, guide] of guides.entries()) {
        const label = typeof guide?.label === 'string' ? guide.label.trim() : '';
        if (!/^[\p{L}\p{N} _-]{1,40}$/u.test(label) || labels.has(label)) throw Error(t('请为每条新导线使用不同的名称。'));
        labels.add(label);
        recipes.push({...anchoredRecipe(model,region,{id:`refit_${current.id}_${index+1}`,label,anchors:guide.anchors}),refit:true});
      }
      current.proposal = {recipes,unresolved};
      current.status = 'ready';
      return [t('收到重做导线'),msg`${region.label} · ${recipes.length} 束待审核`];
    }
    if (action === 'surface-refit-adopt') {
      if (current.status !== 'ready') throw Error(t('等待重做结果返回。'));
      const manual = region.guideRecipes.filter(guide => guide.manual);
      const active = new Set(manual.map(guide => guide.id));
      const incompleteManual = (region.manualGuides ?? []).filter(guide => !active.has(guide.id)).map(guide => guide.label);
      region.guideRecipes = [...current.proposal.recipes,...manual];
      region.incomplete = [...current.proposal.unresolved,...incompleteManual];
      region.uncovered = unmatchedFaces(model,region,region.guideRecipes);
      delete region.refitTask;
      return [t('采用重做导线'),msg`${region.label} · ${region.guideRecipes.length} 束`];
    }
  }
  if (action === 'surface-manual-guide-add' || action === 'surface-manual-guide-remove') {
    if (!region.confirmed || region.fitKey !== maskHash(region.faces)) throw Error(t('请先确认选区并完成本区导线拟合。'));
    const guides = region.manualGuides ?? [];
    if (action === 'surface-manual-guide-remove') {
      const guide = guides.find(item => item.id === payload.guideId);
      if (!guide) throw Error(t('这条补画导线已移除。'));
      region.manualGuides = guides.filter(item => item !== guide);
      region.guideRecipes = region.guideRecipes.filter(item => item.id !== guide.id);
      region.incomplete = region.incomplete.filter(label => label !== guide.label);
      region.uncovered = unmatchedFaces(model,region,region.guideRecipes);
      return [t('移除补画导线'),guide.label];
    }
    if (!/^manual_[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(payload.guideId) ||
        state.groups.some(group => group.manualGuides?.some(item => item.id === payload.guideId))) throw Error(t('导线编号无效或已登记。'));
    const usedLabels = new Set(guides.map(item => item.label));
    let number = 1;
    while (usedLabels.has(msg`${region.label}补线 ${number}`)) number++;
    const guide = {id:payload.guideId,label:msg`${region.label}补线 ${number}`,anchors:payload.anchors};
    const recipe = {...anchoredRecipe(model,region,guide),manual:true};
    guide.anchors = guide.anchors.map(mark => ({position:mark.position,triangle:mark.triangle}));
    region.manualGuides = [...guides,guide];
    region.guideRecipes.push(recipe);
    region.uncovered = unmatchedFaces(model,region,region.guideRecipes);
    return [t('补画区块导线'),guide.label];
  }
  if (action === 'surface-region-remove') {
    state.groups = state.groups.filter(group => group !== region);
    return [t('移除区块'),region.label];
  }
  if (action === 'surface-region-save') {
    const faces = checkFaces(payload.faces,model);
    if (!faces.length && payload.confirm) throw Error(t('请先选中一片头发表面。'));
    const added = new Set(faces);
    if (maskHash(region.faces) !== maskHash(faces)) clearConfirmation(region);
    for (const other of state.groups.filter(group => group !== region)) {
      const rest = other.faces.filter(id => !added.has(id));
      if (rest.length !== other.faces.length) {other.faces=rest;clearConfirmation(other);}
    }
    region.faces = faces;
    if (payload.confirm === true) region.confirmed = true;
    return [payload.confirm ? t('确认发流选区') : t('编辑发流选区'),region.label];
  }
  if (action === 'surface-fit-request') {
    if (!region.confirmed || !region.faces.length) throw Error(t('请先确认这个选区。'));
    if (region.refitTask) throw Error(t('请先处理本区重做任务。'));
    if (region.fitTask?.status === 'pending') return null;
    region.fitTask = task('fit',{regionId:region.id,selectionHash:maskHash(region.faces)});
    setTaskMessage(region.fitTask,()=>instructions(region.fitTask,
      msg`请拟合「${region.label}」的发束导线。沿根到梢拟合，在当前确认面内估计宽度、厚度和朝向。记录选区未覆盖或暂时无法分离的发流。`,
      'complete-surface-fit'),false);
    setTaskMessage(region.fitTask,()=>msg` ${region.id}\n选区校验 ${region.fitTask.selectionHash}`,true);
    return [t('准备区块导线任务'),region.label];
  }
  if (action === 'surface-fit-complete') {
    const pending = region.fitTask;
    if (region.refitTask || !region.confirmed || pending?.id !== payload.taskId || pending.status !== 'pending' ||
        pending.meshStamp !== model.stamp || pending.selectionHash !== maskHash(region.faces)) throw Error(t('区块已修改，请准备新任务。'));
    const result = fitGroup(model,region);
    // A straddling guide can belong to only one confirmed selection.
    for (const guide of result.guideRecipes) if (state.groups.some(group => group !== region && group.fitKey &&
      group.guideRecipes?.some(item => item.id === guide.id))) throw Error(t('候选发束归属冲突，请检查选区。'));
    Object.assign(region,result,{fitKey:pending.selectionHash});
    pending.status = 'completed';
    return [t('收到区块导线'),msg`${region.label} · ${region.guideRecipes.length} 束`];
  }
  throw Error(t('未知分区操作。'));
}
