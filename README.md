# DEHPS Next

P0/P1 持续学习、P2 本地数学研究与 P3 常驻调度/资源/GC。完整设计见
[v1.1 重构方案](docs/architecture/dehps-next-v1.1.md)，本轮边界见
[P0 契约](docs/architecture/p0-contract.md)。

每轮执行：不可变数据快照 → 红蓝球神经网络训练 → 红球Top100与唯一蓝球Top1封存 →
开奖结果评价 → 消费该期标签并自动进入下一轮。预测网络默认106,801参数，CPU运行。
训练保留样本消费、参数更新、父子模型和数据版本证据，服务在线不等于模型正在训练。

**历史回放始终标为 REPLAY，不是开奖前预测，也不证明蓝球50%目标。**
P2 已实现同清单验证、剪枝、父状态恢复，以及本地模型提出假设、调用数学工具和根据反馈换方向。

## 隔离启动

所有命令在新仓库内执行。需要Docker与Compose；不安装宿主机Python依赖，不挂载旧目录。

```bash
python3 scripts/bootstrap-secrets.py
docker network inspect dehps-next-p0p1 >/dev/null 2>&1 || docker network create dehps-next-p0p1
docker compose up -d database
docker compose build
docker compose run --rm worker init
```

`.env`只存放Next专用凭据，自动以0600权限创建。数据库没有宿主机开放端口。

## 开奖历史与回放

已授权使用旧库时，可执行固定SELECT-only导出。该程序仅查询`public.ssq_history`至多5000条开奖事实，
不读取训练派生表，不修改旧数据库和代码。导出文件写到本仓库`runtime/imports`。

```bash
python3 scripts/export-legacy-history.py
docker compose run --rm -v "$PWD/runtime/imports:/imports:ro" worker import-json \
  /imports/legacy-draws.json --source legacy-readonly://dehps/ssq_history \
  --provenance OWNER_AUTHORIZED_LEGACY_HISTORY
docker compose run --rm worker sync
```

`sync`从福彩官方接口读取最近100期，校验与已导入事实的一致性，保存来源回执；冲突会终止该次导入，
不会覆盖已有开奖。官方数据只有日期时，按日末保守登记标签可用时间，不虚构精确发布时间。

选择一个训练起点；例如历史有3520条时，用前3508条作初始训练，连续回放余下12期：

```bash
docker compose run --rm worker create-loop --name history-p1 --mode REPLAY \
  --bootstrap 3508 --epochs 20 --max-cycles 64
docker compose up -d worker source api
docker compose run --rm worker status
```

起点与循环配置不可静默改变；命令重复执行相同配置会复用，配置不一致会报冲突。
数据耗尽显示`WAITING_FOR_DATA`，新开奖导入后自动接续；达到预设轮数预算显示`PAUSED_CYCLE_BUDGET`。
等待不会产生虚假训练轮次，也不反复对同一身份重训。

回放到历史末尾后，还会执行一个明确标记为`REFIT`的纯学习任务，将最新一期标签吸收进模型；
它不生成虚构的下一期预测，也不产生评价成绩。即使缺少下一期日程，收到新标签仍会更新模型。
`--max-cycles`包括预测和纯学习任务，总预算耗尽如实暂停。

## 真正开奖前预测

先从可靠来源核实下一期期号、开奖时间与截止时间，再登记未来日程。禁止用此命令补造历史预测。

```bash
docker compose run --rm worker expect --issue VERIFIED_ISSUE \
  --draw-at 'VERIFIED_ISO_TIME_WITH_TIMEZONE' --deadline 'EARLIER_VERIFIED_ISO_TIME_WITH_TIMEZONE'
docker compose run --rm worker create-loop --name forward-p1 --mode FORWARD --bootstrap 64
```

以上是参数说明，示意占位符不能执行。未来日程有效且标签尚未知时，Worker自动训练并实际封存；
标签导入后再结算、继续等待下一份已核实日程。缺日程显示`WAITING_FOR_TARGET_SCHEDULE`。
P1不猜节假日开奖和跨年期号，日程自动同步属于后续工作。

