"""Selected-byte first import only. Cached modules are never reloaded."""
from pathlib import Path
import sys,types,importlib,importlib.util,importlib.machinery,hashlib,json


def freeze(names,output,*,class_methods=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    before={name:dict(cached=name in sys.modules,spec=importlib.util.find_spec(name)) for name in names}
    for item in before.values():
        item['path']=Path(item['spec'].origin);item['bytes']=item['path'].read_bytes()
    codes={}
    class SelectedBytes(importlib.machinery.SourceFileLoader):
        def get_code(self,fullname):
            item=before[fullname]
            # Normal FIRST import executes this exact code, compiled by THIS
            # interpreter. No pyc read/delete, cached-module replacement, or
            # semantic/debug-metadata comparison relaxation.
            code=compile(item['bytes'],str(item['path']),'exec',dont_inherit=True,optimize=sys.flags.optimize)
            codes[fullname]=code;return code
    class SelectedFinder:
        def find_spec(self,fullname,path=None,target=None):
            if fullname not in before or before[fullname]['cached']:return None
            p=str(before[fullname]['path'])
            return importlib.util.spec_from_file_location(fullname,p,loader=SelectedBytes(fullname,p))
    finder=SelectedFinder();sys.meta_path.insert(0,finder)
    try:
        modules={name:importlib.import_module(name) for name in names}
    finally:sys.meta_path.remove(finder)
    results={}
    for name,module in modules.items():
        item=before[name];raw=item['bytes'];path=item['path']
        funcs={k:v for k,v in vars(module).items() if isinstance(v,types.FunctionType) and v.__module__==name}
        expected={c.co_name:c for c in codes[name].co_consts if isinstance(c,types.CodeType)} if name in codes else {}
        # Only explicitly selected methods; do not infer cached class code from
        # the disk file or weaken the exact executed-code identity check.
        for qualified in (class_methods or {}).get(name,()):
            cls_name,method_name=qualified.split('.')
            cls=getattr(module,cls_name,None);function=getattr(cls,method_name,None)
            cls_code=expected.get(cls_name)
            method_code=next((c for c in cls_code.co_consts if isinstance(c,types.CodeType) and c.co_name==method_name),None) if cls_code else None
            if isinstance(function,types.FunctionType) and function.__module__==name:
                funcs[qualified]=function
            else:funcs[qualified]=None
            expected[qualified]=method_code
        same=bool(funcs) and all(v is not None and k in expected and v.__code__ is expected[k] for k,v in funcs.items())
        proven=not item['cached'] and path.read_bytes()==raw and same
        copied=output/path.name
        if proven:copied.write_bytes(raw)
        results[name]=dict(status='FIRST_IMPORT_SOURCE_BYTES_AND_FUNCTION_CODE_MATCH' if proven else 'UNKNOWN_ACTUAL_LOADED_SOURCE_BYTES',
            execution_basis='NORMAL_FIRST_IMPORT_SELECTED_BYTES_CURRENT_INTERPRETER_CODE_OBJECT_IDENTITY_NO_PYC',
            python=sys.version,was_cached_before_boundary=item['cached'],module_file=module.__file__,
            source_pin=None if not proven else dict(path=str(copied.resolve()),sha256=hashlib.sha256(raw).hexdigest()),
            defined_function_code_matches_candidate=same,functions={k:dict(co_filename=v.__code__.co_filename,co_firstlineno=v.__code__.co_firstlineno,identity_scope='SAME_CODE_OBJECT_CONSTANT_FROM_SELECTED_MODULE_COMPILE' if proven else 'UNKNOWN') for k,v in funcs.items() if v is not None})
    (output/'result.json').write_text(json.dumps(results,indent=2)+'\n');return results
