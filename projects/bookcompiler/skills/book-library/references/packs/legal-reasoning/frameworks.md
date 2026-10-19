# 法律推理分析 · 框架步骤

> 只加载与当前问题相关的框架。不要一次读完。

## Deductive Validity Test

> Determines by form alone whether an argument's premises could be true while its conclusion is false, using Venn diagrams or truth tables.

- book: 
- lenses: general, law
- confidence: medium · status: verified

### Applicable when

- A conclusion is claimed to follow with necessity
- A syllogism, conditional argument, or chain of rule-governed steps must be checked
- A proposed counterexample would show invalidity

### Inputs

- The argument in standard or symbolic form
- The interpretation of its terms (Boolean or Aristotelian)
- For symbolic forms, the connectives and their truth conditions

### Steps

- Classify the argument as deductive, meaning its premises are claimed to give conclusive grounds.
- Put the premises and conclusion into standard form, translating singular propositions into their equivalent universal form.
- Apply the appropriate test: Venn diagram for categorical syllogisms, truth table for propositional forms.
- Search for any row or region in which all premises hold and the conclusion fails.
- If found, record the substitution instance as a counterexample proving invalidity.
- If none is found, record validity while separating that verdict from the truth of the premises.

### Outputs

- A verdict of valid or invalid for a deductive argument
- Counterexample instances when invalidity is shown
- A proof structure when validity is confirmed

### Failure modes

- Concluding that a valid argument has a true conclusion when its premises are false
- Applying the validity-accuracy vocabulary to an inductive argument, where it does not apply
- Misplacing diagram marks and thereby inserting information the premises do not warrant
- Treating a truth-functionally material conditional as a causal or evidential one

### Counterexamples

- Statistical generalizations, which are never certain and are appraised by probability instead of validity
- Arguments whose terms are vague, where standard-form translation already distorts the claim

### Source citations

> A deductive argument is one whose premises are claimed to provide conclusive grounds for the truth of its conclusion.
  -  · p.185
> The truth table thus shows that the argument form has no substitution instance having true premises and a false conclusion, and there-by proves the validity of the argument form being tested.
  -  · p.351
> Placing x's in each of them would also go beyond what the premises assert.
  -  · p.241

## Definition Stress Test

> Evaluates a proposed definition against the rules of genus and difference and asks whether it can settle or only restate the dispute.

- book: 
- lenses: law, general
- confidence: medium · status: verified

### Applicable when

- Two parties argue past each other because a key term is unclear
- A stipulative definition is offered to end a debate
- A legal or philosophical definition must be checked for scope

### Inputs

- The definiendum and the proposed definiens
- The rule set for definition by genus and difference
- The purpose the definition is meant to serve

### Steps

- Restate the definition in the form: genus plus differentiating difference.
- Check whether it is circular, that is, whether the definiens merely repeats the definiendum.
- Test for being too narrow by finding a clear instance of the term the definition excludes.
- Test for being too broad by finding an instance the definition includes but should not.
- Identify which rule is violated and state that violation explicitly.
- Decide whether the definition is stipulative, and therefore neither true nor false, or informative.

### Outputs

- A verdict of too broad, too narrow, circular, or acceptable
- The specific rule violated
- A judgment of whether the definition advances the purpose at hand

### Failure modes

- Rejecting a stipulative definition for being untrue when it is only a proposal
- Accepting a definition that is unclear but rhetorically convenient
- Assuming an agreed definition settles a substantive disagreement it only redescribes

### Counterexamples

- A definition offered purely to reduce the emotive role of language in a contentious exchange, where usefulness rather than truth is the right criterion

### Source citations

> Proposals may be rejected, requests refused, instructions disobeyed-but they can be neither true nor false.
  -  · p.93
> After identifying the difficulty (or difficulties), state the rule (or rules) that are being violated.
  -  · p.112
> By reducing the emotive role of language, however, and by simplifying discourse, they can help to prevent fruitless conflict.
  -  · p.93

## Enthymeme Reconstruction

> Recovers the unstated premises of a persuasive argument and tests whether the conclusion actually follows once they are supplied.

