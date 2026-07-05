#!/usr/bin/env python3
"""
TrainBot Cloud — 训练计划微信推送（GitHub Actions 云端版）
==========================================================

每天由 GitHub Actions 自动触发，解析训练计划并通过 Server酱 推送到微信。
电脑关机也不受影响。

SendKey 通过环境变量 SERVERCHAN_SENDKEY 传入，
训练计划文件在仓库中按相对路径读取。
"""

import re
import os
import json
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, date, timedelta
from dataclasses import dataclass
from typing import Optional

# ─── 配置 ───────────────────────────────────────────────────

PLAN_FILE = Path("跑步记录/跑步训练计划_2026年7月.md")
YEAR = 2026
SERVERCHAN_API = "https://sctapi.ftqq.com/{sendkey}.send"

# SendKey 从环境变量获取（GitHub Secret），失败则尝试本地配置文件
SENDKEY = os.environ.get("SERVERCHAN_SENDKEY", "")

if not SENDKEY:
    config_path = Path(__file__).parent / "trainbot_config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            SENDKEY = config.get("serverchan", {}).get("sendkey", "")
        except Exception:
            pass

# ─── 数据结构 ───────────────────────────────────────────────

@dataclass
class Training:
    date: date
    weekday: str
    type: str
    distance: str
    pace: str
    hr: str
    notes: str
    is_rest: bool = False
    is_completed: bool = False

# ─── 解析器 ─────────────────────────────────────────────────

def parse_date(match: str) -> date:
    parts = match.strip().split("/")
    return date(YEAR, int(parts[0]), int(parts[1]))

def clean_cell(text: str) -> str:
    text = text.strip()
    text = re.sub(r'\s*\n\s*', ' ', text)
    return text

def parse_plan() -> list[Training]:
    content = PLAN_FILE.read_text(encoding="utf-8")
    trainings: list[Training] = []

    table_pattern = re.compile(
        r'\| 日期 \| 星期 \| 类型 \| 距离 \| 配速 \| 心率 \| 要点 \|.*?'
        r'(?=\n\n|\Z)',
        re.DOTALL
    )

    for table_match in table_pattern.finditer(content):
        table = table_match.group()
        rows = table.strip().split("\n")
        data_rows = [r for r in rows[2:] if r.startswith("|")]

        for row in data_rows:
            cells = [clean_cell(c) for c in row.split("|")]
            cells = [c for c in cells if c]

            if len(cells) < 6:
                continue

            try:
                d = parse_date(cells[0])
            except (ValueError, IndexError):
                continue

            is_rest = "休息" in cells[2] or "🚫" in cells[2]
            is_completed = "✅ 已完成" in (cells[6] if len(cells) > 6 else "")

            trainings.append(Training(
                date=d,
                weekday=cells[1],
                type=cells[2],
                distance=cells[3],
                pace=cells[4],
                hr=cells[5],
                notes=cells[6] if len(cells) > 6 else "",
                is_rest=is_rest,
                is_completed=is_completed,
            ))

    trainings.sort(key=lambda t: t.date)
    return trainings

def find_training(trainings: list[Training], target: date) -> Optional[Training]:
    for t in trainings:
        if t.date == target:
            return t
    return None

# ─── 周阶段 & 执行要领 ─────────────────────────────────────

def get_week_info(d: date) -> str:
    """返回训练日所属的周阶段"""
    if date(2026, 7, 5) <= d <= date(2026, 7, 11):
        return "第1周 · 重建基础（7/5–7/11）🔴 关键期"
    elif date(2026, 7, 12) <= d <= date(2026, 7, 18):
        return "第2周 · 恢复节奏（7/12–7/18）"
    elif date(2026, 7, 19) <= d <= date(2026, 7, 25):
        return "第3周 · 质量回归（7/19–7/25）"
    elif date(2026, 7, 26) <= d <= date(2026, 8, 1):
        return "第4周 · 巩固提升（7/26–8/1）"
    return ""

def get_type_tips(t: Training) -> list[str]:
    """返回特定训练类型的详细执行要领"""
    tips = []
    if "间歇" in t.type:
        tips = [
            "充分热身 1.2km + 动态拉伸，不要跳过",
            "每组快跑后 400m 慢跑恢复，不要站着休息",
            "如果心率超 172 或呼吸失控 → 降配速 5-10 秒",
            "跑后 0.8km 慢跑放松 + 静态拉伸",
        ]
    elif "节奏" in t.type:
        tips = [
            "热身 1.2km 慢跑 + 动态拉伸",
            "节奏段保持稳定巡航感，不要忽快忽慢",
            "能说短句但不能聊天 = 正确的节奏配速",
            "如果心率超 172 → 降配速到 5:50-6:00",
            "放松 0.8km 慢跑 + 静态拉伸",
        ]
    elif "长距离" in t.type:
        tips = [
            "距离优先于配速——完成距离比速度重要",
            "每 20 分钟喝一口水，7 月北京高温",
            "中途累了可降配速到 6:15-6:25，但距离要跑完",
            "跑前 30 分钟喝 300ml 水",
        ]
    elif "恢复跑" in t.type:
        tips = [
            "真轻松，能边跑边聊天 = 正确配速",
            "不要追求速度，这是「恢复」不是「训练」",
            "如果昨天跑了强度课，今天重点是排酸放松",
        ]
    elif "有氧" in t.type:
        tips = [
            "首公里必须落在 6:05-6:20，偏慢则下公里提 5-10 秒",
            "任意 1km > 6:25 → 该公里不算有氧刺激，相当于白跑",
            "呼吸深但不喘，能说完整句子但不想说太久",
            "有氧慢跑 ≠ 恢复跑，需要轻微 push",
        ]
    elif "半马配速" in t.type:
        tips = [
            "找轻松巡航感，不像节奏跑那么吃力",
            "比有氧跑稍快但仍在舒适区边缘",
            "注意步频，保持 170-180 spm",
        ]
    return tips

