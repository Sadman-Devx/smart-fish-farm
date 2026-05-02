"""
farm/management/commands/check_pwa.py
─────────────────────────────────────
Run: python manage.py check_pwa

Checks that all required PWA files are in place and reports status.
"""
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Check PWA setup — verifies all required files exist"

    REQUIRED_FILES = [
        "static/pwa/manifest.json",
        "static/pwa/sw.js",
        "static/pwa/pwa.js",
        "static/pwa/icons/icon-72x72.png",
        "static/pwa/icons/icon-96x96.png",
        "static/pwa/icons/icon-128x128.png",
        "static/pwa/icons/icon-144x144.png",
        "static/pwa/icons/icon-152x152.png",
        "static/pwa/icons/icon-192x192.png",
        "static/pwa/icons/icon-384x384.png",
        "static/pwa/icons/icon-512x512.png",
        "templates/pwa/offline.html",
    ]

    def handle(self, *args, **options):
        base = settings.BASE_DIR
        self.stdout.write("\n🔍 Checking PWA setup...\n")

        all_ok = True
        for rel_path in self.REQUIRED_FILES:
            full_path = base / rel_path
            if full_path.exists():
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ {rel_path}")
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"  ✕ MISSING: {rel_path}")
                )
                all_ok = False

        self.stdout.write("")

        if all_ok:
            self.stdout.write(self.style.SUCCESS(
                "✅ All PWA files present!\n\n"
                "Next steps:\n"
                "  1. python manage.py collectstatic\n"
                "  2. Open Chrome → DevTools → Application → Manifest\n"
                "  3. Check 'Service Workers' tab\n"
                "  4. Run Lighthouse audit for PWA score\n"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "⚠ Some files are missing. Check the paths above."
            ))