"""
Migration 0009: Add per-user data isolation

Changes:
  - Pond.owner (ForeignKey → AUTH_USER_MODEL) — nullable for backward compat
  - Remove global unique_together on name; add unique_together (owner, name)
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("farm", "0008_weatherrecord_source_alter_farmprofile_district_and_more"),
    ]

    operations = [
        # Step 1: Drop old unique constraint on name
        migrations.AlterField(
            model_name="pond",
            name="name",
            field=models.CharField(max_length=100),
        ),
        # Step 2: Add owner column (nullable)
        migrations.AddField(
            model_name="pond",
            name="owner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="ponds",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # Step 3: Add unique_together (owner, name)
        migrations.AlterUniqueTogether(
            name="pond",
            unique_together={("owner", "name")},
        ),
    ]