## 状态与证据

- 本机健康接口：`http://127.0.0.1:8341/health`、`/ready`。
- `/status`、`/evidence/{loop_id}`需要`.env`内Next API token，不在页面或日志中显示token。
- 只读API无写入路由、无默认跨域许可，不替代后续操作看板。
- `models.manifest`保存参数数、权重前后摘要、实际训练步数、标签与上下文期次。
- `consumptions`记录每个模型实际用作标签的期次、次数与相对父模型新增消费。
- 封存预测、开奖、数据集、模型、评价由数据库触发器禁止更新或删除。

每个任务有租约和递增执行尝试，过期执行不能提交。训练每5个epoch保存两个交替恢复槽，
含权重、优化器、随机状态和输入摘要；成功提交后才回收本任务恢复文件。
P3将应用产物限额设为1GiB，每文件16MiB，并预留活跃任务写入空间。
宿主机100GiB包络、数据库/WAL、镜像和模型缓存上界由独立主机代理计量；详见P3政策。

## 验证与停止

遵循 [AGENT.md](AGENT.md)：不新增单元测试，不增加无用 CI；原 P1 工作流仅保留手动触发。
通过 lint、编译及真实 Next 数据库/产物的运行验收验证，并提交小型验收报告。
每个 PR 由 Codex 手动 squash merge，再核实远端 main。

```bash
docker compose stop worker source api
```

停止只作用于Next，不操作旧DEHPS。默认保留Next数据库卷和运行证据。

## P2a 自动分支探索

```bash
docker compose run --rm worker research-create --name research-001 --planner rules --max-nodes 3
docker compose run --rm worker research-status --name research-001
```

研究快照只来自Next独立数据库。正式Compose配置冻结最近100期，并用嵌套近50期、近10期复核；不抽取随机历史验证起点。
每个原点只使用该期之前的数据按配方时间窗口训练；当前父模型用于恢复锚，发布锚与历史回归使用同一独立训练契约。
主要比较红球Top100红5及以上的期命中率和唯一蓝球Top1命中率，记录小幅增量、权衡和不确定性；50%不是改善门槛。
100/50/10总共100个不同期次，重复搜索和区间估计不变成更多独立证据。旧随机历史协议的冻结实验保留。

分支经过现有租约队列执行，保存配方、来源、模型/优化器/随机状态、分数、剪枝与恢复记录。
规则规划器用于先验收执行链；达到节点预算即停止，不自动无限开新主题。
研究节点的接受先变更研究指针；通过独立发布守卫后，才可在17:00暂停收尾后选为当期邮件预测。
发布代码改变会阻止旧活动任务；兼容性审查后可用 `adopt-release --loop NAME --reason AUDIT_REASON`
登记 P1 循环兼容升级。研究活动保持冻结代码身份，不提供静默升级。

[实际 P2a 验收](docs/acceptance/p2a-20261029.md)记录真实的 `1 → 1-1 → 剪枝恢复1 → 1-2`。
数据库迁移002为追加结构，降级应用时保留新表与失败事实；不要将旧 P1 Worker 连接到含研究任务的队列。

## P2b 本地数学研究

使用 Next 专用本机推理容器内的 `qwen3:1.7b`，无外部推理回退。模型先提出假设，实际调用数学工具，
再读取工具结果和实验反馈选择候选。已实现因果窗口傅里叶、岭回归残差头与牛顿温度校准，
并实际训练225参数的方向价值网络。推理大模型权重保持冻结，不能把提示修正称为 LLM 微调。

[本地模型运行与边界](docs/architecture/p2-math-agent.md)包含完整启动命令、模型身份、资源限制与故障处理。
[实际 P2b 验收](docs/acceptance/p2b-20261029.md)记录三种数学分支、真实模型调用及中断恢复。
单活动达到预算后停止，由P3常驻程序安排不同问题；P1等待新开奖。
任意候选代码沙箱与隔离最终验证仍需后续完善，不能将有限方法注册表描述成无限自主发现能力。

