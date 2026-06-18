# Docker 容器化部署指南

## 概述

`backtest-worker` 支持通过 Docker Compose 进行容器化部署，由两部分组成：

| 组件 | 说明 |
|------|------|
| **Backtest Worker** | 轮询任务队列并执行策略回测，完全无状态，可水平扩展 |
| **Screening Scheduler** | 每天定时执行全市场股票筛选，写结果到 MongoDB |

---

## 快速开始

### 1. 在 `quantFinance/.env` 里配置必要变量

```env
# 必填：与 quant-api 连接同一个 MongoDB
MONGO_URI=mongodb://mongo:27017

# 可选：回测任务所在业务库
BACKTEST_DB_NAME=finance
```

### 2. 启动（首次需要 build）

```bash
cd /path/to/quantFinance
docker compose up -d --build backtest-worker
```

### 3. 查看日志

```bash
docker compose logs -f backtest-worker
```

### 4. 验证环境变量是否生效

```bash
docker exec backtest-worker env | grep SCREENING
```

> ⚠️ **重要**：修改 `.env` 后必须用 `docker compose up -d backtest-worker`（不能用 `restart`），否则新变量不会生效。

---

## 环境变量参考

### Backtest Worker

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB 连接地址，worker 直接读取 `backtest_tasks` 并写入 `backtest_results` |
| `BACKTEST_DB_NAME` | `finance` | 回测任务和结果所在业务库 |
| `BACKTEST_WORKER_ID` | `backtest_worker_<hostname>` | Worker 唯一标识，留空自动用容器 hostname |
| `BACKTEST_POLL_INTERVAL` | `5` | 轮询任务间隔（秒） |

### Screening Scheduler

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_SCREENING` | `true` | 是否启动 screening 调度器 |
| `SCREENING_MODE` | `conservative` | 筛选策略组合。可选：`conservative`, `standard`, `aggressive`, `all`，支持逗号分隔如 `conservative,standard` |
| `SCREENING_STRATEGIES` | 全部 | 筛选策略类型，逗号分隔。可选：`turtle`, `single_yang`, `hidden_dragon` |
| `SCREENING_DAYS_BACK` | `120` | 回测窗口天数（留空用默认 120 天） |
| `SCREENING_UNIVERSE_INDEX` | 全市场 | 指数成分股股票池，来自 `index_constituents.index_code`，如 `csi1000` |
| `SCREENING_RESULTS_DB_NAME` | `DB_NAME` 或 `finance` | 筛选结果写入的业务库；读取行情/指数成分仍使用 `MONGO_DB`/`quant_data` |
| `SCREENING_RUN_AT` | 工作日 18:30，周末 08:00 | 自定义触发时间，格式 `HH:MM`（上海时区）|

---

## Screening 调度逻辑

```
每 30 秒检查一次当前时间
  ├── 若匹配触发时间 AND 今天还未运行 → 执行所有选定的策略筛选任务
  └── 每天只运行一次（already_ran_today 保护）
```

筛选结果写入 MongoDB：
- `strategy_stock_pool`：当日符合买入信号的股票
- `strategy_trade_history`：所有历史交易记录（含买卖）

注意：行情、指数成分等外部数据从 `MONGO_DB` 指向的数据库读取（通常是 `quant_data`）；`strategy_stock_pool` 和 `strategy_trade_history` 是前端业务结果，写入 `SCREENING_RESULTS_DB_NAME` / `DB_NAME` 指向的业务库（通常是 `finance`）。

---

## 水平扩展（多机部署）

Backtest Worker 完全无状态，可部署多个实例自动分担任务：

```bash
# 本机启动 3 个 worker
docker compose up -d --scale backtest-worker=3
```

**注意**：多实例时，Screening Scheduler 只让一台机器跑，其他关掉：

```env
# 主机器（跑 backtest + screening）
ENABLE_SCREENING=true

# 其他机器（只跑 backtest）
ENABLE_SCREENING=false
```

---

## 本地依赖包

Backtest Worker 依赖两个本地 editable 包，通过 volume mount + 容器启动时安装：

| 挂载路径 | 说明 |
|---------|------|
| `../data-access-lib:/deps/data-access-lib` | 数据访问层 |
| `../quant-strategies:/deps/quant-strategies` | 策略库 |

`entrypoint.sh` 在容器启动时自动执行 `pip install -e` 安装这两个包。

---

## Worker ID 查询

查看哪台机器认领了哪个任务（在 MongoDB 查 `backtest_tasks` 集合的 `worker_id` 字段）：

```js
// MongoDB Shell
db.backtest_tasks.find(
  { status: { $in: ["claimed", "running", "completed"] } },
  { task_id: 1, worker_id: 1, status: 1, updated_at: 1 }
).sort({ updated_at: -1 }).limit(10)
```
