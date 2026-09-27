"""看板与来脂批流共用的查询口径。

本模块是「产地精确筛」「是否挂未收灶值守」「三路对照」的唯一查询入口：
看板（整页 + HTMX 网格片段）与来脂批流（整页 + HTMX 片段）都从这里取数，
禁止在视图里各写一套过滤逻辑，否则整页与局部会出现口径分裂。
"""
from dataclasses import dataclass
from typing import Optional

from django.db.models import Prefetch

from apps.kiln.models import CookRun, FireHearth, ResinLot

# —— 看板「是否挂未收灶值守」过滤 ——
DUTY_ANY = "any"
DUTY_OPEN = "open"
DUTY_NONE = "none"
DUTY_FILTER_CHOICES = (
    (DUTY_ANY, "全部灶台"),
    (DUTY_OPEN, "挂未收灶值守"),
    (DUTY_NONE, "无未收灶值守"),
)


def normalize_duty(value: Optional[str]) -> str:
    """非法 / 缺失的 duty 参数一律回落到「全部灶台」。"""
    valid = {key for key, _ in DUTY_FILTER_CHOICES}
    return value if value in valid else DUTY_ANY


def resin_lots(origin: Optional[str] = None):
    """来脂批查询：传入产地时按 originPlace **精确**匹配，否则全量。

    精确筛：只用 ``filter(originPlace=origin)`` 全等比较，
    不做 icontains / 大小写折叠，「松脂坳」不会命中「松脂坳东沟」。
    """
    qs = ResinLot.objects.all()
    if origin:
        qs = qs.filter(originPlace=origin)
    return qs


def origin_choices():
    """产地精确筛的下拉候选：全库去重产地，按字典序。"""
    return list(
        ResinLot.objects.order_by("originPlace")
        .values_list("originPlace", flat=True)
        .distinct()
    )


def open_runs(lots=None):
    """未收灶值守（closedAt 为空）基础查询，可按来脂批集合收窄。

    看板的「是否挂未收灶值守」过滤与来脂批流的三路对照都以此为底座。
    """
    qs = CookRun.objects.filter(closedAt__isnull=True)
    if lots is not None:
        qs = qs.filter(resinLot__in=lots)
    return qs.select_related("hearth", "resinLot").order_by("-openedAt", "-id")


def hearths_for_runs(runs):
    """值守集合所属灶台（去重），供瓦片去重渲染。"""
    return FireHearth.objects.filter(pk__in=runs.values("hearth_id")).order_by(
        "lane", "tag"
    )


def board_hearths(duty: str = DUTY_ANY):
    """看板灶台：按「是否挂未收灶值守」过滤，并预取未收灶值守。

    duty=open  只留挂着未收灶值守的灶；
    duty=none  只留没有未收灶值守的灶；
    其余       全部灶台。
    """
    qs = FireHearth.objects.all()
    if duty == DUTY_OPEN:
        qs = qs.filter(pk__in=open_runs().values("hearth_id"))
    elif duty == DUTY_NONE:
        qs = qs.exclude(pk__in=open_runs().values("hearth_id"))
    return qs.prefetch_related(
        Prefetch(
            "runs",
            queryset=open_runs().prefetch_related("probes"),
            to_attr="open_runs_cache",
        )
    ).order_by("lane", "tag")


@dataclass
class OriginReconciliation:
    """某一产地（空串表示全部产地）的三路对照结果。

    三路各自的「渲染行」来自实际取出的列表，「复算数」来自独立的
    聚合查询；两者相减为差，差必须恒为 0。
    """

    origin: str
    lots: list          # 渲染用：筛选后卡片行
    runs: list          # 渲染用：未收灶值守条
    hearths: list       # 渲染用：瓦片去重
    lot_total: int      # 复算：该产地批张数
    run_total: int      # 复算：这些批下未收灶值守条数
    hearth_total: int   # 复算：这些值守所属灶去重数

    @property
    def lot_delta(self) -> int:
        return self.lot_total - len(self.lots)

    @property
    def run_delta(self) -> int:
        return self.run_total - len(self.runs)

    @property
    def hearth_delta(self) -> int:
        return self.hearth_total - len(self.hearths)

    @property
    def balanced(self) -> bool:
        return self.lot_delta == 0 and self.run_delta == 0 and self.hearth_delta == 0


def origin_reconciliation(origin: Optional[str] = None) -> OriginReconciliation:
    """三路对照：批张数 / 未收灶值守条数 / 灶去重数，全部按当前产地口径复算。

    产地无命中时三路均为 0、列表为空，不抛错。
    """
    origin = (origin or "").strip()
    lots_qs = resin_lots(origin)
    runs_qs = open_runs(lots_qs)

    # 渲染行：实际取出、交给模板逐行渲染的列表
    lots = list(lots_qs)
    runs = list(runs_qs)
    hearths = list(hearths_for_runs(runs_qs))

    # 复算数：独立的聚合查询，与渲染列表分开算，用于对账
    lot_total = lots_qs.count()
    run_total = runs_qs.count()
    hearth_total = (
        FireHearth.objects.filter(runs__in=runs_qs).distinct().count()
    )

    return OriginReconciliation(
        origin=origin,
        lots=lots,
        runs=runs,
        hearths=hearths,
        lot_total=lot_total,
        run_total=run_total,
        hearth_total=hearth_total,
    )
