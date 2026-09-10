import os

from unittest.mock import patch

from django.core.management import call_command
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import AccountProfile


class SuperAdminTests(TestCase):
	def setUp(self):
		self.admin = User.objects.create_user(
			username='RoRed0',
			password='admin-password',
			is_staff=True,
			is_superuser=True,
		)
		AccountProfile.objects.create(user=self.admin, role='company', display_name='RoRed0')
		self.account = User.objects.create_user(
			username='candidate',
			password='old-password',
			email='old@example.com',
		)
		AccountProfile.objects.create(user=self.account, role='worker', display_name='Old name')

	def test_super_admin_requires_staff_access(self):
		response = self.client.get(reverse('super_admin'))
		self.assertEqual(response.status_code, 302)
		self.assertIn('/login/', response['Location'])
		self.assertIn('next=/super_admin', response['Location'])

		self.client.force_login(self.account)
		response = self.client.get(reverse('super_admin'))
		self.assertEqual(response.status_code, 403)

		self.account.is_staff = True
		self.account.save(update_fields=['is_staff'])
		response = self.client.get(reverse('super_admin'))
		self.assertEqual(response.status_code, 200)

	def test_staff_can_edit_account_and_password(self):
		self.client.force_login(self.admin)
		response = self.client.post(reverse('super_admin'), {
			'action': 'save_user',
			'user_id': self.account.pk,
			'username': 'candidate-updated',
			'email': 'new@example.com',
			'first_name': 'New',
			'last_name': 'Candidate',
			'display_name': 'New name',
			'role': 'worker',
			'new_password': 'new-password',
			'is_active': 'on',
		})
		self.assertRedirects(response, reverse('super_admin'))
		self.account.refresh_from_db()
		self.assertEqual(self.account.username, 'candidate-updated')
		self.assertTrue(self.account.check_password('new-password'))
		self.assertEqual(self.account.account_profile.display_name, 'New name')

	def test_named_user_without_staff_flags_is_denied(self):
		self.admin.is_staff = False
		self.admin.is_superuser = False
		self.admin.save(update_fields=['is_staff', 'is_superuser'])

		self.client.force_login(self.admin)
		response = self.client.get(reverse('super_admin'))

		self.assertEqual(response.status_code, 403)

	def test_logout_requires_post(self):
		self.client.force_login(self.admin)
		response = self.client.get('/logout/')
		self.assertEqual(response.status_code, 405)
		self.assertTrue(response.wsgi_request.user.is_authenticated)

		response = self.client.post('/logout/')
		self.assertRedirects(response, reverse('home'))
		self.assertFalse(response.wsgi_request.user.is_authenticated)

	def test_login_rejects_external_next_url(self):
		response = self.client.post(
			'/login/?next=https://attacker.example',
			{'username': 'RoRed0', 'password': 'admin-password'},
		)
		self.assertRedirects(response, reverse('home'))

	def test_api_rejects_weak_password_and_case_variant_username(self):
		response = self.client.post('/api/register/', {
			'username': 'rored0',
			'email': 'other@example.com',
			'password': '12345678',
			'role': 'worker',
			'display_name': 'Other user',
		}, content_type='application/json')
		self.assertEqual(response.status_code, 400)

	def test_api_mutations_require_authentication(self):
		response = self.client.post('/api/jobs/', {}, content_type='application/json')
		self.assertEqual(response.status_code, 401)

	def test_ensure_admin_promotes_configured_user(self):
		with patch.dict(os.environ, {
			'SUPER_ADMIN_USERNAME': 'deployment-admin',
			'SUPER_ADMIN_PASSWORD': 'deployment-password',
		}):
			call_command('ensure_admin')

		user = User.objects.get(username='deployment-admin')
		self.assertTrue(user.is_active)
		self.assertTrue(user.is_staff)
		self.assertTrue(user.is_superuser)
		self.assertTrue(user.check_password('deployment-password'))

	def test_account_settings_updates_profile_and_password(self):
		self.client.force_login(self.account)
		response = self.client.post(reverse('account_settings'), {
			'username': 'candidate-renamed',
			'email': 'updated@example.com',
			'display_name': 'Updated name',
			'role': 'company',
			'new_password': 'New-secure-password-9482',
			'new_password_confirm': 'New-secure-password-9482',
		})
		self.assertRedirects(response, reverse('account_settings'))
		self.account.refresh_from_db()
		self.assertEqual(self.account.username, 'candidate-renamed')
		self.assertEqual(self.account.email, 'updated@example.com')
		self.assertTrue(self.account.check_password('New-secure-password-9482'))
		self.assertEqual(self.account.account_profile.display_name, 'Updated name')
		self.assertEqual(self.account.account_profile.role, 'company')

	def test_account_settings_requires_login(self):
		response = self.client.get(reverse('account_settings'))
		self.assertEqual(response.status_code, 302)
		self.assertIn('/login/', response['Location'])