# ─── 微信推送 ───────────────────────────────────────────────

def format_wechat_msg(t: Training, trainings: list[Training] = None) -> tuple[str, str]:
    month, day = t.date.month, t.date.day
    week_info = get_week_info(t.date)

    if t.is_rest:
        title = f"🧘 {month}/{day} 周{t.weekday} 休息日"

        content_parts = [f"## 🧘 {month}/{day} 周{t.weekday} — 休息日\n"]
        if week_info:
            content_parts.append(f"*{week_info}*\n")
        content_parts.append("🎉 好好恢复！肌腱适应比心肺慢得多。\n")

        # 明日预告
        if trainings:
            tomorrow = t.date + timedelta(days=1)
            next_t = find_training(trainings, tomorrow)
            if next_t and not next_t.is_rest:
                content_parts.append("---")
                content_parts.append("**📅 明日预告：**")
                content_parts.append(f"**{next_t.type}**  {next_t.distance}  @{next_t.pace}")
                if next_t.hr and next_t.hr != "—":
                    content_parts.append(f"❤️ 心率 {next_t.hr}")
                if next_t.notes:
                    note_clean = re.sub(r'[✅⚠️🔧] ', '', next_t.notes).strip()
                    if note_clean:
                        content_parts.append(f"💡 {note_clean}")

        # 休息日任务
        content_parts.append("")
        content_parts.append("**🌙 休息日任务：**")
        content_parts.append("- 23:30 前放下手机，0:00 前入睡")
        content_parts.append("- 目标深睡 > 1h，睡眠评分 > 75")
        if t.notes:
            note = re.sub(r'[✅⚠️🔧] ', '', t.notes).strip()
            if note:
                content_parts.append(f"- {note}")

        content_parts.append("\n---\n*来自 TrainBot Cloud*")
        return title, "\n".join(content_parts)

    # ── 训练日 ──
    title = f"🏃 {month}/{day} 周{t.weekday} {t.type}"

    content_parts = [f"## 🏃 {month}/{day} 周{t.weekday}\n"]
    if week_info:
        content_parts.append(f"*{week_info}*\n")

    content_parts.append(f"## {t.type}\n")

    if t.distance and t.distance != "—":
        content_parts.append(f"- 📏 **距离**：{t.distance}")
    if t.pace and t.pace != "—":
        content_parts.append(f"- ⚡ **配速**：{t.pace}")
    if t.hr and t.hr != "—":
        content_parts.append(f"- ❤️ **心率**：{t.hr}")
    content_parts.append("")

    # 要点
    if t.notes:
        note_clean = re.sub(r'[✅⚠️🔧] ', '', t.notes).strip()
        if note_clean:
            content_parts.append(f"💡 {note_clean}\n")

    # 执行要领
    tips = get_type_tips(t)
    if tips:
        content_parts.append("**🏃 执行要领：**")
        for tip in tips:
            content_parts.append(f"- {tip}")
        content_parts.append("")

    # 通用提醒
    content_parts.append("**🌙 睡眠硬门槛：**")
    content_parts.append("- 昨晚 < 5h 或评分 < 60 → 降级为「可选恢复跑 3km」")
    content_parts.append("- 连续 2 天 < 5h → 强制休息")
    content_parts.append("- 强度课前检查：睡眠是否达标？\n")
    content_parts.append("**🕐 训练时间窗：**")
    content_parts.append("- 有氧/强度课：下午 5:00-7:30 最佳")
    content_parts.append("- 晚 8:00 后只适合恢复跑\n")

    content_parts.append("---\n*来自 TrainBot Cloud*")
    return title, "\n".join(content_parts)

def send_wechat(title: str, content: str) -> bool:
    url = SERVERCHAN_API.format(sendkey=SENDKEY)
    data = urllib.parse.urlencode({"title": title, "desp": content}).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("code") == 0
    except Exception as e:
        print(f"Push failed: {e}")
        return False

# ─── 主入口 ─────────────────────────────────────────────────

def main():
    if not SENDKEY:
        print("❌ SERVERCHAN_SENDKEY not set. Skipping push.")
        exit(1)

    today = date.today()
    tomorrow = today + timedelta(days=1)

    if not PLAN_FILE.exists():
        print(f"❌ Plan file not found: {PLAN_FILE}")
        exit(1)

    trainings = parse_plan()
    if not trainings:
        print("❌ Failed to parse training plan")
        exit(1)

    t = find_training(trainings, tomorrow)
    if t is None:
        print(f"📭 No training found for {tomorrow}")
        # Still push a reminder for rest days
        title = f"📭 {tomorrow.month}/{tomorrow.day} 无训练安排"
        content = f"## 📭 {tomorrow.month}/{tomorrow.day}\n\n训练计划中未找到明日安排。\n\n可能已超出计划周期 (7/5 - 8/1)。\n\n---\n*来自 TrainBot Cloud*"
        ok = send_wechat(title, content)
        print("✅ Sent" if ok else "❌ Failed")
        return

    print(f"Tomorrow ({tomorrow}): {t.type} {t.distance}")
    title, content = format_wechat_msg(t, trainings)
    ok = send_wechat(title, content)
    if ok:
        print(f"✅ WeChat push sent: {title}")
    else:
        print("❌ WeChat push failed")

if __name__ == "__main__":
    main()
