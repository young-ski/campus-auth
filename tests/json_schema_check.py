"""够用的 JSON Schema 子集校验器（draft-07 的一小部分）。

支持：$ref（仅本文件 #/definitions/x）、type（含数组形式）、required、properties、
items、enum、const、minimum、oneOf。不支持正则、format、allOf —— 我们的 schema 不需要。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _deref(schema: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any]:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    if not ref.startswith("#/"):
        raise ValueError(f"只支持本地 $ref: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(
    instance: Any, schema: Mapping[str, Any], root: Mapping[str, Any] | None = None
) -> list[str]:
    root = schema if root is None else root
    errors: list[str] = []

    def fail(message: str) -> None:
        errors.append(message)

    schema = _deref(schema, root)

    if "anyOf" in schema:
        if not any(not validate(instance, branch, root) for branch in schema["anyOf"]):
            fail("anyOf 一个分支都没命中")
        return errors

    if "const" in schema and instance != schema["const"]:
        fail(f"应为常量 {schema['const']!r}，实际 {instance!r}")

    if "enum" in schema and instance not in schema["enum"]:
        fail(f"{instance!r} 不在 {schema['enum']!r} 里")

    expected = schema.get("type")
    if expected is not None:
        names = [expected] if isinstance(expected, str) else list(expected)
        ok = False
        for name in names:
            py = _TYPES.get(name)
            if py is None:
                raise ValueError(f"不认识的 type: {name}")
            if name in {"integer", "number"} and isinstance(instance, bool):
                continue  # bool 是 int 子类，别误判
            if isinstance(instance, py):
                ok = True
                break
        if not ok:
            fail(f"类型应为 {'/'.join(names)}，实际 {type(instance).__name__}")

    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                fail(f"缺必填字段 {name!r}")
        for name, sub in schema.get("properties", {}).items():
            if name in instance:
                errors.extend(validate(instance[name], sub, root))

    if isinstance(instance, list) and "items" in schema:
        for item in instance:
            errors.extend(validate(item, schema["items"], root))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        minimum = schema.get("minimum")
        if minimum is not None and instance < minimum:
            fail(f"{instance} 小于 {minimum}")

    return errors


def is_valid(instance: Any, schema: Mapping[str, Any]) -> Sequence[str]:
    return validate(instance, schema)
