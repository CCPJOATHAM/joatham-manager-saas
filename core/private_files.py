"""Stream private uploads only after the calling view has authorized the object.

Never redirect to FieldFile.url: MEDIA_ROOT may also contain public logos.
No storage path or client-supplied filename is accepted by this helper.
"""
from django.http import FileResponse, Http404


def private_file_response(field_file, *, filename=None, as_attachment=True, not_found_message=""):
    if not field_file:
        raise Http404(not_found_message)
    try:
        opened = field_file.open("rb")
    except FileNotFoundError as exc:
        raise Http404(not_found_message) from exc
    response = FileResponse(opened, as_attachment=as_attachment, filename=filename)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
