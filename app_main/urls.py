from django.urls import path
from . import views
from .views_2fa import twofa_setup

urlpatterns = [
    path("docs/", views.documents_list, name="documents_list"),
    path("docs/<int:pk>/", views.document_detail, name="document_detail"),
    path("go/monitoring/<int:pk>/", views.monitoring_go, name="monitoring_go"),
    path("security/2fa/setup/", twofa_setup, name="twofa_setup"),
    path("", views.home, name="home"),
]
