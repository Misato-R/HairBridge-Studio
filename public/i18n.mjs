import english from './locales/en.json' with {type:'json'};

export const languageKey = 'hairbridge:language';
export function normalizeLanguage(value) { return /^zh(?:-|$)/i.test(value ?? '') ? 'zh' : 'en'; }
let language = typeof document === 'undefined' ? 'zh' : 'en';
let resolver = () => language;
export function setLanguageResolver(callback) { resolver = callback; }
export const getLanguage = () => normalizeLanguage(resolver());
const escapeRegExp = value => value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
const keys = Object.keys(english).sort((a,b)=>b.length-a.length);
const chinese = new Map(Object.entries(english).map(([source,target])=>[target.trim(),source.trim()]));
const pattern = new RegExp(keys.map(escapeRegExp).join('|'),'gu');
const protectedText = /(?:[A-Za-z]:[\\/][^\r\n<>"']*|https?:\/\/[^\s<>"']+|[\p{L}\p{N}_. -]+\.(?:glb|blend|png|jpe?g|webp|json|hairbridge|zip)\b|[a-f0-9]{32,64})/giu;

/** Translate product copy, never paths, URLs, hashes or interpolation values. */
export function t(value, locale=getLanguage()) {
  const text = String(value ?? '');
  if (normalizeLanguage(locale)==='zh') {
    const source=chinese.get(text.trim());
    return source ? text.replace(text.trim(),source) : text;
  }
  if (Object.hasOwn(english,text)) return english[text];
  const include=/^将(.+)加入 SHP$/.exec(text);
  if(include)return `Include ${t(include[1],locale)} in SHP`;
  const lock=/^(锁定|解锁)(.+)$/.exec(text);
  if(lock)return `${lock[1]==='锁定'?'Lock':'Unlock'} ${t(lock[2],locale)}`;
  const reference=/^(上传|重新补)(.+)参考图$/.exec(text);
  if(reference)return `${reference[1]==='上传'?'Upload':'Regenerate'} ${t(reference[2],locale)} reference`;
  const punctuation={'，':', ','。':'. ','；':'; ','：':': ','！':'!','？':'?','、':', ','「':'“','」':'”'};
  const translate = part => part.replace(pattern, key=>english[key]).replace(/[，。；：！？、「」]/g,key=>punctuation[key]).replace(/[^\S\r\n]{2,}/g,' ');
  let result='', offset=0;
  for (const match of text.matchAll(protectedText)) {
    result += translate(text.slice(offset,match.index)) + match[0]; offset=match.index+match[0].length;
  }
  return result+translate(text.slice(offset));
}
export function msg(strings,...values) {
  return strings.reduce((result,part,i)=>result+t(part)+(i<values.length ? String(values[i]) : ''),'');
}
export function taskMessage(task) { return task?.messages?.[getLanguage()] ?? t(task?.message ?? ''); }

const originals = new WeakMap();
const preserve = '.recent-card > span,.asset-row strong,#projectName,pre,code,[data-i18n-preserve="true"]';
export function translateDOM(root, remember=true) {
  const document = root.ownerDocument ?? root;
  const walker = document.createTreeWalker(root,NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  let node;
  while ((node=walker.nextNode())) {
    if (node.nodeType===Node.ELEMENT_NODE) {
      for (const attribute of ['title','aria-label','placeholder','alt']) {
        if (!node.hasAttribute(attribute) || node.closest(preserve)) continue;
        let saved=originals.get(node); if (!saved) {saved={}; if(remember) originals.set(node,saved);}
        const current=node.getAttribute(attribute), previous=saved[attribute];
        const source=previous && current===previous.last ? previous.source : current;
        const translated=t(source);
        if (remember) saved[attribute]={source,last:translated};
        if(current!==translated)node.setAttribute(attribute,translated);
      }
    } else if (node.parentElement && !node.parentElement.closest(`${preserve},script,style,textarea`)) {
      const previous=originals.get(node);
      const source=previous && node.data===previous.last ? previous.source : node.data;
      const translated=t(source);
      if (remember) originals.set(node,{source,last:translated});
      if(node.data!==translated)node.data=translated;
    }
  }
}
let translationQueued=false;
export function h(value) {
  // Retain canonical text on the actual nodes so either language can be restored.
  // This runs after the caller inserts its HTML and before the next browser paint.
  if(typeof document!=='undefined' && !translationQueued){
    translationQueued=true;queueMicrotask(()=>{translationQueued=false;translateDOM(document);});
  }
  return String(value ?? '');
}
export function setLanguage(value) {
  language=normalizeLanguage(value);
  try {localStorage.setItem(languageKey,language);} catch {}
  document.documentElement.lang=language==='zh'?'zh-CN':'en';
  document.cookie=`hairbridge-language=${language}; Path=/; SameSite=Strict`;
  translateDOM(document);
  document.querySelectorAll('[data-language]').forEach(button=>{
    const active=button.dataset.language===language;
    button.setAttribute('aria-pressed',String(active));button.classList.toggle('active',active);
  });
  document.dispatchEvent(new CustomEvent('hairbridge:language',{detail:{language}}));
}
if (typeof document!=='undefined') {
  let saved;try {saved=localStorage.getItem(languageKey);} catch {}
  language=normalizeLanguage(saved ?? 'en');
}
