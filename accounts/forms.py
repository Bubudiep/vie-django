from django.contrib.auth.forms import AdminUserCreationForm

from .models import User


class CompanyUserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ('username', 'company')

    def clean_username(self):
        # UserCreationForm.clean_username rejects any globally duplicate
        # username; username is only unique per company here, so skip it and
        # let the model's UniqueConstraint (validated via validate_unique)
        # report real conflicts.
        return self.cleaned_data.get('username')
