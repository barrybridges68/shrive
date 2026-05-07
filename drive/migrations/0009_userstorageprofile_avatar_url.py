from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drive', '0008_admintodoitem_description'),
    ]

    operations = [
        migrations.AddField(
            model_name='userstorageprofile',
            name='avatar_url',
            field=models.URLField(blank=True, default='', max_length=500),
        ),
    ]