## P3 常驻研究与容量管理

先创建 `runtime/host`，将 `deploy/dehps-next-host-agent.service` 安装到用户systemd并启用，
再使用完整配置启动 `worker planner steward source api inference`。
主机代理仅处理Next范围；应用没有Docker socket。真实准入、可恢复GC和每日额度默认启用。

```bash
mkdir -p runtime/host ~/.config/systemd/user
cp deploy/dehps-next-host-agent.service ~/.config/systemd/user/
systemctl --user daemon-reload
docker compose -f compose.yaml -f compose.inference.yaml run --rm worker init
docker compose -f compose.yaml -f compose.inference.yaml up -d
systemctl --user enable --now dehps-next-host-agent.service
docker compose -f compose.yaml -f compose.inference.yaml run --rm worker program-enable \
  --name autonomous-v2 --interval 30 --max-daily 12 --max-nodes 8 --planner local
```

推理模型需按P2文档预先安装。程序每天最多12个活动、每活动8节点，24次推理和7200容量秒的总额度保持不变，冷却和额度跨进程重启保留。
同一历史复用快照与评分数组；过期研究明细、尝试和镜像按引用、TTL和宽限期回收，正式模型与活跃恢复输入受保护。
同一数据继续探索尚未尝试的有限配方；推理额度不足时由已训练的方向价值网络选择新方向。只有配方空间或算力预算耗尽才等待。
`/status`显示程序、额度、预留、回收及宿主机上界。缺少新鲜遥测时明确等待，不能猜测资源足够。

[P3运行政策](docs/architecture/p3-autonomous-lifecycle.md) · [P3实际验收](docs/acceptance/p3-20261029.md)

## 邮件报告与数据更新

按2026-10-29最新要求取消看板开发，邮件作为主要交付；保留只读API作运维核验。
`source`每15分钟直接同步福彩官方结果到Next独立数据库，不依赖旧库继续更新，不调用旧更新脚本。
历史已授权导入3520期，旧库来源标签保留；重复官方核对不会改写原始事实或重复存整份回执。

`reporter`常驻服务每30秒检查上海时区日程：持续训练并执行近100期、近50期、近10期顺序回归；开奖日17:00暂停训练并保存检查点，随即完成封存、发送红球Top100/唯一蓝球Top1，不等待19:00，
无合格候选时仍发送明确标注的Top100研究参考及未通过原因，不能用提前验收记录替代；官方完整结果入库并结算后发送复盘。相同收件人/期号/报告类型有持久去重，重启不会重复发送。
SMTP明确接收才记SENT；可能送达但回执丢失记UNKNOWN，不盲目重发。旧系统服务与定时任务保持不动。

将Next专用SMTP配置放入0600的`.mail.env`：`DEHPS_NEXT_SMTP_HOST`、`DEHPS_NEXT_SMTP_PORT`、
`DEHPS_NEXT_SMTP_USER`、`DEHPS_NEXT_SMTP_PASSWORD`、`DEHPS_NEXT_MAIL_TO`。仅reporter读取，禁止提交Git。
Compose的可选邮件文件配置需要Compose 2.24或更新版；没有邮件配置时核心服务仍可启动，邮件发送会明确报配置问题。

```bash
docker compose -f compose.yaml -f compose.inference.yaml up -d source reporter worker
```

首次官方核实完整结果的时间另存为不可变记录，使开奖后复盘不用等到日末；不覆盖旧日期型可用时间。
已核实日历覆盖2026-10-05至2026-12-31；跨年、过期日程或数据断档明确提醒，不猜期号、不补造历史预测。
[邮件与迁移验收](docs/acceptance/mail-20261029.md)记录实际SMTP接收及提前验收封存，已由新的[延后封存与回归政策](docs/architecture/final-seal-regression.md)排除出正式邮件统计。

