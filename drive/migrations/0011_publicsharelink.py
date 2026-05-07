from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('drive', '0010_groupsharedpath'),
    ]

    operations = [
        migrations.CreateModel(
            name='PublicShareLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('relative_path', models.CharField(max_length=500)),
                ('token', models.CharField(max_length=64, unique=True)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='public_shares_created', to='auth.user')),
            ],
            options={
                'ordering': ['owner__username', 'relative_path'],
                'constraints': [models.UniqueConstraint(fields=('owner', 'relative_path'), name='drive_unique_public_share_path')],
            },
        ),
    ]
