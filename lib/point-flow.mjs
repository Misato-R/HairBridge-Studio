import {t,msg} from '../public/i18n.mjs';
import {setTaskMessage,withLanguage,requestLanguage,localizeTaskView} from './locale.mjs';
import fs from 'node:fs/promises';
import {isDeepStrictEqual} from 'node:util';
import {Triangle, Vector3} from '../public/vendor/three.module.js';
import {canPlacePoint, fitPointFlow, guideSegments, pointSlots} from '../public/point-flow-fit.mjs';
import {approvedSeparation, hash, validateCards} from './project.mjs';
import {defaultStrandIds} from '../public/section-profile.mjs';
import {changeSurfaceStage, editableAnchorRecipe, prepareSurfaceMesh, surfaceStageView} from './surface-flow.mjs';
import {inferCoarseSections} from './coarse-sections.mjs';

const fixturePath = new URL(
  '../examples/rain-study/point-flow-fixture.json',
  import.meta.url,
);
const pilotProjectId = 'd2c1ce91-1a40-4398-bec9-917283553216';
let fixture;
try { fixture = JSON.parse(await fs.readFile(fixturePath, 'utf8')); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
const regionStamp = fixture?.regions ? hash(JSON.stringify([fixture.regions,fixture.strandPatches])) : null;
const suggestedRegions = Object.fromEntries((fixture?.regions ?? []).flatMap(region =>
  region.strandIds.map(id => [id,region.id])));
const surfaceModel = prepareSurfaceMesh(fixture);

export function pointSurfaceStageView(project) {
  return surfaceStageView(project,pointFlowAvailable(project) ? surfaceModel : null);
}

export function fitPointSections(project, cards, strands) {
  if (!project.surfaceFlow?.enabled || !pointFlowAvailable(project)) return {};
  const selected = new Map(strands.map(({id},i) => [id,cards[i]]));
  const tips = new Map(strands.map(({id,tipAt}) => [id,tipAt]));
  const regions = project.pointFlow.strandRegions;
  return Object.assign({},...(project.surfaceFlow.groups ?? []).flatMap(group => {
    if (!group.confirmed || !group.fitKey || !group.guideRecipes.some(({id}) =>
      selected.has(id) && regions?.[id] === group.id)) return [];
    const entries = group.guideRecipes.map(recipe => ({
      id:recipe.id,card:selected.get(recipe.id) ?? recipe.base,tipAt:tips.get(recipe.id),
      include:selected.has(recipe.id) && regions[recipe.id] === group.id,
    }));
    return inferCoarseSections(surfaceModel.triangles,group.faces,entries);
  }));
}

export function pointFlowAvailable(project) {
  return !!fixture && (project.id === pilotProjectId || (project.surfaceFlow?.enabled && !!surfaceModel)) && !!project.approvals.reference &&
    project.model?.sha256 === fixture.modelSha256 &&
    approvedSeparation(project)?.hair.sha256 === fixture.hairSha256 &&
    (!project.cards || project.cards.id === project.pointFlow?.cardsId);
}

export function pointFlowFixture(project) {
  if (!pointFlowAvailable(project)) throw Error(t('发束试跑需要测试2中已审核的原粗模及头发。'));
  if (project.surfaceFlow?.enabled) return {version:fixture.version,modelSha256:fixture.modelSha256,hairSha256:fixture.hairSha256,
    surfaceMesh:surfaceModel.mesh,meshStamp:surfaceModel.stamp,
    selectionHints:surfaceModel.hints.map(({strand,faceIds}) => ({id:strand.id,label:strand.label,faceIds}))};
  return fixture;
}

export function editSurfaceFlow(project, action, payload, location) {
  pointFlowFixture(project);
  return changeSurfaceStage(project,surfaceModel,action,payload,location);
}

function pointRegionReview(project) {
  return project.pointRegionReview?.stamp === regionStamp ? project.pointRegionReview : {stamp:regionStamp,ids:[],moves:{}};
}

export function reviewedPointRegions(project) {
  if (project.surfaceFlow?.enabled) return (project.surfaceFlow.groups ?? []).filter(group => group.confirmed).map(group => group.id);
  return pointFlowAvailable(project) ? pointRegionReview(project).ids : [];
}

export function pointRegionAssignments(project) {
  if (project.surfaceFlow?.enabled) return Object.fromEntries((project.surfaceFlow.groups ?? []).filter(group => group.fitKey)
    .flatMap(group => group.guideRecipes.map(guide => [guide.id,group.id])));
  return pointFlowAvailable(project) ? {...suggestedRegions,...pointRegionReview(project).moves} : {};
}

export function confirmPointRegion(project, payload) {
  const {regions} = pointFlowFixture(project);
  if (payload.revision !== project.revision) throw Error(t('项目已更新，请刷新后检查分区。'));
  const region = regions.find(item => item.id === payload.regionId);
  if (!region) throw Error(t('请选择有效的区块。'));
  const review = pointRegionReview(project);
  if (review.ids.includes(region.id)) return null;
  project.pointRegionReview = {...review,ids:[...review.ids,region.id]};
  return region;
}

export function movePointRegionStrand(project, payload) {
  const {regions,strands,strandPatches} = pointFlowFixture(project);
  if (payload.revision !== project.revision) throw Error(t('项目已更新，请刷新后检查分区。'));
  const strand = strands.find(item => item.id === payload.strandId);
  const destination = regions.find(item => item.id === payload.regionId);
  if (!strand || !strandPatches[strand.id]?.faces.length || !destination) throw Error(t('请选择有效的发束和目标区块。'));
  const sourceId = pointRegionAssignments(project)[strand.id];
  if (sourceId === destination.id) return null;
  const review = pointRegionReview(project);
  const moves = {...review.moves};
  if (suggestedRegions[strand.id] === destination.id) delete moves[strand.id];
  else moves[strand.id] = destination.id;
  project.pointRegionReview = {...review, moves, ids:review.ids.filter(id => id !== sourceId && id !== destination.id)};
  return {strand,destination};
}

function belongsToSurface(surface, mark) {
  const face = mark.triangle * 3;
  if (!Number.isInteger(mark.triangle) || face < 0 || face + 2 >= surface.faces.length) return false;
  const vertices = surface.faces.slice(face, face + 3).map(index =>
    new Vector3(...surface.vertices.slice(index * 3, index * 3 + 3)));
  const target = new Vector3(...mark.position);
  return new Triangle(...vertices).closestPointToPoint(target, new Vector3()).distanceToSquared(target) <= 1e-8;
}

export function resolvePointFlow(project, payload) {
  const {version, modelSha256, hairSha256} = pointFlowFixture(project);
  const trial = project.surfaceFlow?.enabled;
  const regions = trial ? project.surfaceFlow.groups ?? [] : fixture.regions;
  const currentRecipes = trial ? Object.fromEntries(regions.filter(group => group.confirmed && group.fitKey)
    .flatMap(group => group.guideRecipes.map(recipe => [recipe.id,recipe]))) : null;
  const priorRecipes = project.surfaceFlow?.generatedRecipes ?? {};
  const available = trial ? {...priorRecipes,...currentRecipes} : null;
  const strands = trial ? [...fixture.strands,...fixture.surfaceFit.extraGuides].filter(item => available[item.id])
    .concat(Object.values(available).filter(item => item.manual || item.refit)) : fixture.strands;
  if (payload.version !== version || payload.revision !== project.revision) {
    throw Error(t('项目已更新，请刷新页面后检查标记。'));
  }
  if (!payload.strands || typeof payload.strands !== 'object') throw Error(t('请先完成勾选发束的标记。'));
  const ids = payload.selectedIds ?? defaultStrandIds;
  if (!Array.isArray(ids) || !ids.length || new Set(ids).size !== ids.length ||
      ids.some(id => !strands.some(strand => strand.id === id))) throw Error(t('请勾选至少一束有效的候选发束。'));
  const selected = strands.filter(strand => ids.includes(strand.id));
  const reviewed = reviewedPointRegions(project);
  const assignments = pointRegionAssignments(project);
  const existingIds = project.pointFlow?.selectedIds ?? (project.pointFlow ? defaultStrandIds : []);
  const edits = {...project.pointFlow?.edits};
  const acceptedRecipes = {}, strandRegions = {}, customStrands = [];
  const cards = selected.map(original => {
    const input = payload.strands[original.id];
    const groupId = assignments[original.id];
    const useSaved = trial && groupId !== payload.surfaceGroupId && !!priorRecipes[original.id] &&
      existingIds.includes(original.id) && isDeepStrictEqual(input,project.pointFlow?.edits[original.id]);
    const sourceRecipe = trial ? (useSaved ? priorRecipes[original.id] : currentRecipes[original.id]) : original;
    if (!sourceRecipe || (trial && !useSaved && groupId !== payload.surfaceGroupId)) throw Error(t('请先确认选区并拟合本组导线。'));
    const region = regions.find(item => item.id === groupId);
    const strand = trial && !useSaved ? editableAnchorRecipe(surfaceModel,region,sourceRecipe) : sourceRecipe;
    if (!input || !input.points || typeof input.thirdBend !== 'boolean' ||
        !['after', 'hairdeck'].includes(input.choice)) throw Error(msg`请检查${strand.label}的标记和预览。`);
    const state = {thirdBend: strand.id === 'curl' && input.thirdBend, points: {}, choice: input.choice};
    const slots = pointSlots(strand,state);
    if (input.expanded !== undefined) {
      const expanded = Object.entries(input.expanded ?? {});
      if (!input.expanded || typeof input.expanded !== 'object' || Array.isArray(input.expanded) ||
          expanded.some(([id,value]) => value !== true || !slots.some(slot => slot.id === id && slot.extraMoveFaces?.length))) {
        throw Error(msg`${strand.label}的可拖范围无效。`);
      }
      if (expanded.length) state.expanded = Object.fromEntries(expanded);
    }
    if (input.arcs !== undefined) {
      const segments = strand.anchorEditing ? guideSegments(strand,slots) : [];
      const arcs = Object.entries(input.arcs ?? {});
      if (!input.arcs || typeof input.arcs !== 'object' || Array.isArray(input.arcs) || arcs.some(([id,delta]) => {
        const segment = segments.find(item => item.id === id);
        return !segment || !Array.isArray(delta) || delta.length !== 3 || !delta.every(Number.isFinite) ||
          Math.hypot(...delta) > segment.limit+1e-8;
      })) throw Error(msg`${strand.label}的分段弧度无效。`);
      if (arcs.length) state.arcs = Object.fromEntries(arcs);
    }
    for (const slot of slots) {
      const mark = input.points[slot.id];
      if (!mark || typeof mark.locked !== 'boolean' || !canPlacePoint(slot, mark.position, mark.triangle,state) ||
          !belongsToSurface(strand.surface, mark)) throw Error(msg`${strand.label} · 请在发片上标记${slot.label}。`);
      state.points[slot.id] = {position: mark.position, triangle: mark.triangle, locked: mark.locked};
    }
    const unchanged = existingIds.includes(strand.id) && isDeepStrictEqual(state,project.pointFlow?.edits[strand.id]);
    if (!useSaved && !reviewed.includes(groupId) && !unchanged) throw Error(msg`请先在粗模上确认「${region?.label ?? t('当前')}」区块。`);
    const card = useSaved && (strand.manual || strand.refit) && !strand.anchorEditing
      ? fitPointFlow({...strand,manual:false,refit:false},state)[state.choice]
      : fitPointFlow(strand, state)[state.choice];
    if (!card) throw Error(msg`${strand.label}的 HairDeck 候选与当前点位不匹配，请选标记后版本。`);
    edits[strand.id] = state;
    if (trial) {
      acceptedRecipes[strand.id] = strand;
      strandRegions[strand.id] = useSaved ? project.pointFlow.strandRegions[strand.id] : groupId;
      if (strand.manual || strand.refit) customStrands.push({id:strand.id,label:strand.label,region:strandRegions[strand.id],
        ends:[t('起点'),t('发梢')],zones:[t('根部'),t('中段'),t('发梢')],tipAt:1});
    }
    return card;
  });
  validateCards(cards);
  return {cards, edits, selectedIds:selected.map(strand => strand.id), version, modelSha256, hairSha256,
    ...(trial ? {acceptedRecipes,strandRegions,customStrands} : {})};
}
