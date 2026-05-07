from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('drive', '0009_userstorageprofile_avatar_url'),
    ]

    operations = [
        migrations.CreateModel(
            name='GroupSharedPath',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('relative_path', models.CharField(max_length=500)),
                ('permission', models.CharField(choices=[('view', 'View only'), ('edit', 'Edit')], default='view', max_length=12)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='group_shares_created', to='auth.user')),
                ('target_group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='group_shares_received', to='auth.group')),
            ],
            options={
                'ordering': ['owner__username', 'target_group__name', 'relative_path'],
                'constraints': [models.UniqueConstraint(fields=('owner', 'target_group', 'relative_path'), name='drive_unique_group_shared_path')],
            },
        ),
    ]
