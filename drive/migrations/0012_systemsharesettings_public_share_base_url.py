from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drive', '0011_publicsharelink'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsharesettings',
            name='public_share_base_url',
            field=models.URLField(blank=True, max_length=500),
        ),
    ]
