# 2核按需常驻研究政策

2026-10-29 用户明确选择：取消轮数截停，日研究上限172800容量秒，暂保留每天24次本机大模型调用。计算Worker的2 CPU/2 GiB、正式任务优先级、1 GiB应用产物硬上限和宿主机/存储保护均保留；不操作旧DEHPS。172800是容量秒上界，不冒充实际CPU秒。

## 线上审计

15:48–16:07，同一数据版本实际完成9个活动、72节点、20920次历史起点拟合、380736个记录梯度步骤，63个不同子方向。原点参数更新标记72/72，抽查三个父锚点实际读取并恢复，权重、优化器、RNG及数学状态与登记摘要全部一致。发生5次确认退步剪枝和58次不确定回退，共63次恢复与换方向。没有线上确认改进，不能称预测能力已进化成功。

16:07程序被“当天12轮”截停（包括旧程序3轮），当时只花费6368.381737/7200容量秒。状态是WAITING_DAILY_BUDGET，不是WAITING_NEW_DATA，也不是算力或存储不足。历史采样显示训练期间平均1.0367逻辑核，占22核约4.712%；暂停后一分钟平均0.00798核，占约0.0363%。资源状态表原先还保留了更早的遥测故障原因，新的成功准入会刷新为ADMITTED。

这一批新活动没有新的LLM调用：原账本23/24、每次完整推理决策需要2次调用，所以实际由已训练的方向价值网络选新配方，再训练预测网络。不能把planner=local配置称为每一轮都调用了大模型。LLM权重保持冻结，预测网络及225参数方向网络实际训练。

## 常驻调度

`max_daily=0`表示不再按活动轮数截停，`interval=0`表示活动结束后可在同次调度进入下一主题。5秒推进调度，GC仍最多每30秒扫描；不靠提高GC轮询消耗CPU。已发生次数、实际消耗和失败调用保留。

CPU容量预算、调用预算、内存、硬盘、写入预留、正式任务抢占和任务生命周期限制仍分别执行。没有新开奖不会阻止在同一快照研究；预算耗尽、硬资源不足或全部注册课程耗尽时必须准确说明原因，不伪造工作或重复失败配方来占CPU。

## 数值身份及实验记忆

全发布代码身份继续冻结任务执行。另有数值身份，覆盖domain/model/research_compute/research_math/research_protocol/scores六个源文件及Torch/NumPy版本；缓存还绑定数据内容、配方、协议、线程数。旧发布只有经过显式数值等价审核登记后才可复用，不能因为改了调度就重算整批相同历史。

`research_recipe_memory`保留数据版本、数值身份、配方摘要、结果及简要分数，与可回收的大模型产物分开。控制器升级和分支明细回收不丢失同一数值语义下的尝试记录。每对数据/数值身份最多16384配方，普通记忆保留最新8对，活跃数据另外保护。正式封存和评分证据不受该回收影响。

课程从局部窗口进入更长历史和更强正则化：第一组用历史128/256；耗尽后可研究512/1024、28/40轮训练；进一步探索较小网络、4–64窗口及更强收缩。仍是有界注册数学方法研究，不是任意新算法发现。所有组继续使用同一近100、最近10、分层随机历史协议，不能通过换课程降低验证标准。

## 容量压力

应用产物达到70%配额后，GC可缩短已完成普通研究产物的保留时间，仍经过写入租约、引用保护、标记和60秒宽限再检查。保护所有核心事实与正式评分、活跃输入、最近两个活动的恢复锚点、缓存和显式pin。保留精简配方记忆，防止回收后再次尝试同一失败方向。普通无压力保留政策继续是7天；不增加磁盘硬上限。

## 操作

```bash
dehps-next init
dehps-next numeric-adopt --release OLD_RELEASE_DIGEST --reason 'Audit numerical files, dependency versions and thread configuration before reuse'
dehps-next program-adopt --name autonomous-v2 --reason 'Controller and GC upgrade with audited identical numerical evaluation'
dehps-next program-continuous --name autonomous-v2 --reason 'Owner selected two-core on-demand continuous research; preserve existing counters'
dehps-next budget-set --capacity-seconds 172800 --model-calls 24 --reason 'Owner selected two-core on-demand continuous research on 2026-10-29'
```

这些操作不清零旧账，不静默升级活动中的冻结任务，不改变16:59–17:00封存及17:00邮件规则。代码/实际运行、长期稳定性和预测能力分别验收。
