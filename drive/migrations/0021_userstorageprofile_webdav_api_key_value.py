from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drive', '0020_userstorageprofile_webdav_api_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='userstorageprofile',
            name='webdav_api_key_value',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
    ]
