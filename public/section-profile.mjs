export const sectionStrands = [
  {id: 'sweep', region: 'front', label: '耳上长束', ends: ['额前收束', '后侧接入'], zones: ['额前', '中段', '后侧'], tipAt: 0},
  {id: 'curl', region: 'front', label: '鬓边 S 卷', ends: ['起点', '发梢'], zones: ['根部', '中段', '发梢'], tipAt: 1},
  {id: 'nape', region: 'back', label: '后脑侧下发片', ends: ['扎点下方', '后颈发梢'], zones: ['扎点附近', '中段', '发梢'], tipAt: 1},
  {id: 'nape_opposite', region: 'back', label: '后脑另一侧发片', ends: ['扎点下方', '后颈发梢'], zones: ['扎点附近', '中段', '发梢'], tipAt: 1},
  {id: 'ponytail', region: 'tail', label: '马尾主束', ends: ['马尾扎点', '马尾尖梢'], zones: ['扎点附近', '中段', '发梢'], tipAt: 1},
  {id: 'nape_center', region: 'back', label: '后脑中央发片', ends: ['扎点下方', '后颈发梢'], zones: ['扎点附近', '中段', '发梢'], tipAt: 1},
];
export const defaultStrandIds = ['sweep', 'curl'];

export function generatedStrands(flow) {
  const ids = flow?.selectedIds ?? defaultStrandIds;
  return [...sectionStrands,...(flow?.customStrands ?? [])].filter(strand => ids.includes(strand.id));
}

export const defaultSection = Object.freeze({roundness: 45, from: 32, to: 70, width: 100, thickness: 100});
export const sectionSliderMax = 200;
export const sectionValueMax = 10000;
export const scalpInsetMax = 12;
export const sectionLimits = {roundness:[0, sectionValueMax], from:[0, 96], to:[4, 100],
  width:[0, sectionValueMax], thickness:[0, sectionValueMax]};
export const sectionEnds = ['start','end'];
export const profileShapes = ['four','ellipse'];
export const profileOffsetLimit = 40;
export const endOutlines = ['inherit','block','round'];
export const endSpan = 18;
export const sectionSeamKnots = Object.freeze([0,16,31,47,63,79,91,100]);
export const sectionsFor = (strands, settings) =>
  Object.fromEntries(strands.map(({id}) => [id, settings?.[id] ?? null]));
export const sectionSources = ['original','fitted'];

export function parseSectionPercent(text) {
  const value = text.trim().replace('％','%');
  if (!/^\d+(?:\.\d+)?%?$|^\.\d+%?$/.test(value)) return null;
  const amount = Math.round(value.endsWith('%') ? Number(value.slice(0,-1)) : Number(value)*100);
  return amount <= sectionValueMax ? amount : null;
}

const isScale = value => Number.isInteger(value) && value >= 0 && value <= sectionValueMax;

function validateEnds(ends) {
  if (!ends || typeof ends !== 'object' || Array.isArray(ends) ||
      Object.keys(ends).some(key => !sectionEnds.includes(key))) throw Error('两端截面设置无效。');
  return Object.fromEntries(Object.entries(ends).map(([side, end]) => {
    if (!end || typeof end !== 'object' || Array.isArray(end) ||
        Object.keys(end).some(key => !['width','thickness','outline'].includes(key)) ||
        (end.outline !== undefined && !endOutlines.includes(end.outline)) ||
        ['width','thickness'].some(key => end[key] !== undefined && !isScale(end[key]))) {
      throw Error('两端截面设置无效。');
    }
    return [side,Object.fromEntries(['width','thickness','outline'].filter(key => end[key] !== undefined)
      .map(key => [key,end[key]]))];
  }));
}

export function sectionPlan(strands, saved = {}) {
  const sources = Object.fromEntries(strands.map(({id}) => [id,
    saved.fittedSections?.[id] && saved.sectionSources?.[id] !== 'original' ? 'fitted' : 'original']));
  const overrides = Object.fromEntries(sectionSources.map(source => {
    const fallback = Object.fromEntries(strands.map(({id}) => [id,
      sources[id] === source ? saved.sectionSettings?.[id] : null]));
    return [source,sectionsFor(strands,{...fallback,...saved.sectionOverrides?.[source]})];
  }));
  return {sources,overrides};
}

