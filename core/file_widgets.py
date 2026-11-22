"""Keep clear/change controls without emitting public storage URLs."""
from pathlib import PurePosixPath

from django.forms import ClearableFileInput
from django.urls import reverse


class AuthorizedFileInput(ClearableFileInput):
    template_name = "core/widgets/authorized_file_input.html"
    download_url_name = None
    include_object_id = True

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        if context["widget"]["is_initial"]:
            context["widget"]["filename"] = PurePosixPath(value.name).name
            args = [value.instance.pk] if self.include_object_id else []
            context["widget"]["download_url"] = reverse(self.download_url_name, args=args)
        return context


class OwnProfilePhotoInput(AuthorizedFileInput):
    download_url_name = "own_profile_photo"
    include_object_id = False


class MessageAttachmentInput(AuthorizedFileInput):
    download_url_name = "message_attachment_download"
