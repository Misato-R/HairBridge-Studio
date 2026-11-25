import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {installExample} from '../lib/example.mjs';
const root=fileURLToPath(new URL('../',import.meta.url));
const data=path.resolve(process.env.HAIRBRIDGE_DATA||path.join(root,'data'));
const project=await installExample(data);
console.log(`Installed a fresh study copy: ${path.join(data,'projects',project.id,'project.hairbridge')}`);
console.log(`${process.env.HAIRBRIDGE_URL||'http://127.0.0.1:8787'}/#${project.id}`);
