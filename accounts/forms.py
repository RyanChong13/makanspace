from django import forms
from django.contrib.auth import get_user_model

from .models import Company, REGION_CHOICES

User = get_user_model()


class ProfileForm(forms.ModelForm):
    """Account settings form — name, email, phone."""

    first_name = forms.CharField(max_length=30, required=False)
    last_name = forms.CharField(max_length=30, required=False)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-input"


class CompanySignupForm(forms.ModelForm):
    """
    Company registration form — a company representative registers
    their landlord company with UEN + uploads business reg doc.
    The registering user becomes the first admin of the company.
    """

    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-input"}))
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-input"}),
        label="Confirm password",
    )
    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": "form-input"}))
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "+65 9123 4567"}),
    )

    class Meta:
        model = Company
        fields = ["name", "uen", "region", "whatsapp_number", "business_reg_doc"]
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "e.g. Kimly Group Pte Ltd",
            }),
            "uen": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "e.g. 201234567A",
            }),
            "region": forms.Select(attrs={"class": "form-select"}),
            "whatsapp_number": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "+65 9123 4567",
            }),
        }

    def clean_uen(self):
        uen = self.cleaned_data.get("uen", "").strip().upper()
        if Company.objects.filter(uen=uen).exists():
            raise forms.ValidationError("A company with this UEN is already registered.")
        return uen

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        pw = cleaned_data.get("password")
        pw_confirm = cleaned_data.get("password_confirm")
        if pw and pw_confirm and pw != pw_confirm:
            raise forms.ValidationError("Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        company = super().save(commit=False)
        company.status = Company.Status.PENDING
        if commit:
            company.save()

            # Create the registering user as a LEASING_MANAGER under this company
            user = User(
                email=self.cleaned_data["email"],
                phone=self.cleaned_data.get("phone", ""),
                username=self.cleaned_data["email"].split("@")[0],
                role=User.Role.LEASING_MANAGER,
                company=company,
                auth_provider=User.AuthProvider.EMAIL,
            )
            user.set_password(self.cleaned_data["password"])
            user.save()

        return company


class LeasingManagerInviteForm(forms.Form):
    """Invite a new Leasing Manager to an existing verified company."""

    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": "form-input",
            "placeholder": "colleague@company.com",
        }),
    )
    first_name = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "First name"}),
    )
    last_name = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "Last name (optional)"}),
    )

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email
