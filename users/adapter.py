from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


class MyAccountAdapter(DefaultAccountAdapter):
    def get_email_confirmation_url_stub(self, request, emailconfirmation):
        url = reverse("account_confirm_email", args=[emailconfirmation.key])
        return settings.SSL_FRONTEND_HOST + url

    def get_login_redirect_url(self, request):
        next_url = request.POST.get("next") or request.GET.get("next")
        allowed_hosts = {request.get_host(), *getattr(settings, "ALLOWED_HOSTS", [])}
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts=allowed_hosts,
            require_https=request.is_secure(),
        ):
            return next_url
        if getattr(request.user, "is_superuser", False):
            return reverse("manage_statistics")
        return super().get_login_redirect_url(request)

    def clean_email(self, email):
        if hasattr(settings, "ALLOWED_DOMAINS_FOR_USER_REGISTRATION") and settings.ALLOWED_DOMAINS_FOR_USER_REGISTRATION:
            if email.split("@")[1] not in settings.ALLOWED_DOMAINS_FOR_USER_REGISTRATION:
                raise ValidationError("El dominio no está en la lista permitida")

        if email.split("@")[1] in settings.RESTRICTED_DOMAINS_FOR_USER_REGISTRATION:
            raise ValidationError("El dominio tiene restringido el registro")
        return email

    def is_open_for_signup(self, request):
        return settings.USERS_CAN_SELF_REGISTER

    def send_mail(self, template_prefix, email, context):
        msg = self.render_mail(template_prefix, email, context)
        msg.send(fail_silently=True)