- book: 
- lenses: law, politics, general
- confidence: medium · status: verified

### Applicable when

- The argument's conclusion depends on a plausible but unstated second premise
- A policy or legal claim is urged rhetorically rather than demonstrated
- Two sides disagree without stating what exactly they disagree about

### Inputs

- The argumentative passage in its original wording
- The conclusion the proponent is claimed to be advancing
- Any context that fixes who is speaking and to whom

### Steps

- Paraphrase the passage, rewording essential propositions and ordering premises before conclusion.
- Identify the stated premises and the stated conclusion, numbering each proposition.
- Formulate candidate unstated premises that would make the inference go through.
- Check whether the argument with the supplied premises is valid, and whether the added wording is warranted by the text.
- Evaluate each reconstructed premise on its own merits rather than treating it as innocent background.
- Report the residual substantive disagreement, which the reconstruction should now localize to a specific premise.

### Outputs

- A complete, numbered statement of the argument
- A list of suppressed assumptions and their plausibility
- A verdict on validity separate from the truth of the premises

### Failure modes

- Supplying a premise stronger than the proponent would accept, thereby building in a straw man
- Supplying a premise so weak the conclusion still does not follow, then declaring the argument sound
- Treating the reconstructed premise as if the proponent had asserted it
- Collapsing the difference between a plausible premise and a true one

### Counterexamples

- A fully explicit deductive proof in which no premise is suppressed
- A passage where the missing wording is idiom rather than a substantive premise, so reconstruction invents content that was never intended

### Source citations

> This argument relies on the unstated second premise: "No one should be ex-ecuted to advance an objective that is not promoted by execution."
  -  · p.19
> In Section 1 we explained the paraphrasing of an argumentative passage, in which the essential propositions may be reworded (or supplied if they are as-sumed but missing), and in which premises and conclusions are put into the most intelligible order.
  -  · p.75

## Expectation-Value Decision Frame

> Compares chancy alternatives by multiplying each outcome's return by its probability and summing the products.

- book: 
- lenses: economics, general
- confidence: medium · status: verified

### Applicable when

- Investments, wagers, or policy options have enumerable outcomes
- Probabilities can at least be estimated even though the future is unknown
- Two or more risky options must be ranked on a common scale

### Inputs

- The set of possible outcomes for each option
- A return figure attached to each outcome
- An estimated probability for each outcome

### Steps

- Enumerate every possible outcome of the option.
- Attach the return or cost to each outcome.
- Estimate the probability of each outcome, stating that these are estimates.
- Multiply each return by its probability.
- Sum the products to obtain the expectation value.
- Compare expectation values across options while recording how sensitive each ranking is to the probability estimates.

### Outputs

- A single comparable number per option
- A ranking of risky alternatives
- A sensitivity note showing which probability estimates drive the ranking

### Failure modes

- Treating estimated probabilities as known facts
- Ignoring outcomes that are hard to quantify
- Comparing options whose returns are measured on incompatible scales
- Letting a higher expectation value override a catastrophic low-probability outcome without discussion

### Counterexamples

- Decisions under deep uncertainty where no defensible probabilities exist, making the arithmetic misleading rather than helpful

### Source citations

> The future cannot be known, but the probabilities may be estimated.
  -  · p.609
> We multiply the return yielded on each possible outcome by the probability of that outcome being realized; the sum of all such products is the expectation value of the bet or investment.
  -  · p.609

## Fallacy Audit with Contextual Exception

> Screens an argument for relevance, ambiguity, and assumption defects while testing whether a special context licenses an otherwise fallacious move.

- book: 
- lenses: law, politics, general
- confidence: medium · status: verified

### Applicable when

- A claim is advanced through a loaded question, a clipped quotation, or an attack on the speaker
- A courtroom, legislative, or journalistic setting supplies agreed-upon rules of evidence
- A rhetorical question needs its buried premise exposed

### Inputs

- The passage and its surrounding context
- The audience and the rules of the exchange
- The conclusion the speaker wants the audience to accept

