#!/usr/bin/env bash
# Curl examples for every endpoint.
#
#   ./examples/curl.sh health
#   ./examples/curl.sh create-order
#   ./examples/curl.sh bulk
#   ./examples/curl.sh bulk-status
#   ./examples/curl.sh track
#   ./examples/curl.sh cancel
#
# create-order, bulk, and cancel call the courier through the local API.
# Set BATCH_ID from the bulk response before bulk-status.

BASE="${BASE:-http://127.0.0.1:8000}"
KEY="${KEY:-demo}"
ORDER_ID="${ORDER_ID:-ORD-2026-1026A}"
BATCH_ID="${BATCH_ID:-replace-with-batch-id}"

health() {
  curl -sS "${BASE}/health"
  echo
}

create_order() {
  curl -sS -X POST "${BASE}/api/v1/orders" \
    -H 'content-type: application/json' \
    -H "x-api-key: ${KEY}" \
    -d @- <<EOF
{
  "order_id": "${ORDER_ID}",
  "courier_partner": "urbanebolt",
  "pickup_details": {
    "contact_name": "Warehouse Alpha",
    "phone": "+919876543210",
    "email": "warehouse@ecommerce.com",
    "address_line1": "Plot No. 42, Phase 3, Industrial Area",
    "address_line2": "Near Main Highway",
    "city": "Indore",
    "state": "Madhya Pradesh",
    "pincode": "452001",
    "country": "India"
  },
  "delivery_details": {
    "contact_name": "Rahul Sharma",
    "phone": "+919123456789",
    "email": "rahul.sharma@email.com",
    "address_line1": "Flat 304, Royal Apartments",
    "address_line2": "Vijay Nagar",
    "city": "Indore",
    "state": "Madhya Pradesh",
    "pincode": "452010",
    "country": "India"
  },
  "package_details": {
    "weight_kg": 1.25,
    "dimensions": {
      "length_cm": 20.0,
      "width_cm": 15.0,
      "height_cm": 10.0
    },
    "payment_mode": "PREPAID",
    "declared_value": 2499.00,
    "currency": "INR"
  },
  "items": [
    {
      "sku": "SKU-PROD-XYZ123",
      "name": "Wireless Ergonomic Mouse",
      "quantity": 1,
      "price": 2499.00
    }
  ]
}
EOF
  echo
}

bulk() {
  curl -sS -X POST "${BASE}/api/v1/orders/bulk" \
    -H 'content-type: application/json' \
    -H "x-api-key: ${KEY}" \
    -d @- <<EOF
[
  {
    "order_id": "${ORDER_ID}-1",
    "courier_partner": "urbanebolt",
    "pickup_details": {
      "contact_name": "Warehouse Alpha",
      "phone": "+919876543210",
      "email": "warehouse@ecommerce.com",
      "address_line1": "Plot No. 42, Phase 3, Industrial Area",
      "address_line2": "Near Main Highway",
      "city": "Indore",
      "state": "Madhya Pradesh",
      "pincode": "452001",
      "country": "India"
    },
    "delivery_details": {
      "contact_name": "Rahul Sharma",
      "phone": "+919123456789",
      "email": "rahul.sharma@email.com",
      "address_line1": "Flat 304, Royal Apartments",
      "address_line2": "Vijay Nagar",
      "city": "Indore",
      "state": "Madhya Pradesh",
      "pincode": "452010",
      "country": "India"
    },
    "package_details": {
      "weight_kg": 1.25,
      "dimensions": {"length_cm": 20.0, "width_cm": 15.0, "height_cm": 10.0},
      "payment_mode": "PREPAID",
      "declared_value": 2499.00,
      "currency": "INR"
    },
    "items": [
      {"sku": "SKU-PROD-XYZ123", "name": "Wireless Ergonomic Mouse", "quantity": 1, "price": 2499.00}
    ]
  },
  {
    "order_id": "${ORDER_ID}-2",
    "courier_partner": "urbanebolt",
    "pickup_details": {
      "contact_name": "Warehouse Alpha",
      "phone": "+919876543210",
      "email": "warehouse@ecommerce.com",
      "address_line1": "Plot No. 42, Phase 3, Industrial Area",
      "address_line2": "Near Main Highway",
      "city": "Indore",
      "state": "Madhya Pradesh",
      "pincode": "452001",
      "country": "India"
    },
    "delivery_details": {
      "contact_name": "Satyam Convent School",
      "phone": "+918320226438",
      "email": "test2@ail.com",
      "address_line1": "Plot No. 26-27, Om Nagar Society",
      "address_line2": "Sumbhal",
      "city": "Surat",
      "state": "Gujarat",
      "pincode": "122001",
      "country": "India"
    },
    "package_details": {
      "weight_kg": 1.1,
      "dimensions": {"length_cm": 12.0, "width_cm": 10.0, "height_cm": 10.0},
      "payment_mode": "COD",
      "declared_value": 100.00,
      "currency": "INR"
    },
    "items": [
      {"sku": "SKU-BOOK-001", "name": "BOOKS", "quantity": 1, "price": 100.00}
    ]
  }
]
EOF
  echo
}

bulk_status() {
  curl -sS "${BASE}/api/v1/orders/bulk/${BATCH_ID}" \
    -H "x-api-key: ${KEY}"
  echo
}

track() {
  curl -sS -G "${BASE}/api/v1/orders/${ORDER_ID}/track" \
    -H "x-api-key: ${KEY}" \
    --data-urlencode "courier_partner=urbanebolt"
  echo
}

cancel() {
  curl -sS -X POST "${BASE}/api/v1/orders/${ORDER_ID}/cancel" \
    -H 'content-type: application/json' \
    -H "x-api-key: ${KEY}" \
    -d '{"courier_partner": "urbanebolt"}'
  echo
}

case "${1:-}" in
  health) health ;;
  create-order) create_order ;;
  bulk) bulk ;;
  bulk-status) bulk_status ;;
  track) track ;;
  cancel) cancel ;;
  *)
    echo "Usage: $0 health|create-order|bulk|bulk-status|track|cancel"
    echo "Optional env: BASE KEY ORDER_ID BATCH_ID"
    exit 1
    ;;
esac