export function activeSections(strands, sources, overrides, fitted) {
  return {
    settings: Object.fromEntries(strands.map(({id}) => [id,overrides[sources[id]][id]])),
    fitted: Object.fromEntries(strands.filter(({id}) => sources[id] === 'fitted' && fitted?.[id])
      .map(({id}) => [id,fitted[id]])),
  };
}

export function validateSectionPlan(plan, strands, fitted) {
  const ids = new Set(strands.map(({id}) => id));
  if (!plan?.sources || !plan.overrides || Object.keys(plan.sources).length !== ids.size ||
      Object.entries(plan.sources).some(([id,source]) => !ids.has(id) || !sectionSources.includes(source) ||
        (source === 'fitted' && !fitted?.[id]))) throw Error('请为每束发片选择一个可用的截面基准。');
  const overrides = Object.fromEntries(sectionSources.map(source => [
    source,validateSections(plan.overrides[source],strands),
  ]));
  return {sources:Object.fromEntries(strands.map(({id}) => [id,plan.sources[id]])),overrides};
}

export function validateSections(settings, strands) {
  if (!settings || typeof settings !== 'object') throw Error('请选择发束并调整截面。');
  const checked = sectionsFor(strands);
  if (Object.keys(settings).some(id => !Object.hasOwn(checked,id))) throw Error('只能调整本次已生成的发束。');
  for (const {id} of strands) {
    const setting = settings[id];
    if (setting === null) continue;
    if (!setting || (setting.originalOutline !== undefined && typeof setting.originalOutline !== 'boolean') ||
        Object.entries(sectionLimits).some(([key, [min, max]]) =>
      !Number.isInteger(setting[key]) || setting[key] < min || setting[key] > max) || setting.to - setting.from < 4) {
      throw Error('截面数值或选区范围无效。');
    }
    checked[id] = Object.fromEntries(Object.keys(sectionLimits).map(key => [key, setting[key]]));
    if (setting.originalOutline === true) checked[id].originalOutline = true;
    if (setting.ends !== undefined) checked[id].ends = validateEnds(setting.ends);
    if (setting.scalpInset !== undefined) {
      if (!Number.isInteger(setting.scalpInset) || setting.scalpInset < 0 || setting.scalpInset > scalpInsetMax) {
        throw Error('贴头皮端的内嵌深度无效。');
      }
      checked[id].scalpInset = setting.scalpInset;
    }
    if (setting.seamFit !== undefined) {
      const fit = setting.seamFit;
      if (!Array.isArray(fit) || fit.length !== sectionSeamKnots.length || fit.some((pair,i) =>
        !Array.isArray(pair) || pair.length !== 2 || pair.some(value => !Number.isInteger(value) ||
          value < 70 || value > 150 || ((i === 0 || i === fit.length-1) && value !== 100)))) {
        throw Error('发束边缘拟合参数无效。');
      }
      checked[id].seamFit = fit.map(pair => [...pair]);
    }
    if (setting.endsAtSelection !== undefined && typeof setting.endsAtSelection !== 'boolean') {
      throw Error('两端截面的选区设置无效。');
    }
    if (setting.endsAtSelection === true && setting.ends) checked[id].endsAtSelection = true;
    if (setting.profile !== undefined) {
      if (!profileShapes.includes(setting.profile)) throw Error('截面形状无效。');
      checked[id].profile = setting.profile;
    }
    for (const key of ['ridge','balance']) {
      if (setting[key] === undefined) continue;
      if (!Number.isInteger(setting[key]) || Math.abs(setting[key]) > profileOffsetLimit) throw Error('截面偏移无效。');
      checked[id][key] = setting[key];
    }
  }
  return checked;
}

export function sectionStations(card) {
  const arc = [0];
  for (let i = 1; i < card.seq.length; i++) {
    arc.push(arc[i - 1] + Math.hypot(...[0, 1, 2].map(axis => card.seq[i][axis] - card.seq[i - 1][axis])));
  }
  return arc.map((value,i) => i === arc.length-1 ? 100 : 100 * value / arc.at(-1));
}

const smooth = value => {
  const u = Math.max(0, Math.min(1, value));
  return u * u * (3 - 2 * u);
};

