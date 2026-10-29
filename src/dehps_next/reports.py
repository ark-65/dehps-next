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
    def __init__(self, db, artifacts):
        self.db, self.artifacts = db, artifacts
        self.mail = Mail(db)

    def prepare(self, force=False):
        latest = self.db.rows("SELECT * FROM draws ORDER BY draw_at DESC LIMIT 1")
        if not latest:
            raise DomainError("NO_HISTORY", "No authoritative history to prepare forecast")
        target = next_target(latest[0])
        clock = now().astimezone(ZONE)
        if clock.date() > target["day"]:
            raise DomainError(
                "SOURCE_STALE", "Previous scheduled draw has not arrived; do not guess a later issue"
            )
        if clock.date() == target["day"] and clock < target["deadline_time"]:
            # Preparation registers a schedule only. Even force cannot seal a forecast early.
            Scheduler(self.db, self.artifacts).expect(
                target["issue"], target["draw_time"].isoformat(), target["deadline_time"].isoformat()
            )
        return target

    def pre_payload(self, prediction, target):
        data = prediction["payload"]
        summary = self.forward_summary()
        selection = self.db.rows(
            "SELECT evidence FROM forecast_selections WHERE issue=%s", (prediction["issue"],)
        )[0]["evidence"]
        windows = selection["windows"]
        return {
            "title": f"[DEHPS Next] {prediction['issue']}期开奖前分析与号码报告",
            "send_deadline_utc": target["deadline_time"].astimezone(UTC).isoformat(),
            "blue": data["blue_top1"],
            "tickets": data["red_top100"],
            "lines": [
                f"期号：{prediction['issue']}；开奖：{target['draw_time'].strftime('%Y-%m-%d %H:%M')}（上海时间）",
                f"证据：真实开奖前封存 FORWARD；封存：{prediction['sealed_at'].astimezone(ZONE).isoformat()}",
                f"历史截至：{prediction['through_issue']}；模型：{prediction['model_id'][:16]}；神经网络实际训练已完成。",
                f"开发回归：近100期 {windows['recent']['blue_top1_hits']}/100；近10期 {windows['recent10']['blue_top1_hits']}/10；随机历史 {windows['random_historical']['blue_top1_hits']}/{windows['random_historical']['n']}。这些是反复搜索使用的开发证据。",
                f"门槛：同一冻结清单、父节点比较、蓝球损失及红球约束通过；研究节点 {selection['path']}，协议 {selection['protocol_digest'][:16]}。",
                "当前为研究性推荐；开发回归通过不代表稳定优于随机，也不代表50%业务目标达标。此前提前生成的验收预测不作为这封正式报告的预测。",
                f"唯一蓝球 Top1：{data['blue_top1']:02d}；红球 Top100 组合见下表。排序分数不等于中奖概率。",
                f"已结算前向蓝球：{summary['hits']}/{summary['n']}（含覆盖缺口 {summary['missing']} 期）；50%目标未建立。研究方向改善不代表已优于随机基线。",
                "数据使用 Next 独立数据库；初始历史来自授权导入，后续开奖直接同步福彩官方。",
            ],
        }

    def forward_summary(self):
        return self.db.rows("""SELECT count(*) AS n,coalesce(sum((e.metrics->>'blue_top1_hit')::int),0) AS hits,
            count(*) FILTER(WHERE s.state='MISSED') AS missing FROM forecast_selections s
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
            "at": now().isoformat(),
            "calendar": CALENDAR,
            "mode": "MAIL_ONLY",
            "reason": "WAITING_SCHEDULE",
        }
        target = None
        try:
            target = self.prepare(prepare_now)
            clock = now().astimezone(ZONE)
            state["draft"] = Forecast(self.db, self.artifacts).preview()
            if target["seal_time"] <= clock < target["mail_time"]:
                state["seal"] = Forecast(self.db, self.artifacts).seal(target)
            if target["day"] == clock.date() and clock >= target["mail_time"]:
                prediction = Forecast(self.db, self.artifacts).for_report(
                    target,
                    {
                        "reason": "NO_VALIDATED_FORECAST_AT_17",
                        "draft": state["draft"],
                        "goal50": "UNPROVEN",
                        "business_coverage": "MISSED_COUNTS_AS_NON_HIT",
                    },
                )
                existing = self.db.rows(
                    "SELECT id FROM mail_reports WHERE kind='PRE' AND issue=%s", (target["issue"],)
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
                        "PRE",
                        prediction["issue"],
                        self.pre_payload(prediction, target),
                        "FORWARD",
                        prediction["cycle_id"],
                    )
                    state["reason"] = "PRE_REPORT_QUEUED_OR_ALREADY_SENT"
                else:
                    state["reason"] = "NO_VALIDATED_FORECAST_AT_17"
                    self.mail.queue(
                        "PRE",
                        target["issue"],
                        {
                            "title": f"[DEHPS Next] {target['issue']}期研究与开奖前校验报告",
                            "send_deadline_utc": target["deadline_time"].astimezone(UTC).isoformat(),
                            "lines": [
                                "17:00前没有完成合格候选封存，本期无通过门槛的正式推荐。",
                                f"近期100期、最近10期与随机历史回归状态：{state['draft']['state']}",
                                f"校验未通过原因：{(state['draft'].get('gate') or {}).get('reasons', ['尚无完整验证结果'])}",
                                "白天继续历史验证、退步回退和新方向探索；不会等待下一期开奖才训练。",
                                "提前验收预测已保留为验收记录，不算本期正式报告；业务覆盖缺口如实计入。50%目标未建立。",
                            ],
                        },
                        "STATUS",
                    )
            else:
                state["reason"] = "WAITING_17_00" if clock.date() == target["day"] else "WAITING_DRAW_DAY"
        except DomainError as exc:
            state["reason"] = exc.code
            if now().astimezone(ZONE).hour >= 17:
                self.alert(exc.code, str(exc))
        for row in self.db.rows(
            """SELECT p.*,e.metrics,d.red,d.blue,d.issue AS actual_issue,ds.through_issue
                FROM evaluations e JOIN predictions p ON p.cycle_id=e.cycle_id JOIN cycles cy ON cy.id=e.cycle_id
                JOIN draws d ON d.issue=e.issue JOIN datasets ds ON ds.id=cy.dataset_id
                WHERE cy.loop_id=%s AND e.mode='FORWARD' AND EXISTS(SELECT 1 FROM mail_reports pre WHERE pre.kind='PRE' AND pre.cycle_id=p.cycle_id) AND NOT EXISTS(SELECT 1 FROM mail_reports r WHERE r.kind='POST' AND r.issue=e.issue) ORDER BY e.created_at DESC LIMIT 32""",
            (LOOP,),
        ):
            self.mail.queue("POST", row["issue"], self.post_payload(row), "FORWARD", row["cycle_id"])
        for missed in self.db.rows("""SELECT s.issue,d.red,d.blue FROM forecast_selections s JOIN effective_draws d ON d.issue=s.issue
            WHERE s.state='MISSED' AND d.available_at<=now() AND d.draw_at<=now()
            AND NOT EXISTS(SELECT 1 FROM mail_reports r WHERE r.kind='POST' AND r.issue=s.issue) LIMIT 32"""):
            self.mail.queue(
                "POST",
                missed["issue"],
                {
                    "title": f"[DEHPS Next] {missed['issue']}期开奖结果与研究状态",
                    "lines": [
                        f"官方开奖号：{missed['red']} + {missed['blue']:02d}",
                        "本期17:00前未完成合格封存，无正式预测可结算；业务指定期次计为未命中并记录覆盖缺口。",
                        "不会拿提前验收预测、历史回放或开奖后预测补造本期命中。50%目标未建立。",
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
        day = now().astimezone(ZONE).date().isoformat()
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
            0, "本封是链路验收邮件；17:00正式报告按独立去重账本发送。旧系统邮件任务保持不变。"
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
