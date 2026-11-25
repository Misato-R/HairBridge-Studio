import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {t,msg} from '../public/i18n.mjs';
import {withLanguage,setTaskMessage,localizeTaskView,requestLanguage} from '../lib/locale.mjs';

test('language-specific prompts preserve paths, IDs and user-authored content',()=>{
  const task={id:'task-123'};
  const path='C:\\项目\\后脑\\原图.png';
  const note='保留刘海 / keep fringe';
  withLanguage('en',()=>setTaskMessage(task,()=>msg`项目 ${task.id}\n原图 ${path}\n用户反馈 ${note}`));
  assert.match(task.messages.en,/Project task-123/);
  assert.ok(task.messages.en.includes(path));assert.ok(task.messages.en.includes(note));
  assert.match(task.messages.zh,/项目 task-123/);
  const view=withLanguage('zh',()=>localizeTaskView({task}));
  assert.equal(view.task.message,task.messages.zh);
  assert.equal(task.message,task.messages.en,'view changes must not rewrite saved task language');
});

test('simultaneous request languages stay isolated across async work',async()=>{
  const results=await Promise.all(['en','zh'].map(language=>withLanguage(language,async()=>{
    await new Promise(resolve=>setImmediate(resolve));return t('保存项目包');
  })));
  assert.deepEqual(results,['Export project package','保存项目包']);
  assert.equal(requestLanguage({url:'/',headers:{'accept-language':'*'}}),'zh');
  assert.equal(requestLanguage({url:'/',headers:{cookie:'hairbridge-language=en'}}),'en');
});

test('English product copy covers visible source fragments and shared Blender vocabulary',()=>{
  assert.equal(t('7 束导线','en'),'7 guides');
  assert.equal(t('已保存在本机','en'),'Saved locally');
  assert.equal(t('截面调整','en'),'Cross-section controls');
  const catalog=JSON.parse(fs.readFileSync(new URL('../public/locales/en.json',import.meta.url),'utf8'));
  assert.ok(Object.keys(catalog).length>1000);
  assert.ok(Object.values(catalog).every(value=>!/[\u3400-\u9fff]/u.test(value)));
});
