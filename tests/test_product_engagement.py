import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from app import db, main


class ProductEngagementTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "engagement.db"
        self.conn = db.connect(self.path)
        db.init_db(self.conn)
        db.create_user(self.conn, "one@example.com", "Customer One", "overseas_customer", "password-1")
        db.create_user(self.conn, "two@example.com", "Customer Two", "overseas_customer", "password-2")
        self.users = {
            row["email"]: row
            for row in self.conn.execute("SELECT id, email FROM users WHERE email LIKE '%@example.com'").fetchall()
        }

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_customers_only_read_their_own_messages_and_admin_reads_all(self):
        first_id = self.users["one@example.com"]["id"]
        second_id = self.users["two@example.com"]["id"]
        db.create_product_message(self.conn, first_id, "sku-100", "Please send lifestyle photos.")
        db.create_product_message(self.conn, second_id, "SKU-100", "Can this be available in blue?")

        first_messages = db.user_product_messages(self.conn, first_id, "SKU-100")
        second_messages = db.user_product_messages(self.conn, second_id, "SKU-100")
        self.assertEqual([row["body"] for row in first_messages], ["Please send lifestyle photos."])
        self.assertEqual([row["body"] for row in second_messages], ["Can this be available in blue?"])

        admin_page = db.admin_product_messages(self.conn, q="SKU-100")
        self.assertEqual(admin_page["total"], 2)
        self.assertEqual({row["user_email"] for row in admin_page["messages"]}, {"one@example.com", "two@example.com"})

    def test_favorites_are_private_per_user_and_can_be_removed(self):
        first_id = self.users["one@example.com"]["id"]
        second_id = self.users["two@example.com"]["id"]
        db.set_product_favorite(self.conn, first_id, "sku-100", True)
        db.set_product_favorite(self.conn, second_id, "SKU-200", True)

        self.assertEqual(db.user_favorite_skus(self.conn, first_id), {"SKU-100"})
        self.assertEqual(db.user_favorite_skus(self.conn, second_id), {"SKU-200"})

        db.set_product_favorite(self.conn, first_id, "SKU-100", False)
        self.assertEqual(db.user_favorite_skus(self.conn, first_id), set())

    def test_seed_admin_migrates_the_single_super_admin_and_replaces_the_old_password(self):
        old_admin = self.conn.execute("SELECT id, email FROM users WHERE role='super_admin'").fetchone()
        with patch.dict(os.environ, {"ADMIN_EMAIL": "new-admin@example.com", "ADMIN_PASSWORD": "new-password-123"}):
            db.seed_admin(self.conn)
            self.conn.commit()

        migrated = self.conn.execute("SELECT id, email FROM users WHERE role='super_admin'").fetchall()
        self.assertEqual(len(migrated), 1)
        self.assertEqual(migrated[0]["id"], old_admin["id"])
        self.assertEqual(migrated[0]["email"], "new-admin@example.com")
        self.assertIsNone(db.authenticate(self.conn, old_admin["email"], "legacy-test-password"))
        self.assertIsNotNone(db.authenticate(self.conn, "new-admin@example.com", "new-password-123"))

    def test_seed_admin_without_configured_password_preserves_existing_hash(self):
        admin = self.conn.execute("SELECT id, password_hash FROM users WHERE role='super_admin'").fetchone()
        with patch.dict(os.environ, {"ADMIN_PASSWORD": ""}):
            db.seed_admin(self.conn)
        unchanged = self.conn.execute("SELECT password_hash FROM users WHERE id=?", (admin["id"],)).fetchone()
        self.assertEqual(unchanged["password_hash"], admin["password_hash"])

    def test_password_login_is_reserved_for_non_admin_accounts(self):
        backend = Path("app/main.py").read_text(encoding="utf-8")
        super_admin = self.conn.execute("SELECT * FROM users WHERE role='super_admin'").fetchone()
        customer = self.conn.execute("SELECT * FROM users WHERE email='one@example.com'").fetchone()
        self.assertFalse(main.password_login_allowed(super_admin))
        self.assertTrue(main.password_login_allowed(customer))
        self.assertIn("Administrator accounts must sign in with DingTalk", backend)
        self.assertIn('@app.get("/api/admin/notifications")', backend)

    def test_frontend_uses_private_messages_favorites_and_in_app_original_modal(self):
        root = Path("app/fontend/src")
        app = (root / "App.tsx").read_text(encoding="utf-8")
        drawer = (root / "components/ProductDrawer.tsx").read_text(encoding="utf-8")
        header = (root / "components/Header.tsx").read_text(encoding="utf-8")
        brand = (root / "components/BrandMark.tsx").read_text(encoding="utf-8")
        landing = (root / "components/LandingPage.tsx").read_text(encoding="utf-8")
        filters = (root / "components/FilterSidebar.tsx").read_text(encoding="utf-8")
        styles = (root / "styles.css").read_text(encoding="utf-8")
        admin_nav = (root / "admin/AdminNav.tsx").read_text(encoding="utf-8")
        backend = Path("app/main.py").read_text(encoding="utf-8")
        index = Path("app/fontend/index.html").read_text(encoding="utf-8")

        self.assertIn("Favorites", app)
        self.assertIn("setProductFavorite", app)
        self.assertIn("related-sets-divider", app)
        self.assertIn("Related sets containing SKU", app)
        self.assertIn("Comments & messages", drawer)
        self.assertIn("Set current image as cover", drawer)
        self.assertIn("isAdmin && selectedAsset.kind", drawer)
        self.assertIn("const canAdmin = user.isAdmin", header)
        self.assertIn("Search by SKU, event, year or asset name", header)
        self.assertNotIn("Search by SKU, product name, or Drive path", header)
        self.assertIn("{canAdmin && (", header)
        self.assertNotIn("Drive location", drawer)
        self.assertNotIn("Copy path", drawer)
        self.assertIn("createPortal", drawer)
        self.assertNotIn('target="_blank"', drawer)
        self.assertIn("KAIRAY GOLF", brand)
        self.assertIn("/assets/kairay-golf-logo.png", brand)
        self.assertIn("KAIRAY GOLF · CLIENT ASSET PORTAL", landing)
        self.assertIn('const dingtalkLoginUrl = "/api/auth/dingtalk/start"', landing)
        self.assertIn('params.get("dingtalk_error")', landing)
        self.assertIn("Sign in with DingTalk", landing)
        self.assertNotIn("管理员和超级管理员请使用钉钉登录", landing)
        self.assertNotIn("<span>钉钉登录</span>", landing)
        self.assertIn("pendingNotificationCount", header)
        self.assertIn("notification-badge", styles)
        self.assertIn("login-dingtalk-link", styles)
        self.assertIn('option.trim().toLowerCase() !== "unassigned"', filters)
        self.assertNotIn('label="Access"', filters)
        self.assertIn("filters.brand.includes(product.brand)", filters)
        self.assertIn("brand: value as string[], category: []", app)
        self.assertIn("onClick={() => onChange([option])}", filters)
        self.assertIn("onClick={() => onChange([category])}", filters)
        self.assertIn("Include ${option} in Brand selection", filters)
        self.assertIn("Include ${category} in Product Category selection", filters)
        self.assertIn("filter-flow-step", filters)
        self.assertIn('title="Product Category"', filters)
        self.assertIn('title="Asset Type"', filters)
        self.assertIn("Clicking a collection resets the product filters above", filters)
        self.assertIn("matchesOtherCollection", app)
        self.assertIn("return hasProductFilters || !filters.other.length", app)
        self.assertNotIn("KOL & UCG", filters)
        self.assertNotIn("other: [], theme", app)
        self.assertIn('rel="icon" type="image/png" href="/assets/kairay-golf-logo.png"', index)
        self.assertIn(".original-modal-media", styles)
        self.assertIn("overflow: hidden", styles)
        self.assertIn("/* Kairay admin workspace */", styles)
        self.assertIn("background: var(--kairay-red-dark);", styles)
        self.assertIn("box-shadow: inset 3px 0 0 var(--kairay-yellow);", styles)
        self.assertIn('id: "messages"', admin_nav)
        self.assertIn('@app.get("/api/admin/messages")', backend)
        self.assertIn('@app.post("/api/admin/products/{sku}/cover")', backend)
        self.assertIn("user=Depends(require_api_admin)", backend)


if __name__ == "__main__":
    unittest.main()
