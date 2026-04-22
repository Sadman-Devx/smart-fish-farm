from django.db import migrations

def seed_feeding_profiles(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0005_new_features'),  
    ]

    operations = [
        migrations.RunPython(seed_feeding_profiles, migrations.RunPython.noop),
    ]