"""Whitelist-only retrieval configuration provenance; never changes configuration."""
import math
import os
from pathlib import Path
import re
import shlex

FIELDS={'SEMANTIC_MIN_SIMILARITY':('min_similarity',.60),'RERANK_MIN_SCORE':('rerank_min_score',.6)}


def thresholds(config):
    result={}
    for name,(attr,default) in FIELDS.items():
        value=getattr(config,attr);raw=os.getenv(name)
        source='code_default' if value==default else 'explicit_settings'
        if raw is not None:
            try:source='process_environment' if float(raw)==value else 'explicit_settings'
            except ValueError:pass
        result[name]={'effective':value,'source':source,'code_default':default}
    return result


def inspect(config,path):
    report=thresholds(config);entries={key:[] for key in FIELDS};path=Path(path)
    if path.is_file():
        for number,line in enumerate(path.read_text().splitlines(),1):
            match=re.match(r'^\s*(?:export\s+)?(SEMANTIC_MIN_SIMILARITY|RERANK_MIN_SCORE)\s*=(.*)$',line)
            if not match:continue
            try:
                parts=shlex.split(match[2],comments=True);value=float(parts[0]) if len(parts)==1 else None
                if value is not None and not math.isfinite(value):value=None
            except ValueError:value=None
            entries[match[1]].append({'line':number,'value':value})
    for name,values in entries.items():
        report[name]['file_entries']=values
        report[name]['file_matches_effective']=values[-1]['value']==report[name]['effective'] if values else None
        report[name]['duplicate_file_entries']=len(values)>1
    return {'thresholds':report,'env_file_present':path.is_file(),
        'precedence':'running container environment > local .env loaded with setdefault > code default',
        'note':'Compose env_file is loaded when the container is created; editing .env does not change a running container. No values were modified.'}
