from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drive', '0012_systemsharesettings_public_share_base_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsharesettings',
            name='public_share_link_lifetime',
            field=models.CharField(default='never', max_length=16),
        ),
    ]
