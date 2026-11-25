import fs from 'node:fs/promises';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {stamp,record} from './project.mjs';

export const exampleRoot=fileURLToPath(new URL('../examples/rain-study/',import.meta.url));
export async function installExample(dataRoot) {
  const manifest=JSON.parse(await fs.readFile(path.join(exampleRoot,'manifest.json'),'utf8'));
  const files=[];
  for(const entry of manifest.files) {
    const source=path.resolve(exampleRoot,entry.file);
    if(!source.startsWith(path.resolve(exampleRoot)+path.sep))throw Error('Invalid example asset path.');
    const bytes=await fs.readFile(source);
    if(bytes.length!==entry.bytes||createHash('sha256').update(bytes).digest('hex')!==entry.sha256)
      throw Error(`Example checksum mismatch: ${entry.file}`);
    files.push({name:entry.file,bytes});
  }
  const template=files.find(file=>file.name==='project.hairbridge');
  if(!template)throw Error('Example project is missing.');
  const p=JSON.parse(template.bytes), oldId=p.id;
  p.id=randomUUID();
  const rewrite=value=>{
    if(typeof value==='string')return value.replaceAll(oldId,p.id);
    if(Array.isArray(value))return value.map(rewrite);
    if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,rewrite(item)]));
    return value;
  };
  const project=rewrite(p);
  project.inputStamp=stamp(project);
  record(project,'Loaded bundled study','Previously reviewed reference, separation and guides. No new generation or final approval.');
  const directory=path.resolve(dataRoot,'projects',project.id);
  await fs.mkdir(path.dirname(directory),{recursive:true});
  await fs.mkdir(directory); // A fresh UUID; never replace an existing project.
  for(const file of files.filter(file=>file.name.startsWith('references/')||file.name.startsWith('assets/'))) {
    const destination=path.resolve(directory,file.name);
    if(!destination.startsWith(directory+path.sep))throw Error('Invalid destination.');
    await fs.mkdir(path.dirname(destination),{recursive:true});
    await fs.writeFile(destination,file.bytes,{flag:'wx'});
  }
  await fs.writeFile(path.join(directory,'project.hairbridge'),JSON.stringify(project,null,2)+'\n',{flag:'wx'});
  return project;
}
