"""
farm/management/commands/check_pwa.py
─────────────────────────────────────────────
Run: python manage.py check_pwa

Checks that all required PWA files exist, have minimum size, 
and validates manifest.json structure if applicable.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Check PWA setup — verifies files exist, size, and basic manifest rules"

    REQUIRED_FILES = [
        {"path": "static/pwa/manifest.json", "check_json": True, "min_size_kb": 0.5},
        {"path": "static/pwa/sw.js",                     "min_size_kb": 0.1},
        {"path": "static/pwa/pwa.js",                     "min_size_kb": 0.1},
        {"path": "static/pwa/icons/icon-72x72.png",           "min_size_kb": 1.0},
        {"path": "static/pwa/icons/icon-96x96.png",           "min_size_kb": 1.0},
        {"path": "static/pwa/icons/icon-128x128.png",         "min_size_kb": 1.0},
        {"path": "static/pwa/icons/icon-144x144.png",         "min_size_kb": 1.0},
        {"path": "static/pwa/icons/icon-152x152.png",         "min_size_kb": 1.0},
        {"path": "static/pwa/icons/icon-192x192.png",         "min_size_kb": 1.0},
        {"path": "static/pwa/icons/icon-384x384.png",         "min_size_kb": 2.0},
        {"path": "static/pwa/icons/icon-512x512.png",         "min_size_kb": 2.0},
        {"path": "templates/pwa/offline.html",              "min_size_kb": 0.1},
    ]

    def _check_file(self, file_info: dict) -> tuple[bool, str]:
        """Returns (is_ok, status_message)."""
        path = Path(settings.BASE_DIR) / file_info["path"]
        
        if not path.exists():
            return False, "MISSING"
        
        size_kb = path.stat().st_size / 1024
        min_size = file_info.get("min_size_kb", 0)
        
        if size_kb < min_size:
            return False, f"TOO SMALL ({size_kb:.1f} KB < {min_size} KB min)"
            
        if file_info.get("check_json"):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    return False, "INVALID JSON"
            except Exception:
                return False, "JSON PARSE ERROR"
            
        return True, "OK"

    def handle(self, *args, **options):
        self.stdout.write("\n🔍 Checking PWA setup...\n")

        all_ok = True
        for file_info in self.REQUIRED_FILES:
            is_ok, status = self._check_file(file_info)
            
            if is_ok:
                self.stdout.write(self.style.SUCCESS(f"  ✓ {file_info['path']} ({status})"))
            else:
                self.stdout.write(self.style.ERROR(f"  ✕ {file_info['path']} → {status}"))
                all_ok = False

        self.stdout.write("")

        if all_ok:
            self.stdout.write(self.style.SUCCESS(
                "✅ All PWA files valid!\n\n"
                "Next steps:\n"
                "  1. python manage.py collectstatic\n"
                "  2. Chrome DevTools → Application → Manifest\n"
                "  3. Lighthouse audit for PWA score\n"
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "⚠ Fix the errors above to make your app installable."
            ))