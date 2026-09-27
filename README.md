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

- 首页：**灶台值守看板** — 左侧班次条 + 按过道排布的灶台瓦片；点瓦片打开右侧抽屉（值守、探针时间线、改相位 / 登记探针 / 开灶）；可按「是否挂未收灶值守」过滤瓦片
- 次页：**来脂批** — 卡片时间线，非宽表 CRUD；产地精确筛 + 三路对照面板

## 产地精确筛与三路对照

来脂批流按产地**精确**筛选：`originPlace` 全等匹配，不做模糊包含 / 大小写折叠 —— `?origin=松脂坳` 只命中 `originPlace="松脂坳"` 的批，不会命中「松脂坳东沟」。下拉候选来自全库去重产地。

选定产地后，页面给出**三路对照**，复算步骤：

1. **批张数**：`ResinLot` 按产地精确过滤后计数 ↔ 对齐筛选后卡片行；
2. **未收灶值守条数**：这些批下 `closedAt IS NULL` 的 `CookRun` 计数 ↔ 对齐值守条；
3. **灶去重数**：这些值守所属 `FireHearth` 去重计数（按筛选口径，不是全库灶数）↔ 对齐瓦片去重。

每一路都分「复算数」（独立聚合查询）与「渲染行」（实际渲染列表）两列，差 = 复算 − 渲染，**三路差必须均为 0**。产地无命中时三路全为 0、卡片流为空，页面正常渲染不抛错。

看板另按「是否挂未收灶值守」过滤：`?duty=any|open|none`（全部 / 仅挂未收灶值守 / 仅无未收灶值守）。

**单一口径**：以上过滤与对照全部收敛在 `apps/kiln/services/queries.py` —— 看板（整页 `/` 与 HTMX 网格 `/floor/grid/`）和来脂批流（整页 `/resin-lots/` 与其 HTMX 片段）共用同一组查询函数，禁止各写一套；切换产地 / 值守过滤时，整页刷新与 HTMX 局部刷新走同一代码路径，口径不分裂。

## 种子数据

```bash
python manage.py seed_data
```

幂等：已有灶台则只保证账号存在。样例产地两个 —— 「松脂坳 / 桐油坑」，每地既有来脂批也有未收灶值守；桐油坑另有一条已收灶值守，用于区分「未收灶」口径。

## 测试

```bash
USE_SQLITE=1 python manage.py test
```

覆盖：三路差为 0、产地精确匹配、无命中全 0 不抛错、已收灶不计入、看板值守过滤、整页与 HTMX 局部同口径。

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
