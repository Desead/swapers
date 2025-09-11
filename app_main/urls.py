from django.urls import path
from . import views
from .views_2fa import twofa_setup

urlpatterns = [
    path("security/2fa/setup/", twofa_setup, name="twofa_setup"),
    path("", views.home, name="home"),
]
