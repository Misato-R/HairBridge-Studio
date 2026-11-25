"""Product language support; object IDs, node names and saved data are unchanged."""
import json
import re
from pathlib import Path
import bpy

_english=json.loads((Path(__file__).parent/'i18n.en.json').read_text(encoding='utf-8'))
_reverse={value.strip():key.strip() for key,value in _english.items()}
_pattern=re.compile('|'.join(re.escape(key) for key in sorted(_english,key=len,reverse=True)))
_protected=re.compile(r'(?:[A-Za-z]:[\\/][^\r\n<>"\']*|https?://[^\s<>"\']+)')

def language():
    scene=getattr(bpy.context,'scene',None)
    return getattr(scene,'hairbridge_language',getattr(scene,'surface_hair_language','en'))

def t(value):
    text=str(value)
    if language()=='zh':
        return _reverse.get(text.strip(),text)
    if text in _english:return _english[text]
    def translate(part):
        part=_pattern.sub(lambda m:_english[m.group()],part)
        return part.translate(str.maketrans({'，':',','。':'.','；':';','：':':','「':'“','」':'”'}))
    result=[];start=0
    for match in _protected.finditer(text):
        result.extend([translate(text[start:match.start()]),match.group()]);start=match.end()
    return ''.join(result)+translate(text[start:])

class LocalizedLayout:
    def __init__(self,layout):object.__setattr__(self,'_layout',layout)
    def __setattr__(self,key,value):setattr(self._layout,key,value)
    def __getattr__(self,key):
        original=getattr(self._layout,key)
        if not callable(original):return original
        def call(*args,**kwargs):
            if 'text' in kwargs:kwargs['text']=t(kwargs['text'])
            elif key=='prop' and len(args)>=2:
                try:kwargs['text']=t(args[0].bl_rna.properties[args[1]].name)
                except (AttributeError,KeyError):pass
            elif key=='operator' and args:
                try:
                    group,name=args[0].split('.')
                    kwargs['text']=t(getattr(getattr(bpy.ops,group),name).get_rna_type().name)
                except (AttributeError,ValueError):pass
            value=original(*args,**kwargs)
            return localized_layout(value) if isinstance(value,bpy.types.UILayout) else value
        return call

def localized_layout(layout):
    return layout if isinstance(layout,LocalizedLayout) else LocalizedLayout(layout)

def redraw(_self,context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:area.tag_redraw()

LANGUAGES=(('en','English','English interface'),('zh','中文','中文界面'))
