import unittest
from delivery import delivery_price

class DeliveryPriceTests(unittest.TestCase):
    def price(self, **kwargs):
        return delivery_price(origin_city="Cidade da loja", origin_state="BA", **kwargs)

    def test_local_neighborhood_has_fixed_fee(self):
        self.assertEqual(self.price(neighborhood="  Sete de Abril ", city="Cidade da loja", state="ba"), 500)
        self.assertEqual(self.price(neighborhood="7 de Abril", city="Cidade da loja", state="BA"), 500)

    def test_same_name_in_other_city_requires_distance(self):
        with self.assertRaises(ValueError):
            self.price(neighborhood="Sete de Abril", city="Outra cidade", state="BA")

    def test_distance_and_minimum(self):
        address = dict(neighborhood="Outro bairro", city="Cidade da loja", state="BA")
        self.assertEqual(self.price(**address, distance_km="3.333", rate_cents_per_km=200), 667)
        self.assertEqual(self.price(**address, distance_km=1, rate_cents_per_km=200, minimum_cents=600), 600)

    def test_invalid_distances(self):
        for distance in ["NaN", "Infinity", -1, 0]:
            with self.assertRaises(ValueError):
                self.price(neighborhood="Outro", city="Cidade da loja", state="BA", distance_km=distance, rate_cents_per_km=200)
