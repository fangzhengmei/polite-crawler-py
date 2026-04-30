# R4 质量加固报告：URL 规则模块可维护性与鲁棒性增强

**日期**: 2026-04-30  
**变更类型**: 质量加固 - 依赖规则模块增强

---

## 1. 变更概述

本轮 R4 质量加固聚焦于 URL 规则模块的 **可维护性** 与 **鲁棒性**，完成以下目标：

1. **统一判定边界**：明确四类场景的优先级和触发条件
2. **等价输入一致性**：确保不同表达方式的等价输入产生一致结果
3. **异常输入降级处理**：确保异常输入不抛出异常，而是优雅降级
4. **测试覆盖增强**：补充边界测试覆盖新增功能
5. **无新增告警**：确保所有测试全绿且无新增弃用告警

---

## 2. 规则引擎增强

### 2.1 新增核心组件

#### `URLNormalizer` 类 - URL 归一化器

```python
class URLNormalizer:
    """URL normalizer for consistent URL handling."""
    
    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize a URL for consistent handling.
        
        Normalization steps:
        1. Strip leading/trailing whitespace
        2. Remove trailing slash from path (unless path is just "/")
        3. Convert scheme and hostname to lowercase
        """
    
    @staticmethod
    def are_urls_equivalent(url1: str, url2: str) -> bool:
        """Check if two URLs are semantically equivalent after normalization."""
```

**归一化规则**：

| 输入 | 归一化后 | 说明 |
|------|---------|------|
| `https://example.com/page` | `https://example.com/page` | 不变 |
| `https://example.com/page/` | `https://example.com/page` | 移除尾斜杠 |
| `https://example.com` | `https://example.com/` | 根路径添加 `/` |
| `HTTPS://EXAMPLE.COM/PATH` | `https://example.com/path` | 小写 scheme 和 hostname |
| `  https://example.com  ` | `https://example.com/` | 去除首尾空白 |

#### `URLRuleConfig` 增强

新增配置选项：

```python
class URLRuleConfig:
    def __init__(
        self,
        max_retries_min: int = 0,        # 新增：最小允许值
        max_retries_max: int = 10,       # 新增：最大允许值
        normalize_urls: bool = True,     # 新增：是否归一化 URL
        reject_empty_urls: bool = True,  # 新增：是否拒绝空 URL
        # ... 原有选项
    ):
```

新增验证方法：

```python
def validate_and_clamp_max_retries(self, value: Optional[int]) -> int:
    """Validate and clamp max_retries value to valid range."""

def is_valid_status(self, status: Optional[str]) -> bool:
    """Check if a status value is valid."""
```

#### `URLRuleResult` 增强

新增字段：

```python
@dataclass
class URLRuleResult:
    # ... 原有字段
    original_url: Optional[str] = None  # 新增：原始 URL（归一化前）
```

新增属性：

```python
@property
def normalized_url(self) -> str:
    """Get the normalized URL, or original if normalization failed."""
```

### 2.2 安全属性访问

新增 `_safe_getattr` 方法，确保记录属性缺失时不会崩溃：

```python
def _safe_getattr(self, obj: Any, attr: str, default: Any = None) -> Any:
    """Safely get an attribute from an object, returning default if missing."""
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default
```

### 2.3 异常状态检测与警告

所有异常状态都会生成警告，但不会中断处理流程：

| 异常状态 | 警告内容 |
|---------|---------|
| 未知 status 值 | `"Unknown status value: 'xxx'"` |
| `completed` 但 `is_success=False` | `"Inconsistent state: status='completed' but is_success=False"` |
| `failed` 但 `is_success=True` | `"Inconsistent state: status='failed' but is_success=True"` |
| `completed_at < started_at` | `"Abnormal timestamps: completed_at (...) < started_at (...)"` |
| 负数 `retry_count` | `"Negative retry_count: -5"` |
| 负数 `max_retries` | `"Negative max_retries: -3"` |
| `in_progress` 但 `started_at=None` | `"Inconsistent state: 'in_progress' but started_at is None"` |

### 2.4 规则优先级确认

```
INVALID_INPUT > DIRTY_DATA_WARNING > CIRCULAR_DEPENDENCY > DUPLICATE_DEPENDENCY > NEW_OPTIONAL > NORMAL
```

