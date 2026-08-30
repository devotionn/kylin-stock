# 扫描单据识别导入

## 目标

首期仅针对固定版式的 **调拨（接收）通知单**，从扫描图片提取并核对：

- 调拨依据；
- 供应单位；
- 接收单位；
- 物资名称；
- 规格型号；
- 应发数量。

识别结果只是草稿，**OCR 不得直接修改库存**。

## 为什么不按“黄色像素”硬切

黄色区域是当前样张的视觉提示，不是稳定业务协议。黑白扫描、曝光、打印模板或底色变化都可能破坏纯颜色定位。

当前实现以固定表单的文字锚点和 OCR 坐标为主：

1. 定位 `调拨依据` / `供应单位` / `接收单位`；
2. 读取同一行右侧值；
3. 定位 `名称` / `规格型号` / `应发数-数量` 表头；
4. 按列坐标和行聚类提取物资明细；
5. 无法可靠识别的字段保留为空并产生 warning，由人工补正。

## 数据模型先决条件

扫描单上的规格型号是物资身份的一部分，因此 schema V2 为 `materials` 增加 `specification`。

系统的人类可读匹配键为：

```text
物资名称 + 规格型号
```

名称相同、规格不同的物资不允许被 OCR 自动猜成同一个物资。若扫描件没有可靠识别出规格型号，而系统中的同名物资本身存在规格，系统也不会退化成“只按名称”自动匹配，必须人工确认。

## 安全入账边界

页面流程：

```text
选择扫描图片
  -> 本地 OCR
  -> 展示识别草稿
  -> 自动匹配物资/规格（只做确定性匹配）
  -> 人工核对名称、规格、数量、位置
  -> 人工确认
  -> 整张单据一个 SQLite BEGIN IMMEDIATE 事务入库
```

任何一行失败，整张单据全部回滚，不允许“半张单入账”。

## 防重复导入

OCR worker 在读取图片时计算 SHA-256。schema V3 的 `document_imports.source_hash` 为 UNIQUE。

单据入库事务会：

1. 在写库存前检查图片指纹；
2. 写所有入库流水与库存余额；
3. 写 `document_imports` 及本次流水号列表；
4. 一起提交。

再次导入完全相同的图片会被拒绝，避免重复增加库存。

> 指纹防重解决“同一图片重复提交”。如果以后业务需要识别“同一纸质单据重新扫描成不同图片”，应再引入调拨单号/业务唯一键作为第二层去重规则。

## OCR 运行时

OCR 与主程序进程隔离：

```text
Tauri/Rust
  -> bundled resources/ocr_worker.py
  -> Python venv
  -> RapidOCR
  -> ONNX Runtime CPU
```

主程序不把 Python 包或模型写进数据库，也不把 OCR 库直接链接进库存核心。

依赖锁定在：

`src-tauri/resources/requirements-ocr.txt`

### 银河麒麟 / Linux

目标环境运行：

```bash
bash scripts/setup-ocr-runtime.sh
```

默认安装到：

```text
$HOME/.local/share/kylin-stock/ocr-venv
```

应用会自动发现该标准 venv，因此从桌面图标启动时**不需要**再手工 `export` 环境变量。

完全离线安装时，通过 `KYLIN_STOCK_OCR_WHEELHOUSE` 指向事先准备好的 ARM64 wheels 目录：

```bash
KYLIN_STOCK_OCR_WHEELHOUSE=/path/to/wheels bash scripts/setup-ocr-runtime.sh
```

### Windows 开发机

运行：

```powershell
.\scripts\setup-ocr-runtime.ps1
```

默认安装到：

```text
%LOCALAPPDATA%\KylinStock\ocr-venv
```

应用同样会自动发现该 venv。

### 高级覆盖

只有需要使用自定义 Python 环境时，才显式设置：

```text
KYLIN_STOCK_OCR_PYTHON=/absolute/path/to/python
```

运行时优先级：

```text
KYLIN_STOCK_OCR_PYTHON
  -> 标准 KylinStock OCR venv
  -> 系统 python/python3 fallback
```

## 当前模板范围

首期解析器是固定模板解析，不声称支持任意票据、任意 Excel 打印版式或手写单据。

支持图片：

- JPG/JPEG
- PNG
- BMP
- TIF/TIFF

单图最大 30 MB；单张单据最多 200 行。

## 验收样例

对当前客户样张，人工最终确认目标数据为：

```json
{
  "调拨依据": "2026年计划",
  "供应单位": "仓库",
  "接收单位": "超市",
  "明细": [
    { "名称": "粉笔", "规格型号": "10.9型粉笔", "应发数量": 1000 },
    { "名称": "橡皮", "规格型号": "20型橡皮", "应发数量": 1000 }
  ]
}
```

验收不只看 OCR 文本，还必须验证：

- 识别结果可人工修正；
- 同名不同规格不会错误自动匹配；
- OCR 未识别规格时不会猜选一个带规格的同名物资；
- `资料袋`、`附件盒` 等包含表头词的真实物资名称不会被过滤；
- 任一明细不完整时禁止提交；
- 一次确认后所有行一起成功；
- 人为制造一行数据库失败时整单回滚；
- 同一图片第二次提交被拒绝；
- 库存、流水、Excel 导出均显示规格型号；
- 目标 ARM64 环境可安装并通过 RapidOCR/ONNX Runtime 自检；
- 目标 ARM64 包仍能通过 native package smoke build，且包含 OCR worker 与依赖清单资源。

## 后续增强（非首期阻塞）

- 单据编号/业务编号第二层防重；
- 多模板配置化；
- 扫描件自动旋转/透视纠偏；
- 低置信度单元格局部重识别；
- 物资别名表；
- 原始扫描图片归档，用于更强审计追溯；
- 大模型仅作为低置信度纠错/建议层，不直接获得库存写权限。