function seamScales(fit, percent) {
  if (!fit || percent <= 0 || percent >= 100) return [1,1];
  const hi = sectionSeamKnots.findIndex(knot => knot >= percent);
  const lo = hi-1;
  const mix = smooth((percent-sectionSeamKnots[lo])/(sectionSeamKnots[hi]-sectionSeamKnots[lo]));
  return fit[lo].map((value,side) => (value+(fit[hi][side]-value)*mix)/100);
}

export function regionWeight(percent, from, to) {
  const feather = Math.min(12, (to - from) * .30);
  const start = from === 0 ? 1 : smooth((percent - from) / feather);
  const end = to === 100 ? 1 : smooth((to - percent) / feather);
  return start * end;
}

const shoulders = [[.96,.12],[.62,1],[-.62,1],[-.96,.12],[-.77,-1],[.77,-1]];
const ellipse = Array.from({length: 16}, (_, i) => [Math.cos(i * Math.PI / 8), Math.sin(i * Math.PI / 8)]);
const diamond = ellipse.map(([x,y]) => [x/(Math.abs(x)+Math.abs(y)),y/(Math.abs(x)+Math.abs(y))]);
const squared = (x,y,power) => {
  const scale = (Math.abs(x)**power+Math.abs(y)**power)**(-1/power);
  return [x*scale,y*scale];
};
const block = ellipse.map(([x,y]) => squared(x,y,5));
const cross = ([a,b], [c,d]) => a*d - b*c;

const sampledOutline = points => ellipse.map(ray => {
  for (let i = 0; i < points.length; i++) {
    const a = points[i], b = points[(i + 1) % points.length];
    const edge = [b[0] - a[0], b[1] - a[1]];
    const determinant = cross(ray, edge);
    if (Math.abs(determinant) < 1e-10) continue;
    const r = cross(a, edge) / determinant;
    const along = cross(a, ray) / determinant;
    if (r >= 0 && along >= 0 && along <= 1) return ray.map(value => value * r);
  }
  throw Error('截面轮廓无法采样。');
});
const trapezoid = sampledOutline(shoulders);

function usesFourPoint(setting, fitted) {
  if (setting?.profile) return setting.profile === 'four';
  return !fitted && (!setting || setting.originalOutline);
}

function sectionDimensions(card, index, fitted, fourPoint) {
  if (fitted) return fitted.rings[index];
  const row = card.seq[index];
  const [top,bottom] = fourPoint && card.shape === 'triangle' ? [3,6] : [2,2];
  return [row[3]/2,row[3]/2,row[4]/bottom,row[4]/top,0];
}

export function sectionEndRegion({from,to}, side) {
  const start = side === 'start';
  const boundary = start ? from : to;
  const direction = start ? 1 : -1;
  const span = Math.min(endSpan,(to-from)/2);
  const feather = Math.min(span,5);
  const inside = boundary+direction*span;
  const outside = Math.max(0,Math.min(100,boundary-direction*feather));
  return {boundary,inside,outside,from:Math.min(inside,outside),to:Math.max(inside,outside)};
}

const wholeSection = {from:0,to:100};

function nearestStation(stations, target) {
  return stations.reduce((closest,station,i) =>
    Math.abs(station-target) < Math.abs(stations[closest]-target) ? i : closest,0);
}

function endInfluence(percent, region) {
  if (percent < region.from || percent > region.to) return 0;
  if (percent === region.boundary) return 1;
  const interior = (percent-region.boundary)*(region.inside-region.boundary) > 0;
  const edge = interior ? region.inside : region.outside;
  return 1-smooth(Math.abs((percent-region.boundary)/(edge-region.boundary)));
}

export function endSectionValues(card, setting, fitted, side, range=wholeSection) {
  const stations = sectionStations(card);
  const fourPoint = usesFourPoint(setting,fitted);
  const region = sectionEndRegion(range,side);
  const edge = sectionDimensions(card,nearestStation(stations,region.boundary),fitted,fourPoint);
  const nearby = sectionDimensions(card,nearestStation(stations,region.inside),fitted,fourPoint);
  const width = Math.round(100*(edge[0]+edge[1])/(nearby[0]+nearby[1]));
  const thickness = Math.round(100*(edge[2]+edge[3])/(nearby[2]+nearby[3]));
  const saved = setting?.endsAtSelection || (range.from === 0 && range.to === 100) ? setting?.ends?.[side] : null;
  return {width,thickness,outline:'inherit',...saved};
}

