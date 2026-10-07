"""Delivery pricing for the shop motorcyclist (amounts in cents)."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import unicodedata


def normalized_place(value):
    plain = unicodedata.normalize("NFKD", str(value))
    return " ".join("".join(c for c in plain if not unicodedata.combining(c)).casefold().split())


def delivery_price(*, neighborhood, city, state, origin_city, origin_state,
                   distance_km=None, rate_cents_per_km=None, minimum_cents=0):
    # A neighborhood name alone must not match an address in another city.
    if not origin_city or not origin_state:
        raise ValueError("Configure a cidade e o estado de origem da loja.")
    if (normalized_place(city) == normalized_place(origin_city)
            and normalized_place(state) == normalized_place(origin_state)
            and normalized_place(neighborhood) in {"sete de abril", "7 de abril"}):
        return 500
    if distance_km is None or rate_cents_per_km is None:
        raise ValueError("Informe a distancia por ruas e a tarifa por quilometro.")
    try:
        distance = Decimal(str(distance_km))
        rate = Decimal(str(rate_cents_per_km))
        minimum = Decimal(str(minimum_cents))
    except InvalidOperation as exc:
        raise ValueError("Valores de entrega invalidos.") from exc
    if (not all(v.is_finite() for v in (distance, rate, minimum))
            or distance <= 0 or rate <= 0 or minimum < 0
            or rate != rate.to_integral_value() or minimum != minimum.to_integral_value()):
        raise ValueError("Valores de entrega invalidos.")
    return int(max(minimum, distance * rate).to_integral_value(rounding=ROUND_CEILING))
