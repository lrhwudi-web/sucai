import unittest
from pathlib import Path


class LoginAssetPerformanceTest(unittest.TestCase):
    def test_login_uses_small_responsive_webp_assets(self):
        frontend = Path("app/fontend")
        landing = (frontend / "src/components/LandingPage.tsx").read_text(encoding="utf-8")
        index = (frontend / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("login-command-center.png", landing)
        self.assertIn("login-command-center-720.v2.webp 720w", landing)
        self.assertIn("login-command-center-1080.v2.webp 1080w", landing)
        self.assertIn('media="(min-width: 1181px)"', landing)
        self.assertIn('fetchPriority="high"', landing)
        self.assertIn('rel="preload"', index)
        self.assertIn('media="(min-width: 1181px)"', index)

        for name in (
            "login-command-center-720.v2.webp",
            "login-command-center-1080.v2.webp",
        ):
            asset = frontend / "public/assets" / name
            self.assertTrue(asset.is_file(), name)
            self.assertLess(asset.stat().st_size, 75_000, name)


if __name__ == "__main__":
    unittest.main()
