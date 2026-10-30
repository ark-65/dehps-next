# init.scope开机CPU保留修正

2026-10-30。PR11上线后真实检查发现system/user限制写入/etc/systemd/system.control，而init.scope的50-AllowedCPUs.conf位于/run/systemd/transient，单靠set-property不足以证明重启后保留。

新增dehpsnext-cpu-reservation.service，After=dbus.service和独立Next slice，Before=docker.service，Type=oneshot、RemainAfterExit，开机重新设置init.scope为20-21。管理员prepare安装单元，apply在所有Next容器迁移检查后enable --now，check要求单元enabled/active；回退时disable --now。

实际管理员prepare/apply通过：启动单元FragmentPath位于/etc/systemd/system，UnitFileState=enabled、ActiveState=active、Result=success、ExecMainStatus=0，Before包含docker.service。system/user/init有效CPU均20-21，Next有效CPU0-19，8个容器亲和性全部0-19，APIready。没有重启应用或整机；这证明配置持久化及单元当次执行成功，不冒充整机重启实测。

Ruff、Python编译、systemd-analyze verify及diff检查通过。当前systemd259对既有slice的CPUAccounting选项给出已移除/忽略提示，CPU亲和性和读取cgroup的容器统计均正常，不把该提示当成单位绑定失败。无新增单元测试或CI，应用代码/数值身份及冻结线程配置保持PR11版本。
