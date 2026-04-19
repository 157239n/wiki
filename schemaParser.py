from __future__ import annotations
import ast, inspect, json, re, time, requests, typing, dataclasses, functools, traceback; from typing import Any, Callable, Dict, List, Optional, Union

__all__ = ["toolCatchErr", "function_to_ollama_tool"]

@functools.lru_cache
def toolCatchErr(func: Callable) -> Callable:
    original_signature = inspect.signature(func); original_annotations = dict(getattr(func, "__annotations__", {})); original_defaults = getattr(func, "__defaults__", None); original_kwdefaults = getattr(func, "__kwdefaults__", None)
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try: res = yield from func(*args, **kwargs)
        except Exception as e: return {"resultType": "error", "result": f"{type(e)}\n{e}\n{traceback.format_exc()}", "note": "Is there an error? If yes, think about how to fix it and then go do it"}
        try: res["resultType"]; res["success"] = True; return res
        except: pass
        return {"resultType": f"{type(res).__name__}", "result": res.hex() if type(res) == bytes else res, "success": True}
    wrapper.__signature__ = original_signature; wrapper.__annotations__ = original_annotations; wrapper.__defaults__ = original_defaults; wrapper.__kwdefaults__ = original_kwdefaults; return wrapper

def python_type_to_json_schema(tp: Any) -> Dict[str, Any]:
    origin = typing.get_origin(tp); args = typing.get_args(tp)
    if tp is inspect._empty: return {"type": "string"}
    if tp in (str,): return {"type": "string"}
    if tp in (int,): return {"type": "integer"}
    if tp in (float,): return {"type": "number"}
    if tp in (bool,): return {"type": "boolean"}
    if origin in (list, List): item_type = args[0] if args else str; return { "type": "array", "items": python_type_to_json_schema(item_type), }
    if origin in (dict, Dict): return {"type": "object"}
    if origin is Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and len(non_none) != len(args): schema = python_type_to_json_schema(non_none[0]); schema["nullable"] = True; return schema
        return {"anyOf": [python_type_to_json_schema(a) for a in args]}
    return {"type": "string"}

def parse_docstring(func: Callable) -> Dict[str, Any]: # Very lightweight docstring parser. Supports: summary line & args.name
    doc = inspect.getdoc(func) or ""; lines = doc.splitlines(); summary = ""; arg_docs: Dict[str, str] = {}
    if lines: summary = lines[0].strip()
    in_args = False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped.lower() in ("args:", "arguments:", "params:", "parameters:"): in_args = True; continue
        if in_args:
            if not stripped: continue
            m = re.match(r"^(\w+)\s*:\s*(.+)$", stripped)
            if m: arg_docs[m.group(1)] = m.group(2).strip()
    return { "summary": summary, "arg_docs": arg_docs, }

def function_to_ollama_tool(func: Callable) -> Dict[str, Any]:
    sig = inspect.signature(func); hints = inspect.get_annotations(func, eval_str=True); doc = parse_docstring(func); properties = {}; required = []
    for name, param in sig.parameters.items():
        if name == "env": continue # skip private args
        schema = python_type_to_json_schema(hints.get(name, param.annotation))
        if name in doc["arg_docs"]: schema["description"] = doc["arg_docs"][name]
        properties[name] = schema
        if param.default is inspect._empty: required.append(name)
    return { "type": "function", "function": {
            "name": func.__name__, "description": doc["summary"] or f"Call function {func.__name__}",
            "parameters": { "type": "object", "properties": properties, "required": required } } }



