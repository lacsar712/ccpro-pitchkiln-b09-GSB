"""产地精确筛 / 看板值守过滤 / 三路对照的口径测试。

种子数据（两产地，每地有批有值守）：
- 松脂坳：lot_a、lot_c 两批；未收灶值守 3 条（h1/h2/h5），去重灶 3 台
- 桐油坑：lot_b 一批；未收灶值守 1 条（h3），去重灶 1 台；另有 1 条已收灶值守（h4，不计入）
"""
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import CookRun, ResinLot
from .seed import ensure_seed_data
from .services.queries import board_hearths, origin_reconciliation


class ReconTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_seed_data()

    def setUp(self):
        self.client = Client()
        self.assertTrue(self.client.login(username="admin", password="123456"))


class OriginReconciliationTests(ReconTestBase):
    def test_recon_balanced_for_seeded_origins(self):
        """两产地三路对照：复算数与渲染行一一对应，差必须为 0。"""
        expected = {
            "松脂坳": (2, 3, 3),
            "桐油坑": (1, 1, 1),
        }
        for origin, (lots, runs, hearths) in expected.items():
            with self.subTest(origin=origin):
                recon = origin_reconciliation(origin)
                self.assertEqual(
                    (recon.lot_total, recon.run_total, recon.hearth_total),
                    (lots, runs, hearths),
                )
                self.assertEqual(len(recon.lots), lots)
                self.assertEqual(len(recon.runs), runs)
                self.assertEqual(len(recon.hearths), hearths)
                self.assertEqual(recon.lot_delta, 0)
                self.assertEqual(recon.run_delta, 0)
                self.assertEqual(recon.hearth_delta, 0)
                self.assertTrue(recon.balanced)

    def test_recon_all_origins_balanced(self):
        """不选产地（全部）时同样三路对齐。"""
        for origin in (None, ""):
            with self.subTest(origin=origin):
                recon = origin_reconciliation(origin)
                self.assertEqual(
                    (recon.lot_total, recon.run_total, recon.hearth_total),
                    (3, 4, 4),
                )
                self.assertTrue(recon.balanced)

    def test_origin_filter_is_exact(self):
        """精确筛：「松脂坳」不得命中「松脂坳东沟」。"""
        ResinLot.objects.create(
            lotCode="脂-松脂坳东沟-999",
            originPlace="松脂坳东沟",
            arrivalKg=Decimal("1.00"),
            receivedAt=timezone.now(),
        )
        recon = origin_reconciliation("松脂坳")
        self.assertEqual(recon.lot_total, 2)
        self.assertNotIn("松脂坳东沟", [lot.originPlace for lot in recon.lots])

        recon_exact = origin_reconciliation("松脂坳东沟")
        self.assertEqual(recon_exact.lot_total, 1)
        self.assertTrue(recon_exact.balanced)

    def test_unknown_origin_all_zero_no_error(self):
        """产地无命中：三路都为 0、流为空，不得抛错。"""
        recon = origin_reconciliation("不存在的产地")
        self.assertEqual(
            (recon.lot_total, recon.run_total, recon.hearth_total), (0, 0, 0)
        )
        self.assertEqual(recon.lots, [])
        self.assertEqual(recon.runs, [])
        self.assertEqual(recon.hearths, [])
        self.assertTrue(recon.balanced)

    def test_closed_run_not_counted(self):
        """已收灶值守不计入：桐油坑有 2 条值守，未收灶只有 1 条。"""
        self.assertEqual(
            CookRun.objects.filter(resinLot__originPlace="桐油坑").count(), 2
        )
        recon = origin_reconciliation("桐油坑")
        self.assertEqual(recon.run_total, 1)
        self.assertEqual(recon.hearth_total, 1)

    def test_hearth_count_is_scoped_not_global(self):
        """灶去重数按筛选口径算，不是全库灶数（全库 5 台）。"""
        recon = origin_reconciliation("松脂坳")
        self.assertEqual(recon.hearth_total, 3)
        self.assertNotEqual(recon.hearth_total, 5)


