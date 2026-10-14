from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views import View

from .forms import CompanySignupForm, LeasingManagerInviteForm, ProfileForm
from .models import LANG_CHOICES, Company
from .services import apply_acra_lookup

User = get_user_model()


# ─── Company Signup (spec 2 / 5.1) ──────────────────────────────────────────

class CompanySignupView(View):
    """
    Company representative registers their landlord company with UEN +
    business reg doc. The registering user becomes the first Leasing Manager.
    Company enters pending_verification until admin approves.
    """

    template_name = "accounts/company_signup.html"

    def get(self, request):
        form = CompanySignupForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = CompanySignupForm(request.POST, request.FILES)
        if form.is_valid():
            company = form.save()
            # Automated ACRA UEN check (advisory; never blocks signup).
            apply_acra_lookup(company)
            # Auto-login the user who registered the company
            user = User.objects.get(email=form.cleaned_data["email"])
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            from django.contrib import messages
            messages.success(
                request,
                # One-line literal: the extraction checker only sees the first fragment
                # of an implicitly concatenated gettext string.
                _("Company '%(name)s' registered. Your account is pending business verification by our admin team.")
                % {"name": company.name},
            )
            return redirect("listings:listing_list")
        return render(request, self.template_name, {"form": form})


# ─── Leasing Manager Invite (spec 2) ────────────────────────────────────────

class CompanyRequiredMixin(UserPassesTestMixin):
    """Restricts to leasing managers/admins of a verified company."""

    def test_func(self):
        user = self.request.user
        return (
            user.is_authenticated
            and user.role == User.Role.LEASING_MANAGER
            and user.company is not None
            and user.company.is_verified
        )


class LeasingManagerInviteView(LoginRequiredMixin, CompanyRequiredMixin, View):
    """
    A verified company's leasing manager can invite colleagues.
    Creates a new User with role=LEASING_MANAGER under the same company.
    The invited user sets their password on first login.
    """

    template_name = "accounts/invite_leasing_manager.html"

    def get(self, request):
        form = LeasingManagerInviteForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = LeasingManagerInviteForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            first_name = form.cleaned_data["first_name"]
            last_name = form.cleaned_data.get("last_name", "")

            # Create user with unusable password (they'll set it via invite link)
            user = User.objects.create_user(
                username=email.split("@")[0],
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=User.Role.LEASING_MANAGER,
                company=request.user.company,
                auth_provider=User.AuthProvider.EMAIL,
            )
            user.set_unusable_password()
            user.save()

            from django.contrib import messages
            messages.success(
                request,
                # One-line literal, as above.
                _("Invitation created for %(email)s. They can sign up using the standard signup with this email.")
                % {"email": email},
            )
            return redirect("accounts:profile")

        return render(request, self.template_name, {"form": form})


# ─── Language Selection (spec 3.1) ──────────────────────────────────────────

class LanguageSelectView(View):
    """Stores language preference in session (guest) or user profile (logged in)."""

    def post(self, request, lang_code):
        from django.utils import translation

        valid_codes = [code for code, _ in LANG_CHOICES]
        # Normalise: zh → zh-hans for Django locale
        django_lang = "zh-hans" if lang_code == "zh" else lang_code
        if lang_code not in valid_codes and django_lang not in [c for c, _ in settings.LANGUAGES]:
            return JsonResponse({"error": "Invalid language code."}, status=400)

        # Store in session (both our key and Django's built-in key)
        request.session["preferred_language"] = lang_code
        request.session["django_language"] = django_lang

        if request.user.is_authenticated:
            request.user.preferred_language = lang_code
            request.user.save(update_fields=["preferred_language"])

        # Activate translation immediately
        translation.activate(django_lang)

        # HTMX: trigger a page reload to apply new language
        if request.htmx:
            from django_htmx.http import HttpResponseClientRefresh
            return HttpResponseClientRefresh()

        return redirect(request.META.get("HTTP_REFERER", "/"))


def get_user_language(request):
    """Helper to get current language for a request."""
    if request.user.is_authenticated:
        return request.user.preferred_language
    return request.session.get("preferred_language", "en")


# ─── Profile (spec 1a) ─────────────────────────────────────────────────────

class ProfileView(LoginRequiredMixin, View):
    """Account settings page — view/edit profile details."""

    template_name = "accounts/profile.html"

    def get(self, request):
        form = ProfileForm(instance=request.user)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            from django.contrib import messages
            messages.success(request, _("Profile updated successfully."))
            return redirect("accounts:profile")
        return render(request, self.template_name, {"form": form})