**优先级验证测试覆盖**：

1. `DIRTY_DATA_WARNING` 优先于 `CIRCULAR_DEPENDENCY`
2. `CIRCULAR_DEPENDENCY` 优先于 `DUPLICATE_DEPENDENCY`
3. `in_progress` 状态归属于 `CIRCULAR_DEPENDENCY`，不是 `DUPLICATE_DEPENDENCY`

---

## 3. 新增测试覆盖

### 3.1 等价输入测试 (`TestURLEquivalence`)

| 测试用例 | 验证内容 |
|---------|---------|
| `test_url_with_trailing_slash_equivalent` | URL 尾斜杠等价性 |
| `test_url_with_root_slash_equivalent` | 根 URL 斜杠处理 |
| `test_url_case_insensitive_scheme` | scheme/hostname 大小写无关 |
| `test_url_with_whitespace_equivalent` | 首尾空白等价性 |
| `test_max_retries_none_vs_default` | `None` 与默认值等价 |
| `test_custom_default_max_retries_equivalence` | 自定义默认值等价性 |

**等价性矩阵**：

| 输入 1 | 输入 2 | 是否等价 | 场景 |
|--------|--------|---------|------|
| `https://example.com/page` | `https://example.com/page/` | ✅ 是 | 尾斜杠 |
| `HTTPS://EXAMPLE.COM` | `https://example.com` | ✅ 是 | 大小写 |
| `  https://example.com  ` | `https://example.com` | ✅ 是 | 空白 |
| `max_retries=None` | `max_retries=3` | ✅ 是 | 默认值 |

### 3.2 异常输入降级测试 (`TestURLInvalidInputDegradation`)

| 测试用例 | 验证内容 |
|---------|---------|
| `test_empty_url_rejected` | 空 URL 被拒绝（`INVALID_INPUT`） |
| `test_whitespace_only_url_rejected` | 仅空白 URL 被拒绝 |
| `test_allow_empty_urls_config` | 配置可允许空 URL |
| `test_negative_max_retries_clamped` | 负数 `max_retries` 被钳制并警告 |
| `test_excessive_max_retries_clamped` | 超限 `max_retries` 被钳制并警告 |
| `test_custom_max_retries_range` | 自定义取值范围生效 |

### 3.3 异常记录降级测试 (`TestAbnormalRecordDegradation`)

| 测试用例 | 验证内容 |
|---------|---------|
| `test_unknown_status_warns_and_treats_as_pending` | 未知 status 警告，按 pending 处理 |
| `test_completed_but_not_success_warns` | `completed` 但 `is_success=False` 警告 |
| `test_failed_but_success_true_warns` | `failed` 但 `is_success=True` 警告 |
| `test_completed_before_started_warns` | 异常时间戳警告 |
| `test_negative_retry_count_warns` | 负数 `retry_count` 警告 |
| `test_negative_max_retries_warns` | 负数 `max_retries` 警告 |
| `test_in_progress_without_started_at_is_dirty_data` | `in_progress` 无 `started_at` 归为 `DIRTY_DATA_WARNING` |

### 3.4 属性缺失测试 (`TestMissingAttributeHandling`)

| 测试用例 | 验证内容 |
|---------|---------|
| `test_record_with_missing_status` | 缺失 `status` 属性安全处理 |
| `test_record_with_missing_is_success` | 缺失 `is_success` 属性安全处理 |
| `test_record_with_missing_timestamps` | 缺失时间戳属性安全处理 |

### 3.5 规则优先级冲突测试 (`TestRulePriorityConflicts`)

| 测试用例 | 验证内容 |
|---------|---------|
| `test_dirty_data_overrides_circular` | `DIRTY_DATA_WARNING` 优先于 `CIRCULAR_DEPENDENCY` |
| `test_circular_overrides_duplicate` | `CIRCULAR_DEPENDENCY` 优先于 `DUPLICATE_DEPENDENCY` |
| `test_in_progress_is_circular_not_duplicate` | `in_progress` 归为 `CIRCULAR_DEPENDENCY` |

### 3.6 批量处理边界测试 (`TestBatchEvaluationEdgeCases`)

| 测试用例 | 验证内容 |
|---------|---------|
| `test_batch_with_mixed_validity` | 混合有效/无效 URL 批量处理 |
| `test_stats_summary_with_mixed_scenarios` | 包含新场景（`INVALID_INPUT`）的统计摘要 |

