const clamp = (n, low, high) => Math.max(low,Math.min(high,n));
const mix = (a,b,t) => a+(b-a)*t;
const median = values => [...values].sort((a,b) => a-b)[Math.floor(values.length/2)];

function clean(samples, prior, influence) {
  let rejected = 0;
  const measured = samples.map((sample,i) => {
    if (!Number.isFinite(sample) || sample <= 0) return null;
    const neighbors = samples.slice(Math.max(0,i-2),i+3)
      .filter((value,j) => Math.max(0,i-2)+j !== i && Number.isFinite(value) && value > 0);
    if (neighbors.length >= 3) {
      const center = median(neighbors.map(Math.log));
      const deviation = median(neighbors.map(value => Math.abs(Math.log(value)-center)));
      if (Math.abs(Math.log(sample)-center) > Math.max(.17,3.5*deviation)) {
        rejected++;
        return null;
      }
    }
    return sample;
  });
  const last = prior.length-1;
  const retained = measured.filter(value => value !== null).length;
  // The terminal measurements are supplied by the existing end rings. Adjacent
  // sections use the existing fit as a low-confidence prior when no slice survives.
  const target = prior.map((value,i) => i === 0 || i === last || measured[i] === null ?
    Math.log(value) : mix(Math.log(value),Math.log(clamp(measured[i],.62*value,1.6*value)),influence));
  const smoothed = target.map((value,i) => i === 0 || i === last ? value :
    (target[Math.max(0,i-2)]+2*target[i-1]+3*value+2*target[i+1]+target[Math.min(last,i+2)])/9);
  return {target:smoothed,weights:measured.map((value,i) => value !== null && i > 0 && i < last ? 1 : .27),
    rejected, retained};
}

function isotonic(values,weights) {
  const blocks = [];
  for (const [index,value] of values.entries()) {
    blocks.push({from:index,to:index,sum:value*weights[index],weight:weights[index]});
    while (blocks.length > 1) {
      const right = blocks.at(-1), left = blocks.at(-2);
      if (left.sum/left.weight <= right.sum/right.weight) break;
      left.sum += right.sum;
      left.weight += right.weight;
      left.to = right.to;
      blocks.pop();
    }
  }
  return blocks.flatMap(({from,to,sum,weight}) => Array(to-from+1).fill(sum/weight));
}

function fitAtPeak({target,weights},peak) {
  const last = target.length-1, firstValue = target[0], lastValue = target[last];
  if (peak === 0 || peak === last) {
    if (peak === 0 && firstValue < lastValue || peak === last && firstValue > lastValue) return null;
    const middle = target.slice(1,-1), confidence = weights.slice(1,-1);
    const increasing = peak === last;
    if (!increasing) {middle.reverse();confidence.reverse();}
    const fitted = isotonic(middle,confidence).map(value =>
      clamp(value,Math.min(firstValue,lastValue),Math.max(firstValue,lastValue)));
    if (!increasing) fitted.reverse();
    return [firstValue,...fitted,lastValue];
  }
  const before = isotonic(target.slice(1,peak),weights.slice(1,peak));
  const after = isotonic(target.slice(peak+1,last).reverse(),weights.slice(peak+1,last).reverse()).reverse();
  // Every sample in a pool clipped to the peak contributes to the objective
  // at that peak height. This includes pools on both sides.
  let lo = Math.max(firstValue,lastValue), hi = Math.max(lo,target[peak],...before,...after);
  for (let i=0;i<30;i++) {
    const height = (lo+hi)/2;
    let gradient = (height-target[peak])*weights[peak];
    before.forEach((value,j) => {if (value > height) gradient += (height-target[j+1])*weights[j+1];});
    after.forEach((value,j) => {if (value > height) gradient += (height-target[peak+1+j])*weights[peak+1+j];});
    if (gradient > 0) hi = height;
    else lo = height;
  }
  const top = (lo+hi)/2;
  return [firstValue,...before.map(value => clamp(value,firstValue,top)),top,
    ...after.map(value => clamp(value,lastValue,top)),lastValue];
}

// Both dimensions use the same peak so cross-sectional area also has at most one peak.
export function coherentSections(width, thickness, widthPrior, thickPrior, confidence = [.55,.55]) {
  const data = [clean(width,widthPrior,confidence[0]),clean(thickness,thickPrior,confidence[1])];
  const last = width.length-1;
  const stride = Math.max(1,Math.ceil(last/80));
  const peaks = Array.from({length:Math.ceil(last/stride)},(_,i) => i*stride).concat(last);
  let winner;
  for (const peak of peaks) {
    const curves = data.map(input => fitAtPeak(input,peak));
    if (curves.some(curve => !curve)) continue;
    const loss = data.reduce((sum,input,j) => sum+input.target.reduce((s,value,i) =>
      s+input.weights[i]*(value-curves[j][i])**2,0),0);
    if (!winner || loss < winner.loss-1e-10) winner = {curves,peak,loss};
  }
  const flat = (first,lastValue) => Math.abs(first-lastValue)<1e-9;
  const falls = winner.curves.some(curve => !flat(Math.max(...curve),curve[last]));
  const rises = winner.curves.some(curve => !flat(Math.max(...curve),curve[0]));
  return {dimensions:winner.curves.map(curve => curve.map(Math.exp)),
    peak:winner.peak, trend:rises && falls ? 'single-peak' : falls ? 'decreasing' : 'increasing',
    rejected:data.reduce((sum,axis) => sum+axis.rejected,0), retained:data.map(axis => axis.retained)};
}
