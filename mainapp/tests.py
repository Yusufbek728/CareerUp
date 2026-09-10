from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import AccountProfile


class SuperAdminTests(TestCase):
	def setUp(self):
		self.admin = User.objects.create_user(
			username='admin',
			password='admin-password',
			is_staff=True,
		)
		AccountProfile.objects.create(user=self.admin, role='company', display_name='Admin')
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
		self.assertEqual(response.status_code, 302)
		self.assertIn('/login/', response['Location'])
		self.assertIn('next=/super_admin', response['Location'])

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