## 2核按需常驻（2026-10-29 后续修订）

用户明确选择日上限172800容量秒、24次本机推理。活动轮数不再截停，活动间不强制冷却；保留已用计数、存储硬上限、正式任务优先及当前晚间封存限制。普通研究产物可在容量压力下安全回收，精简配方记忆独立保留；局部课程结束后进入更长历史/正则化课程，不把同一数据上的研究默认停为等待新开奖。

[最新执行政策与实际停机审计](docs/architecture/continuous-capacity-policy.md)优先于前面P3初版的7200容量秒/12轮默认说明。

## 最新核数分配

用户已选择训练8核、Qwen最多4核、规划1核，研究日上限同步为691200容量秒、24次推理，旧消耗不清零。线程变化须在旧活动结束后登记，历史评分严格匹配训练线程。详见[8核分配政策](docs/architecture/eight-core-allocation.md)和[实际验收](docs/acceptance/eight-core-20261029.md)。这条更新优先于上方2核政策。

## 本地用量统计最新政策

本地Qwen不按消耗计费，也不再按日容量秒、调用次数或token累计截停。保留8/4/1实时核数和内存/存储等保护，只通过 `dehps-next token-usage`、只读status及正常报告展示实际输入/输出token。旧额度记录仅为历史，budget-set退役；此政策覆盖上面的每日691200/24说明。[执行政策](docs/architecture/local-token-observability.md) · [真实Qwen验收](docs/acceptance/local-token-20261029.md)。

当前规则见 [并行历史起点与17:00报告](docs/architecture/parallel-origins-and-pause.md)。17:00开始暂停收尾，完成即发；19:30仅为故障兜底截止，不作为正常等待时间。每日容量秒/调用用量限额已由后续token观察政策取消。

当前CPU分区采用Next独立CPU0-19、系统LP-E CPU20-21；训练与Qwen线程按真实吞吐选定，详见[CPU分区与吞吐](docs/architecture/cpu-pool-throughput.md)。部署前先执行管理员脚本prepare，所有Next容器迁入独立slice后才能apply系统限制；restore-host可恢复原系统CPU范围。


## 2026-10-30 全GPU推理

实测后默认Qwen经Intel Arc Vulkan全29层卸载，CPU辅助最多4；预测训练仍为CPU8、规划1，两个LP-E核继续留给系统。固定同量工作块重复对照快34%–54%；真实3节点活动127.24→119.64秒，但GPU选择了不同、更重的分支，不能把两者当成严格同量加速。温度只记录，不作为选型门槛。[完整验收与显式CPU回退](docs/acceptance/gpu-qwen-20261030.md)。此更新替代上方默认CPU空闲12/繁忙4方案；原CPU方案保留为显式回退。


GPU启用后的[训练CPU扩容复测](docs/acceptance/training-gpu-scaling-20261030.md)比较8/12/16/20线程，保留训练8；GPU并发时12线程训练更慢、整个周期没有可用加速，未为填满CPU而升配。

当前历史起点训练使用8个独立进程，每个1个Torch线程，合计8 CPU配额；Qwen全GPU不变。完整固定工作量闭环83.76s→64.99s，耗时下降22.4%。数学与线程兼容性、暂停/恢复、报告Top100和结果复盘见 [实测验收](docs/acceptance/parallel-origins-20261030.md)。

最新研究控制器与业务核验见 [去重新候选与有界流水线](docs/architecture/qwen-candidate-pipeline.md)。新轮使用近100/50/10期递进核验，逐步比较红球Top100红5+期命中率和蓝球Top1命中率；50%不是发现改善的门槛。旧随机历史冻结实验保留。Qwen只选择全量去重后的候选并引用具体反馈；流水线最多两个待完成训练节点，父状态变化时作废旧计划。可用compose.research.serial.yaml在排空冻结轮后回退串行，保留新反馈、近期核验和17:00日程。
