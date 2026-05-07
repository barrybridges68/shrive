from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('drive', '0007_admintodoitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='admintodoitem',
            name='description',
            field=models.TextField(blank=True),
        ),
    ]