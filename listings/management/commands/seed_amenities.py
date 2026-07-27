"""
Seed the Amenity table with standard hawker-stall amenities.

Usage:  python manage.py seed_amenities
Safe to run multiple times (uses update_or_create).
"""

from django.core.management.base import BaseCommand

from listings.models import Amenity

AMENITIES = [
    # slug, name_en, lucide icon name
    ("fridge", "Fridge included", "refrigerator"),
    ("exhaust-hood", "Exhaust hood", "wind"),
    ("sink", "Sink with running water", "droplets"),
    ("water-supply", "Water supply point", "droplet"),
    ("gas-supply", "Gas supply available", "flame"),
    ("electrical-points", "Electrical points (13A+)", "plug"),
    ("storage-space", "Storage space / dry store", "package"),
    ("air-conditioning", "Air-conditioned area", "snowflake"),
    ("ceiling-fan", "Ceiling fan", "fan"),
    ("roller-shutter", "Roller shutter / security grille", "lock"),
    ("loading-bay", "Loading bay access", "truck"),
    ("trolley-access", "Trolley / ramp access", "shopping-cart"),
    ("wifi", "Wi-Fi available", "wifi"),
    ("cctv", "CCTV surveillance", "video"),
    ("waste-disposal", "Centralised waste disposal", "trash-2"),
    ("table-seating", "Communal table seating", "armchair"),
    ("tray-return", "Tray return station nearby", "utensils"),
    ("handicap-access", "Handicap-accessible", "accessibility"),
    ("car-park", "Adjacent car park", "car"),
]


class Command(BaseCommand):
    help = "Seed the Amenity table with standard hawker-stall amenities."

    def handle(self, *args, **options):
        created = updated = 0
        for slug, name_en, icon in AMENITIES:
            _, is_new = Amenity.objects.update_or_create(
                slug=slug,
                defaults={"name_en": name_en, "icon": icon},
            )
            if is_new:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"Done: {created} created, {updated} updated.")
        )
