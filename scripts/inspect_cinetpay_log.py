"""Read journal text on stdin; emit HTTP status and allowlisted field NAMES only.

No network, no Django imports, no file writes. Never echo input on parse failure.
Historical no-checkout-url messages do not contain an exact HTTP status.
"""
import ast
import json
import re
import sys

FIELDS = {"code", "status", "description", "message", "data", "details",
          "payment_url", "paymentUrl", "payment_token", "paymentToken",
          "notify_token", "notifyToken", "access_token", "token",
          "transaction_id", "merchant_transaction_id", "errors"}
MARKER = "CinetPay payment creation returned no checkout URL: "


def inspect_line(line):
    if len(line) > 65536:
        return None
    match = re.search(r"CinetPay HTTP response: http_status=([1-5][0-9]{2}) response=(.*)", line)
    historical = MARKER in line
    if not match and not historical:
        return None
    raw = match.group(2) if match else line.split(MARKER, 1)[1]
    try:
        payload = ast.literal_eval(raw.strip())
    except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError):
        return {"http_status": int(match.group(1)) if match else None, "schema": "unparseable"}
    if not isinstance(payload, dict):
        return {"http_status": int(match.group(1)) if match else None, "schema": "not_object"}
    result = {"http_status": int(match.group(1)) if match else None}
    if match or isinstance(payload.get("fields"), list):
        for key in ("fields", "data_fields", "details_fields"):
            names = payload.get(key, [])
            result[key] = sorted(FIELDS.intersection(name for name in names if isinstance(name, str))) if isinstance(names, list) else []
    else:
        # Old messages contain a redacted raw body. Extract names, never values.
        result["fields"] = sorted(FIELDS.intersection(payload))
        for key in ("data", "details"):
            value = payload.get(key)
            result[key + "_fields"] = sorted(FIELDS.intersection(value)) if isinstance(value, dict) else []
    return result


if __name__ == "__main__":
    for line in sys.stdin:
        result = inspect_line(line)
        if result is not None:
            print(json.dumps(result, ensure_ascii=True))
