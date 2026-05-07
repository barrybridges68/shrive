from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drive', '0002_systemsharesettings'),
    ]

    operations = [
        migrations.AlterField(
            model_name='systemsharesettings',
            name='readonly_storage_root',
            field=models.TextField(blank=True),
        ),
    ]