class BoardDutyFilterTests(ReconTestBase):
    def test_duty_open_lists_only_hearths_with_open_runs(self):
        tags = {h.tag for h in board_hearths("open")}
        self.assertEqual(tags, {"坳火-甲", "坳火-乙", "坳火-夜班", "坑火-西一"})

    def test_duty_none_lists_only_hearths_without_open_runs(self):
        tags = [h.tag for h in board_hearths("none")]
        self.assertEqual(tags, ["坑火-西二"])

    def test_duty_any_and_invalid_fall_back_to_all(self):
        self.assertEqual(len(list(board_hearths("any"))), 5)
        self.assertEqual(len(list(board_hearths("bogus"))), 5)

    def test_board_and_recon_share_open_run_scope(self):
        """看板「挂未收灶值守」与三路对照的瓦片去重出自同一口径。"""
        board_tags = {h.tag for h in board_hearths("open")}
        recon_tags = {h.tag for h in origin_reconciliation("").hearths}
        self.assertEqual(board_tags, recon_tags)


class ViewConsistencyTests(ReconTestBase):
    def test_feed_full_and_htmx_partial_share_recon(self):
        """切换产地：整页刷新与 HTMX 局部同一口径（同函数、同数值）。"""
        url = reverse("resin_lot_feed")
        full = self.client.get(url, {"origin": "松脂坳"})
        partial = self.client.get(url, {"origin": "松脂坳"}, HTTP_HX_REQUEST="true")

        self.assertEqual(full.status_code, 200)
        self.assertEqual(partial.status_code, 200)
        self.assertIn("resin/feed.html", [t.name for t in full.templates])
        self.assertIn("resin/_feed_results.html", [t.name for t in partial.templates])

        rf, rp = full.context["recon"], partial.context["recon"]
        self.assertEqual(
            (rf.lot_total, rf.run_total, rf.hearth_total),
            (rp.lot_total, rp.run_total, rp.hearth_total),
        )
        self.assertEqual((rf.lot_total, rf.run_total, rf.hearth_total), (2, 3, 3))
        self.assertTrue(rf.balanced and rp.balanced)
        # 片段只含结果区，不含整页的登记表单
        self.assertContains(full, "lot-intake")
        self.assertNotContains(partial, "lot-intake")
        # 整页内嵌同一片段，三路对照面板两边都在
        self.assertContains(full, "三路对照")
        self.assertContains(partial, "三路对照")

    def test_feed_unknown_origin_renders_empty(self):
        url = reverse("resin_lot_feed")
        for kwargs in ({}, {"HTTP_HX_REQUEST": "true"}):
            with self.subTest(kwargs=kwargs):
                resp = self.client.get(url, {"origin": "查无此地"}, **kwargs)
                self.assertEqual(resp.status_code, 200)
                recon = resp.context["recon"]
                self.assertEqual(
                    (recon.lot_total, recon.run_total, recon.hearth_total),
                    (0, 0, 0),
                )
                self.assertContains(resp, "该产地暂无来脂批")

    def test_board_full_and_partials_share_duty_scope(self):
        """看板：整页、home 的 HTMX 分支、网格片段三者同一值守口径。"""
        home = reverse("home")
        grid = reverse("floor_grid")

        full = self.client.get(home, {"duty": "open"})
        hx_home = self.client.get(home, {"duty": "open"}, HTTP_HX_REQUEST="true")
        partial = self.client.get(grid, {"duty": "open"})

        tags_full = sorted(h.tag for h in full.context["hearths"])
        tags_hx = sorted(h.tag for h in hx_home.context["hearths"])
        tags_partial = sorted(h.tag for h in partial.context["hearths"])
        self.assertEqual(tags_full, tags_hx)
        self.assertEqual(tags_full, tags_partial)
        self.assertEqual(len(tags_full), 4)

        none_resp = self.client.get(grid, {"duty": "none"})
        self.assertEqual([h.tag for h in none_resp.context["hearths"]], ["坑火-西二"])

    def test_grid_refresh_url_carries_duty(self):
        """网格自刷新地址携带当前 duty，floor-refresh 后口径不漂。"""
        resp = self.client.get(reverse("home"), {"duty": "none"})
        self.assertContains(resp, "?duty=none")