### Steps

- Restate the argument so that its conclusion is explicit.
- Name the suspected fallacy by type: relevance, ambiguity, or assumption.
- Locate the buried assumption or the omitted wording that changes the sense.
- Ask whether the setting supplies agreed rules that make the move acceptable, as impeachment does in a trial.
- If an exception applies, justify it by those rules rather than by the argument's persuasiveness.
- State what must be shown for the charge of fallacy to stand, and what evidence would rebut it.

### Outputs

- A named fallacy or a documented contextual exception
- The suppressed premise or the omitted wording that produces the distortion
- A recommendation about whether the argument may be relied upon

### Failure modes

- Charging ad hominem whenever a speaker's credibility is questioned, even where testimony is at issue
- Calling a complex question fallacious while ignoring that some of its parts are uncontroversial
- Treating a clipped quotation as a mere stylistic quibble rather than a reversal of sense
- Applying courtroom standards of evidence to informal polemic, or vice versa

### Counterexamples

- Impeaching a witness by exhibiting contradictions in the testimony, which is appropriate in that context even though it is strictly an ad hominem consideration

### Source citations

> In courtroom proceedings, for example, it is acceptable, and often ef-fective, to call a jury's attention to the unreliability of a witness, and by so doing to undermine the claims upheld by the testimony of that witness.
  -  · p.130
> Because assumptions like these are not asserted openly, the questioners evade the need to defend them forthrightly.
  -  · p.148
> The omission of the words "will claim with a straight face"-and of Gore's express conviction that cancer is caused by smoking-unfairly reversed the sense of the passage from which the quotation was pulled.
  -  · p.167

## Inductive Causal Appraisal

> Weighs a causal or predictive claim by the inductive method used to support it and states the probability level it actually earns.

- book: 
- lenses: general, economics, politics
- confidence: medium · status: verified

### Applicable when

- A policy or medical claim rests on observed regularities
- Concomitant variation, method of difference, or analogy is doing the causal work
- A conclusion is offered with more certainty than the evidence carries

### Inputs

- The observed cases and how they were grouped
- Whether the compared groups differ in only one circumstance
- Alternative explanations that could produce the same correlation

### Steps

- Name the inductive pattern being used: concomitant variation, method of difference, or analogy.
- State the conclusion as a probabilistic claim rather than a necessary one.
- Check whether the compared cases differ in only one circumstance before inferring a causal connection.
- Enumerate rival causes and background conditions that could explain the same data.
- Adjust the confidence expressed to the strength of the design, noting that the conclusion is never certain.
- Compare the cost of acting on the claim with the cost of waiting for stronger evidence.

### Outputs

- A graded probability judgment instead of a verdict of valid or invalid
- A list of rival explanations still open
- A calibrated statement of how strongly the evidence supports the causal claim

### Failure modes

- Reporting a correlation as an established causal connection
- Using the vocabulary of validity and invalidity for an inductive conclusion
- Over-generalizing from a voluntary or unrepresentative sample
- Ignoring that the same data admit a weaker as well as a stronger reading

### Counterexamples

- A deductive argument whose conclusion is guaranteed by its premises, where probability language understates what is known

### Source citations

> The causal connection between the absence of cir-cumcision and the spread of HIV is not known with certainty, the way the conclusion of a deductive argument is known, but it is now known with a very high degree of probability.
  -  · p.38
> Difference, Method of: A pattern of inductive argument in which, when cases in which the phenomenon under investi-gation occurs and cases in which it does not occur differ in only one circumstance, that circumstance is inferred to be causally connected to the phenomenon under investigation
  -  · p.628
> Whenever the U.S. says things that make a military conflict with Iran seem more likely, the price of oil rises, strengthening Iran's regime rather than weakening it.
  -  · p.554

## Refutation by Logical Analogy

> Attacks a non-deductive argument by constructing a different argument of the same form whose conclusion is known or widely believed to be false.

- book: 
- lenses: politics, economics, general
- confidence: medium · status: verified

### Applicable when

