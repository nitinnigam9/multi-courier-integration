"""Order placed with a courier partner."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Party:
    """Pickup or delivery contact."""

    contact_name: str
    phone: str
    email: str
    address_line1: str
    address_line2: str
    city: str
    state: str
    pincode: str
    country: str


@dataclass(frozen=True, slots=True)
class Dimensions:
    """Package size in centimetres."""

    length_cm: float
    width_cm: float
    height_cm: float


@dataclass(frozen=True, slots=True)
class Package:
    """Physical package and payment for one shipment."""

    weight_kg: float
    dimensions: Dimensions
    payment_mode: str
    declared_value: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class OrderLine:
    """One product line inside an order."""

    sku: str
    name: str
    quantity: int
    price: Decimal


@dataclass(frozen=True, slots=True)
class Order:
    """Shipment request accepted by the orders API."""

    order_id: str
    courier_partner: str
    pickup: Party
    delivery: Party
    package: Package
    items: tuple[OrderLine, ...]
