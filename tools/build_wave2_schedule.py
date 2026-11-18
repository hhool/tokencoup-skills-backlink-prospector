# -*- coding: utf-8 -*-
"""Build an R-522-compliant follow-up schedule for wave-2 (multi-step) targets.

R-522 (SEXTANT wb-seo-ops) ceilings enforced here:
  * one recipient site: <=1 pitch / 24h, <=5 / 30d, same target once / 90d
  * warm-up: global <=10 sends/day, in 2 batches of <=5, >=4h apart
  * R-520: this tool only PLANS. A human always sends. No mail is sent here.
  * R-510: no identical copy — the schedule carries a per-row topic reminder.

Outputs (under backlink-prospector/reports/):
  wave2-schedule.csv   — one row per planned send with date/batch/sequence
  wave2-schedule.md    — human-readable timeline + rules + per-site plan

Usage: python3 tools/build_wave2_schedule.py [--start 2026-11-18] [--per-day 10]
"""
import argparse
import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

LEDGERS = [
    ("/Users/hou/seo/downer.app/targets.jsonl", "downer.app"),
    ("/Users/hou/seo/soundbuttons.cc/targets.jsonl", "soundbuttons.cc"),
    ("/Users/hou/seo/soundbuttons.click/targets.jsonl", "soundbuttons.click"),
    ("/Users/hou/seo/balancebiketoddler.com/targets.jsonl", "balancebiketoddler.com"),
]
OUT_DIR = Path("/Users/hou/Desktop/skill-seo-geo/backlink-prospector/reports")

# R-522: 需要邮件建联的 submit_type；directory/listing/profile/registry 等
# 「已发现链接」不算 pitch，不占配额。
MAIL_TYPES = {"guest_post", "pitch", "apply", "paid", "exchange"}
STAGE_PLAN = [
    ("D0",  "首封 pitch",      "写具体站点+具体页面，禁止通用模板（R-510）；英文正文"),
    ("D+3", "第一封跟进",       "仅在未回复时发；补充一个具体价值点，不重复首封"),
    ("D+10", "第二次跟进（收尾）", "最后封；明确不再打扰，保留 90 天窗口"),
]
PER_DAY = 10          # warm-up 全局上限（2 批 × 5）
BATCH_SIZE = 5
BATCH_GAP_HOURS = 4


def load_wave2():
    rows = []
    for path, site in LEDGERS:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            t = json.loads(line)
            if t.get("wave") != 2:
                continue
            st = t.get("submit_type") or "unknown"
            if st not in MAIL_TYPES:
                continue  # 已发现链接，不占邮件配额
            note = (t.get("note") or "").strip()
            # 「同上 / - / 空」是台账里的占位符，不能当邮件切入点
            if note in {"同上", "-", "—", "N/A", "n/a", ""}:
                note = ""
            topic = note or t.get("title") or t["domain"]
            rows.append({
                "site": site, "id": t["id"], "domain": t["domain"],
                "title": t.get("title", ""), "submit_type": st,
                "fit_score": t.get("fit_score") or 0,
                "topic": topic[:80],
            })
    return rows