- The target argument is scientific, political, or economic rather than deductively claimed
- Its form is recognizable but its conclusion seems intuitively right
- A counterexample must be shown without disputing every premise

### Inputs

- The target argument stated in a form-neutral way
- Its underlying pattern or design
- A substitute argument of that pattern with a false or improbable conclusion

### Steps

- Restate the target argument and identify its underlying form or pattern.
- Confirm that the target does not claim deductive necessity, since the technique targets inductive support.
- Construct a second argument with the same design but with premises and a conclusion that are clearly unacceptable.
- Present the pair so the shared form is visible to the audience.
- Draw the conclusion that the same design cannot carry the evidential weight claimed for it.
- Identify which feature of the target's content, not its form, would have to do all the work.

### Outputs

- A parallel argument exposing the weakness of the original design
- A form-based reason for withholding assent
- A diagnosis of where the target's real support must come from

### Failure modes

- Choosing a refuting analogy whose form differs subtly from the target
- Assuming the target is deductive, where a same-form counterexample shows only false premises rather than invalidity
- Failing to distinguish a form defect from an unlucky choice of content
- Using the technique to dismiss an argument whose conclusion is independently well supported

### Counterexamples

- Arguments explicitly advanced as deductively valid, which must be tested for validity rather than defeated by a merely similar-looking counterexample

### Source citations

> Scientific, political, or economic arguments, not purporting to be deductive, may be countered by pre-senting other arguments that have very similar designs and whose conclusions are known to be false or are generally believed to be improbable.
  -  · p.517
> Analogy is the common ground of our everyday inferences from past experience to what the future will hold.
  -  · p.499

## Two-Dimensional Argument Diagram

> Numbers every proposition in a complex passage and draws its premise-to-conclusion relations graphically to expose structure and gaps.

- book: 
- lenses: general, law
- confidence: medium · status: verified

### Applicable when

- Several arguments are interwoven in one passage
- Conclusions of subarguments serve as premises for further arguments
- An extended chain of reasoning must be checked step by step

### Inputs

- A paraphrased passage with each proposition assigned a number
- The claimed final conclusion
- Permission to add no propositions beyond those present

### Steps

- Paraphrase the passage and number its component propositions.
- Mark which propositions are offered as premises and which as conclusions.
- Draw arrows from each premise to the conclusion it supports.
- Handle cascades, in which a subargument's conclusion feeds a later argument, by chaining the arrows.
- Identify propositions that support nothing and conclusions that receive no support.
- Re-read the diagram against the source to confirm no relation was invented.

### Outputs

- A two-dimensional diagram of numbered propositions
- A visible map of independent and dependent subarguments
- A list of unsupported conclusions and unused premises

### Failure modes

- Adding information the passage does not assert
- Assuming an arrow because two propositions are topically related
- Over-reading a passage whose connectives are ambiguous
- Producing a diagram too intricate to communicate to a reader

### Counterexamples

- A single-premise argument, where paraphrase alone is faster and clearer
- Passages already stated as numbered lists, where diagramming adds little

### Source citations

> In Section 2 we explained the diagramming of an argument, in which the propositions of an argument are represented by numbers, and the relations of the premises and conclusions are then exhibited graphically in two dimensions, by showing on a page the relations of those numbered propositions.
  -  · p.75
> Multiple arguments may be interwoven in patterns more complicated than cascades, and these will require careful analysis.
  -  · p.56

## 个人主义促进思想自由框架

> 给思想的成长或者这一方面的普遍进步定出"计划"或进行"组织",这种说法本身就是词语上的矛盾。

- book: 
- lenses: general
- confidence: medium · status: verified

### Applicable when

- 个人主义促进思想自由

### Inputs

- 个人主义
- 思想自由

### Steps

- 分析个人主义
- 评估思想自由的促进
- 提出支持建议

### Outputs

- 支持建议

### Failure modes

- 忽视个人主义的作用
- 忽视思想自由的重要性

### Counterexamples

- 忽视个人主义的作用可能导致思想自由的丧失

### Source citations

> 给思想的成长或者这一方面的普遍进步定出"计划"或进行"组织",这种说法本身就是词语上的矛盾。
  -  · p.100

