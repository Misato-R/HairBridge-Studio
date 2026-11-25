import {AsyncLocalStorage} from 'node:async_hooks';
import {getLanguage,normalizeLanguage,setLanguageResolver,t} from '../public/i18n.mjs';
const context=new AsyncLocalStorage();
setLanguageResolver(()=>context.getStore() ?? 'zh');
export const withLanguage=(language,fn)=>context.run(normalizeLanguage(language),fn);
export function projectPackageInstructions() {
  return getLanguage()==='en'
    ? 'Extract the complete project package. Install HairBridge Studio in Blender, then load project.hairbridge from the HairBridge sidebar.\nKeep the assets folder beside the manifest. Install SHP and Surface Hair Curve Tool separately.\n'
    : '解压整个项目包。在 Blender 安装 HairBridge Studio 后，从 HairBridge 面板载入 project.hairbridge。\n保留 assets 文件夹。SHP 与 Surface Hair Curve Tool 需单独安装。\n';
}
export function requestLanguage(request) {
  const url=new URL(request.url,'http://localhost');
  const cookie=/(?:^|;\s*)hairbridge-language=(en|zh)(?:;|$)/.exec(request.headers.cookie ?? '')?.[1];
  const header=request.headers['accept-language']?.split(',')[0];
  return normalizeLanguage(url.searchParams.get('lang') ?? cookie ?? (/^(en|zh)(-|$)/i.test(header ?? '')?header:'zh'));
}
export function setTaskMessage(task,factory,append=false) {
  const previous=task.messages ?? {};
  task.messages=Object.fromEntries(['zh','en'].map(locale=>[locale,
    (append ? previous[locale] ?? task.message ?? '' : '') + withLanguage(locale,factory)]));
  task.language=getLanguage();task.message=task.messages[task.language];
  return task.message;
}
export function localizeTaskView(value) {
  const result=structuredClone(value);
  function visit(item) {
    if (!item || typeof item!=='object')return;
    if (item.messages?.[getLanguage()] && typeof item.message==='string')item.message=item.messages[getLanguage()];
    for(const child of Object.values(item))if(typeof child==='object')visit(child);
  }
  visit(result);return result;
}
