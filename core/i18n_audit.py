"""Checks shared by the translation command and the bilingual test suite."""
import ast
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re

from django.conf import settings
from django.template import Engine

PRESENTATION_ATTRIBUTES = {"placeholder", "title", "alt", "aria-label"}
UNCHANGED_LABELS = {
    "JOATHAM", "JOATHAM Manager", "Manager", "FR", "EN", "PDF", "CSV", "Excel",
    "USD", "CDF", "EUR", "FC", "RCCM", "NIF", "IBAN", "SWIFT", "ID", "ID NAT",
    "OHADA", "SYSCOHADA", "/ FC",
}


def catalog_entries(path):
    """Read PO fields, including wrapped strings, without an optional library."""
    for paragraph in path.read_text(encoding="utf-8").split("\n\n"):
        if not paragraph.strip() or paragraph.lstrip().startswith("#~"):
            continue
        fields = {}
        field = None
        for line in paragraph.splitlines():
            if line.startswith("#"):
                continue
            match = re.match(r"(msgid_plural|msgid|msgctxt|msgstr(?:\[\d+\])?)\s+(.*)", line)
            if match:
                field = match.group(1)
                fields[field] = ast.literal_eval(match.group(2))
            elif line.startswith('"') and field:
                fields[field] += ast.literal_eval(line)
        if fields.get("msgid"):
            yield fields, bool(re.search(r"^#,\s*.*\bfuzzy\b", paragraph, re.M))


def catalog_state(path):
    """Compare catalog content independently of filesystem traversal order."""
    return sorted(catalog_entries(path), key=lambda entry: (
        entry[0].get("msgctxt", ""), entry[0]["msgid"],
    ))


def catalog_errors():
    errors = []
    for language in ("fr", "en"):
        for domain in ("django", "djangojs"):
            path = settings.BASE_DIR / "locale" / language / "LC_MESSAGES" / (domain + ".po")
            for entry, fuzzy in catalog_entries(path):
                translations = [value for key, value in entry.items() if key.startswith("msgstr")]
                if fuzzy or not translations or any(not value.strip() for value in translations):
                    errors.append(f"{path.relative_to(settings.BASE_DIR)}: {entry['msgid']}")
                pattern = r"%(?:\([A-Za-z_][A-Za-z_0-9]*\))?[sdf]"
                expected = Counter(re.findall(pattern, entry["msgid"]))
                if any(Counter(re.findall(pattern, value)) != expected for value in translations):
                    errors.append(f"{path.relative_to(settings.BASE_DIR)}: changed format parameters: {entry['msgid']}")
    return errors


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.untranslated = []

    def check(self, value):
        value = " ".join(value.split()).strip(" |:-")
        if value and re.search(r"[A-Za-zÀ-ÿ]{2}", value) and value not in UNCHANGED_LABELS:
            if not value.startswith(("https://", "http://", "www.")):
                self.untranslated.append((self.getpos()[0], value))

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden.append(tag)
        if self.hidden:
            return
        for key, value in attrs:
            if value and key in PRESENTATION_ATTRIBUTES:
                self.check(value)
        if tag == "input" and dict(attrs).get("type") in ("submit", "button"):
            self.check(dict(attrs).get("value", ""))

    def handle_endtag(self, tag):
        if self.hidden and self.hidden[-1] == tag:
            self.hidden.pop()

    def handle_data(self, data):
        if not self.hidden:
            self.check(data)


def template_errors():
    errors = []
    for app in settings.BASE_DIR.iterdir():
        template_root = app / "templates" if app.is_dir() else None
        if app.name == "templates":
            template_root = app
        if not template_root or not template_root.is_dir():
            continue
        for path in template_root.rglob("*"):
            if path.suffix not in (".html", ".txt"):
                continue
            source = path.read_text(encoding="utf-8")
            try:
                Engine.get_default().from_string(source)
            except Exception as error:
                errors.append(f"{path.relative_to(settings.BASE_DIR)}: {error}")
                continue
            if path.suffix == ".txt":
                continue
            source = re.sub(r"(?s){%\s*block\s+\w*(?:css|style|class)\w*\s*%}.*?{%\s*endblock\s*%}", "", source)
            source = re.sub(r"(?s){%\s*(?:blocktrans|blocktranslate)\b.*?{%\s*end(?:blocktrans|blocktranslate)\s*%}", "", source)
            source = re.sub(r"(?s){%.*?%}|{{.*?}}|{#.*?#}", "", source)
            parser = VisibleTextParser()
            parser.feed(source)
            errors.extend(f"{path.relative_to(settings.BASE_DIR)}:{line}: {text}" for line, text in parser.untranslated)
    return errors


def python_errors():
    errors = []
    display_keywords = {"label", "help_text", "verbose_name", "verbose_name_plural", "field_label"}
    message_methods = {"success", "error", "warning", "info"}
    for app in settings.BASE_DIR.iterdir():
        if not app.is_dir() or not (app.name == "core" or app.name.startswith("joatham_")):
            continue
        for path in app.rglob("*.py"):
            if "migrations" in path.parts or "tests" in path.parts or path.name.startswith("test"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                values = [item.value for item in node.keywords if item.arg in display_keywords]
                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "messages"
                    and node.func.attr in message_methods
                    and len(node.args) > 1
                ):
                    values.append(node.args[1])
                if isinstance(node.func, ast.Name) and node.func.id == "ValidationError" and node.args:
                    values.append(node.args[0])
                for value in values:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        literal = value.value
                    elif isinstance(value, ast.JoinedStr):
                        literal = "".join(part.value for part in value.values if isinstance(part, ast.Constant))
                    else:
                        continue
                    if re.search(r"[A-Za-zÀ-ÿ]{2}", literal):
                        errors.append(f"{path.relative_to(settings.BASE_DIR)}:{node.lineno}: unmarked interface text")
    return errors