## 党政体制—条块矩阵

> 把中国共产党作为理解中国政府的关键，用党政双轨、条块结合与领导小组识别谁有权、谁能协调、谁承担执行责任。

- book: 
- lenses: politics, law
- confidence: medium · status: verified

### Applicable when

- 分析政策执行与跨部门协调
- 判断中央与地方关系
- 识别监管机构与媒体、安全等领域的权力结构

### Inputs

- 党组织关系与政府序列
- 条条与块块归属
- 领导小组与议事协调机构
- 人事任免与考核指标

### Steps

- 画出党政双轨结构。
- 标出具体事务的条条与块块归属。
- 识别领导小组和协调机构的实际权力与临时性。
- 分析人事、考核与财政激励。
- 判断执行阻塞点在条、块还是党政衔接处。

### Outputs

- 权力矩阵与协调路径
- 执行风险点与责任归属判断

### Failure modes

- 正式文本与实际运作不一致。
- 领导小组权力边界随情境变化。
- 部门利益与地方变通改变执行结果。

### Counterexamples

- 单一部门权责清晰、无需跨部门协调时，矩阵分析的增量有限。
- 运动式治理可能暂时绕过常规条块结构。

### Source citations

> 将中国共产党作为理解中国政府与政治的钥匙
  -  · p.4
> 将"党政体制"作为理解中国政府与政治的关键词
  -  · p.4
> 学界一般将领导小组视为议事协调机构,拥有跨部门的协调权力,但实际上这些领导小组享有更大的权力
  -  · p.19
> 党的十八届三中全会之后,中央成立了全面深化改革领导小组
  -  · p.19
> 国家安全部门则实行"条块结合,以条为主"的体制
  -  · p.136
> 党政双轨、条块结合的管理方式使得新闻媒体的管理机构形成了复杂的矩阵结构
  -  · p.172

## 党规—国法双重约束

> 在中国政府与政治中，行为合法性同时受国家法律和党内法规约束；分析法律问题必须把党规、党委文件与党政关系纳入。

- book: 
- lenses: law, politics
- confidence: medium · status: verified

### Applicable when

- 分析监管权限与政策合法性
- 判断执法、司法与地方治理风险
- 做合规与政治风险双重评估

### Inputs

- 法律与行政法规
- 党内法规与党委文件
- 机构权限与授权链条
- 司法审查与问责机制

### Steps

- 列明国家法上的权限依据。
- 列明党规与党委文件上的依据。
- 判断两者关系、冲突解决与效力层级。
- 确认执行主体是政府、党委还是两者共同。
- 评估法律问责与政治问责的双重风险，并注明不是法律意见。

### Outputs

- 双重合法性矩阵
- 权限边界与风险提示

### Failure modes

- 只看法条而忽略党规与党委文件。
- 把政策文件直接当作法律依据。
- 法律修订滞后或地方执行差异。

### Counterexamples

- 纯技术性、低政治敏感度的行政事项，国法可能是主要约束。
- 党内法规未公开时，外部分析只能给出条件性判断。

### Source citations

> 不但要了解国家法律和行政法规,也要了解党内法规和党委文件
  -  · p.20
> 把坚持党的领导,人民当家作主和依法治国有机统一起来
  -  · p.34
> 我们坚持依法治国、依法执政、依法行政共同推进
  -  · p.21
> 权力的行使开始纳入宪法和法律的轨道
  -  · p.31

## 国际组织影响框架

> 一个联邦组织所代表的比较密切的联合,也许其覆盖面起初甚至不能超越像西欧的某一局部地区那样狭小的一个区域,虽则它可以逐步得到扩展。

- book: 
- lenses: politics, law
- confidence: medium · status: verified

### Applicable when

- 国际组织影响国家主权

### Inputs

- 国际组织
- 国家主权

### Steps

- 分析国际组织
- 评估国家主权的影响
- 提出建议

### Outputs

- 建议

### Failure modes

- 忽视国际组织的影响
- 忽视国家主权的重要性