def schedule(rows, start: date, per_day: int):
    # 优先级：机会分降序；同分先 downer（新站冷启动更缺链接）
    site_rank = {"downer.app": 0, "balancebiketoddler.com": 1,
                 "soundbuttons.cc": 2, "soundbuttons.click": 3}
    rows.sort(key=lambda r: (-r["fit_score"], site_rank.get(r["site"], 9), r["domain"]))
    # R-522「同目标 90 天」：同一域名只安排一次（保留机会分最高的那条）。
    # 不能靠往后推日期规避 —— 那仍是 90 天内对同一目标第二次 pitch。
    seen_domains = set()
    deduped = []
    for r in rows:
        if r["domain"] in seen_domains:
            continue
        seen_domains.add(r["domain"])
        deduped.append(r)
    rows = deduped
    plans = []
    # 全局每天 2 批，每批 <=5，同一收件站 24h 内只 1 封
    per_day = min(per_day, 10)
    batch_cap = min(BATCH_SIZE, per_day)
    day = start
    day_sent = 0
    for r in rows:
        # 已按域名去重；这里只需处理当日满额（2 批 × 5）
        while day_sent >= per_day:
            day += timedelta(days=1)
            day_sent = 0
        # R-522 warm-up：每天 <=10 封，按 2 批各 <=5 封安排，间隔 6h。
        # 同域 24h 限制常使当天发不满 5 封 —— 那种情况集中在早批即可，
        # 「2 批 / 间隔 4h」是上限结构，不强制每天必须拆成两批。
        batch = 1 if day_sent < batch_cap else 2
        slot_hour = 9 if batch == 1 else 15
        send_at = datetime(day.year, day.month, day.day, slot_hour)
        plans.append({
            **r, "send_at": send_at.strftime("%Y-%m-%d %H:%M"),
            "batch": batch, "seq": len(plans) + 1,
        })
        day_sent += 1
    return plans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-11-18")
    ap.add_argument("--per-day", type=int, default=PER_DAY)
    args = ap.parse_args()
    start = datetime.strptime(args.start, "%Y-%m-%d").date()

    rows = load_wave2()
    plans = schedule(rows, start, args.per_day)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = OUT_DIR / "wave2-schedule.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["seq", "send_at", "batch", "site", "id",
                                          "domain", "submit_type", "fit_score", "stage", "topic"])
        w.writeheader()
        for p in plans:
            first_dt = datetime.strptime(p["send_at"], "%Y-%m-%d %H:%M")
            for stage, _, _ in STAGE_PLAN:
                delta = {"D0": 0, "D+3": 3, "D+10": 10}[stage]
                follow_dt = first_dt + timedelta(days=delta)
                w.writerow({
                    "seq": p["seq"],
                    "send_at": follow_dt.strftime("%Y-%m-%d %H:%M"),
                    "batch": p["batch"],
                    "site": p["site"], "id": p["id"], "domain": p["domain"],
                    "submit_type": p["submit_type"], "fit_score": p["fit_score"],
                    "stage": stage, "topic": p["topic"],
                })

    md = ["# wave=2 邮件建联排期（R-522 合规）", "",
          "生成时间：%s  起始：%s  全局上限：%d 封/天（2 批）" % (
              datetime.now().strftime("%Y-%m-%d %H:%M"), start, args.per_day), "",
          "## 硬规则", "",
          "- **R-520**：本表只排期，**永远人发送**，工具不自动投递任何邮件。",
          "- **R-522**：同一收件站 ≤1 封/24h、≤5 封/30 天、同目标 90 天内不再投。",
          "- **warm-up**：每发件域名每天 ≤10 封，分 2 批各 ≤5 封，间隔 ≥4h（本表用 09:00 / 15:00）。",
          "- **R-510**：禁止通用模板；每封必须点名具体站点与页面（topic 列）。正文与标题只用英文。",
          "- **配额口径**：仅 `guest_post / pitch / apply / paid / exchange` 计入；"
          "directory / listing / profile / registry 等「已发现链接」不占配额。", "",
          "## 每个目标的 3 阶段", ""]
    for code, label, note in STAGE_PLAN:
        md.append("- **%s %s**：%s" % (code, label, note))
    md += ["", "## 首封日程（前 40 条）", "",
           "| # | 计划发送 | 批次 | 站点 | 域名 | 方式 | 分 | 切入点 |",
           "|---|---|---|---|---|---|---|---|"]
    for p in plans[:40]:
        md.append("| %d | %s | %d | %s | %s | %s | %d | %s |" % (
            p["seq"], p["send_at"], p["batch"], p["site"], p["domain"],
            p["submit_type"], p["fit_score"], p["topic"].replace("|", "/")[:40]))
    if len(plans) > 40:
        md += ["", "... 另有 %d 条，见 `wave2-schedule.csv`。" % (len(plans) - 40)]
    bysite = defaultdict(int)
    for p in plans:
        bysite[p["site"]] += 1
    md += ["", "## 按站点", ""]
    for s, n in sorted(bysite.items(), key=lambda kv: -kv[1]):
        md.append("- %s：%d 个目标" % (s, n))
    md += ["", "## 注意", "",
           "- 90 天窗口：一旦首封已发，90 天内不再对同一目标重复整轮；"
           "跟进只在**未回复**时发，收到回复立即转人工对话。",
           "- 排期是**上限不是目标**（R-522）：一个季度发 3 封是正常节奏。",
           "- 低价值企业邮箱（pr@ / adsales@ / licensing@）先转编辑渠道再投。"]
    md_path = OUT_DIR / "wave2-schedule.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("wave2 mail targets: %d" % len(plans))
    print("schedule through: %s" % plans[-1]["send_at"] if plans else "n/a")
    print("wrote %s" % csv_path)
    print("wrote %s" % md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
