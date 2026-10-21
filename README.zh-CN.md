# 遥测意图的 Chatito 模板生成方法

[English](README.md) | **简体中文**

本工具将**每张遥测语义卡转换为三个英文表述变体**，导出 Chatito 语法，并调用 Chatito 核对展开结果。文本由观测范围、指标、采集、聚合和交付等语义字段组合构造。



## 范围

本包包含模板构造、词汇化、稳定风格选择、Chatito 运行与验证代码，以及六张使用虚构设备名称的演示语义卡。


## 快速开始

环境：Python 3.10及以上；需要执行Chatito时使用Node.js 18及以上和npm。

在本目录打开终端，先安装锁定的Chatito依赖：

```text
npm --prefix vendor/chatito ci --ignore-scripts
```

运行完整流程：

```text
python -B run.py generate --cards examples/cards.jsonl --output outputs/demo
```

该命令生成模板和文本，在两个独立临时目录中执行Chatito，核对全部文本变体与两次编译结果的字节一致性。验证成功后保留输出目录；输出目录须为尚不存在的路径。

只查看模板和Python生成的文本时：

```text
python -B run.py prepare --cards examples/cards.jsonl --output outputs/preview
```

`prepare`仅生成模板和文本，验证状态为`not_run`。安装依赖后执行：

```text
python -B run.py verify --output outputs/preview
```

Node不在PATH中时，通过`--node`传入其可执行文件路径。运行时位置不同时，使用`--runtime`传入包含`src/bin.ts`、`package-lock.json`和`node_modules`的Chatito目录。

## 输入

输入采用UTF-8 JSON Lines格式，每行一张语义卡，示例见[examples/cards.jsonl](examples/cards.jsonl)。

| 字段 | 含义 |
|---|---|
| `sample_id` | 唯一标识，以ASCII字母开头，后续为字母、数字、下划线或连字符，最长64个字符 |
| `semantic_ir.tasks` | 按顺序排列的观测任务列表 |
| `region` | 每个任务的观测范围及对象信息 |
| `metric_ids` | 每个任务的非空指标列表，指标定义见`vocabulary.py` |
| `acquire` | 采集参数对象，未指定参数时使用`{}` |
| `aggregate`、`deliver`、`lifecycle` | 可选的聚合、交付和任务持续时间参数 |

采样周期、聚合窗口长度、窗口步长和交付周期分别指定。时长使用`{"value": 数值, "unit": 单位}`表示；路径中间节点按`via`列表顺序表达。

## 输出

| 文件 | 用途 |
|---|---|
| `templates.chatito` | 根据输入语义卡导出的Chatito语法，每张卡三个表述变体 |
| `variants.jsonl` | 全部变体、语义卡、文本片段及事实跨度 |
| `selected.jsonl` | 每张卡按结构族内稳定轮换规则选出的一个变体 |
| `chatito_raw.json` | 实际Chatito编译输出，仅成功执行验证后产生 |
| `manifest.json` | 输入和代码摘要、输出摘要、实际验证状态 |

输出采用UTF-8和LF换行。`spans`为Python字符索引的左闭右开区间。相同输入集合与代码版本下，选择和生成过程确定；改变样本标识或输入集合可能改变风格分配。

## 核心代码

| 文件 | 作用 |
|---|---|
| `src/telemetry_chatito/renderer.py` | 三种变体、结构族、风格分配和Chatito语法导出；主要方法入口 |
| `src/telemetry_chatito/base_renderer.py` | 范围、指标、阶段、时间参数等语义字段的文本构造及事实跨度 |
| `src/telemetry_chatito/vocabulary.py` | 指标英文词表 |
| `src/telemetry_chatito/chatito.py` | 调用Chatito展开模板并校验结果 |
| `src/telemetry_chatito/cli.py` | JSONL输入、命令行、输出与校验摘要 |
| `vendor/chatito/` | 原项目使用的Chatito运行源码子集、原MIT许可证、依赖锁 |

Python接口由`telemetry_chatito`导出：`render_variants`生成文本变体，`surface_family`计算结构族标识，`assign_styles`分配风格，`render_grammar`导出Chatito语法。

## 检查

```text
python -B run_tests.py
```

测试覆盖时间角色、路径顺序、多任务关联、证据跨度、输入不变、稳定生成及验证失败的处理。Chatito集成验证使用上述`generate`命令。

环境及跨平台检查摘要见[verification/checks.json](verification/checks.json)，演示输出见`verification/demo/`。Windows验证复用了已安装的JavaScript依赖；依赖锁的独立安装检查在Linux上完成。

各验证记录中的`source_files`标明当次验证的代码版本。Linux记录保留了说明文字和输入错误提示更新前的源码摘要；当前版本生成的模板、文本和Chatito输出已与该记录逐项核对一致。

文件完整性检查：

```text
python -B check_package.py
```

## 扩展与适用范围

新增语义字段时，同步扩展文本映射、跨度和测试；新增指标时扩展词表。

## 来源与许可

模板代码源自本研究的遥测语义卡生成模块。Chatito采用MIT许可证，来源、版本和许可证见[第三方说明](THIRD_PARTY_NOTICES.md)。本项目自有代码的许可证尚未指定。
