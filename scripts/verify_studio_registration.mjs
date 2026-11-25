// Integration QA with an existing GLB. Does not operate Studio or submit generation.
import {spawnSync} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=process.argv[2];if(!source)throw Error('Pass an existing Tripo GLB path.');
const base=process.env.HAIRBRIDGE_URL||'http://127.0.0.1:8787';
async function post(route,body){const r=await fetch(base+route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const p=await r.json();if(!r.ok)throw Error(p.error);return p;}
let p=await post('/api/demo',{});const route=`/api/projects/${p.id}`;
await post(route+'/review',{step:'reference',note:'Integration QA; existing Rain assets, not new generation.'});
p=await post(route+'/studio-request',{note:'QA only: register an existing Rain Tripo GLB. Do not submit any generation.'});
const result=spawnSync(process.execPath,[path.join(root,'scripts/project.mjs'),'attach-model',p.id,source,p.studioRequests.at(-1).id],{cwd:root,encoding:'utf8',windowsHide:true});
if(result.status!==0)throw Error(result.stderr||result.stdout);
p=await(await fetch(base+route)).json();
if(!p.model||p.studioRequests.at(-1).status!=='registered')throw Error('Model registration not recorded.');
await post(route+'/review',{step:'draft',note:'Integration QA of coarse-model import; not aesthetic acceptance.'});
p=await post(route+'/job',{kind:'blender',requestId:randomUUID()});
console.log(JSON.stringify({projectId:p.id,model:p.model.name,registered:true,blenderJob:p.jobs.at(-1).id,status:p.jobs.at(-1).status},null,2));
