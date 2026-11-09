import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.resolve()
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient

from api_server import app
from saas_store import (
    CHANNEL_CATALOG,
    PRICING_PLANS,
    calculate_pricing_comparison,
    create_job_record,
    create_series_record,
    discover_rendered_vault,
    get_account_pool_telemetry,
    list_job_records,
    list_series_records,
    update_job_record,
)


class TestSaaSPlatform(unittest.TestCase):
    """
    Unit and integration tests for the VoxFlow Studio SaaS platform:
      1. RPM-tiered language pricing rules (English > Urdu; Dual-Stream 2-for-1 arbitrage).
      2. Series & Render Job SQLite persistence and input validation.
      3. Rendered video vault discovery & English/Urdu episode pairing.
      4. FastAPI REST endpoints and media streaming security.
    """

    def test_pricing_hierarchy_english_higher_than_urdu(self):
        """English plans must be priced higher than Urdu plans due to higher Tier-1 RPMs."""
        urdu_starter = PRICING_PLANS["urdu_starter"]["price_usd"]
        english_starter = PRICING_PLANS["english_starter"]["price_usd"]
        both_starter = PRICING_PLANS["both_starter"]["price_usd"]

        urdu_daily = PRICING_PLANS["urdu_daily"]["price_usd"]
        english_daily = PRICING_PLANS["english_daily"]["price_usd"]
        both_daily = PRICING_PLANS["both_daily"]["price_usd"]

        self.assertGreater(english_starter, urdu_starter)
        self.assertGreater(english_daily, urdu_daily)
        self.assertGreater(both_starter, english_starter)
        self.assertGreater(both_daily, english_daily)

        # Dual-Stream arbitrage: 2x videos delivered using the exact same Flow scene renders
        self.assertEqual(
            PRICING_PLANS["both_daily"]["flow_renders_used"],
            PRICING_PLANS["english_daily"]["flow_renders_used"],
        )
        self.assertEqual(
            PRICING_PLANS["both_daily"]["videos_delivered_per_month"],
            PRICING_PLANS["english_daily"]["videos_delivered_per_month"] * 2,
        )

    def test_roi_calculator_by_language_tier(self):
        """English RPM payout must exceed Urdu RPM payout at identical view counts."""
        ur_roi = calculate_pricing_comparison("urdu", monthly_views=500_000)
        en_roi = calculate_pricing_comparison("english", monthly_views=500_000)
        both_roi = calculate_pricing_comparison("both", monthly_views=500_000)

        self.assertGreater(
            en_roi["estimated_creator_ad_revenue_usd"],
            ur_roi["estimated_creator_ad_revenue_usd"],
        )
        self.assertGreater(
            both_roi["estimated_creator_ad_revenue_usd"],
            en_roi["estimated_creator_ad_revenue_usd"],
        )
        # Per-video cost on Dual-Stream must be lower than English-only
        self.assertLess(
            both_roi["effective_cost_per_video_usd"],
            en_roi["effective_cost_per_video_usd"],
        )

    def test_series_and_jobs_sqlite_lifecycle(self):
        """Series creation, validation, and job state updates must persist cleanly."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_db = Path(tmp_dir) / "test_saas.db"

            series = create_series_record(
                name="Gym Biology Daily",
                channel="body_simulator",
                language_tier="both",
                db_path=test_db,
            )
            self.assertEqual(series["channel"], "body_simulator")
            self.assertEqual(series["language_tier"], "both")
            self.assertEqual(series["price_usd"], PRICING_PLANS["both_daily"]["price_usd"])

            all_series = list_series_records(db_path=test_db)
            self.assertEqual(len(all_series), 1)

            # Invalid channel must raise ValueError
            with self.assertRaises(ValueError):
                create_series_record(
                    name="Bad Channel",
                    channel="invalid_niche",
                    language_tier="english",
                    db_path=test_db,
                )

            job = create_job_record(
                channel="garage_guru",
                lang="english",
                mock_mode=True,
                series_id=series["id"],
                db_path=test_db,
            )
            self.assertEqual(job["status"], "queued")

            update_job_record(
                job["job_id"],
                db_path=test_db,
                status="completed",
                progress=100,
                stage="[6/6] Completed",
            )
            jobs = list_job_records(db_path=test_db)
            self.assertEqual(jobs[0]["status"], "completed")
            self.assertEqual(jobs[0]["progress"], 100)

    def test_vault_discovery_and_account_pool(self):
        """Vault discovery must locate existing rendered MP4s and pair English/Urdu siblings."""
        vault_all = discover_rendered_vault()
        self.assertGreater(len(vault_all), 0, "Expected existing rendered MP4 videos in output/")
        dual_pairs = [ep for ep in vault_all if ep["english"] and ep["urdu"]]
        self.assertGreater(len(dual_pairs), 0, "Expected at least one paired English+Urdu episode")

        # Multi-tenant client isolation: empty allowed_video_urls must return 0 episodes
        vault_new_client = discover_rendered_vault(allowed_video_urls=set())
        self.assertEqual(len(vault_new_client), 0, "A client with 0 rendered videos must see 0 episodes in their vault")

        # Client with 1 specific allowed video URL sees ONLY that episode
        sample_url = (vault_all[0]["english"] or vault_all[0]["urdu"])["video_url"]
        vault_one_client = discover_rendered_vault(allowed_video_urls={sample_url})
        self.assertEqual(len(vault_one_client), 1)

        pool = get_account_pool_telemetry()
        self.assertEqual(pool["total_workers"], 6)
        self.assertEqual(len(CHANNEL_CATALOG), 6)
        self.assertIn("cluster_tokens_remaining", pool)
        self.assertIn("cluster_tokens_max", pool)
        self.assertIn("cluster_percent", pool)
        self.assertGreater(pool["cluster_tokens_remaining"], 0)
        for w in pool["workers"]:
            self.assertIn("tokens_remaining", w)
            self.assertIn("tokens_total", w)
            self.assertIn("tokens_percent", w)

    def test_fastapi_endpoints_and_media_streaming(self):
        """FastAPI routes must serve UI, catalog, pricing, vault, and stream real MP4s safely."""
        client = TestClient(app)

        # 1. Health & Web UI
        r_health = client.get("/health")
        self.assertEqual(r_health.status_code, 200)
        self.assertEqual(r_health.json()["status"], "ok")

        r_ui = client.get("/")
        self.assertEqual(r_ui.status_code, 200)
        self.assertIn("VoxFlow Studio", r_ui.text)

        # 2. Catalog & Pricing API
        r_cat = client.get("/api/catalog")
        self.assertEqual(r_cat.status_code, 200)
        self.assertEqual(len(r_cat.json()["channels"]), 6)

        r_price = client.get("/api/pricing?language_tier=english&monthly_views=1000000")
        self.assertEqual(r_price.status_code, 200)
        self.assertEqual(r_price.json()["language_tier"], "english")

        # 3. Vault & Real Video Stream
        r_vault = client.get("/api/vault")
        self.assertEqual(r_vault.status_code, 200)
        episodes = r_vault.json()["episodes"]
        self.assertGreater(len(episodes), 0)

        first_pair = episodes[0]
        stream_info = first_pair["english"] or first_pair["urdu"]
        r_media = client.get(stream_info["video_url"])
        self.assertEqual(r_media.status_code, 200)
        self.assertEqual(r_media.headers["content-type"], "video/mp4")

        # 4. Path traversal security check
        r_bad = client.get("/media/body_simulator/english/../../config.py")
        self.assertIn(r_bad.status_code, (400, 404))

        # 5. Security headers check
        self.assertEqual(r_health.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(r_health.headers.get("x-frame-options"), "DENY")

    def test_security_zero_email_leakage_and_live_render_gate(self):
        """
        Public endpoints must NEVER leak personal @gmail/@aleeas/@mask emails,
        and live Google Flow / Playwright renders (mock=False) must reject unauthenticated callers.
        """
        client = TestClient(app)

        # 1. Verify zero email addresses leaked in /api/catalog and that /api/pool-status is admin-only
        r_pool_anon = client.get("/api/pool-status")
        self.assertEqual(r_pool_anon.status_code, 403)
        pool_text = r_pool_anon.text.lower()
        cat_text = client.get("/api/catalog").text.lower()
        for forbidden_domain in ("@gmail.com", "@aleeas.com", "@mask.me", "ammar.akbar", "saleemiman"):
            self.assertNotIn(forbidden_domain, pool_text)
            self.assertNotIn(forbidden_domain, cat_text)

        # 2. Verify live Flow/Playwright render (mock=False) is blocked with 401 without X-Studio-Key
        r_unauth_live = client.post(
            "/api/generate",
            json={"channel": "body_simulator", "lang": "both", "mock": False},
        )
        self.assertEqual(r_unauth_live.status_code, 401)

        # 3. Verify unauthenticated webhook /trigger/{niche} is blocked with 401
        r_webhook = client.post("/trigger/body_simulator")
        self.assertEqual(r_webhook.status_code, 401)

    def test_custom_director_and_manual_scene_compilation(self):
        """
        Custom AI Director & Manual 4-Scene Matrix must compile 4 camera-motion shots
        with synchronized English and Urdu dialogue and zero secret leakage.
        """
        from brain.multi_channel_director import MultiChannelDirector

        director = MultiChannelDirector()

        # 1. Test deterministic custom episode fallback & style DNA resolution
        style_dna = director._resolve_style_dna("xray_cutaway", "xray_mechanics")
        self.assertIn("x-ray", style_dna.lower())

        manual_ep = director.compile_manual_episode(
            custom_scenes=[
                {
                    "flow_prompt": "Macro dolly-in on lithium-ion anode dendrites sparking in 8K",
                    "speaker": "narrator",
                    "english_line": "At 800 volts, microscopic lithium dendrites pierce the separator!",
                    "urdu_line": "800 volt par bareek lithium dendrites separator ko phaar dete hain!",
                },
                {
                    "flow_prompt": "Low-angle tracking shot of electrolyte boiling inside glass cell",
                    "speaker": "narrator",
                    "english_line": "Within milliseconds, the liquid electrolyte flashes into superheated gas!",
                    "urdu_line": "Chand milliseconds mein liquid electrolyte garam gas ban jata hai!",
                },
            ],
            title="EV Battery Thermal Runaway",
            visual_style="xray_cutaway",
            channel="xray_mechanics",
        )
        self.assertEqual(len(manual_ep.scenes), 2)
        self.assertEqual(len(manual_ep.dialogue_english), 2)
        self.assertEqual(len(manual_ep.dialogue_urdu), 2)
        self.assertIn("lithium-ion anode", manual_ep.scenes[0].flow_prompt)

        # 2. Test /api/config/public exposes Supabase anon config but NEVER private keys
        client = TestClient(app)
        r_cfg = client.get("/api/config/public")
        self.assertEqual(r_cfg.status_code, 200)
        cfg_json = r_cfg.json()
        self.assertEqual(cfg_json["supabase_project_ref"], "ouqjlqqgnboytjvudylv")
        self.assertTrue(cfg_json["supabase_url"].startswith("https://ouqjlqqgnboytjvudylv.supabase.co"))
        self.assertNotIn("service_role", r_cfg.text)
        self.assertNotIn("vf_admin_", r_cfg.text)

        # 3. Test /api/director/preview for custom_director and manual_scenes
        r_prev = client.post(
            "/api/director/preview",
            json={
                "creation_mode": "custom_director",
                "channel": "body_simulator",
                "custom_prompt": "Inside your brain 10 minutes after drinking double espresso",
                "visual_style": "pixar_3d",
            },
        )
        self.assertEqual(r_prev.status_code, 200)
        prev_data = r_prev.json()
        self.assertEqual(len(prev_data["scenes"]), 4)
        self.assertEqual(len(prev_data["dialogue_english"]), 4)
        self.assertEqual(len(prev_data["dialogue_urdu"]), 4)

    def test_flow_tokens_telemetry_and_deduction(self):
        """Flow tokens must decrement on renders and be queryable via /api/pool-status."""
        from video_engine.pool_manager import FlowPoolManager
        from api_server import STUDIO_ADMIN_KEY

        pm = FlowPoolManager()
        # Calibrate account_1 to test value
        pm.set_account_tokens("account_1", tokens_remaining=950, tokens_total=1000)
        self.assertEqual(pm.status["account_1"]["tokens_remaining"], 950)

        # Deduct 10 tokens
        new_val = pm.deduct_tokens("account_1", cost=10)
        self.assertEqual(new_val, 940)
        self.assertEqual(pm.status["account_1"]["tokens_remaining"], 940)

        # Fast API endpoint verification
        client = TestClient(app)
        r_pool = client.get("/api/pool-status", headers={"X-Studio-Key": STUDIO_ADMIN_KEY})
        self.assertEqual(r_pool.status_code, 200)
        p_data = r_pool.json()
        self.assertIn("cluster_tokens_remaining", p_data)
        self.assertIn("cluster_tokens_max", p_data)
        self.assertGreater(p_data["cluster_tokens_remaining"], 0)

        # Test admin calibration endpoint security
        # Unauthorized without admin credentials
        r_unauth = client.post(
            "/api/pool/set-tokens",
            json={"account_name": "account_1", "tokens_remaining": 880, "tokens_total": 1000},
        )
        self.assertEqual(r_unauth.status_code, 403)

        # Authorized with Studio Admin Key
        r_auth = client.post(
            "/api/pool/set-tokens",
            headers={"X-Studio-Key": STUDIO_ADMIN_KEY},
            json={"account_name": "account_1", "tokens_remaining": 900, "tokens_total": 1000},
        )
        self.assertEqual(r_auth.status_code, 200)
        self.assertEqual(r_auth.json()["status"], "ok")

        # 4. Verify single-palette production UI, zero '//' AI-slop labels, no wheel hijacking, and workspace CSS
        ui_html = client.get("/").text
        self.assertNotIn("setReelTheme", ui_html)
        self.assertNotIn("lenis.min.js", ui_html)
        self.assertNotIn("ADMIN //", ui_html)
        self.assertNotIn("01 //", ui_html)
        self.assertNotIn("02 //", ui_html)
        self.assertNotIn("id=\"auth-tab-signup\"", ui_html)
        self.assertIn("body.authenticated-workspace #pricing-sec", ui_html)
        self.assertIn("@supabase/supabase-js@2", ui_html)
        self.assertIn("Preset Shows", ui_html)
        self.assertIn("Custom Prompt", ui_html)
        self.assertIn("Scene Editor", ui_html)

        # 5. Verify /api/admin/provision-customer blocks non-admins (403)
        r_unauth_prov = client.post(
            "/api/admin/provision-customer",
            json={
                "email": "unauthorized@client.com",
                "password": "ClientPass#2026!",
                "plan_tier": "english_daily",
            },
        )
        self.assertEqual(r_unauth_prov.status_code, 403)

        # 6. Verify per-user WhatsApp setup UI & isolation from Founder's .env number
        self.assertIn("How to get your WhatsApp Agent Key", ui_html)
        self.assertIn("Yes, I received it", ui_html)
        r_unauth_wa = client.post(
            "/api/whatsapp/test",
            json={"wa_agent_token": "WAA_test_token", "wa_user_id": "user:12345"},
        )
        self.assertEqual(r_unauth_wa.status_code, 401)


if __name__ == "__main__":
    unittest.main()
