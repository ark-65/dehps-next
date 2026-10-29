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

研究快照只来自 Next 已导入的数据。当前默认冻结最近100期（最近10期另列守卫）、十个时间分层随机抽取200期及40个备用期，
重叠去重；历史每个原点均从当时可用的前缀重新训练，当前父模型仅供研究恢复锚点继承；发布锚点按与历史回归一致的独立训练流程生成。
同清单比较蓝球对数损失，并约束红球 Brier 分数；配对区块 bootstrap 仅作为开发期证据。
不确定时使用一次预定有限复核，仍不确定则保留父节点。

分支经过现有租约队列执行，保存配方、来源、模型/优化器/随机状态、分数、剪枝与恢复记录。
规则规划器用于先验收执行链；达到节点预算即停止，不自动无限开新主题。
研究节点的接受先变更研究指针；通过独立发布守卫后，才可在16:59–17:00选为当期邮件预测。
发布代码改变会阻止旧活动任务；兼容性审查后可用 `adopt-release --loop NAME --reason AUDIT_REASON`
登记 P1 循环兼容升级。研究活动保持冻结代码身份，不提供静默升级。

[实际 P2a 验收](docs/acceptance/p2a-20261029.md)记录真实的 `1 → 1-1 → 剪枝恢复1 → 1-2`。
数据库迁移002为追加结构，降级应用时保留新表与失败事实；不要将旧 P1 Worker 连接到含研究任务的队列。

## P2b 本地数学研究

使用 Next 专用 CPU 容器内的 `qwen3:1.7b`，无外部推理回退。模型先提出假设，实际调用数学工具，
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

`reporter`常驻服务每30秒检查上海时区日程：持续训练并执行近100期、最近10期与随机历史回归；开奖日16:59–17:00才封存、17:00发送红球Top100/唯一蓝球Top1，
无候选通过守卫则发送未通过状态，不能用提前验收记录替代；官方完整结果入库并结算后发送复盘。相同收件人/期号/报告类型有持久去重，重启不会重复发送。
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

用户明确选择日上限172800容量秒、24次本机推理。活动轮数不再截停，活动间不强制冷却；保留已用计数、存储硬上限、正式任务优先及16:59–17:00封存限制。普通研究产物可在容量压力下安全回收，精简配方记忆独立保留；局部课程结束后进入更长历史/正则化课程，不把同一数据上的研究默认停为等待新开奖。

[最新执行政策与实际停机审计](docs/architecture/continuous-capacity-policy.md)优先于前面P3初版的7200容量秒/12轮默认说明。