### Counterexamples

- 忽视国际组织的影响可能导致国家主权的丧失

### Source citations

> 一个联邦组织所代表的比较密切的联合,也许其覆盖面起初甚至不能超越像西欧的某一局部地区那样狭小的一个区域,虽则它可以逐步得到扩展。
  -  · p.142

## 极权主义利用民主框架

> 分析极权主义如何利用民主机制来巩固其地位。

- book: 
- lenses: politics
- confidence: medium · status: verified

### Applicable when

- 极权主义利用民主机制

### Inputs

- 民主机制
- 极权主义

### Steps

- 分析民主机制
- 评估极权主义的利用
- 提出防范建议

### Outputs

- 防范建议

### Failure modes

- 忽视极权主义的利用
- 忽视民主机制的脆弱性

### Counterexamples

- 忽视极权主义的利用可能导致民主机制的破坏

### Source citations

> 政府首脑一次又一次地通过人民投票巩固他的地位,使其能确保投票将按他所想往的方向进行。
  -  · p.43

## 自由主义适应性框架

> 评估自由主义原则在不同社会环境中的适应性。

- book: 
- lenses: economics, politics
- confidence: medium · status: verified

### Applicable when

- 自由主义原则需要适应变化

### Inputs

- 社会环境
- 自由主义原则

### Steps

- 分析社会环境
- 评估自由主义原则的适应性
- 提出适应性建议

### Outputs

- 适应性建议

### Failure modes

- 忽视自由主义原则的适应性
- 忽视社会环境的变化

### Counterexamples

- 忽视自由主义原则的适应性可能导致集中计划和极权主义

### Source citations

> 在自由主义的基本原则中没有什么东西能使它成为一个静止的教条,也不存在一成不变的一劳永逸的规则。
  -  · p.15

## 试点—推广的适应性政策过程

> 地方分散试验是党政体制的风险吸收机制：先试点、再评估、后推广，用地方差异换取中央政策的可纠错性。

- book: 
- lenses: politics, law
- confidence: medium · status: verified

### Applicable when

- 分析改革方案与监管创新
- 判断地方试点与政策扩散
- 评估中央—地方学习与纠错

### Inputs

- 试点授权与边界
- 地方方案与执行能力
- 评估指标与中央反馈
- 推广条件与地方竞争

### Steps

- 确认试点授权、法律边界与责任主体。
- 比较地方方案的差异与适用条件。
- 观察中央如何评估、选择与吸收地方经验。
- 判断推广受财政、法律还是政治条件约束。
- 识别试点失败的责任归属与止损机制。

### Outputs

- 试点—评估—推广路径图
- 可推广性条件与失败止损点

### Failure modes

- 试点被美化或选择性汇报。
- 推广忽视地方异质性。
- 试点成为寻租或政绩工程。

### Counterexamples

- 危机处置需要全国统一行动时，分散试点可能延误。
- 法律明确禁止地方变通时，试点空间收窄。

### Source citations

> 地方的分散试验并不威胁党政体制的基本原则
  -  · p.229
> 分散试验可以降低中央推行新政策的风险与成本
  -  · p.229
> 学界一般将领导小组视为议事协调机构,拥有跨部门的协调权力,但实际上这些领导小组享有更大的权力
  -  · p.19
> 将"党政体制"作为理解中国政府与政治的关键词
  -  · p.4

## 集中计划控制框架

> 当局所掌握的对所有消费的控制权的根源,就是它对于生产的控制。

- book: 
- lenses: economics
- confidence: medium · status: verified

### Applicable when

- 集中计划威胁个人自由

### Inputs

- 集中计划
- 个人自由

### Steps

- 分析集中计划
- 评估个人自由的威胁
- 提出保护建议

### Outputs

- 保护建议

### Failure modes

- 忽视集中计划的威胁
- 忽视个人自由的重要性

### Counterexamples

- 忽视集中计划的威胁可能导致个人自由的丧失

### Source citations

> 当局所掌握的对所有消费的控制权的根源,就是它对于生产的控制。
  -  · p.57
