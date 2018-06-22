from __future__ import absolute_import

import mock
import six

from django.core.urlresolvers import reverse

from sentry.models import Authenticator, TotpInterface, RecoveryCodeInterface, SmsInterface
from sentry.testutils import APITestCase


class UserAuthenticatorDetailsTest(APITestCase):
    def setUp(self):
        self.user = self.create_user(email='test@example.com', is_superuser=False)
        self.login_as(user=self.user)

    def _assert_security_email_sent(self, email_type, email_log):
        assert email_log.info.call_count == 1
        assert 'mail.queued' in email_log.info.call_args[0]
        assert email_log.info.call_args[1]['extra']['message_type'] == email_type

    def test_wrong_auth_id(self):
        url = reverse(
            'sentry-api-0-user-authenticator-details',
            kwargs={
                'user_id': self.user.id,
                'auth_id': 'totp',
            }
        )

        resp = self.client.get(url)
        assert resp.status_code == 404

    def test_get_authenticator_details(self):
        interface = TotpInterface()
        interface.enroll(self.user)
        auth = interface.authenticator

        url = reverse(
            'sentry-api-0-user-authenticator-details',
            kwargs={
                'user_id': self.user.id,
                'auth_id': auth.id,
            }
        )

        resp = self.client.get(url)
        assert resp.status_code == 200
        assert resp.data['isEnrolled']
        assert resp.data['id'] == "totp"
        assert resp.data['authId'] == six.text_type(auth.id)

        # should not have these because enrollment
        assert 'totp_secret' not in resp.data
        assert 'form' not in resp.data
        assert 'qrcode' not in resp.data

    @mock.patch('sentry.utils.email.logger')
    def test_get_recovery_codes(self, email_log):
        interface = RecoveryCodeInterface()
        interface.enroll(self.user)

        url = reverse(
            'sentry-api-0-user-authenticator-details',
            kwargs={
                'user_id': self.user.id,
                'auth_id': interface.authenticator.id,
            }
        )

        resp = self.client.get(url)
        assert resp.status_code == 200
        assert resp.data['id'] == "recovery"
        assert resp.data['authId'] == six.text_type(interface.authenticator.id)
        assert len(resp.data['codes'])

        assert email_log.info.call_count == 0

    def test_u2f_get_devices(self):
        auth = Authenticator.objects.create(
            type=3,  # u2f
            user=self.user,
            config={
                'devices': [{
                    'binding': {
                        'publicKey': u'aowekroawker',
                        'keyHandle': u'aowkeroakewrokaweokrwoer',
                        'appId': u'https://dev.getsentry.net:8000/auth/2fa/u2fappid.json'
                    },
                    'name': u'Amused Beetle',
                    'ts': 1512505334
                }]
            }
        )

        url = reverse(
            'sentry-api-0-user-authenticator-details',
            kwargs={
                'user_id': self.user.id,
                'auth_id': auth.id,
            }
        )

        resp = self.client.get(url)
        assert resp.status_code == 200
        assert resp.data['id'] == "u2f"
        assert resp.data['authId'] == six.text_type(auth.id)
        assert len(resp.data['devices'])
        assert resp.data['devices'][0]['name'] == 'Amused Beetle'

        # should not have these because enrollment
        assert 'challenge' not in resp.data
        assert 'response' not in resp.data

    @mock.patch('sentry.utils.email.logger')
    def test_u2f_remove_device(self, email_log):
        auth = Authenticator.objects.create(
            type=3,  # u2f
            user=self.user,
            config={
                'devices': [{
                    'binding': {
                        'publicKey': 'aowekroawker',
                        'keyHandle': 'devicekeyhandle',
                        'appId': 'https://dev.getsentry.net:8000/auth/2fa/u2fappid.json'
                    },
                    'name': 'Amused Beetle',
                    'ts': 1512505334
                }, {
                    'binding': {
                        'publicKey': 'publickey',
                        'keyHandle': 'aowerkoweraowerkkro',
                        'appId': 'https://dev.getsentry.net:8000/auth/2fa/u2fappid.json'
                    },
                    'name': 'Sentry',
                    'ts': 1512505334
                }]
            }
        )

        url = reverse(
            'sentry-api-0-user-authenticator-device-details',
            kwargs={
                'user_id': self.user.id,
                'auth_id': auth.id,
                'interface_device_id': 'devicekeyhandle'
            }
        )

        resp = self.client.delete(url)
        assert resp.status_code == 204

        authenticator = Authenticator.objects.get(id=auth.id)
        assert len(authenticator.interface.get_registered_devices()) == 1

        self._assert_security_email_sent('device-removed', email_log)

        # Can't remove last device
        url = reverse(
            'sentry-api-0-user-authenticator-device-details',
            kwargs={
                'user_id': self.user.id,
                'auth_id': auth.id,
                'interface_device_id': 'aowerkoweraowerkkro',
            }
        )
        resp = self.client.delete(url)
        assert resp.status_code == 500

        # only one send
        self._assert_security_email_sent('device-removed', email_log)

    def test_sms_get_phone(self):
        interface = SmsInterface()
        interface.phone_number = '5551231234'
        interface.enroll(self.user)

        url = reverse(
            'sentry-api-0-user-authenticator-details',
            kwargs={
                'user_id': self.user.id,
                'auth_id': interface.authenticator.id,
            }
        )

        resp = self.client.get(url)
        assert resp.status_code == 200
        assert resp.data['id'] == "sms"
        assert resp.data['authId'] == six.text_type(interface.authenticator.id)
        assert resp.data['phone'] == '5551231234'

        # should not have these because enrollment
        assert 'totp_secret' not in resp.data
        assert 'form' not in resp.data

    @mock.patch('sentry.utils.email.logger')
    def test_recovery_codes_regenerate(self, email_log):
        interface = RecoveryCodeInterface()
        interface.enroll(self.user)

        url = reverse(
            'sentry-api-0-user-authenticator-details',
            kwargs={
                'user_id': self.user.id,
                'auth_id': interface.authenticator.id,
            }
        )

        resp = self.client.get(url)
        assert resp.status_code == 200
        old_codes = resp.data['codes']

        resp = self.client.get(url)
        assert old_codes == resp.data['codes']

        # regenerate codes
        resp = self.client.put(url)

        resp = self.client.get(url)
        assert old_codes != resp.data['codes']

        self._assert_security_email_sent('recovery-codes-regenerated', email_log)

    @mock.patch('sentry.utils.email.logger')
    def test_delete(self, email_log):
        user = self.create_user(email='a@example.com', is_superuser=True)
        auth = Authenticator.objects.create(
            type=3,  # u2f
            user=user,
        )

        self.login_as(user=user, superuser=True)

        url = reverse(
            'sentry-api-0-user-authenticator-details',
            kwargs={
                'user_id': user.id,
                'auth_id': auth.id,
            }
        )
        resp = self.client.delete(url, format='json')
        assert resp.status_code == 204, (resp.status_code, resp.content)

        assert not Authenticator.objects.filter(
            id=auth.id,
        ).exists()

        self._assert_security_email_sent('mfa-removed', email_log)

    @mock.patch('sentry.utils.email.logger')
    def test_cannot_delete_without_superuser(self, email_log):
        user = self.create_user(email='a@example.com', is_superuser=False)
        auth = Authenticator.objects.create(
            type=3,  # u2f
            user=user,
        )

        actor = self.create_user(email='b@example.com', is_superuser=False)
        self.login_as(user=actor)

        url = reverse(
            'sentry-api-0-user-authenticator-details',
            kwargs={
                'user_id': user.id,
                'auth_id': auth.id,
            }
        )
        resp = self.client.delete(url, format='json')
        assert resp.status_code == 403, (resp.status_code, resp.content)

        assert Authenticator.objects.filter(
            id=auth.id,
        ).exists()

        assert email_log.info.call_count == 0
