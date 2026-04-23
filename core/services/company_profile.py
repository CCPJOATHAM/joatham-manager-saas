from base64 import b64encode

from core.services.currency import get_currency_code, get_currency_label


def build_entreprise_identity(entreprise):
    if entreprise is None:
        return {}

    logo = getattr(entreprise, "logo", None)
    logo_url = ""
    if logo and getattr(logo, "name", ""):
        try:
            logo_url = logo.url
        except Exception:
            logo_url = ""

    primary_name = (getattr(entreprise, "nom", "") or "").strip() or "Entreprise"
    secondary_name = (getattr(entreprise, "raison_sociale", "") or "").strip()
    if secondary_name == primary_name:
        secondary_name = ""

    return {
        "primary_name": primary_name,
        "secondary_name": secondary_name,
        "address": (getattr(entreprise, "adresse", "") or "").strip(),
        "city": (getattr(entreprise, "ville", "") or "").strip(),
        "country": (getattr(entreprise, "pays", "") or "").strip(),
        "phone": (getattr(entreprise, "telephone", "") or "").strip(),
        "email": (getattr(entreprise, "email", "") or "").strip(),
        "bank_name": (getattr(entreprise, "banque", "") or "").strip(),
        "bank_account": (getattr(entreprise, "compte_bancaire", "") or "").strip(),
        "rccm": (getattr(entreprise, "rccm", "") or "").strip(),
        "id_nat": (getattr(entreprise, "id_nat", "") or "").strip(),
        "impot": (getattr(entreprise, "numero_impot", "") or "").strip(),
        "currency_code": get_currency_code(entreprise),
        "currency_label": get_currency_label(get_currency_code(entreprise)),
        "logo_url": logo_url,
    }


def build_logo_data_uri(entreprise):
    logo = getattr(entreprise, "logo", None)
    if not logo:
        return ""

    file_obj = getattr(logo, "file", None)
    if file_obj is None:
        return ""

    try:
        file_obj.seek(0)
        encoded = b64encode(file_obj.read()).decode("ascii")
    except Exception:
        return ""

    content_type = "image/png"
    if getattr(logo, "name", "").lower().endswith((".jpg", ".jpeg")):
        content_type = "image/jpeg"
    return f"data:{content_type};base64,{encoded}"
