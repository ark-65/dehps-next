"""Mail-only pre-draw forecast and authoritative post-draw settlement scheduling."""

from datetime import UTC

from psycopg.types.json import Jsonb

from .calendar import CALENDAR, ZONE, next_target
from .domain import now
from .errors import DomainError
from .forecast import LOOP, Forecast
from .mail import Mail
from .scheduler import Scheduler


class Reports:
    def __init__(self, db, artifacts, clock=None):
        self.db, self.artifacts = db, artifacts
        self.mail = Mail(db)
        self.clock = clock or now

    def prepare(self, force=False):
        latest = self.db.rows("SELECT * FROM draws ORDER BY draw_at DESC LIMIT 1")
        if not latest:
            raise DomainError("NO_HISTORY", "No authoritative history to prepare forecast")
        target = next_target(latest[0])
        clock = self.clock().astimezone(ZONE)
        if clock.date() > target["day"]:
            raise DomainError(
                "SOURCE_STALE", "Previous scheduled draw has not arrived; do not guess a later issue"
            )
        if clock.date() == target["day"] and target["prepare_time"] <= clock < target["deadline_time"]:
            # Preparation registers a schedule only. Even force cannot seal a forecast early.
            Scheduler(self.db, self.artifacts).expect(
                target["issue"],
                target["draw_time"].isoformat(),
                target["deadline_time"].isoformat(),
                at=self.clock(),
            )
        return target

    def pre_payload(self, prediction, target):
        data = prediction["payload"]
        summary = self.forward_summary()
        selection = self.db.rows(
            "SELECT evidence FROM effective_forecast_selections WHERE issue=%s", (prediction["issue"],)
        )[0]["evidence"]
        windows = selection["windows"]
        return {
            "title": f"[DEHPS Next] {prediction['issue']}期最终开奖前分析与号码报告",
            "send_deadline_utc": target["deadline_time"].astimezone(UTC).isoformat(),
            "blue": data["blue_top1"],
            "tickets": data["red_top100"],
            "lines": [
                *self.revision_lines(prediction["issue"]),
                f"期号：{prediction['issue']}；开奖：{target['draw_time'].strftime('%Y-%m-%d %H:%M')}（上海时间）",
                f"证据：真实开奖前封存 FORWARD；封存：{prediction['sealed_at'].astimezone(ZONE).isoformat()}",
                f"历史截至：{prediction['through_issue']}；模型：{prediction['model_id'][:16]}；神经网络实际训练已完成。",
                self.validation_line(windows, selection.get("business")),
                f"门槛：同一冻结清单、父节点比较、蓝球损失及红球约束通过；研究节点 {selection['path']}，协议 {selection['protocol_digest'][:16]}。",
                "当前为研究性推荐；开发回归通过不代表稳定优于随机，也不代表50%业务目标达标。此前提前生成的验收预测不作为这封正式报告的预测。",
                f"唯一蓝球 Top1：{data['blue_top1']:02d}；红球 Top100 组合见下表。排序分数不等于中奖概率。",
                f"已结算前向蓝球：{summary['hits']}/{summary['n']}；红5及以上：{summary['red5_hits']}/{summary['n']}（含覆盖缺口 {summary['missing']} 期）。历史开发指标的缓步提高不代表已建立前向能力。",
                "训练日程：开奖日17:00暂停，收尾完成即封存发信，不等待19:00；本期完整官方结果核验后恢复。",
                "数据使用 Next 独立数据库；初始历史来自授权导入，后续开奖直接同步福彩官方。",
            ],
        }

    @staticmethod
    def validation_line(windows, business=None):
        labels = {
            "recent": "近100期",
            "recent50": "近50期",
            "recent10": "近10期",
            "random_historical": "历史抽样",
        }
        parts = []
        for key in ("recent", "recent50", "recent10", "random_historical"):
            if key not in windows:
                continue
            w = windows[key]
            text = f"{labels[key]}蓝球{w['blue_top1_hits']}/{w['n']}"
            if business:
                text += f"、红5及以上{business['windows'][key]['red5_periods']}/{w['n']}"
            parts.append(text)
        return (
            "开发回归："
            + "；".join(parts)
            + "。按相同冻结期次比较小幅进步；重叠窗口不是独立证据，50%不是改善门槛。"
        )

    def revision_lines(self, issue):
        if self.db.rows("SELECT 1 FROM forecast_schedule_reopenings WHERE issue=%s", (issue,)):
            return [
                "日程修正：17:00是暂停及收尾开始时间，完成即发送。此前17:00状态邮件保留为历史，本封是按新日程生成的最终报告。"
            ]
        return []

    def forward_summary(self):
        return self.db.rows("""SELECT count(*) AS n,coalesce(sum((e.metrics->>'blue_top1_hit')::int),0) AS hits,
            count(*) FILTER(WHERE s.state='MISSED') AS missing,
            coalesce(sum(((e.metrics->>'red_max_matches')::int>=5)::int),0) AS red5_hits FROM effective_forecast_selections s
            JOIN effective_draws d ON d.issue=s.issue LEFT JOIN evaluations e ON e.cycle_id=s.cycle_id
            WHERE d.available_at<=now() AND d.draw_at<=now()""")[0]

    def predictions(self):
        return self.db.rows(
            """SELECT p.*,cy.dataset_id,ds.through_issue FROM predictions p JOIN cycles cy ON cy.id=p.cycle_id
            JOIN datasets ds ON ds.id=cy.dataset_id WHERE cy.loop_id=%s ORDER BY p.sealed_at DESC LIMIT 32""",
            (LOOP,),
        )

    def tick(self, prepare_now=False, deliver=True):
        state = {
            "at": self.clock().isoformat(),
            "calendar": CALENDAR,
            "mode": "MAIL_ONLY",
            "reason": "WAITING_SCHEDULE",
        }
        from .training_window import status as training_window

        with self.db.pool.connection() as c:
            state["training_window"] = training_window(c, self.clock())
        target = None
        try:
            target = self.prepare(prepare_now)
            clock = self.clock().astimezone(ZONE)
            state["phase"] = (
                "FINAL_PREPARATION"
                if target["prepare_time"] <= clock < target["seal_time"]
                else "FINAL_SEAL"
                if target["seal_time"] <= clock < target["mail_time"]
                else "FINAL_REPORT"
                if target["mail_time"] <= clock < target["deadline_time"]
                else "CONTINUOUS_RESEARCH"
            )
            if (
                target["day"] == clock.date()
                and target["prepare_time"] <= clock < target["deadline_time"]
                and self.db.rows(
                    "SELECT 1 FROM jobs WHERE kind IN ('TRAIN','RESEARCH_EVALUATE','RESEARCH_PLAN') AND state='RUNNING' AND lease_until>now() LIMIT 1"
                )
            ):
                raise DomainError(
                    "WAITING_TRAINING_CHECKPOINT",
                    "Waiting for the last bounded training/plan operation to pause",
                )
            state["draft"] = Forecast(self.db, self.artifacts, clock=self.clock).preview()
            if target["seal_time"] <= clock < target["deadline_time"]:
                state["seal"] = Forecast(self.db, self.artifacts, clock=self.clock).seal(target)
            if target["day"] == clock.date() and clock >= target["mail_time"]:
                prediction = Forecast(self.db, self.artifacts, clock=self.clock).for_report(
                    target,
                    {
                        "reason": "NO_VALIDATED_FORECAST_AT_FINAL_MAIL",
                        "draft": state["draft"],
                        "goal50": "UNPROVEN",
                        "business_coverage": "MISSED_COUNTS_AS_NON_HIT",
                    },
                )
                existing = self.db.rows(
                    """SELECT id FROM mail_reports WHERE issue=%s AND kind='PRE_FINAL' """,
                    (target["issue"],),
                )
                if existing:
                    state["reason"] = "PRE_REPORT_ALREADY_QUEUED"
                elif clock >= target["deadline_time"]:
                    state["reason"] = "PRE_REPORT_DEADLINE_PASSED"
                    self.alert(
                        state["reason"], "下午报告未能在发送截止前完成；封存事实保持原样，不补造预测。"
                    )
                elif prediction:
                    self.mail.queue(
                        "PRE_FINAL",
                        prediction["issue"],
                        self.pre_payload(prediction, target),
                        "FORWARD",
                        prediction["cycle_id"],
                    )
                    state["reason"] = "PRE_REPORT_QUEUED_OR_ALREADY_SENT"
                else:
                    state["reason"] = "NO_VALIDATED_FORECAST_AT_FINAL_MAIL"
                    reference = Forecast(self.db, self.artifacts, clock=self.clock).reference(target)
                    self.mail.queue(
                        "PRE_FINAL",
                        target["issue"],
                        {
                            **{k: reference[k] for k in ("blue", "tickets", "reference")},
                            "title": f"[DEHPS Next] {target['issue']}期Top100研究参考与开奖前校验报告",
                            "send_deadline_utc": target["deadline_time"].astimezone(UTC).isoformat(),
                            "lines": [
                                *self.revision_lines(target["issue"]),
                                "17:00收尾时仍没有完成合格候选封存，本期无通过门槛的正式推荐。",
                                f"{'近100期、近50期、近10期' if self.db.settings.research_validation == 'recent-windows-v4' else '近100期、近10期与历史抽样'}核验状态：{state['draft']['state']}",
                                f"校验未通过原因：{(state['draft'].get('gate') or {}).get('reasons', ['尚无完整验证结果'])}",
                                "17:00停止训练并收尾复核，完成即封存、发送，不等待19:00；19:30仅为故障兜底截止。本期官方开奖号核验后自动恢复训练。",
                                "提前验收预测已保留为验收记录，不算本期正式报告；业务覆盖缺口如实计入。50%目标未建立。",
                                *reference["lines"],
                            ],
                        },
                        "STATUS",
                    )
            else:
                state["reason"] = (
                    "FINAL_PREPARATION"
                    if target["prepare_time"] <= clock < target["mail_time"]
                    else "WAITING_PREPARATION"
                    if clock.date() == target["day"]
                    else "WAITING_DRAW_DAY"
                )
        except DomainError as exc:
            state["reason"] = exc.code
            if exc.code != "WAITING_TRAINING_CHECKPOINT" and self.clock().astimezone(ZONE).hour >= 17:
                self.alert(exc.code, str(exc))
        for row in self.db.rows(
            """SELECT p.*,e.metrics,d.red,d.blue,d.issue AS actual_issue,ds.through_issue
                FROM evaluations e JOIN predictions p ON p.cycle_id=e.cycle_id JOIN cycles cy ON cy.id=e.cycle_id
                JOIN draws d ON d.issue=e.issue JOIN datasets ds ON ds.id=cy.dataset_id
                WHERE cy.loop_id=%s AND e.mode='FORWARD' AND EXISTS(SELECT 1 FROM mail_reports pre WHERE pre.kind IN ('PRE','PRE_FINAL') AND pre.cycle_id=p.cycle_id) AND NOT EXISTS(SELECT 1 FROM mail_reports r WHERE r.kind='POST' AND r.issue=e.issue) ORDER BY e.created_at DESC LIMIT 32""",
            (LOOP,),
        ):
            self.mail.queue("POST", row["issue"], self.post_payload(row), "FORWARD", row["cycle_id"])
        for missed in self.db.rows("""SELECT s.issue,d.red,d.blue FROM effective_forecast_selections s JOIN effective_draws d ON d.issue=s.issue
            WHERE s.state='MISSED' AND d.available_at<=now() AND d.draw_at<=now()
            AND NOT EXISTS(SELECT 1 FROM mail_reports r WHERE r.kind='POST' AND r.issue=s.issue) LIMIT 32"""):
            reference_lines = []
            prior = self.db.rows(
                "SELECT payload FROM mail_reports WHERE kind='PRE_FINAL' AND issue=%s", (missed["issue"],)
            )
            if prior and prior[0]["payload"].get("reference"):
                payload = prior[0]["payload"]
                matches = [len(set(ticket) & set(missed["red"])) for ticket in payload["tickets"]]
                reference_lines = [
                    f"开奖前冻结研究参考蓝球{payload['blue']:02d}：{'命中' if payload['blue'] == missed['blue'] else '未命中'}；红球Top100最高命中{max(matches)}/6。",
                    f"研究参考命中分布：{ {str(i): matches.count(i) for i in range(7)} }；该参考结果不混入合格推荐统计。",
                ]
            self.mail.queue(
                "POST",
                missed["issue"],
                {
                    "title": f"[DEHPS Next] {missed['issue']}期开奖结果与研究状态",
                    "lines": [
                        f"官方开奖号：{missed['red']} + {missed['blue']:02d}",
                        "本期最终报告截止前未完成合格封存，无正式预测可结算；业务指定期次计为未命中并记录覆盖缺口。",
                        "不会拿提前验收预测、历史回放或开奖后预测补造本期命中。50%目标未建立。",
                        *reference_lines,
                    ],
                },
                "STATUS",
            )
        overdue = self.db.rows(
            "SELECT p.issue FROM predictions p JOIN cycles cy ON cy.id=p.cycle_id JOIN targets t ON t.issue=p.issue WHERE cy.loop_id=%s AND t.draw_at<now()-interval '1 hour' AND NOT EXISTS(SELECT 1 FROM mail_reports r WHERE r.kind='POST' AND r.issue=p.issue) LIMIT 1",
            (LOOP,),
        )
        if overdue:
            self.alert("POST_REPORT_PENDING", "官方结果或封存结算尚未完成，不会生成虚假的开奖结果汇总。")
        if deliver:
            state["delivery"] = self.mail.deliver_one()
        with self.db.pool.connection() as c:
            c.execute(
                "INSERT INTO report_state VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (Jsonb(state),),
            )
        return state

    def alert(self, code, message):
        day = self.clock().astimezone(ZONE).date().isoformat()
        self.mail.queue(
            "ALERT",
            day + ":" + code,
            {
                "title": f"[DEHPS Next] {day} 报告状态提醒",
                "lines": [
                    f"状态：{code}",
                    message,
                    "未生成或未送达的预测不会记为成功；请查看系统状态或后续邮件。",
                ],
            },
            "STATUS",
        )

    def post_payload(self, row):
        metrics = row["metrics"]
        history = self.forward_summary()
        return {
            "title": f"[DEHPS Next] {row['issue']}期开奖结果与预测复盘",
            "lines": [
                f"官方开奖号：{' '.join(f'{v:02d}' for v in row['red'])} + {row['blue']:02d}",
                f"开奖前蓝球推荐：{row['payload']['blue_top1']:02d}；结果：{'命中' if metrics['blue_top1_hit'] else '未命中'}",
                f"红球Top100最高命中：{metrics['red_max_matches']}/6；命中分布：{metrics['red_hit_distribution']}",
                f"蓝球对数损失：{metrics['blue_log_loss']:.6f}；简单历史基线：{metrics['baseline_blue_log_loss']:.6f}",
                f"累计真实前向蓝球命中：{history['hits']}/{history['n']}（含覆盖缺口 {history['missing']} 期）；历史回放单独统计，不混入本项。",
                f"本次严格比对已封存预测 {row['payload_digest'][:16]}；封存时间 {row['sealed_at'].astimezone(ZONE).isoformat()}",
                "这是命中和概率复盘，不是实际购票或奖金到账证明；50%目标未建立。",
            ],
        }

    def acceptance(self):
        predictions = self.predictions()
        if not predictions:
            raise DomainError("WAITING_SEALED_FORECAST", "Prepare and seal a genuine future forecast first")
        latest = self.db.rows("SELECT * FROM draws ORDER BY draw_at DESC LIMIT 1")[0]
        payload = self.pre_payload(predictions[0], next_target(latest))
        payload["title"] = "[DEHPS Next 验收] 邮件、官方同步与开奖报告链路已就绪"
        payload["lines"].insert(
            0, "本封是链路验收邮件；17:00收尾后的报告按独立去重账本发送；旧系统保持关闭。"
        )
        example = self.db.rows(
            "SELECT e.metrics,e.issue FROM evaluations e WHERE e.mode='REPLAY' ORDER BY e.created_at DESC LIMIT 1"
        )
        if example:
            payload["lines"].append(
                f"历史回放复盘示例（非真实前向）：{example[0]['issue']}，红球最高{example[0]['metrics']['red_max_matches']}/6、蓝球命中{example[0]['metrics']['blue_top1_hit']}。"
            )
        return self.mail.queue(
            "ACCEPTANCE", predictions[0]["issue"], payload, "STATUS", predictions[0]["cycle_id"]
        )
