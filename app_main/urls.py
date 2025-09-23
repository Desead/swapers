from django.urls import path
from .views import home, monitoring_go, document_view
from .views_2fa import twofa_setup

urlpatterns = [
    path("docs/<slug:slug>/", document_view, name="document_view"),
    path("go/monitoring/<int:pk>/", monitoring_go, name="monitoring_go"),
    path("security/2fa/setup/", twofa_setup, name="twofa_setup"),
    path("", home, name="home"),
]
