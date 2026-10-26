import unittest

from server import is_valid_infinitepay_checkout_url


class InfinitePayCheckoutUrlTests(unittest.TestCase):
    def test_accepts_current_checkout_domain(self):
        self.assertTrue(is_valid_infinitepay_checkout_url("https://checkout.infinitepay.io/loja/abc123"))

    def test_accepts_legacy_checkout_domain(self):
        self.assertTrue(is_valid_infinitepay_checkout_url("https://checkout.infinitepay.com.br/abc123"))

    def test_rejects_non_checkout_urls(self):
        for url in (
            "http://checkout.infinitepay.io/abc123",
            "https://checkout.infinitepay.io.evil.example/abc123",
            "https://evil.example/checkout.infinitepay.io/abc123",
            "https://user@checkout.infinitepay.io/abc123",
            "https://checkout.infinitepay.io:8443/abc123",
            "https://checkout.infinitepay.io/",
            None,
        ):
            with self.subTest(url=url):
                self.assertFalse(is_valid_infinitepay_checkout_url(url))


if __name__ == "__main__":
    unittest.main()
