"""Order request and response schemas."""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.domain.entities.order import Dimensions, Order, OrderLine, Package, Party


class PartyDetails(BaseModel):
    """Pickup or delivery contact from the orders API."""

    contact_name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    email: str = Field(min_length=3, max_length=254)
    address_line1: str = Field(min_length=1, max_length=300)
    address_line2: str = ""
    city: str = Field(min_length=1, max_length=80)
    state: str = Field(min_length=1, max_length=80)
    pincode: str = Field(pattern=r"^\d{6}$")
    country: str = Field(min_length=1, max_length=80)

    @field_validator("email")
    @classmethod
    def email_has_at(cls, value: str) -> str:
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("must be an email address")
        return value.strip()


class PackageDimensions(BaseModel):
    """Package size in centimetres."""

    length_cm: float = Field(gt=0)
    width_cm: float = Field(gt=0)
    height_cm: float = Field(gt=0)


class PackageDetails(BaseModel):
    """Package weight, size, and payment."""

    weight_kg: float = Field(gt=0)
    dimensions: PackageDimensions
    payment_mode: Literal["PREPAID", "COD"]
    declared_value: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("payment_mode", mode="before")
    @classmethod
    def uppercase_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.strip().upper()


class OrderItem(BaseModel):
    """One product line."""

    sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=1)
    price: Decimal = Field(ge=0)


class OrderCreate(BaseModel):
    """Body for POST /api/v1/orders."""

    order_id: str = Field(min_length=1, max_length=64)
    courier_partner: str = Field(min_length=1, max_length=40)
    pickup_details: PartyDetails
    delivery_details: PartyDetails
    package_details: PackageDetails
    items: list[OrderItem] = Field(min_length=1)

    def to_order(self) -> Order:
        return Order(
            order_id=self.order_id.strip(),
            courier_partner=self.courier_partner.strip(),
            pickup=_party(self.pickup_details),
            delivery=_party(self.delivery_details),
            package=Package(
                weight_kg=self.package_details.weight_kg,
                dimensions=Dimensions(
                    length_cm=self.package_details.dimensions.length_cm,
                    width_cm=self.package_details.dimensions.width_cm,
                    height_cm=self.package_details.dimensions.height_cm,
                ),
                payment_mode=self.package_details.payment_mode,
                declared_value=self.package_details.declared_value,
                currency=self.package_details.currency,
            ),
            items=tuple(
                OrderLine(sku=item.sku.strip(), name=item.name.strip(), quantity=item.quantity, price=item.price)
                for item in self.items
            ),
        )


class OrderAccepted(BaseModel):
    """Order booked with the courier."""

    order_id: str
    courier_partner: str
    manifest: Any


class OrderTracking(BaseModel):
    """Tracking returned for a stored order."""

    order_id: str
    awb_number: str
    courier_partner: str
    tracking: Any


class CancelOrderRequest(BaseModel):
    """Body for cancelling an order."""

    courier_partner: str = Field(min_length=1, max_length=50)


class OrderCancelled(BaseModel):
    """Cancellation accepted by the courier."""

    order_id: str
    awb_number: str
    courier_partner: str
    cancellation: Any


def _party(details: PartyDetails) -> Party:
    return Party(
        contact_name=details.contact_name.strip(),
        phone=details.phone.strip(),
        email=details.email.strip(),
        address_line1=details.address_line1.strip(),
        address_line2=details.address_line2.strip(),
        city=details.city.strip(),
        state=details.state.strip(),
        pincode=details.pincode.strip(),
        country=details.country.strip(),
    )
