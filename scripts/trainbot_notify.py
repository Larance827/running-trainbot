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

PLAN_FILE = Path("跑步记录/跑步训练计划_2026年6月.md")
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

# ─── 微信推送 ───────────────────────────────────────────────

def format_wechat_msg(t: Training) -> tuple[str, str]:
    if t.is_rest:
        title = f"🧘 {t.date.month}/{t.date.day} 休息日"
        content = f"## 🧘 {t.date.month}/{t.date.day} 周{t.weekday} — 休息日\n\n🎉 好好恢复！\n\n---\n*来自 TrainBot Cloud*"
        if t.notes:
            content = content.replace("*来自 TrainBot Cloud*", f"{t.notes}\n\n*来自 TrainBot Cloud*")
        return title, content

    title = f"🏃 {t.date.month}/{t.date.day} 周{t.weekday} {t.type}"
    content_parts = [f"## 🏃 {t.date.month}/{t.date.day} 周{t.weekday}\n"]
    content_parts.append(f"**{t.type}**\n")

    if t.distance and t.distance != "—":
        content_parts.append(f"- 📏 **距离**：{t.distance}")
    if t.pace and t.pace != "—":
        content_parts.append(f"- ⚡ **配速**：{t.pace}")
    if t.hr and t.hr != "—":
        content_parts.append(f"- ❤️ **心率**：{t.hr}")
    content_parts.append("")

    if "间歇" in t.type:
        content_parts.append("> ⚡ **强度课**！充分热身，组间充分恢复")
    elif "节奏" in t.type:
        content_parts.append("> 🎯 **节奏课**！保持稳定巡航感")
    elif "长距离" in t.type:
        content_parts.append("> 💧 **长距离**！注意补水，每20分钟喝一口")
    elif "恢复跑" in t.type or "有氧" in t.type:
        content_parts.append("> 🐢 **慢！** 不要追求速度，压住心率")
    content_parts.append("")

    if t.notes:
        note_text = re.sub(r'[✅⚠️🔧] ', '', t.notes).strip()
        if note_text:
            content_parts.append(f"💡 {note_text}\n")

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
        content = f"## 📭 {tomorrow.month}/{tomorrow.day}\n\n训练计划中未找到明日安排。\n\n可能已超出计划周期 (6/4 - 7/3)。\n\n---\n*来自 TrainBot Cloud*"
        ok = send_wechat(title, content)
        print("✅ Sent" if ok else "❌ Failed")
        return

    print(f"Tomorrow ({tomorrow}): {t.type} {t.distance}")
    title, content = format_wechat_msg(t)
    ok = send_wechat(title, content)
    if ok:
        print(f"✅ WeChat push sent: {title}")
    else:
        print("❌ WeChat push failed")

if __name__ == "__main__":
    main()
