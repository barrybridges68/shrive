from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drive', '0019_uploadsharelink'),
    ]

    operations = [
        migrations.AddField(
            model_name='userstorageprofile',
            name='webdav_api_key_created_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='userstorageprofile',
            name='webdav_api_key_hash',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
