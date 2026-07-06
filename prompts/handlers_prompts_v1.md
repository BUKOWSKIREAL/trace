# File Handlers 提示词 — v1

> 用于驱动 AI 生成 `code/core/handlers/{base,text_handler,binary_handler}.py`。
> **版本 v1 — 只实现 P0 三个 handler（base / text / binary 兜底）**。
> 后续 v2 加 docx；v3 加 pptx/xlsx/image。

---

## 完整提示词（直接复制粘贴给 AI 即可）

```
<role>
你是一位有 Python OOP 经验的工程师，熟悉抽象基类、Strategy 设计模式，
理解"开闭原则"（对扩展开放，对修改关闭）。
</role>

<task>
请实现 3 个 Python 文件：
1. core/handlers/base.py 定义抽象基类 FileHandler 和 HandlerRegistry
2. core/handlers/text_handler.py 实现 TextHandler（处理 .py/.txt/.md/.json/.csv）
3. core/handlers/binary_handler.py 实现 BinaryHandler（兜底任意未知/二进制类型）

后续会有 DocxHandler / PptxHandler / ImageHandler 等扩展，所以 base 类的
接口设计必须能容纳多种格式。
</task>

<context>
项目背景：
- 工具叫"Trace"，记录多 AI agent 改的各种文件
- 存储层已经按字节 SHA-256 存 blob（与文件类型无关）
- 但**展示层**（diff、预览）需要按文件类型走不同策略，所以引入 FileHandler

P0 阶段我们只做文本和兜底：
- 文本：能算行级 diff（用 stdlib 的 difflib）
- 二进制兜底：不做内容 diff，只显示"大小变化、hash 变化"

FileHandler 接口契约（最小版）：
    class FileHandler:
        extensions: list[str]   # 该 handler 处理的扩展名，如 ['.py', '.txt']
        
        def extract_text(self, blob: bytes) -> str | None:
            \"\"\"从 blob 字节里提取可比对的文本；二进制 handler 返回 None\"\"\"
        
        def describe_change(self, old_blob: bytes, new_blob: bytes) -> str:
            \"\"\"返回一行人类可读的变更摘要，如 '+12 行 / -3 行' 或
               '大小 1.2KB → 1.5KB, hash 变化'\"\"\"
        
        def render_diff(self, old_blob, new_blob) -> list[tuple[str, str]]:
            \"\"\"返回 [(tag, line)] 列表给 UI 渲染。tag 是 'added'/'removed'/'normal'/'meta'。
               二进制 handler 返回单条 [('meta', '二进制文件，未做内容 diff')]\"\"\"

HandlerRegistry 接口：
    class HandlerRegistry:
        @staticmethod
        def for_path(path: Path) -> FileHandler:
            \"\"\"按扩展名分发；查不到返回 BinaryHandler 兜底\"\"\"
</context>

<constraints>
1. 用 abc.ABC + @abstractmethod 定义基类（Python 标准库写法）
2. TextHandler 的 diff 用 stdlib 的 difflib.ndiff 或 unified_diff
3. 文本解码统一用 utf-8，errors='replace'（避免 UTF-16 等怪文件崩）
4. BinaryHandler.describe_change 输出格式：
   "大小 {old_size} → {new_size}，哈希 {old_hash[:8]} → {new_hash[:8]}"
5. 不要在 handler 里做磁盘 IO（blob 已经是字节，调用者负责加载）
6. HandlerRegistry 必须是"加新类型只改一处"的设计，符合开闭原则
7. 中文注释
8. 不要写 main 块
</constraints>

<example>
TextHandler 处理 '.py' 时，对于：
    old = b"def f():\n    return 1\n"
    new = b"def f():\n    return 2\n"

extract_text(old) 应返回 "def f():\n    return 1\n"
describe_change(old, new) 可返回 "+1 行 / -1 行"
render_diff 大致返回：
    [
        ("normal",  "def f():"),
        ("removed", "    return 1"),
        ("added",   "    return 2"),
    ]

BinaryHandler 处理 '.zip' 时：
extract_text(_) 返回 None
describe_change 返回 "大小 1024 → 2048，哈希 a1b2c3d4 → e5f6g7h8"
render_diff 返回 [("meta", "二进制文件，未做内容 diff")]
</example>

<reasoning>
设计 base 类时，请先想清楚：
- 哪些方法所有 handler 都必须实现（→ @abstractmethod）
- 哪些方法可以有默认实现，子类按需重写（→ 普通方法）
- 是否需要在基类提供工具方法（比如安全 utf-8 解码）让子类复用

如果你发现 render_diff 和 extract_text 之间有重复逻辑（比如都要先解码字节），
请把公共部分提到 base 的辅助方法里。
</reasoning>

<format>
输出 3 个独立文件，每个都带：
- 模块 docstring
- import
- 类定义
- 中文注释

请清楚标明每个文件的开头，例如：
```
# === core/handlers/base.py ===
...

# === core/handlers/text_handler.py ===
...

# === core/handlers/binary_handler.py ===
...
```
</format>

<防幻觉>
- 不要用 difflib.SequenceMatcher 配复杂操作；优先用现成的 ndiff/unified_diff
- 不要编造 abc 模块不存在的功能（abstractmethod、ABC、ABCMeta 都是真的；
  abstractproperty 在新版废弃了，用 @property + @abstractmethod 代替）
- 如果你不确定 difflib 某个 API 的输出格式，请直说"需要查文档"
</防幻觉>
```

---

## 这个提示词的关键设计决策

| 章节 | 设计意图 |
|------|---------|
| `<task>` 第 3 句 | 明示"会有后续 handler"，让 AI 设计基类时考虑可扩展性 |
| `<context>` 接口契约部分 | 把方法签名直接写出来，避免 AI 自己脑补不同的参数名 |
| `<example>` | 用 2 个具体输入输出例子防止 AI 把 render_diff 输出搞成奇形怪状 |
| `<reasoning>` | 引导 AI 思考"哪些必须抽象 / 哪些可以有默认实现"，体现 OOP 抽象层级判断 |

---

## 预期 AI 输出（人工初步审查清单）

应该看到的：
- ✅ base.py 里 FileHandler 用 abc.ABC 继承，关键方法 @abstractmethod
- ✅ TextHandler 有 extensions = ['.py', '.txt', ...] 类属性
- ✅ TextHandler.extract_text 用 .decode('utf-8', errors='replace')
- ✅ BinaryHandler.extract_text 返回 None
- ✅ HandlerRegistry.for_path 用 dict 或 if-elif 分发
- ✅ HandlerRegistry 找不到匹配时返回 BinaryHandler 实例

**人工修正常见点**：
- AI 可能漏 errors='replace' → 文本是 utf-16 时会崩 → 人工补
- AI 可能让 HandlerRegistry 内部 if-elif 写死，导致加新格式要改注册表 → 改为 dict 注册
- AI 可能给 render_diff 用错 tag 名（如 '+' '-' 而非 'added' 'removed'）→ 统一

---

## 迭代历史

- **v1（本版）**：仅 P0 三个 handler（base / text / binary）；P1 起加 docx。
