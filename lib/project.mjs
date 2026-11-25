import {t,msg} from '../public/i18n.mjs';
import {setTaskMessage,withLanguage,requestLanguage,localizeTaskView} from './locale.mjs';
import {randomUUID, createHash} from 'node:crypto';
export const now = () => new Date().toISOString();
export const hash = bytes => createHash('sha256').update(bytes).digest('hex');
export const STAGES = ['reference', 'draft', 'review', 'blender', 'finish'];
export const REFERENCE_VIEWS = ['front', 'left', 'right', 'back'];
export const VIEW_LABELS = {front:t('正面'),left:t('左侧'),right:t('右侧'),back:t('背面')};
export function makeProject(name = t('未命名发型')) {
  return {schemaVersion: 1, id: randomUUID(), name: String(name).slice(0,80), revision: 0,
    createdAt: now(), updatedAt: now(), assets: [], reference: null, cards: null,
    model: null, result: null, versions: [], approvals: {}, jobs: [], studioRequests: [], history: []};
}
export function record(p, action, detail = '') {
  p.history.push({at: now(), action, detail}); p.updatedAt = now(); p.revision++;
}
function referenceSources(p) {
  if (p.referenceMode !== 'multiview') return [p.reference?.sha256];
  return [p.sourceReference?.sha256, ...REFERENCE_VIEWS.map(view=>(p.references ?? []).find(asset=>asset.view===view)?.sha256)];
}
export function referenceStamp(p) { return hash(JSON.stringify(referenceSources(p))); }
export const coarseOnly = p => p.entryMode === 'coarse' && !p.sourceReference && !p.reference;
export const separationState = () => ({requests: [], head: null, hair: null, review: null});
export function supersedeSeparationRequests(separation) {
  for (const request of separation.requests) {
    if (request.status === 'awaiting_agent') request.status = 'superseded';
  }
}
export function invalidateSeparation(p) {
  delete p.pointRegionReview;
  if (p.surfaceFlow?.enabled) p.surfaceFlow = {enabled:true};
  if (!p.separation) return;
  supersedeSeparationRequests(p.separation);
  Object.assign(p.separation, {head: null, hair: null, review: null});
}
export function approvedSeparation(p) {
  const separation = p.separation;
  const review = separation?.review;
  if (review?.decision === 'approved' && p.model && p.model.id === review.modelId &&
      p.model.sha256 === review.modelSha256 && referenceStamp(p) === review.referenceStamp &&
      separation.head?.id === review.headId && separation.hair?.id === review.hairId &&
      separation.head && separation.hair) return separation;
  return null;
}
export function stamp(p) {
  const sources = [p.reference?.sha256, p.cards?.sha256, p.model?.sha256];
  if (p.referenceMode === 'multiview') sources.push(...referenceSources(p));
  if (p.flow) sources.push(p.flow.preparedBlend.sha256, ...p.references.map(asset => asset.sha256));
  const separation = approvedSeparation(p);
  if (separation) sources.push('separation', separation.head.sha256, separation.hair.sha256);
  return hash(JSON.stringify(sources));
}
export function requireReview(p, step) {
  if (step === 'reference' && coarseOnly(p)) {
    if (!p.model) throw Error(t('请先上传并检查粗模 GLB。'));
    return;
  }
  if (step === 'reference' && p.referenceMode === 'multiview') {
    if (!p.sourceReference) throw Error(t('请先上传一张原图。'));
    const pending = REFERENCE_VIEWS.filter(view=>{
      const asset = p.references.find(item=>item.view===view);
      return !asset || p.referenceReviews[view]?.assetId !== asset.id;
    });
    if (pending.length) throw Error(msg`请补齐并审核：${pending.map(view=>VIEW_LABELS[view]).join('、')}。`);
  }
  if (step === 'reference' && !p.reference) throw Error(t('请先添加参考图。'));
  if (step === 'draft' && (!p.cards || !p.approvals.reference)) throw Error(t('请先确认参考图并准备导线。'));
  if (step === 'draft' && p.flow?.strands.some(strand => !p.flow.reviews[strand.id]))
    throw Error(t('请先逐束保存发流检查结果。'));
  if (step === 'finish' && (!p.result || !p.approvals.draft)) throw Error(t('请先确认导线并生成 Blender 项目。'));
}
export function versions(p) {
  const list = p.versions ?? [];
  const result = p.result;
  const id = result?.id ?? result?.blend?.id;
  if (!id || list.some(version => version.id === id)) return list;
  // Existing projects saved before version history have one recoverable result.
  return [...list, {...result, id, label:t('已有成果'), approved:p.approvals.finish ?? null}];
}
export function saveResult(p, result, label) {
  p.versions = versions(p);
  p.result = {...result, id:result.blend.id, label, approved:null};
  p.versions.push(p.result);
  delete p.approvals.finish;
}
export function approveResult(p, approval) {
  p.versions = versions(p);
  const active = p.versions.find(version => version.id === (p.result.id ?? p.result.blend.id));
  active.approved = approval;
  p.result = active;
}
export function restoreResult(p, id) {
  if (!p.approvals.draft) throw Error(t('请先确认这一组导线。'));
  p.versions = versions(p);
  const version = p.versions.find(candidate => candidate.id === id && candidate.sourceStamp === stamp(p));
  if (!version) throw Error(t('这版成果与当前输入不匹配。'));
  p.result = version;
  if (version.approved) p.approvals.finish = version.approved;
  else delete p.approvals.finish;
  return version;
}
export function invalidate(p, role) {
  p.versions = versions(p);
  if (['reference', 'reference-view', 'model'].includes(role)) invalidateSeparation(p);
  if (role === 'reference' || role === 'reference-view') {
    p.approvals = {};
    p.cards = null;
    p.model = null;
    delete p.hairdeckPreview;
    for (const request of p.studioRequests) {
      if (request.status === 'awaiting_agent') request.status = 'superseded';
    }
  }
  else { delete p.approvals.draft; delete p.approvals.finish; }
  if (role === 'model' && coarseOnly(p)) {
    delete p.approvals.reference;
    p.cards = null;
  }
  if (role === 'reference') {
    if (p.referenceMode === 'multiview') {
      p.reference = null;
      p.references = [];
      p.referenceReviews = {};
      for (const request of p.referenceRequests) {
        if (request.status === 'awaiting_agent') request.status = 'superseded';
      }
    } else delete p.references;
  }
  delete p.flow;
  delete p.pointFlow;
  p.result = null;
}
export function validateCards(cards) {
  if (!Array.isArray(cards) || cards.length < 1 || cards.length > 2000) throw Error(t('需要非空 HairDeck cards 数组（最多 2000 束）。'));
  let points = 0;
  for (const card of cards) {
    if (!['square','triangle'].includes(card.shape) || !Array.isArray(card.seq) || card.seq.length < 2 || card.seq.length > 10000)
      throw Error(t('发束 shape 或 seq 格式不正确。'));
    let length = 0;
    card.seq.forEach((r,i) => {
      if (!Array.isArray(r) || r.length !== 8 || !r.every(Number.isFinite) || r[3] < 0 || r[4] < 0 || Math.hypot(...r.slice(5)) < 1e-10)
        throw Error(t('发束样本必须包含 8 个有限数值、有效尺寸和方向。'));
      if(i) length += Math.hypot(...r.slice(0,3).map((x,k)=>x-card.seq[i-1][k]));
    });
    if (length < 1e-9) throw Error(t('导线长度为零。'));
    points += card.seq.length;
  }
  if(points > 500000) throw Error(t('导线采样点总数超过限制。'));
  return {count: cards.length, points};
}
export function view(p) {
  const result = structuredClone(p);
  const inputStamp = stamp(p);
  result.referenceStamp = referenceStamp(p);
  result.separation ??= separationState();
  result.versions = structuredClone(versions(p)).map(version => ({...version, restorable:version.sourceStamp === inputStamp}));
  if (result.result && !result.result.id) result.result.id = result.result.blend?.id;
  result.stage = !p.approvals.reference ? 'reference' : p.approvals.finish ? 'finish' : p.approvals.draft ? 'blender' : p.cards ? 'review' : 'draft';
  return result;
}