---

## 4. 测试统计

### 4.1 测试数量对比

| 模块 | 原测试数 | 新增测试数 | 当前测试数 |
|------|---------|-----------|-----------|
| URL 规则核心 | 21 | 0 | 21 |
| URL 规则边界 | 0 | 27 | 27 |
| **URL 规则总计** | **21** | **27** | **48** |

### 4.2 新增测试分类统计

| 测试类别 | 测试数量 | 覆盖场景 |
|---------|---------|---------|
| 等价输入一致性 | 6 | URL 变体、参数变体 |
| 异常输入降级 | 6 | 空 URL、数值超限 |
| 异常记录降级 | 7 | 状态矛盾、时间戳异常、数值异常 |
| 属性缺失处理 | 3 | 安全属性访问 |
| 规则优先级 | 3 | 冲突场景判定 |
| 批量处理边界 | 2 | 混合有效性、新场景统计 |
| **总计** | **27** | |

---

## 5. 测试结果

### 5.1 URL 规则模块测试

```
tests/test_url_rules.py: 21 passed
tests/test_url_rules_boundary.py: 27 passed

============================= 48 passed in 0.21s ==============================
```

### 5.2 规则优先级验证

所有优先级冲突测试通过，确认优先级顺序：

```
INVALID_INPUT > DIRTY_DATA_WARNING > CIRCULAR_DEPENDENCY > DUPLICATE_DEPENDENCY > NEW_OPTIONAL > NORMAL
```

### 5.3 警告触发验证

所有异常状态测试通过，确认：
1. **异常状态会生成警告**（添加到 `result.warnings`）
2. **处理流程不会中断**（优雅降级）
3. **结果结构保持完整**（`URLRuleResult` 所有字段正常填充）

---

## 6. 新增/修改文件清单

### 6.1 新增文件

| 文件路径 | 说明 |
|---------|------|
| `polite_crawler/url_rules.py` | 增强版规则引擎（重写） |
| `tests/test_url_rules_boundary.py` | 边界测试（27 个测试） |

### 6.2 修改文件

| 文件路径 | 变更内容 |
|---------|---------|
| `tests/test_url_rules.py` | 修复 `test_evaluate_batch_mixed` 以适配 URL 归一化 |

---

## 7. 可维护性改进

### 7.1 规则优先级文档化

在代码中明确标注规则优先级：

```python
"""
Rule Priority (highest to lowest):
1. INVALID_INPUT - Empty/invalid URL (if reject_empty_urls is True)
2. DIRTY_DATA_WARNING - Inconsistent state that needs attention
3. CIRCULAR_DEPENDENCY - URL already processed (completed/in_progress)
4. DUPLICATE_DEPENDENCY - URL already exists (pending/failed)
5. NEW_OPTIONAL - New URL with optional parameters
6. NORMAL - Standard new URL
"""
```

### 7.2 异常处理统一

所有异常处理遵循相同模式：

```python
# 1. 检测异常
if abnormal_condition:
    warnings.append("Warning message")

# 2. 使用默认值/降级处理
value = safe_value if abnormal else original_value

# 3. 继续处理流程
return normal_result
```

### 7.3 归一化可配置

URL 归一化行为可通过配置控制：

```python
config = URLRuleConfig(
    normalize_urls=True,      # 启用/禁用归一化
    reject_empty_urls=True,   # 拒绝/允许空 URL
)
```

---

## 8. 结论

本轮 R4 质量加固完成以下目标：

| 目标 | 状态 | 验证方式 |
|------|------|---------|
| 统一四类场景判定边界 | ✅ 完成 | 规则优先级测试（3 个） |
| 等价输入一致性 | ✅ 完成 | 等价输入测试（6 个） |
| 异常输入降级处理 | ✅ 完成 | 异常输入测试（13 个） |
| 属性缺失安全处理 | ✅ 完成 | 属性缺失测试（3 个） |
| 批量处理边界 | ✅ 完成 | 批量边界测试（2 个） |
| 无新增告警 | ✅ 完成 | 所有测试全绿（48 个） |

**最终测试结果**：48 个 URL 规则相关测试全部通过，无失败用例。
