"""数据模型的 JSON 导入 / 归一化

设计目标：**用户随手写的 JSON 也能建出模型**。
- 宽松解析：允许 `//` 注释、`/* */` 注释、尾随逗号（手写 JSON 的高频笔误）
- 别名宽容：`key/id/slug/标识`、`fields/columns/字段` 都认
- 类型宽容：`string/字符串/varchar` → `text`，`int/金额/money` → `number` …
- 结构宽容：允许 `{...}`、`{"model":{...},"fields":[...]}`、直接给 `[...]` 字段数组
- 缺省补全：`key`/`name`/`order` 缺失时自动补齐，`select` 缺选项时补空数组
- 一切「猜」出来的改动都进 `warnings`，前端原样展示给用户，不静默吞掉

归一化后的结构就是 `schemas.EntityTypeIn`，可以直接建模型 / 覆盖已有模型。
"""
from __future__ import annotations

import json
import re
from typing import Any

FIELD_TYPES = (
    "text", "textarea", "richtext", "number", "date", "datetime",
    "select", "multiselect", "boolean", "file", "image", "reference",
)

# 需要选项列表的类型
CHOICE_TYPES = ("select", "multiselect")
# 需要目标模型的类型
REF_TYPES = ("reference",)

TYPE_ALIASES: dict[str, str] = {
    # 文本
    "text": "text", "string": "text", "str": "text", "varchar": "text",
    "char": "text", "单行文本": "text", "文本": "text", "字符串": "text",
    # 多行文本
    "textarea": "textarea", "text_area": "textarea", "longtext": "textarea",
    "multiline": "textarea", "多行文本": "textarea", "长文本": "textarea",
    "正文": "textarea", "备注": "textarea", "remark": "textarea",
    # 富文本
    "richtext": "richtext", "rich_text": "richtext", "html": "richtext",
    "富文本": "richtext",
    # 数字
    "number": "number", "num": "number", "int": "number", "integer": "number",
    "float": "number", "double": "number", "decimal": "number",
    "money": "number", "currency": "number", "数字": "number",
    "数值": "number", "金额": "number", "价格": "number",
    # 日期
    "date": "date", "day": "date", "日期": "date",
    "datetime": "datetime", "date_time": "datetime", "timestamp": "datetime",
    "日期时间": "datetime", "时间": "datetime",
    # 选择
    "select": "select", "enum": "select", "radio": "select",
    "single": "select", "single_select": "select", "单选": "select",
    "下拉": "select", "下拉选择": "select",
    "multiselect": "multiselect", "multi_select": "multiselect",
    "multi": "multiselect", "tags": "multiselect", "tag": "multiselect",
    "checkbox": "multiselect", "array": "multiselect", "list": "multiselect",
    "多选": "multiselect", "标签": "multiselect", "多选标签": "multiselect",
    # 布尔
    "boolean": "boolean", "bool": "boolean", "switch": "boolean",
    "布尔": "boolean", "开关": "boolean", "是否": "boolean",
    # 文件
    "file": "file", "files": "file", "attachment": "file",
    "附件": "file", "文件": "file",
    "image": "image", "img": "image", "picture": "image", "photo": "image",
    "图片": "image", "图像": "image",
    # 引用
    "reference": "reference", "ref": "reference", "relation": "reference",
    "foreign": "reference", "foreign_key": "reference", "fk": "reference",
    "link": "reference", "引用": "reference", "外键": "reference",
    "关联": "reference",
}

# 模型级字段别名
MODEL_KEY_ALIASES = ("key", "slug", "identifier", "id", "标识", "键")
MODEL_NAME_ALIASES = ("name", "title", "label", "名称", "模型名", "模型")
MODEL_ICON_ALIASES = ("icon", "图标")
MODEL_DESC_ALIASES = ("description", "desc", "remark", "说明", "描述", "备注")
MODEL_APP_ALIASES = ("app", "application", "应用", "分组")
MODEL_ORDER_ALIASES = ("order", "sort", "seq", "排序", "顺序")
MODEL_FIELDS_ALIASES = ("fields", "columns", "properties", "props", "字段", "字段定义")

# 字段级别名
FIELD_KEY_ALIASES = ("key", "field", "slug", "code", "id", "标识", "字段")
FIELD_NAME_ALIASES = ("name", "label", "title", "名称", "字段名", "显示名")
FIELD_TYPE_ALIASES = ("type", "kind", "datatype", "data_type", "类型")
FIELD_REQUIRED_ALIASES = ("required", "is_required", "must", "必填", "必填项")
FIELD_OPTIONS_ALIASES = ("options", "opt", "config", "配置", "选项配置")
FIELD_CHOICES_ALIASES = ("choices", "enum", "options_list", "values", "选项")
FIELD_TARGET_ALIASES = ("target", "ref", "reference", "to", "指向", "目标", "目标模型")
FIELD_HINT_ALIASES = ("hint", "help", "placeholder", "tip", "提示", "说明")

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ---------------------------------------------------------------- 宽松解析

