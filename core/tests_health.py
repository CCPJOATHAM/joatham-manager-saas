import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.audit import record_audit_event
from core.models import ActivityLog


class HealthCheckTests(TestCase):
    def test_health_check_returns_ok_without_sensitive_information(self):
        response = self.client.get(reverse("health_check"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(json.loads(response.content), {"status": "ok"})
        response_text = response.content.decode("utf-8").lower()
        for forbidden_value in ("secret", "password", "database", "postgres", "sqlite", "user"):
            self.assertNotIn(forbidden_value, response_text)

    def test_health_check_supports_head_requests(self):
        response = self.client.head(reverse("health_check"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")

    @override_settings(DEBUG=True, HEALTH_CHECK_TOKEN="")
    def test_database_health_check_returns_ok(self):
        response = self.client.get(reverse("database_health_check"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(json.loads(response.content), {"status": "ok"})

    @override_settings(DEBUG=True, HEALTH_CHECK_TOKEN="")
    def test_database_health_check_hides_failure_details(self):
        with patch("core.health.connection.cursor", side_effect=Exception("db password should never leak")):
            response = self.client.get(reverse("database_health_check"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content), {"status": "error"})
        self.assertNotIn("password", response.content.decode("utf-8").lower())

    @override_settings(DEBUG=False, HEALTH_CHECK_TOKEN="")
    def test_database_health_check_requires_token_when_debug_is_disabled(self):
        response = self.client.get(reverse("database_health_check"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content), {"status": "forbidden"})

    @override_settings(HEALTH_CHECK_TOKEN="expected-token")
    def test_database_health_check_can_be_token_protected(self):
        denied = self.client.get(reverse("database_health_check"))
        allowed = self.client.get(reverse("database_health_check"), HTTP_X_HEALTH_TOKEN="expected-token")

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(json.loads(denied.content), {"status": "forbidden"})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(json.loads(allowed.content), {"status": "ok"})


class AuditLoggingTests(TestCase):
    def test_audit_failure_logging_uses_safe_extra_fields(self):
        with patch("core.audit.ActivityLog.objects.create", side_effect=Exception("boom")):
            with self.assertLogs("core.audit", level="ERROR"):
                result = record_audit_event(
                    entreprise=None,
                    utilisateur=None,
                    action="test_action",
                    module="test_module",
                    objet_type="TestObject",
                    objet_id=1,
                    description="Test audit failure.",
                )

        self.assertIsNone(result)

    def test_record_audit_event_serializes_lazy_and_nested_metadata(self):
        result = record_audit_event(
            entreprise=None,
            utilisateur=None,
            action="test_action",
            module="test_module",
            objet_type="TestObject",
            objet_id=1,
            description=_("Description traduite"),
            metadata={
                "label": _("Valeur paresseuse"),
                "nested": {
                    "status": _("Statut imbrique"),
                    "amount": Decimal("12.50"),
                    "as_of": date(2026, 5, 10),
                },
                "items": [_("Element de liste"), Decimal("4.75"), timezone.now()],
            },
            fail_silently=False,
        )

        self.assertIsNotNone(result)
        self.assertTrue(ActivityLog.objects.filter(pk=result.pk).exists())

        audit = ActivityLog.objects.get(pk=result.pk)
        self.assertEqual(audit.description, "Description traduite")
        self.assertEqual(audit.metadata["label"], "Valeur paresseuse")
        self.assertEqual(audit.metadata["nested"]["status"], "Statut imbrique")
        self.assertEqual(audit.metadata["nested"]["amount"], "12.50")
        self.assertEqual(audit.metadata["nested"]["as_of"], "2026-05-10")
        self.assertEqual(audit.metadata["items"][0], "Element de liste")
        self.assertEqual(audit.metadata["items"][1], "4.75")
        self.assertIsInstance(audit.metadata["items"][2], str)
