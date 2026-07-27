"""
Management command: seed_property_reference

Reads hawker_centre_reference_seed.csv (74 rows) and creates/updates
PropertyReference records.  Safe to run multiple times (upsert by name).
"""

import csv
import os

from django.conf import settings
from django.core.management.base import BaseCommand

from listings.models import PropertyReference


# Map CSV display labels → model choice values
CATEGORY_MAP = {
    "Government (NEA Direct)": PropertyReference.Category.NEA_DIRECT,
    "Government (SEHC)": PropertyReference.Category.SEHC,
    "Private (Food Court)": PropertyReference.Category.PRIVATE_FOOD_COURT,
    "Private (Coffeeshop)": PropertyReference.Category.PRIVATE_COFFEESHOP,
    "Private (Thematic)": PropertyReference.Category.PRIVATE_THEMATIC,
}


class Command(BaseCommand):
    help = "Seed the PropertyReference table from hawker_centre_reference_seed.csv"

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default="",
            help="Path to CSV file (defaults to project root hawker_centre_reference_seed.csv)",
        )

    def handle(self, *args, **options):
        csv_path = options["csv"]
        if not csv_path:
            csv_path = os.path.join(settings.BASE_DIR, "hawker_centre_reference_seed.csv")

        if not os.path.exists(csv_path):
            self.stderr.write(self.style.ERROR(f"CSV file not found: {csv_path}"))
            return

        created = 0
        updated = 0
        skipped = 0

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                category_label = row.get("category", "").strip()
                category = CATEGORY_MAP.get(category_label)
                if not category:
                    self.stderr.write(self.style.WARNING(
                        f"Skipping row — unknown category: '{category_label}'"
                    ))
                    skipped += 1
                    continue

                name = row.get("establishment_name", "").strip()
                if not name:
                    skipped += 1
                    continue

                in_scope_raw = row.get("in_scope", "").strip().upper()
                in_scope = in_scope_raw not in ("FALSE", "0", "NO", "N")

                defaults = {
                    "category": category,
                    "operator": row.get("operator", "").strip(),
                    "region": row.get("region", "").strip(),
                    "in_scope": in_scope,
                    "scope_reason": row.get("scope_reason", "").strip(),
                }

                obj, was_created = PropertyReference.objects.update_or_create(
                    establishment_name=name,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done: {created} created, {updated} updated, {skipped} skipped."
        ))