def _strip_noise(text: str) -> str:
    """去掉注释与尾随逗号（只处理字符串字面量之外的字符）"""
    out: list[str] = []
    mask: list[bool] = []          # True = 该字符在字符串之外（属于语法）
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            mask.append(False)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                mask.append(False)
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            mask.append(False)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        mask.append(True)
        i += 1

    res: list[str] = []
    for idx, ch in enumerate(out):
        if ch == "," and mask[idx]:
            j = idx + 1
            while j < len(out) and out[j].isspace() and mask[j]:
                j += 1
            if j < len(out) and mask[j] and out[j] in "}]":
                continue           # 尾随逗号，丢弃
        res.append(ch)
    return "".join(res)


def loose_loads(text: str) -> Any:
    """宽松的 JSON 解析：失败时抛出带行列的 ValueError"""
    if text is None or not str(text).strip():
        raise ValueError("内容为空，请粘贴 JSON")
    raw = str(text)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    cleaned = _strip_noise(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"JSON 解析失败：第 {e.lineno} 行第 {e.colno} 列 —— {e.msg}"
            f"（已自动忽略注释与尾随逗号，行号以去掉注释后的内容为准）"
        ) from e


# ---------------------------------------------------------------- 小工具

def _pick(raw: dict, aliases) -> Any:
    """按别名顺序取第一个存在的值（大小写不敏感）"""
    if not isinstance(raw, dict):
        return None
    lower = {str(k).lower(): v for k, v in raw.items()}
    for a in aliases:
        if a in raw and raw[a] not in (None, ""):
            return raw[a]
        if a.lower() in lower and lower[a.lower()] not in (None, ""):
            return lower[a.lower()]
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def _to_list(value: Any) -> list[str]:
    """选项可以是列表、逗号分隔字符串、"a/b/c" """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, dict):
        # 支持 {"选项名": 值} 这类写法，取 key
        return [str(k).strip() for k in value.keys() if str(k).strip()]
    s = str(value).strip()
    if not s:
        return []
    parts = re.split(r"[,，/、|]", s)
    return [p.strip() for p in parts if p.strip()]


def slug_key(raw: Any) -> str:
    """把任意文本清洗成合法字段/模型 key"""
    s = _text(raw).lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_{2,}", "_", s).strip("_")
    if not s:
        return ""
    if not KEY_RE.match(s):
        s = "f_" + s
    return s


def normalize_type(raw: Any, warnings: list[str], where: str) -> str:
    t = _text(raw).lower()
    if not t:
        return "text"
    if t in TYPE_ALIASES:
        return TYPE_ALIASES[t]
    warnings.append(f"{where}：无法识别的类型「{raw}」，已按单行文本（text）处理")
    return "text"


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- 主流程

def _split_payload(payload: Any) -> tuple[dict, list]:
    """把入口 payload 拆成 (模型元信息, 字段数组)"""
    if isinstance(payload, str):
        payload = loose_loads(payload)

    if isinstance(payload, list):
        return {}, payload

    if not isinstance(payload, dict):
        raise ValueError("JSON 顶层必须是对象 {...} 或字段数组 [...]")

    # {"model": {...}, "fields": [...]} 包装写法
    inner = payload.get("model") if isinstance(payload.get("model"), dict) else None
    if inner is not None:
        fields = None
        for a in MODEL_FIELDS_ALIASES:
            if a in payload and payload[a] is not None:
                fields = payload[a]
                break
        if fields is None:
            for a in MODEL_FIELDS_ALIASES:
                if a in inner and inner[a] is not None:
                    fields = inner[a]
                    break
        meta = {k: v for k, v in inner.items() if k not in MODEL_FIELDS_ALIASES}
        return meta, (fields if isinstance(fields, list) else [])

    # 直接顶层写法
    fields = None
    for a in MODEL_FIELDS_ALIASES:
        if a in payload and payload[a] is not None:
            fields = payload[a]
            break
    meta = {k: v for k, v in payload.items() if k not in MODEL_FIELDS_ALIASES}
    return meta, (fields if isinstance(fields, list) else [])


