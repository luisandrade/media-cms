from django.test import SimpleTestCase
from unittest.mock import patch

from payments.flow import FlowAPIError, FlowClient


class FlowClientTests(SimpleTestCase):
    def test_create_payment_raises_real_flow_message(self):
        client = FlowClient()

        with patch.object(client, "_request", return_value={"code": 1620, "message": "The userEmail is not valid."}):
            with self.assertRaises(FlowAPIError) as ctx:
                client.create_payment(
                    commerce_order="123",
                    subject="Test payment",
                    amount=990,
                    email="invalid@example.org",
                    url_return="http://localhost/return",
                    url_confirmation="http://localhost/confirm",
                )

        self.assertEqual(str(ctx.exception), "Flow create_payment failed: The userEmail is not valid.")
        self.assertEqual(ctx.exception.raw, {"code": 1620, "message": "The userEmail is not valid."})

    def test_create_payment_accepts_alternate_redirect_key(self):
        client = FlowClient()

        with patch.object(client, "_request", return_value={"urlPayment": "https://flow.example/pay", "token": "abc"}):
            result = client.create_payment(
                commerce_order="123",
                subject="Test payment",
                amount=990,
                email="valid@example.com",
                url_return="http://localhost/return",
                url_confirmation="http://localhost/confirm",
            )

        self.assertEqual(result.redirect_url, "https://flow.example/pay?token=abc")
        self.assertEqual(result.token, "abc")
