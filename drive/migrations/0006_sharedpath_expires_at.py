from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drive', '0005_userreadonlyshare'),
    ]

    operations = [
        migrations.AddField(
            model_name='sharedpath',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
