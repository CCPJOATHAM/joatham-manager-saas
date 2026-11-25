from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, RequestFactory, override_settings
from django.utils import translation

from core.services.payment_providers import (
    CinetPayPaymentProvider, PaymentProviderError, _post_json,
    _url_looks_like_sandbox, _url_looks_like_production,
)
from core.services.subscription_payments import generate_external_reference
from scripts.inspect_cinetpay_log import inspect_line


@override_settings(
    CINETPAY_APIKEY="FAKE_KEY_ONLY", CINETPAY_API_PASSWORD="FAKE_PASSWORD_ONLY",
    CINETPAY_CURRENCY="CDF", CINETPAY_CHANNEL="PUSH",
    JOATHAM_PAYMENT_CALLBACK_URL="https://merchant.example/notify",
    JOATHAM_PAYMENT_RETURN_URL="https://merchant.example/return",
    CINETPAY_AUTH_URL="https://api.cinetpay.net/v1/oauth/login",
    CINETPAY_PAYMENT_URL="https://api.cinetpay.net/v1/payment",
)
class CinetPayInitializationTests(SimpleTestCase):
    def payment(self):
        return SimpleNamespace(
            amount_expected=Decimal("23000"), montant_usd=Decimal("10"), montant=Decimal("10"),
            external_reference=generate_external_reference(), created_by=None,
            entreprise=SimpleNamespace(nom="Fixture enterprise", email="fixture@example.com"),
            plan=SimpleNamespace(nom="Starter"),
        )

    def response(self, payload, status=200):
        response = Mock(status_code=status)
        response.json.return_value = payload
        return response

    def run_payment(self, payload):
        with patch("core.services.payment_providers.requests.post", side_effect=[
            self.response({"access_token": "FAKE_ACCESS_TOKEN"}),
            self.response(payload),
        ]) as post:
            result = CinetPayPaymentProvider().create_payment(self.payment())
            return result, post.call_args_list[-1].kwargs["json"]

    def test_reference_fits_documented_limit_without_changing_prefix(self):
        refs = {generate_external_reference() for _ in range(100)}
        self.assertEqual(len(refs), 100)
        for reference in refs:
            self.assertEqual(len(reference), 30)
            self.assertTrue(reference.startswith("SUB-"))

    def test_success_top_level_and_historical_wrappers_in_fr_en(self):
        data = {"payment_url": "https://checkout.example/FIXTURE",
                "notify_token": "FAKE_NOTIFY_TOKEN", "payment_token": "FAKE_PAYMENT_TOKEN"}
        for language in ("fr", "en"):
            for payload in ({"code": 200, **data}, {"data": data}, {"data": {"details": data}}):
                with self.subTest(language=language, shape=list(payload)), translation.override(language):
                    result, sent = self.run_payment(payload)
                    self.assertEqual(result.checkout_url, data["payment_url"])
                    self.assertEqual(sent["lang"], language)
                    self.assertEqual(sent["currency"], "CDF")
                    self.assertEqual(sent["amount"], 23000)
                    self.assertFalse(sent["direct_pay"])
                    self.assertLessEqual(len(sent["merchant_transaction_id"]), 30)

    def test_http_200_business_error_is_not_reported_as_missing_url(self):
        for language in ("fr", "en"):
            with translation.override(language), self.assertLogs("core.services.payment_providers", level="WARNING") as logs:
                with self.assertRaises(PaymentProviderError) as error:
                    self.run_payment({"code": 400, "status": "VALIDATION_ERROR",
                                      "description": "FAKE_PASSWORD_ONLY", "payment_url": "https://secret.example/TOKEN"})
                self.assertNotIn("URL", str(error.exception))
                self.assertIn("400", str(logs.output))
                self.assertNotIn("FAKE_PASSWORD_ONLY", str(logs.output))
                self.assertNotIn("secret.example", str(logs.output))

    def test_missing_url_diagnostic_never_logs_payload_or_free_text(self):
        with self.assertLogs("core.services.payment_providers", level="WARNING") as logs:
            with self.assertRaises(PaymentProviderError):
                self.run_payment({"code": 200, "status": "FAKE_SECRET_UPPERCASE",
                                  "description": "FAKE_PASSWORD_ONLY",
                                  "details": {"anything": "FAKE_CLIENT_DATA"},
                                  "Authorization": "FAKE_KEY_ONLY",
                                  "notify_token": "FAKE_NOTIFY_TOKEN"})
        rendered = str(logs.output)
        for secret in ("FAKE_SECRET_UPPERCASE", "FAKE_PASSWORD_ONLY", "FAKE_CLIENT_DATA", "FAKE_KEY_ONLY", "FAKE_NOTIFY_TOKEN"):
            self.assertNotIn(secret, rendered)
        self.assertIn("has_details_object", rendered)

    def test_no_notify_token_is_still_rejected(self):
        with self.assertRaises(PaymentProviderError):
            self.run_payment({"code": 200, "payment_url": "https://checkout.example/FIXTURE"})

    def test_invalid_checkout_urls_are_not_invented_or_logged(self):
        for value in ("javascript:FAKE_SECRET", "http://checkout.example/FIXTURE",
                      "https://FAKE_USER:FAKE_PASSWORD_ONLY@checkout.example/", {"bad": "FAKE_SECRET"}):
            with self.assertLogs("core.services.payment_providers", level="WARNING") as logs:
                with self.assertRaises(PaymentProviderError):
                    self.run_payment({"code": 200, "payment_url": value, "notify_token": "FAKE_NOTIFY_TOKEN"})
            self.assertNotIn("FAKE_SECRET", str(logs.output))
            self.assertNotIn("FAKE_PASSWORD_ONLY", str(logs.output))

    def test_http_rejection_does_not_log_response_body(self):
        response = self.response({"code": 401, "description": "FAKE_PASSWORD_ONLY"}, 401)
        with patch("core.services.payment_providers.requests.post", return_value=response), self.assertLogs(
            "core.services.payment_providers", level="WARNING"
        ) as logs:
            with self.assertRaises(PaymentProviderError):
                _post_json("https://api.example", {}, timeout=1)
        self.assertNotIn("FAKE_PASSWORD_ONLY", str(logs.output))
        self.assertIn("401", str(logs.output))

    def test_non_object_json_is_rejected(self):
        for payload in ([], None, "FAKE_SECRET"):
            with patch("core.services.payment_providers.requests.post", return_value=self.response(payload)):
                with self.assertRaises(PaymentProviderError):
                    _post_json("https://api.example", {}, timeout=1)

    def test_invalid_json_is_rejected(self):
        response = self.response(None)
        response.json.side_effect = ValueError("FAKE_RESPONSE_BODY")
        with patch("core.services.payment_providers.requests.post", return_value=response):
            with self.assertRaises(PaymentProviderError) as error:
                _post_json("https://api.example", {}, timeout=1)
        self.assertNotIn("FAKE_RESPONSE_BODY", str(error.exception))

    def test_timeout_is_safe(self):
        import requests
        with patch("core.services.payment_providers.requests.post", side_effect=requests.Timeout("FAKE_PASSWORD_ONLY")):
            with self.assertRaises(PaymentProviderError) as error:
                _post_json("https://api.example", {}, timeout=1)
        self.assertNotIn("FAKE_PASSWORD_ONLY", str(error.exception))

    def test_all_log_levels_exclude_secrets_payloads_and_customer_data(self):
        private_values = ["FIXTURE_PASSWORD", "FIXTURE_APIKEY", "FIXTURE_TOKEN",
                          "fixture-customer@example.invalid", "+243000000001", "Fixture Customer Private",
                          "https://checkout.example/FIXTURE_TOKEN", "FIXTURE_REQUEST_BODY"]
        payload = {
            "code": 200, "status": "OK", "payment_url": private_values[6],
            "notify_token": private_values[2], "API_KEY": private_values[1],
            "Password": private_values[0],
            "customer": {"email": private_values[3], "phone": private_values[4], "name": private_values[5]},
            "description": private_values[7],
        }
        with self.assertLogs("core.services.payment_providers", level="DEBUG") as logs:
            self.run_payment(payload)
        rendered = str(logs.output)
        for private in private_values:
            self.assertNotIn(private, rendered)
        self.assertNotIn("'customer':", rendered)
        self.assertNotIn("'description':", rendered)
        self.assertIn("http_status=200", rendered)

    def test_sandbox_domain_is_not_misclassified_as_production(self):
        self.assertTrue(_url_looks_like_sandbox("https://api.cinetpay.net/v1/payment"))
        self.assertFalse(_url_looks_like_production("https://api.cinetpay.net/v1/payment"))
        self.assertFalse(_url_looks_like_sandbox("https://api.cinetpay.co/v1/payment"))
        self.assertTrue(_url_looks_like_production("https://api.cinetpay.co/v1/payment"))

    def test_explicit_error_status_without_code_is_rejected(self):
        with self.assertRaises(PaymentProviderError):
            self.run_payment({"status": "ERROR", "payment_url": "https://checkout.example/FIXTURE"})

    def test_log_filter_extracts_names_without_values_from_historical_log(self):
        result = inspect_line("CinetPay payment creation returned no checkout URL: " + repr({
            "code": 400, "status": "FAKE_PASSWORD_ONLY", "description": "FAKE_KEY_ONLY",
            "FAKE_SECRET_FIELD_NAME": "FAKE_SECRET", "data": {"payment_url": "FAKE_URL_SECRET"}
        }))
        self.assertEqual(result["http_status"], None)
        self.assertEqual(result["fields"], ["code", "data", "description", "status"])
        self.assertEqual(result["data_fields"], ["payment_url"])
        self.assertNotIn("FAKE", str(result))

    def test_log_filter_extracts_only_http_and_names_from_new_log(self):
        result = inspect_line("CinetPay HTTP response: http_status=200 response=" + repr({
            "api_code": "FAKE_SECRET", "fields": ["code", "FAKE_SECRET_FIELD_NAME"],
            "data_fields": ["payment_url"], "details_fields": [],
        }))
        self.assertEqual(result, {"http_status": 200, "fields": ["code"],
                                  "data_fields": ["payment_url"], "details_fields": []})
        self.assertEqual(inspect_line("CinetPay payment creation returned no checkout URL: INVALID"),
                         {"http_status": None, "schema": "unparseable"})