export function sectionOffsets(card, setting, tipAt, stations = sectionStations(card), fitted) {
  const fourPoint = usesFourPoint(setting,fitted);
  // Versions saved before selection-based edits used the physical ends.
  const endRange = setting?.endsAtSelection ? setting : wholeSection;
  const endSettings = sectionEnds.flatMap(side => {
    const edit = setting?.ends?.[side];
    if (!edit) return [];
    const region = sectionEndRegion(endRange,side);
    return [{...edit,region,reference:sectionDimensions(card,nearestStation(stations,region.inside),fitted,fourPoint)}];
  });
  const resample = endSettings.some(end => end.outline && end.outline !== 'inherit');
  const manualFour = setting?.profile === 'four';
  const ridge = manualFour ? (setting.ridge ?? 0)/100 : 0;
  const balance = manualFour ? (setting.balance ?? 0)/100 : 0;
  const corners = [[1,0],[ridge,1],[-1,0],[-ridge,-1]];
  const angular = ridge && resample ? sampledOutline(corners) : diamond;
  const explicitEllipse = setting?.profile === 'ellipse';
  const fullness = (setting?.roundness ?? fitted?.roundness ?? 0)/100;
  const ellipseShape = explicitEllipse
    ? ellipse.map(([x,y]) => squared(x,y,fullness < 1 ? 1.35+.65*fullness : 2+4*(1-Math.exp(-(fullness-1)))))
    : null;
  return card.seq.map((_, i) => {
    const percent = stations[i];
    const weight = setting ? regionWeight(percent, setting.from, setting.to) : 0;
    const widthScale = setting ? 1 + (setting.width / 100 - 1) * weight : 1;
    const thickScale = setting ? 1 + (setting.thickness / 100 - 1) * weight : 1;
    const base = sectionDimensions(card,i,fitted,fourPoint);
    const local = endSettings.find(({region}) => percent > region.from && percent < region.to ||
      percent === region.boundary);
    const blend = local ? endInfluence(percent,local.region) : 0;
    const dimensions = base.map((value,axis) => {
      if (!local || axis === 4) return value;
      const scale = axis < 2 ? local.width : local.thickness;
      return scale === undefined ? value : value*(1-blend)+local.reference[axis]*(scale/100)*blend;
    });
    const [left,right,bottom,top,angle] = dimensions;
    const adjustment = balance * Math.min(bottom,top);
    const fromTip = tipAt === 0 ? percent : 100 - percent;
    const round = 1 - (1 - fullness) * smooth(fromTip / 25);
    let outline = fourPoint ? (resample ? angular : corners) : ellipseShape ?? (round > 1
      ? ellipse.map(([x,y]) => squared(x,y,2+4*(1-Math.exp(-(round-1)))))
      : trapezoid.map((point,j) => point.map((value,axis) => value*(1-round)+ellipse[j][axis]*round)));
    const shape = local?.outline === 'block' ? block : local?.outline === 'round' ? ellipse : null;
    if (shape) outline = outline.map((point,j) => point.map((value,axis) =>
      value*(1-blend)+shape[j][axis]*blend));
    const xs = outline.map(point => point[0]), ys = outline.map(point => point[1]);
    const cos = Math.cos(angle), sin = Math.sin(angle);
    const [leftScale,rightScale] = seamScales(setting?.seamFit,percent);
    if (!fitted && !fourPoint) {
      const xScale = (left+right)*widthScale/(Math.max(...xs)-Math.min(...xs));
      const yScale = (bottom+top)*thickScale/(Math.max(...ys)-Math.min(...ys));
      return outline.map(([x,y]) => [x*xScale*(x < 0 ? leftScale : rightScale),y*yScale]);
    }
    const xMin = -Math.min(...xs), xMax = Math.max(...xs), yMin = -Math.min(...ys), yMax = Math.max(...ys);
    return outline.map(([x,y]) => {
      const u = x * widthScale * (x < 0 ? left*leftScale/xMin : right*rightScale/xMax);
      const v = y * thickScale * (y < 0 ? (bottom-adjustment)/yMin : (top+adjustment)/yMax);
      return [u*cos-v*sin,u*sin+v*cos];
    });
  });
}
