from django.urls import path

from . import views


urlpatterns = [
    path(
        "api/v1/media/<str:friendly_token>/download/checkout/",
        views.VideoDownloadCheckoutView.as_view(),
        name="video_download_checkout",
    ),
    path(
        "api/v1/media/<str:friendly_token>/download/file/",
        views.VideoDownloadFileView.as_view(),
        name="video_download_file",
    ),
    path(
        "payments/flow/confirm/",
        views.FlowConfirmView.as_view(),
        name="flow_confirm",
    ),
    path(
        "payments/flow/return/",
        views.FlowReturnView.as_view(),
        name="flow_return",
    ),
]