def normalize_field(raw: Any, idx: int, used: set[str], warnings: list[str]) -> dict:
    """归一化单个字段定义"""
    where = f"第 {idx + 1} 个字段"

    if isinstance(raw, str):
        raw = {"key": raw, "name": raw, "type": "text"}
    if not isinstance(raw, dict):
        warnings.append(f"{where}：不是对象，已按单行文本处理")
        raw = {}

    options_raw = _pick(raw, FIELD_OPTIONS_ALIASES)
    options: dict = dict(options_raw) if isinstance(options_raw, dict) else {}

    raw_type = _pick(raw, FIELD_TYPE_ALIASES)
    # 兼容 {"type": "select", "choices": [...]} 与 {"type": {"choices": [...]}}
    if isinstance(raw_type, dict):
        options.update(raw_type)
        raw_type = None
    # 顶层直接写 choices / target 也认
    choices = _pick(raw, FIELD_CHOICES_ALIASES)
    if choices is None:
        choices = options.get("choices")
    target = _pick(raw, FIELD_TARGET_ALIASES)
    if target is None:
        target = options.get("target")
    hint = _pick(raw, FIELD_HINT_ALIASES)

    ftype = normalize_type(raw_type, warnings, where)
    name = _text(_pick(raw, FIELD_NAME_ALIASES))
    key_raw = _pick(raw, FIELD_KEY_ALIASES)

    key = slug_key(key_raw) or slug_key(name)
    if not key:
        key = f"field_{idx + 1}"
        if name:
            warnings.append(
                f"{where}：「{name}」没有英文 key（中文名无法自动转写），"
                f"已暂用 {key}，建议手动指定"
            )
        else:
            warnings.append(f"{where}：缺少 key / 名称，已自动命名为 {key}")
    base, n = key, 2
    while key in used:
        key = f"{base}_{n}"
        n += 1
    if key != base:
        warnings.append(f"{where}：key「{base}」重复，已改为「{key}」")
    used.add(key)

    if not name:
        name = key

    clean_options: dict = {}
    if ftype in CHOICE_TYPES:
        lst = _to_list(choices)
        if not lst:
            warnings.append(f"{where}「{name}」是选择类型但没有选项，已置为空选项")
        clean_options["choices"] = lst
    elif ftype in REF_TYPES:
        tgt = _text(target)
        if not tgt:
            warnings.append(f"{where}「{name}」是引用类型但没有指定目标模型（target）")
        clean_options["target"] = tgt
    else:
        # 保留用户自定义的额外配置，但去掉已单独处理的键
        for k, v in options.items():
            if k not in ("choices", "target"):
                clean_options[k] = v
    if hint:
        clean_options["hint"] = _text(hint)

    required_raw = _pick(raw, FIELD_REQUIRED_ALIASES)
    if isinstance(required_raw, str):
        required = required_raw.strip().lower() in ("1", "true", "yes", "y", "是", "必填")
    else:
        required = bool(required_raw)

    return {
        "key": key,
        "name": name,
        "type": ftype,
        "required": required,
        "options": clean_options,
        "order": _to_int(_pick(raw, ("order", "sort", "排序")), idx + 1),
    }


def normalize_model(payload: Any, default_app: str = "default") -> tuple[dict, list[str]]:
    """任意输入 → (EntityTypeIn 结构的 dict, warnings)。

    结构性错误（缺 key、没有字段…）直接抛 ValueError，由路由转成 400。
    """
    warnings: list[str] = []
    meta, fields_raw = _split_payload(payload)

    name = _text(_pick(meta, MODEL_NAME_ALIASES))
    key = slug_key(_pick(meta, MODEL_KEY_ALIASES))
    if not key:
        key = slug_key(name)
    if not key:
        raise ValueError("缺少模型标识 key（英文/数字/下划线），例如 \"key\": \"contract\"")
    if not name:
        name = key
        warnings.append(f"未提供模型名，已用 key「{key}」代替")

    if not isinstance(fields_raw, list) or not fields_raw:
        raise ValueError("没有解析到任何字段，请检查 fields 数组")

    used: set[str] = set()
    fields = [normalize_field(f, i, used, warnings) for i, f in enumerate(fields_raw)]

    model = {
        "key": key,
        "name": name,
        "icon": _text(_pick(meta, MODEL_ICON_ALIASES)) or "Document",
        "description": _text(_pick(meta, MODEL_DESC_ALIASES)),
        "app": _text(_pick(meta, MODEL_APP_ALIASES)) or default_app,
        "order": _to_int(_pick(meta, MODEL_ORDER_ALIASES), 0),
        "fields": fields,
    }
    return model, warnings


def model_to_json(model: dict, indent: int = 2) -> str:
    """模型定义 → JSON 文本（导出让用户编辑）"""
    return json.dumps(model, ensure_ascii=False, indent=indent)


def example_json() -> str:
    """新手模板：第一次打开 JSON 面板时给一份能直接跑的样例"""
    return model_to_json({
        "key": "contract",
        "name": "合同",
        "icon": "Document",
        "description": "采购 / 销售合同台账",
        "app": "default",
        "fields": [
            {"key": "title", "name": "合同名称", "type": "text", "required": True},
            {"key": "code", "name": "合同编号", "type": "text"},
            {"key": "amount", "name": "金额（元）", "type": "number"},
            {"key": "status", "name": "状态", "type": "select",
             "choices": ["草稿", "生效中", "已归档"]},
            {"key": "sign_date", "name": "签订日期", "type": "date"},
            {"key": "owner", "name": "负责人", "type": "text"},
            {"key": "tags", "name": "标签", "type": "multiselect",
             "choices": ["重点", "长期", "续签"]},
            {"key": "files", "name": "合同附件", "type": "file"},
            {"key": "signed", "name": "是否盖章", "type": "boolean"},
            {"key": "remark", "name": "备注", "type": "textarea"},
        ],
    })
