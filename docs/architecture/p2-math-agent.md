# P2 本地数学研究与自主边界

v1.1 的实现补充，保留原方案原文。P2a 已先验证规则分支树；P2b 在同一队列接入实际本地模型。

## 推理和学习

推理运行在远程开发机的 Next 专用 CPU 容器，通过 Ollama 本地接口使用 `qwen3:1.7b`。
固定模型 manifest SHA256 为 `8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7`，
主 GGUF blob 为 `3d0b790534fe4b79525fc3692950408dca41171676ed7e21db57af5c65ef6ab6`，约1.36GB。
Ollama 镜像使用 compose.inference.yaml 中的固定摘要，关闭云功能；没有外部推理或付费模型回退。

每轮规划实际调用两次模型：先生成各数学方法的可证伪假设和受限配方，再读取真实数值工具结果、
失败分支和方向价值估计，选择下一候选。不同方法占用不同 JSON 字段，候选不能靠编号变化重复执行。
先覆盖尚未尝试的方法族；仅剩一个方法时，为短/长窗口预留不同候选。具体配方、解释、选择理由由模型生成。
这里的多样性约束是搜索政策，不能当作模型自行发明了数学方法。

红蓝预测网络使用真实梯度更新；方向价值网络为12输入、16隐藏单元、225参数的小网络，
从最多128个开发实验反馈学习收益，每次128步。奖励为蓝球损失下降减去红球恶化惩罚，裁剪到[-5,5]。
保留父策略版本、训练种子、样本身份、权重前后摘要和训练损失。几条经验的训练拟合不代表方向预测可靠。
推理模型的语言权重保持冻结；经验读取、提示修正和价值网络训练不冒充 LLM 微调。

## 实际数学方法

| 方法 | 候选实现 | 数值工具 | 限制 |
|---|---|---|---|
| 傅里叶 | 每个因果窗口对时间轴 rFFT，保留前4个频率槽，再逆变换输入神经网络 | 已知正弦与高频扰动的恢复误差 | 频谱峰不证明开奖周期；禁止全序列滤波后切历史 |
| 岭回归 | 窗口均值与截距构成50维输入，用正则线性方程拟合神经网络概率残差，混合权重0.25 | 线性方程残差与已知线性关系 | 仅用过去256个训练标签；正则化可能带来偏差 |
| 牛顿校准 | 从过去训练样本中排除最多32条作校准，阻尼牛顿与回溯线搜索拟合 log temperature | 先验小例子的校准损失、步数 | 固定 logits 的温度不会改变 Top1；不把训练/校准成绩当作目标期成绩 |

岭回归系数、温度、数学状态摘要与模型锚点共同保存。数学表示不兼容时重建当前锚点；
历史验证始终重新初始化，最新父权重不会进入较早期历史验证。
数值小例子只说明工具可用，实际候选仍必须经过冻结历史评分器。

实现参考：[NumPy rFFT](https://numpy.org/doc/stable/reference/generated/numpy.fft.rfft.html)、
[NumPy 线性方程求解](https://numpy.org/doc/stable/reference/generated/numpy.linalg.solve.html)、
[Ollama 结构化输出](https://docs.ollama.com/capabilities/structured-outputs)。
牛顿温度拟合是本仓库有限步实现，不声称调用了通用符号数学系统；黎曼几何等方法尚未接入。

## 资源与权限

每研究活动最多8节点、默认600秒/节点、最多8次模型调用，失败调用也计预算；没有无限自动开新活动。
推理一次最多1300输出 token、4096上下文、180秒请求超时、单请求、4 CPU/6GiB。
计算2 CPU/2GiB，规划1 CPU/1GiB，BLAS/OpenMP各2线程，P1任务优先。
模型仅拿到开发评价摘要和数学方法卡，不拿未来标签、隔离集或密钥；不执行模型生成的任意代码。
所有候选经静态方法注册表和参数范围校验，模型无法更改评分器、历史清单、权限或发布指针。

实际初始模型缓存约1.4GB，仅允许当前固定模型；10GiB模型缓存预算和完整100GiB包络的统一监测/回收在P3完成，
此版本没有实现全宿主机自动GC。应用产物继续受256MiB硬上限约束，单文件16MiB。
达到预算即停止研究，不反复生成同一活动；P1新数据学习仍常驻等待官方新开奖。
研究选中节点不直接替换P1模型。正式替换、隔离验证与长期FORWARD观测仍须后续交付。

## 运行

已有模型缓存后，使用完整 Compose 配置避免误把推理服务当作孤立容器：

```bash
docker compose -f compose.yaml -f compose.inference.yaml up -d inference
docker exec dehps-next-inference ollama list
docker compose -f compose.yaml -f compose.inference.yaml up -d worker planner api source
docker compose -f compose.yaml -f compose.inference.yaml run --rm worker research-create \
  --name local-research-001 --planner local --max-nodes 4
docker compose -f compose.yaml -f compose.inference.yaml run --rm worker research-status --name local-research-001
```

首次可在足够磁盘空间下运行 `docker exec dehps-next-inference ollama pull qwen3:1.7b`，
然后核实 `ollama list` 的模型身份。若镜像站/代理让标签内容变化，先核实新摘要并登记版本，不能静默继续。
本次环境因代理 fake-IP 触发下载重定向拒绝，通过官方 registry 获取同一 manifest 与 blobs，
逐文件按 manifest 验证大小和 SHA256 后装入 Next 缓存；未关闭下载器的安全检查。

发布改变会冻结已有研究代码身份。实现修订后停止活动任务，使用 `research-stop --name NAME --reason REASON`
标记旧活动为 SUPERSEDED，保留全部失败事实，重新创建新的冻结活动。P1兼容升级另用 adopt-release 留痕。
各活动内的普通推理、数学计算、训练、评分、剪枝、回退和换方向均自动执行，不需要逐轮人工审批。
