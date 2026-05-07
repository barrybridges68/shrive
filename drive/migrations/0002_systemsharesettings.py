from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drive', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SystemShareSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_storage_root', models.CharField(blank=True, max_length=1024)),
                ('readonly_storage_root', models.CharField(blank=True, max_length=1024)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'System share settings',
                'verbose_name_plural': 'System share settings',
            },
        ),
    ]
