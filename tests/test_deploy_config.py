import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class DeploymentConfigTests(unittest.TestCase):
    def test_nginx_applies_safe_cache_headers_to_revalidated_assets(self) -> None:
        config = (ROOT / "deploy" / "nginx-app.conf").read_text(
            encoding="utf-8"
        )

        self.assertIn(r"location ~* \.(?:html|js|css)$", config)
        self.assertIn('add_header Cache-Control "no-cache" always;', config)
        self.assertIn("add_header X-Content-Type-Options nosniff always;", config)
        self.assertIn("add_header Referrer-Policy strict-origin-when-cross-origin always;", config)
        self.assertIn("add_header X-Frame-Options SAMEORIGIN always;", config)

    def test_nginx_compresses_json_geojson_javascript_and_css(self) -> None:
        config = (ROOT / "deploy" / "nginx-app.conf").read_text(
            encoding="utf-8"
        )

        self.assertIn("application/geo+json geojson;", config)
        self.assertIn(
            "include /etc/nginx/mime.types;\n    types {\n"
            "        application/geo+json geojson;\n    }",
            config,
        )
        self.assertIn("gzip on;", config)
        self.assertIn("gzip_min_length 1024;", config)
        self.assertIn(
            "gzip_types application/json application/geo+json "
            "text/css application/javascript;",
            config,
        )

    def test_compose_host_binding_is_configurable_and_loopback_by_default(self) -> None:
        compose = yaml.safe_load(
            (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        )

        self.assertEqual(
            compose["services"]["co2-map"]["ports"],
            ["${CO2_MAP_BIND:-127.0.0.1:18080}:8080"],
        )


if __name__ == "__main__":
    unittest.main()
