"""Fake delivery only. This module has no transport or credential access."""
import hashlib

class FakeDeliveryProvider:
    def deliver(self, key, message):
        return {'provider_id': 'simulated-' + hashlib.sha256(key.encode()).hexdigest()[:20],
                'status': 'simulated', 'sent': False}
