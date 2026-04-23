from django.conf import settings
from django.http import HttpResponse
from django.template.loader import get_template


class PdfRenderError(Exception):
    pass


def render_pdf_response(request, template_name, context, filename, disposition="inline"):
    engine = getattr(settings, "JOATHAM_PDF_ENGINE", "xhtml2pdf")
    template = get_template(template_name)
    html = template.render(context, request)
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'

    if engine == "weasyprint":
        try:
            from weasyprint import HTML
        except ImportError as exc:
            raise PdfRenderError("WeasyPrint n'est pas installe.") from exc

        HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf(response)
        return response

    try:
        from xhtml2pdf import pisa
    except ImportError as exc:
        raise PdfRenderError("xhtml2pdf n'est pas installe.") from exc

    pdf_status = pisa.CreatePDF(src=html, dest=response, encoding="UTF-8")
    if pdf_status.err:
        raise PdfRenderError("Erreur lors de la generation du PDF.")

    return response
