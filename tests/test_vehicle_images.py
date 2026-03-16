import unittest

from warthunder_rpc.vehicle_images import VehicleImageResolver


class FakeResponse:
    def __init__(self, text="", ok=True, headers=None):
        self.text = text
        self.ok = ok
        self.headers = headers or {}

    def close(self):
        return None


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, timeout=0, stream=False):
        self.calls.append((url, timeout, stream))
        if not self.responses:
            raise AssertionError("No fake response available")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class VehicleImageResolverTests(unittest.TestCase):
    def test_format_vehicle_name_strips_country_and_redundant_suffix(self):
        self.assertEqual(VehicleImageResolver.format_vehicle_name("us_m1a1_hc_abrams"), "M1A1 HC")

    def test_format_vehicle_name_keeps_non_redundant_names(self):
        self.assertEqual(VehicleImageResolver.format_vehicle_name("germ_leopard_2a7v"), "Leopard 2A7V")

    def test_dummy_plane_name_is_preserved(self):
        self.assertEqual(VehicleImageResolver.format_vehicle_name("DUMMY_PLANE"), "DUMMY PLANE")

    def test_extract_display_name_from_wiki_title(self):
        session = FakeSession([
            FakeResponse("<html><head><title>M1A1 HC | War Thunder Wiki</title></head></html>")
        ])
        resolver = VehicleImageResolver(session=session)
        self.assertEqual(resolver.get_display_name("us_m1a1_hc_abrams"), "M1A1 HC")

    def test_display_name_is_cached(self):
        session = FakeSession([
            FakeResponse("<html><head><title>M1A1 HC | War Thunder Wiki</title></head></html>")
        ])
        resolver = VehicleImageResolver(session=session)
        self.assertEqual(resolver.get_display_name("us_m1a1_hc_abrams"), "M1A1 HC")
        self.assertEqual(resolver.get_display_name("us_m1a1_hc_abrams"), "M1A1 HC")
        self.assertEqual(len(session.calls), 1)

    def test_country_code_uses_slug_prefix(self):
        self.assertEqual(VehicleImageResolver.get_country_code("us_m1a1_hc_abrams"), "US")
        self.assertEqual(VehicleImageResolver.get_country_code("ussr_t_80u"), "RU")
        self.assertEqual(VehicleImageResolver.get_country_code("germ_leopard_2a7v"), "DE")
        self.assertEqual(VehicleImageResolver.get_country_code("uk_challenger_2"), "GB")
        self.assertEqual(VehicleImageResolver.get_country_code("sw_strv_122"), "SE")

    def test_resolve_works_after_display_name_only_cache_entry(self):
        session = FakeSession([
            FakeResponse("<html><head><title>M1A1 HC | War Thunder Wiki</title></head></html>"),
            FakeResponse("", ok=True, headers={"content-type": "image/png"}),
        ])
        resolver = VehicleImageResolver(session=session)
        resolver.get_display_name("us_m1a1_hc_abrams")
        image_url, status = resolver.resolve("us_m1a1_hc_abrams")
        self.assertEqual(image_url, resolver.CDN_IMAGE_URL.format(slug="us_m1a1_hc_abrams"))
        self.assertEqual(status, "resolved_direct")


if __name__ == "__main__":
    unittest.main()
