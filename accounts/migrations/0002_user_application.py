import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        migrations.swappable_dependency(settings.OAUTH2_PROVIDER_APPLICATION_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='application',
            field=models.ForeignKey(
                blank=True,
                help_text='OAuth2 client application this user registered through.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='users',
                to=settings.OAUTH2_PROVIDER_APPLICATION_MODEL,
            ),
        ),
    ]
