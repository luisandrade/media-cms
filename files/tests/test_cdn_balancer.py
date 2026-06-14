from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings

from files.cdn_balancer import get_balanced_hosts_for_request


class CdnBalancerTests(TestCase):
    @override_settings(
        CDN_BALANCER_ENABLED=True,
        CDN_BALANCER_FALLBACK_TO_CDN=True,
        CDN_BALANCER_FALLBACK_VOD_HOST="claro-vtrlolla-vod.cl.cdnz.cl",
        CDN_BALANCER_FALLBACK_LIVE_HOST="claro.02.cl.cdnz.cl",
    )
    @patch("files.cdn_balancer.geoip2", None)
    def test_missing_geoip2_uses_cdn_fallback_hosts(self):
        request = RequestFactory().get("/", HTTP_X_REAL_IP="186.79.196.48")

        balanced = get_balanced_hosts_for_request(request)

        self.assertEqual(balanced.vod_host, "claro-vtrlolla-vod.cl.cdnz.cl")
        self.assertEqual(balanced.live_host, "claro.02.cl.cdnz.cl")
        self.assertEqual(balanced.client_ip, "186.79.196.48")
        self.assertEqual(balanced.decision, "fallback_cdn:no_geoip2")
