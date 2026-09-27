# PitchKiln-01 · 灶台值守看板

Django 5 + PostgreSQL：灶台瓦片看板 + 右侧抽屉探针时间线，无 Vue/React SPA。

## 技术栈

- Django 5、PostgreSQL
- Session 登录
- HTMX：局部刷新灶台网格与抽屉
- Docker Compose：`web` + `db`

## 端口与数据库

| 服务 | 端口 |
|------|------|
| Web  | **4710** |
| Postgres | **6110**（容器内 5432） |

数据库账号：`pitchkiln` / `pitchkiln` / 库名 `pitchkiln`

## 快速启动

```bash
cd PitchKiln/PitchKiln-01
docker compose up --build -d
```

浏览器打开：http://localhost:4710

演示账号：

- `admin` / `123456`（超级用户）
- `worker` / `123456`（普通用户）

容器启动时会自动：`migrate` → `seed_data` → `collectstatic` → `gunicorn`

## 本地开发（可选）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
# 确保本机 Postgres 监听 6110，或先 docker compose up -d db
set POSTGRES_HOST=localhost
set POSTGRES_PORT=6110
python manage.py migrate
python manage.py seed_data
python manage.py runserver 0.0.0.0:4710
```

## 业务模型

1. **ResinLot（来脂批）**：`lotCode`、`originPlace`、`arrivalKg`、`receivedAt`
2. **FireHearth（灶台）**：`lane`、`tag`（唯一）、`resinGrade`、相位 `cold|charging|ramping|holding|drawing`
3. **CookRun（熬制值守）**：归属灶台与来脂批、`openedAt`、`closedAt`（可空）、`targetSoftPointC`
4. **SoftPointProbe（软化点探针）**：归属值守、`sampledAt`、`softPointC`、`samplerName`

**业务规则**：将灶台相位切到 `drawing`（出胶）时，进行中的 CookRun 必须至少有一条 SoftPointProbe 的 `softPointC ≤ 95`。逻辑在 `apps/kiln/services/floor_rules.py`，由相位切换入口调用。

## 界面

- 首页：**灶台值守看板** — 左侧班次条 + 按过道排布的灶台瓦片；点瓦片打开右侧抽屉（值守、探针时间线、改相位 / 登记探针 / 开灶）。看板可按「是否挂未收灶值守」过滤：`?open=1` 只显示有未收灶 CookRun 的灶（去重），复选框切换时 HTMX 局部刷新网格，与整页 `?open=1` 同一口径
- 次页：**来脂批** — 卡片时间线，非宽表 CRUD；支持产地精确筛 + 三路对照（见下）

## 产地精确筛与三路复算

来脂批流按 `?origin=<产地>` 过滤，匹配规则为 **`originPlace` 全等**（精确匹配，不做模糊 / 前缀）。整页渲染与 HTMX 局部刷新走同一视图、同一上下文、同一结果片段（`templates/resin/_feed_results.html`），切换产地后两种路径口径一致。

看板与卡片共用 `apps/kiln/services/queries.py` 中的查询函数，禁止各写一套：

- `lots_for_origin(origin)` — 批查询集（产地精确筛）
- `open_runs(lots)` — 未收灶值守（`closedAt IS NULL`），可限定到给定批集合
- `hearths_with_open_runs(runs)` — 值守所属灶去重
- `board_hearths(only_open)` — 看板瓦片（`only_open` 即「是否挂未收灶值守」过滤）
- `origin_recon(origin)` — 三路对照入口

**三路复算步骤**（选定产地后，`origin_recon` 一次算清）：

1. **批张数** = 该产地（精确）的 ResinLot 数 → 对齐筛选后来脂批卡行数
2. **未收灶值守条数** = 这些批之下 `closedAt IS NULL` 的 CookRun 数 → 对齐值守条行数
3. **灶去重数** = 这些值守所属灶 `DISTINCT` 数（只算筛选命中的值守，不按全库）→ 对齐涉及灶台瓦片行数

页面「三路对照」条同时显示数据库聚合计数与实际渲染行数，**三路差都必须为 0**。产地无命中时三路均为 0、流为空，页面正常渲染不抛错。

## 种子数据

```bash
python manage.py seed_data
```

幂等：已有灶台则只保证账号存在。样例地名仅用「松脂坳 / 桐油坑」系，共**两个产地**：`松脂坳东沟`（2 批、3 条未收灶值守、涉及 3 灶）与 `桐油坑北坡`（2 批、1 条未收灶值守、涉及 1 灶）——每个产地都有批、都有未收灶值守，可直接验证三路对照。

## 目录结构

```
PitchKiln-01/
  manage.py
  requirements.txt
  Dockerfile
  entrypoint.sh
  docker-compose.yml
  config/
  apps/kiln/          # 模型、视图、floor_rules、种子
  templates/floor/    # 值守看板 + 抽屉
  templates/resin/    # 来脂批时间线
  static/css/         # 值守台 ops-console 样式
```
