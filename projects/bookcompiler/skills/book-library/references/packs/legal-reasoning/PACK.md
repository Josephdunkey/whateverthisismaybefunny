# 法律推理分析

> 领域能力包 `legal-reasoning` · version `1.0.2` · status `active`

> 这是生成文件。个人补充请写在同目录的 `LOCAL.md`；重新构建不会覆盖它。

## 何时使用

当问题涉及以下任一主题时加载本包：

- 法律
- 法规
- 规章
- 上位法
- 适用规则
- 司法
- 合法性
- 权利
- 程序
- 比例原则
- 先例
- 宪法
- 党规
- 国法
- 监管
- 处罚
- 合规
- deductive validity test
- definition stress test
- enthymeme reconstruction
- expectation-value decision frame
- fallacy audit with contextual exception
- inductive causal appraisal
- refutation by logical analogy
- two-dimensional argument diagram
- 个人主义促进思想自由框架
- 党政体制
- 条块矩阵
- 国法双重约束
- 国际组织影响框架
- 极权主义利用民主框架
- 自由主义适应性框架
- 试点
- 推广的适应性政策过程
- 集中计划控制框架

## 不用于

- 单纯的书本摘要或作者角色扮演。
- 没有书库证据、只靠常识就能回答的问题。
- 需要实时行情、最新法规原文或未入库数据的问题；先提示用户补充来源。

## 推理协议（必须按顺序走）

1. `事件拆解`：拆成主体、约束、机制、时间尺度。
2. `选择镜头`：说明本问题需要哪些 lens，以及为什么。
3. `选择框架`：从 `frameworks.md` 选 1–3 个框架，写出适用条件。
4. `执行步骤`：按框架的 inputs/steps/outputs 真走一遍，不得只引用结论。
5. `跨书对照`：至少找一本支持、一本限制或反对的书；没有就说没有。
6. `冲突处理`：读 `debates.md`；有冲突就并列呈现，不取平均。
7. `边界与证伪`：写清结论在什么条件下失效，以及什么指标会改变判断。
8. `引用`：每个事实句给出书名、章节/页码和原文引用；推断与建议单独标注。

## 领域概览

- 镜头：law, politics
- 书：3 本
- 框架：16 个
- claims：40 条
- 跨书实体：40 个
- 争议：0 条

## 书与框架的对应

| 书 | 学科 | 框架数 |
| --- | --- | ---: |
| Introduction to Logic | logic, law | 8 |
| 当代中国政府与政治 | politics, law | 3 |
| 通往奴役之路 | politics, economics, law | 5 |

详细来源见 `sources.md`，框架步骤见 `frameworks.md`，争议见 `debates.md`。

## 加载顺序（渐进披露）

1. 先读本文件，确认是否适用。
2. 只加载与问题相关的 1–3 个框架（`frameworks.md`）。
3. 需要出处时再读 `sources.md` / `debates.md`。
4. 回答完成后按 `eval.md` 的 rubric 自评。

## 当前覆盖缺口

- no cross-book conflicts detected; this may be extraction coverage, not agreement

## 评估

- Golden set：`eval/golden.jsonl`
- 最近一次覆盖率评估：`{'book_coverage': 1.0, 'framework_coverage': 1.0, 'lens_coverage': 1.0, 'topic_coverage': 1.0, 'conflict_coverage': 1.0}`
- 覆盖率不等于答案深度；深度仍需要独立 judge 或人工盲评。
