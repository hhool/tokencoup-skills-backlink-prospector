#!/usr/bin/env python3
"""按权威度分带选批（口径：authority_score，用户 2026-11-17 定为唯一标准）。

80-100 = 顶级，专门维护不批量执行；第一批只做 20-80。

口径：`authority_score`（0-100，known 榜单分）即权威度标准，不再区分 Ahrefs DR。
`authority_source=none` 的记为 unknown（无数据，待测）。

用法：
  band_select.py                    # 只出报告
  band_select.py --tag              # 顺带把分带写入台账 tags（看板可筛）
"""
import argparse
import csv
import json
import os
import urllib.request

SITE_DIR = os.path.expanduser("~/seo/azgames.poki2.online")
TARGETS = os.path.join(SITE_DIR, "targets.jsonl")
BASE = "http://127.0.0.1:8765"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")

TOP, MID = "auth80-100", "auth20-80"
UNK = "auth-unknown"


def band_of(t):
    s = t.get("authority_score")
    if s is None or t.get("authority_source", "").startswith("none"):
        return UNK
    if s >= 80:
        return TOP
    if s >= 20:
        return MID
    return "auth-lt20"


def load():
    with open(TARGETS) as f:
        return [json.loads(l) for l in f if l.strip()]


def write_csv(path, rows, fields):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", action="store_true")
    a = ap.parse_args()

    rows = load()
    for t in rows:
        t["_band"] = band_of(t)

    top = [t for t in rows if t["_band"] == TOP]
    mid = [t for t in rows if t["_band"] == MID]
    unk = [t for t in rows if t["_band"] == UNK]

    fields = ["domain", "id", "authority_score", "authority_grade", "fit_score",
              "wave", "submit_type", "category", "status", "url"]

    top_sorted = sorted(top, key=lambda x: -(x.get("authority_score") or 0))
    write_csv(os.path.join(OUT_DIR, "azgames-toptier-80-100.csv"), top_sorted, fields)

    mid_sorted = sorted(mid, key=lambda x: (-(x.get("fit_score") or 0)))
    for t in mid_sorted:
        t["first_batch"] = "是" if t.get("wave") == 1 else "否(wave2)"
    write_csv(os.path.join(OUT_DIR, "azgames-batch1-dr20-80.csv"), mid_sorted,
              fields + ["first_batch"])

    write_csv(os.path.join(OUT_DIR, "azgames-dr-unknown.csv"),
              sorted(unk, key=lambda x: -(x.get("fit_score") or 0)), fields)

    print("权威度分带：80-100 %d 条（不批量执行）· 20-80 %d 条（第一批）· 未知 %d 条"
          % (len(top), len(mid), len(unk)))
    print("第一批（wave=1）：%d 条" % sum(1 for t in mid_sorted if t.get("first_batch") == "是"))
    for t in mid_sorted:
        print("  %-24s auth=%-3s fit=%-3s wave=%s %-9s %s" % (
            t["domain"], t.get("authority_score"), t.get("fit_score"),
            t.get("wave"), t["submit_type"], t["status"]))

    if a.tag:
        for t in rows:
            tags = [x for x in (t.get("tags") or [])
                    if x not in (TOP, MID, UNK, "auth-lt20", "auth-top")]
            tags.append("auth-top" if t["_band"] == TOP else t["_band"])
            req = urllib.request.Request(
                "%s/api/target/%s" % (BASE, t["id"]),
                data=json.dumps({"tags": tags}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                urllib.request.urlopen(req, timeout=15).read()
            except Exception as e:
                print("打标失败 %s：%s" % (t["domain"], e))
        print("已写入 tags（看板可按标签筛）")


if __name__ == "__main__":
    main()