@override_settings(
    CINETPAY_APIKEY="FAKE_KEY_ONLY", CINETPAY_API_PASSWORD="FAKE_PASSWORD_ONLY",
    CINETPAY_CURRENCY="CDF", JOATHAM_PAYMENT_CALLBACK_URL="https://merchant.example/notify",
    JOATHAM_PAYMENT_RETURN_URL="https://merchant.example/return",
    CINETPAY_AUTH_URL="https://api.cinetpay.net/v1/oauth/login",
    CINETPAY_PAYMENT_CHECK_URL="https://api.cinetpay.net/v1/payment/{merchant_transaction_id}",
)
class HistoricalCinetPayReferenceTests(TestCase):
    def setUp(self):
        from core.models import PaiementAbonnement
        from joatham_billing.tests.factories import create_entreprise
        from joatham_users.models import Abonnement
        self.company = create_entreprise("Historical fixture")
        self.plan = Abonnement.objects.create(nom="Starter", code="starter", prix=10, duree_jours=30, actif=True)
        self.old_reference = "SUB-" + "a" * 32
        self.payment = PaiementAbonnement.objects.create(
            entreprise=self.company, plan=self.plan, duree="mensuel", montant=10,
            montant_usd=10, amount_expected=23000, paid_currency="CDF",
            reference_paiement=self.old_reference, external_reference=self.old_reference,
            provider="cinetpay", methode_paiement="automatique",
            checkout_url="https://checkout.example/HISTORICAL",
            provider_notify_token="FAKE_HISTORICAL_NOTIFY",
        )
        self.snapshot = self.row()

    def row(self):
        return type(self.payment).objects.values().get(pk=self.payment.pk)

    def test_generating_new_references_never_updates_existing_transactions(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            for _ in range(20):
                self.assertEqual(len(generate_external_reference()), 30)
        self.assertEqual(len(queries), 0)
        self.assertEqual(self.row(), self.snapshot)
        self.assertEqual(len(self.old_reference), 36)

    def test_resume_keeps_historical_reference_and_entire_transaction_unchanged(self):
        from core.services.subscription_payments import resume_or_create_automatic_payment
        with patch("core.services.subscription_payments.create_automatic_subscription_payment_request") as create:
            result = resume_or_create_automatic_payment(
                entreprise=self.company, plan=self.plan, duree="mensuel", provider="cinetpay",
            )
        create.assert_not_called()
        self.assertEqual(result.pk, self.payment.pk)
        self.assertEqual(result.external_reference, self.old_reference)
        self.assertEqual(self.row(), self.snapshot)

    def test_status_check_uses_full_historical_reference_without_database_update(self):
        with patch("core.services.payment_providers._post_json", return_value={"access_token": "FAKE_AUTH"}), patch(
            "core.services.payment_providers._get_json",
            return_value={"data": {"status": "PENDING", "merchant_transaction_id": self.old_reference,
                                   "amount": "23000", "currency": "CDF"}},
        ) as check:
            result = CinetPayPaymentProvider().fetch_transaction_status(self.old_reference)
        self.assertEqual(check.call_args.args[0], "https://api.cinetpay.net/v1/payment/" + self.old_reference)
        self.assertEqual(result.external_reference, self.old_reference)
        self.assertEqual(self.row(), self.snapshot)

    def test_authenticated_notification_matches_full_historical_reference(self):
        import json
        from core.services.payment_providers import VerifiedWebhookPayment
        canonical = VerifiedWebhookPayment(
            external_reference=self.old_reference, event_id="FAKE_EVENT", status="processing",
            amount=Decimal("23000"), currency="CDF", provider_transaction_id="FAKE_TX",
            provider_status="PENDING", raw_payload={}, paid_at=None,
        )
        request = RequestFactory().post("/fixture", data=json.dumps({
            "merchant_transaction_id": self.old_reference, "notify_token": "FAKE_HISTORICAL_NOTIFY",
        }), content_type="application/json")
        with patch.object(CinetPayPaymentProvider, "fetch_transaction_status", return_value=canonical) as fetch:
            result = CinetPayPaymentProvider().verify_webhook(request)
        fetch.assert_called_once_with(self.old_reference)
        self.assertEqual(result.external_reference, self.old_reference)
        self.assertEqual(self.row(), self.snapshot)
