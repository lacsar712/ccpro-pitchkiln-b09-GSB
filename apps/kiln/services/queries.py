"""看板与来脂批流共用的查询函数 —— 唯一口径来源。

约定：
- 产地过滤一律按 ``ResinLot.originPlace`` **精确**匹配（非模糊、非前缀）。
- 「未收灶值守」= ``CookRun.closedAt IS NULL``。
- 看板瓦片、来脂批卡、值守条、灶去重全部从这里取数，禁止各写一套。
"""
from django.db.models import Prefetch

from ..models import CookRun, FireHearth, ResinLot


def lots_for_origin(origin=""):
    """来脂批查询集；``origin`` 非空时按产地精确过滤。"""
    qs = ResinLot.objects.all()
    if origin:
        qs = qs.filter(originPlace=origin)
    return qs


def open_runs(lots=None):
    """未收灶值守查询集；给定批查询集时限定到这些批之下。"""
    qs = CookRun.objects.filter(closedAt__isnull=True)
    if lots is not None:
        qs = qs.filter(resinLot__in=lots.order_by())
    return qs.select_related("hearth", "resinLot").order_by("-openedAt", "-id")


def hearths_with_open_runs(runs=None):
    """挂有（给定）未收灶值守的灶，去重后按过道 / 灶牌排序。"""
    runs = runs if runs is not None else open_runs()
    return (
        FireHearth.objects.filter(runs__in=runs.order_by())
        .distinct()
        .order_by("lane", "tag")
    )


def board_hearths(only_open=False):
    """看板瓦片查询集（预取未收灶值守）；``only_open`` 时只留挂值守的灶。"""
    qs = FireHearth.objects.all()
    if only_open:
        qs = qs.filter(runs__in=open_runs().order_by()).distinct()
    return qs.prefetch_related(
        Prefetch(
            "runs",
            queryset=open_runs().prefetch_related("probes"),
            to_attr="open_runs_cache",
        )
    ).order_by("lane", "tag")


def origin_recon(origin=""):
    """三路对照：同一查询链派生 批 / 未收灶值守 / 灶去重。

    计数走数据库聚合，行数走实际渲染列表，二者之差必须为 0；
    产地无命中时三路均为 0、列表为空，不抛错。
    """
    lots_qs = lots_for_origin(origin)
    runs_qs = open_runs(lots_qs)
    hearths_qs = hearths_with_open_runs(runs_qs)

    lots = list(lots_qs)
    runs = list(runs_qs)
    hearths = list(hearths_qs)

    lot_count = lots_qs.count()
    run_count = runs_qs.count()
    hearth_count = hearths_qs.count()

    return {
        "origin": origin,
        "lots": lots,
        "runs": runs,
        "hearths": hearths,
        "lot_count": lot_count,
        "run_count": run_count,
        "hearth_count": hearth_count,
        "lot_diff": lot_count - len(lots),
        "run_diff": run_count - len(runs),
        "hearth_diff": hearth_count - len(hearths),
    }
