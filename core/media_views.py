from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.views.static import serve

from core.private_files import private_file_response
from core.services.tenancy import get_user_entreprise_or_raise


def serve_public_logo(request, path, document_root):
    """Development-only allowlist, including traversal/symlink boundaries."""
    if path.startswith(("/", "\\")) or any(
        part in (".", "..") for part in path.replace("\\", "/").split("/")
    ):
        raise Http404
    base = Path(document_root).resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base):
        raise Http404
    return serve(request, path, document_root=document_root)


@login_required
def own_profile_photo(request):
    # Platform accounts have no tenant; tenant accounts must still be active.
    if request.user.entreprise_id:
        get_user_entreprise_or_raise(request.user)
    return private_file_response(request.user.profile_photo, as_attachment=False)
