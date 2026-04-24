from base64 import b64encode
import logging
from io import BytesIO

from core.services.currency import get_currency_code, get_currency_label

logger = logging.getLogger(__name__)
MAX_LOGO_DIMENSION = 240
MAX_LOGO_BYTES = 2 * 1024 * 1024


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
        raw_content = file_obj.read()
        if not raw_content:
            logger.warning("Logo entreprise ignore: fichier vide.", extra={"entreprise_id": getattr(entreprise, "id", None)})
            return ""
        if len(raw_content) > MAX_LOGO_BYTES:
            logger.warning(
                "Logo entreprise ignore: fichier trop lourd pour le PDF.",
                extra={"entreprise_id": getattr(entreprise, "id", None), "logo_bytes": len(raw_content)},
            )
            return ""

        from PIL import Image, UnidentifiedImageError

        source_buffer = BytesIO(raw_content)
        with Image.open(source_buffer) as image:
            image.load()
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")

            image.thumbnail((MAX_LOGO_DIMENSION, MAX_LOGO_DIMENSION))
            output_buffer = BytesIO()
            image.save(output_buffer, format="PNG", optimize=True)
            encoded = b64encode(output_buffer.getvalue()).decode("ascii")
    except (FileNotFoundError, OSError, ValueError, UnidentifiedImageError):
        logger.warning(
            "Logo entreprise ignore: fichier introuvable ou invalide pour le PDF.",
            extra={"entreprise_id": getattr(entreprise, "id", None), "logo_name": getattr(logo, "name", "")},
        )
        return ""
    except Exception:
        logger.warning(
            "Logo entreprise ignore: erreur inattendue lors de la preparation du logo PDF.",
            exc_info=True,
            extra={"entreprise_id": getattr(entreprise, "id", None), "logo_name": getattr(logo, "name", "")},
        )
        return ""
    return f"data:image/png;base64,{encoded}"
