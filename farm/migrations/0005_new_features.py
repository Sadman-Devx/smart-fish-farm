from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('farm', '0004_dailyweather_location_query'),
    ]

    operations = [
        migrations.CreateModel(
            name='HarvestRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('harvest_date', models.DateField(default=django.utils.timezone.now)),
                ('harvested_count', models.PositiveIntegerField(help_text='Number of fish harvested')),
                ('avg_weight_g', models.DecimalField(decimal_places=2, help_text='Average weight per fish (grams)', max_digits=7)),
                ('total_weight_kg', models.DecimalField(decimal_places=2, help_text='Total harvest weight (kg)', max_digits=9)),
                ('price_per_kg', models.DecimalField(decimal_places=2, default=0, help_text='Sale price per kg (BDT)', max_digits=7)),
                ('buyer_name', models.CharField(blank=True, max_length=150)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='harvests', to='farm.fishbatch')),
            ],
            options={'ordering': ['-harvest_date']},
        ),
        migrations.CreateModel(
            name='Expense',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(default=django.utils.timezone.now)),
                ('category', models.CharField(choices=[('feed','Feed'),('medicine','Medicine / Treatment'),('labour','Labour'),('equipment','Equipment'),('electricity','Electricity'),('fingerlings','Fingerlings / Stocking'),('other','Other')], max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, help_text='Amount (BDT)', max_digits=10)),
                ('description', models.CharField(max_length=255)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('pond', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='expenses', to='farm.pond', help_text='Leave blank for farm-wide expense')),
            ],
            options={'ordering': ['-date']},
        ),
        migrations.CreateModel(
            name='MortalityLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(default=django.utils.timezone.now)),
                ('count', models.PositiveIntegerField(help_text='Number of dead fish')),
                ('cause', models.CharField(choices=[('disease','Disease'),('oxygen','Low Oxygen'),('temperature','Temperature Stress'),('predator','Predator'),('unknown','Unknown'),('other','Other')], default='unknown', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mortality_logs', to='farm.fishbatch')),
            ],
            options={'ordering': ['-date']},
        ),
        migrations.CreateModel(
            name='FarmAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('alert_type', models.CharField(choices=[('low_oxygen','Low Dissolved Oxygen'),('high_temp','High Temperature'),('low_temp','Low Temperature'),('ph_out','pH Out of Range'),('high_mortality','High Mortality'),('harvest_due','Harvest Due'),('feed_overdue','Feed Overdue'),('custom','Custom')], max_length=20)),
                ('level', models.CharField(choices=[('info','Info'),('warning','Warning'),('critical','Critical')], default='warning', max_length=10)),
                ('message', models.TextField()),
                ('resolved', models.BooleanField(default=False)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('pond', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='alerts', to='farm.pond')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='PondNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('author', models.CharField(default='Farm Manager', max_length=100)),
                ('body', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('pond', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notes', to='farm.pond')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
