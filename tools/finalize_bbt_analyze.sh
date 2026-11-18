#!/bin/zsh
# bbt analyze 结果收尾：等待结果 → 导出（活链 + 品类相关性）→ 导入 workbench → 波次回填。
# 用法：bash tools/finalize_bbt_analyze.sh [--wait-minutes N]
# 只读 analyze 结果，不重跑校验；导入前自动备份台账。
set -euo pipefail

PROSP=/Users/hou/Desktop/skill-seo-geo/backlink-prospector
BLW=/Users/hou/.workbuddy/skills/backlink-workbench/scripts/blw.py
RESULT=/tmp/analyze-bbt-result.json
SITE=balancebiketoddler.com
LEDGER=/Users/hou/seo/$SITE/targets.jsonl
WAIT=20
[[ "${1:-}" == "--wait-minutes" ]] && WAIT="${2:-20}"

echo "== 等待 analyze 结果（最多 ${WAIT} 分钟）=="
for i in $(seq 1 $((WAIT * 6))); do
  [[ -s "$RESULT" ]] && break
  sleep 10
done
if [[ ! -s "$RESULT" ]]; then
  echo "结果仍未写出：$RESULT"; exit 2
fi

python3 -c "
import json
d=json.load(open('$RESULT')); r=d.get('result') or {}
print('analyze ok:',d.get('ok'))
print('pool_merged:',r.get('pool_merged'))
print('pool_stats:',json.dumps(r.get('pool_stats'),ensure_ascii=False)[:200])
"

echo "== 备份台账 =="
cp "$LEDGER" "$LEDGER.bak-before-bbt-analyze"
echo "→ $LEDGER.bak-before-bbt-analyze"

echo "== 快速路径：WDC 竞品反链证据直接入池（不重跑 HTTP 校验）=="
echo "   analyze.py 只有 24 workers × 9s timeout，4.1 万条需 ~4h，90min 必超时；"
echo "   存活性交给 workbench scan 后置检测（link_state=unknown 已标注）。"
python3 "$PROSP/tools/export_wdc_fast.py" --center "$SITE" \
  --keywords "$PROSP/data/keywords-$SITE.json" \
  --min-via 2 --out /tmp/bbt-fast.json
python3 "$BLW" --data "/Users/hou/seo/$SITE" add --file /tmp/bbt-fast.json --round 2

echo "== 可选：若 analyze 结果后来写出，用一条龙做增量补充（自动去重）=="
echo "   python3 $BLW --data /Users/hou/seo/$SITE import-prospector \\"
echo "     --center-domain $SITE --prospector-dir $PROSP \\"
echo "     --relevance $PROSP/data/keywords-$SITE.json --round 3"

echo "== 波次回填（一次投递优先、多次交互靠后）=="
python3 "$BLW" --data "/Users/hou/seo/$SITE" wave --apply --recompute

echo "== 最终统计 =="
python3 "$BLW" --data "/Users/hou/seo/$SITE" stats 2>&1 | sed -n '/总量/,/按品类/p;/按投递波次/,/链接可见性/p'
echo "done"
