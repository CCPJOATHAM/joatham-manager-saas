from django.urls import path

from . import views


urlpatterns = [
    path("", views.conversation_list, name="message_conversation_list"),
    path("nouvelle/", views.conversation_create, name="message_conversation_create"),
    path("conversation/<int:conversation_id>/", views.conversation_detail, name="message_conversation_detail"),
    path("conversation/<int:conversation_id>/envoyer/", views.send_conversation_message, name="message_send"),
    path("piece-jointe/<int:attachment_id>/", views.download_attachment, name="message_attachment_download"),
    path("suggestions/", views.suggestion_create, name="message_suggestion_create"),
]
