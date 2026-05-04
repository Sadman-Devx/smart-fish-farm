"""
farm/signals.py
───────────────
প্রথম Pond বা Batch তৈরির সময় সিস্টেম automatically 
FeedingProfiles সেটআপ করে নেয়।
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import FishBatch, Pond


@receiver(post_save, sender=Pond)
def auto_setup_profiles_on_first_pond(sender, instance, created, **kwargs):
    """প্রথম পুকুর তৈরির সাথে সাথে feeding profiles সেটআপ"""
    if created and Pond.objects.count() == 1:
        from .services.feed_calculator import ensure_default_feeding_profiles
        ensure_default_feeding_profiles()


@receiver(post_save, sender=FishBatch)
def auto_setup_profiles_on_first_batch(sender, instance, created, **kwargs):
    """প্রথম ব্যাচ তৈরির সাথে সাথে feeding profiles সেটআপ"""
    if created and FishBatch.objects.count() == 1:
        from .services.feed_calculator import ensure_default_feeding_profiles
        ensure_default_feeding_profiles()