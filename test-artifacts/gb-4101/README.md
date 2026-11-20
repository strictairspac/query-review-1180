# gb-4101 外币折算 / 汇率锁定验证

本目录是批次根目录的测试留档，不进入源码。三个脚本都连真实后端、worker、PostgreSQL 和 Redis，只应在一次性数据库上运行。

## 前置

1. 起一个空库并 seed：`PYTHONPATH=. python -m scripts.seed_demo`（`DATABASE_URL` / `JWT_SECRET` 必填）。
2. 后端：`uvicorn src.main:app --port 19241 --host 127.0.0.1`，`SEED_DEMO=false` 避免重复 seed。
3. worker：`python -m src.worker`，`ARTIFACTS_DIR` 指向可写目录。

## fx_e2e.py：主链路（两阶段）

worker 必须在两阶段之间保持停止，否则队列会被提前消费。

```bash
export BASE=http://127.0.0.1:19241
export PG_DSN="host=/tmp/pgrun port=55432 user=app dbname=query_review_test"
python3 fx_e2e.py accept   # 接单锁定 → 制造缺价 → 两个批次挂起
# 启动 worker
python3 fx_e2e.py verify   # 已锁汇率不受母表删除影响；并发补价首个值胜出并续跑；
                           # 后续更正只影响新批次；两侧折算与手算一致；差异仍判 different；观察员只读
```

覆盖点：
- 接单时锁定汇率，之后从 `fx_rates` 删除该行也不改变批次已锁值；
- 缺价批次 `held`、不占执行配额，其他批次照常 `passed`；
- 3 个并发补价请求中恰好 1 个 `201`（首个入库值），其余 `200` 且不改写；
- 挂起批次用首个值续跑并 `passed`，`fx_missing` 清空；
- `PUT /fx/rates` 更正母表后，已锁定批次的快照与证据校验和不变，新批次用新值；
- 证据两侧结果相同、摘要相同，并与直接按汇率表手算的人民币合计一致；
- 故意改成 `temperature > 8` 的候选仍是 `different`，不是错误；
- viewer 读汇率 200、写 201/PUT 403；非法币种 201 前会规范化，汇率 ≤ 0 返回 422。

## fx_crash_prep.py + 重启 worker：中断恢复

```bash
python3 fx_crash_prep.py   # 删掉某批 JSON 产物、状态置 running、改动母表汇率
# 重启 worker
```

预期：worker 发现证据行已存在，只补写 `review-<id>.json`，不重算、不新增证据，快照仍是当时锁定值。

## render_pages.mjs：页面渲染

用 esbuild 把 `frontend/src/app.js` 打成 IIFE，在 jsdom 里加载真实页面并打桩 `fetch` 到测试后端：

```bash
cd test-artifacts/gb-4101 && npm i
npx esbuild ../../frontend/src/app.js --bundle --format=iife --outfile=./app.bundle.js
node render_pages.mjs
```

预期：运行历史显示“已锁定 EUR · N 天 · 区间”可展开明细或“缺价 USD 缺某日”，观察员看不到补录表单；证据页显示按运输日锁定的汇率明细。

## 已知口径

- 汇率由人工补录，无外部行情；折算为 `ROUND(amount * 运输日汇率, 2)`，不处理四舍五入以外的拆单或手续费。
- `held` 批次不会因上游账单变化自动重新定价；worker 执行前若发现快照未覆盖的币种/日期会再次转 `held`。
- 证据表对 `batch_id` 唯一，重复投递（Redis 重放、双 worker）只产生一份证据。
