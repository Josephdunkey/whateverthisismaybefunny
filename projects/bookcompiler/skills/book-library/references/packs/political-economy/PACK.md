# 政治经济分析

> 领域能力包 `political-economy` · version `1.0.5` · status `active`

> 这是生成文件。个人补充请写在同目录的 `LOCAL.md`；重新构建不会覆盖它。

## 何时使用

当问题涉及以下任一主题时加载本包：

- 财政
- 地方债
- 地方政府
- 土地财政
- 央地关系
- 转移支付
- 货币供给
- 基础货币
- 货币乘数
- 银行信贷
- 信贷
- 信用扩张
- 债务周期
- 去杠杆
- 金融危机
- 货币政策
- 财政政策
- 产业政策
- 国家能力
- 政策传导
- 金融稳定
- 房地产
- 城投
- 化债
- 流动性
- 准备金
- 专项债
- 特别国债
- 城投平台
- 融资平台
- 银行间市场
- 汇率
- 资本流动
- 利率
- 加息
- 降息
- 影子银行
- 贸易
- 监管
- 降准
- 地方财政
- 消费
- 产权
- 统一大市场
- 人口
- 国企
- 非税收入
- 结构性货币政策
- beautiful deleveraging balance
- credibility-backed currency reform test
- crisis political-economy risk map
- debt cycle phase classifier
- external-currency fragility screen
- restructuring leverage assessment
- zero-bound policy triage
- 三角外交杠杆测算
- 党政体制
- 条块矩阵
- 党规
- 国法双重约束
- 军队私有化链条
- 县际竞争激励诊断
- 合约约束竞争分析
- 土地
- 金融三位一体
- 货币乘数控制链
- 央行资产负债表投放渠道
- 官督商办治理诊断
- 政策归因波动分析
- 王朝衰败诊断树
- 礼仪即秩序分析
- 租值替代交易费用分析
- 税租判别法
- 继承与派系斗争机制
- 试点
- 推广的适应性政策过程
- 财权
- 事权错配压力测试
- 货币供给内生性检验
- 逐层责任合约传导

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

- 镜头：economics, politics
- 书：6 本
- 框架：29 个
- claims：60 条
- 跨书实体：40 个
- 争议：0 条

## 书与框架的对应

| 书 | 学科 | 框架数 |
| --- | --- | ---: |
| 中央银行与货币供给 | economics, finance | 3 |
| 以利为利：财政关系与地方政府行为 | politics, economics, public_finance | 3 |
| Principles for Navigating Big Debt Crises | economics, finance | 7 |
| 当代中国政府与政治 | politics, law | 3 |
| 中国近代史 | history, politics | 7 |
| 中国的经济制度 | economics, law | 6 |

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
