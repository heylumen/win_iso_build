#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微软官方 release-info 监控脚本

抓取 Win11 / Win10 官方发布信息页，提取各产品线最新 OS build 号，
与本仓库已记录的基线（watchdog-state.json）比对。

发现微软发布了更高的 build 时：
  - 输出 new=true 并列出变化（供 GitHub Actions 开 Issue + 触发构建）
  - 更新 watchdog-state.json 基线

设计要点：
  - 仅当我们实际构建并跟踪的产品线（build 前缀）才报警，避免无关噪声。
  - 抓取失败 / 页面改版时静默跳过，绝不会误报。
  - 微软发布新构建 ≠ 我们能立刻制作；真正的制作仍受 adavak 社区 meta4 数据门控，
    本脚本只是「发现微软更新」这一信号的可靠来源。
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date

# 候选地址：微软页面路径偶有调整，多个都试，任一可达即可
WIN11_URLS = [
    "https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information",
    "https://learn.microsoft.com/en-us/windows/release-health/status-windows-11-24h2",
]
WIN10_URLS = [
    "https://learn.microsoft.com/en-us/windows/release-health/release-information",
    "https://learn.microsoft.com/en-us/windows/release-health/status-windows-10-22h2",
]

# 本仓库实际构建并跟踪的产品线（按 build 前缀匹配）
TRACKED = {
    "26200": "Windows 11 (25H2 / LTSC2024 线)",
    "19044": "Windows 10 21H2 / LTSC 2021",
    "17763": "Windows 10 1809 / LTSC 2019",
    "14393": "Windows 10 1607 / LTSB 2016",
}

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchdog-state.json")
UA = {"User-Agent": "Mozilla/5.0 (compatible; MSReleaseWatchdog/1.0)"}
TIMEOUT = 25


def fetch(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] fetch failed {url}: {e}", file=sys.stderr)
        return ""


def extract_builds(html):
    if not html:
        return set()
    builds = set()
    # 优先匹配 "OS Build XXXXX.YYYY" / "build XXXXX.YYYY"
    for m in re.finditer(r"(?:os\s*build|build)\D{0,12}?(\d{5}\.\d{3,5})", html, re.I):
        builds.add(m.group(1))
    # 兜底：所有 5位.3-5位 数字
    for m in re.finditer(r"\b(\d{5}\.\d{3,5})\b", html):
        builds.add(m.group(1))
    return builds


def key_of(b):
    a, c = b.split(".")
    return (int(a), int(c))


def max_for_prefix(builds, prefix):
    cand = [b for b in builds if b.startswith(prefix + ".")]
    return max(cand, key=key_of) if cand else None


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def write_outputs(new, detail=""):
    out = os.environ.get("GITHUB_OUTPUT", "/dev/null")
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"new={'true' if new else 'false'}\n")
        if new:
            f.write(f"detail={detail}\n")


def main():
    builds = set()
    for url in WIN11_URLS + WIN10_URLS:
        builds |= extract_builds(fetch(url))

    if not builds:
        print("[warn] 未能从任何官方页面提取到 build 号，跳过本次检测")
        write_outputs(False)
        return

    state = load_state()
    changes = []
    new_state = dict(state)
    for prefix, label in TRACKED.items():
        cur = max_for_prefix(builds, prefix)
        if not cur:
            continue
        prev = state.get(prefix)
        if prev is None or key_of(cur) > key_of(prev):
            changes.append({"prefix": prefix, "label": label, "build": cur, "prev": prev})
            new_state[prefix] = cur

    if changes:
        new_state["updated_at"] = date.today().isoformat()
        save_state(new_state)
        summary = []
        for c in changes:
            p = c["prev"] or "无记录"
            summary.append(f"{c['label']}: {p} → {c['build']}")
        detail = " | ".join(summary)
        print("new=true")
        print(detail)
        write_outputs(True, detail)
    else:
        print("new=false")
        write_outputs(False)


if __name__ == "__main__":
    main()
