import base64
import os

from unittest.mock import patch

from django.core.management import call_command
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .forms import JobForm
from .models import AccountProfile, Job


class JobHourlyIncomeTests(TestCase):
	def test_hourly_income_is_calculated_when_job_is_created(self):
		form = JobForm({
			'company_name': 'Example Company',
			'phone_number': '+998901234567',
			'salary': 1000,
			'required_experience': 1,
			'work_time': 8,
			'job_title': 'Developer',
			'requirements_of_job': 'Python',
			'working_condition': 'full_time',
			'work_schedule_and_working_hours': '5/2',
			'work_field': 'permament',
			'status': 'qidirilyapti',
		})

		self.assertTrue(form.is_valid(), form.errors)
		job = form.save()

		self.assertEqual(job.hourly_income, 125)

	def test_zero_work_time_does_not_raise_when_job_is_saved(self):
		job = Job(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=0,
			job_title='Developer',
			requirements_of_job='Python',
		)

		job.save()

		self.assertEqual(job.hourly_income, 0)


class ImageUploadTests(TestCase):
	def test_company_can_publish_job_with_logo(self):
		company = User.objects.create_user(username='company', password='company-password')
		AccountProfile.objects.create(user=company, role='company', display_name='Company')
		self.client.force_login(company)

		response = self.client.post(reverse('create_listing', args=['job']), {
			'company_name': 'Example Company',
			'company_logo': SimpleUploadedFile(
				'logo.png',
				base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='),
				content_type='image/png',
			),
			'phone_number': '+998901234567',
			'salary': 1000,
			'required_experience': 1,
			'work_time': 8,
			'job_title': 'Developer',
			'requirements_of_job': 'Python',
			'working_condition': 'full_time',
			'work_schedule_and_working_hours': '5/2',
			'work_field': 'permament',
			'status': 'qidirilyapti',
		})

		self.assertEqual(response.status_code, 302)
		self.assertTrue(Job.objects.get().company_logo.name.startswith('company_logos/'))


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

	def test_super_admin_can_set_new_password_without_current_password(self):
		self.client.force_login(self.admin)
		response = self.client.post(reverse('super_admin'), {
			'action': 'save_user',
			'user_id': self.account.pk,
			'username': self.account.username,
			'email': self.account.email,
			'first_name': '',
			'last_name': '',
			'display_name': 'Old name',
			'role': 'worker',
			'new_password': 'Admin-set-password-9482',
			'is_active': 'on',
		})
		self.assertRedirects(response, reverse('super_admin'))
		self.account.refresh_from_db()
		self.assertTrue(self.account.check_password('Admin-set-password-9482'))

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
			'current_password': 'old-password',
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

	def test_account_settings_rejects_wrong_current_password(self):
		self.client.force_login(self.account)
		response = self.client.post(reverse('account_settings'), {
			'username': self.account.username,
			'email': self.account.email,
			'display_name': 'Updated name',
			'role': 'worker',
			'current_password': 'wrong-password',
			'new_password': 'New-secure-password-9482',
			'new_password_confirm': 'New-secure-password-9482',
		})
		self.assertEqual(response.status_code, 200)
		self.account.refresh_from_db()
		self.assertTrue(self.account.check_password('old-password'))
		self.assertEqual(response.context['form']['current_password'].value(), '')

	def test_super_admin_creator_can_access_all_listing_types(self):
		self.admin.account_profile.role = 'creator'
		self.admin.account_profile.save(update_fields=['role'])
		self.client.force_login(self.admin)

		for listing_type in ('job', 'internship', 'resume'):
			response = self.client.get(reverse('create_listing', args=[listing_type]))
			self.assertEqual(response.status_code, 200)
			self.assertIn('form', response.context)

	def test_non_superuser_creator_role_is_blocked(self):
		self.account.account_profile.role = 'creator'
		self.account.account_profile.save(update_fields=['role'])
		self.client.force_login(self.account)

		for listing_type in ('job', 'internship', 'resume'):
			response = self.client.get(reverse('create_listing', args=[listing_type]))
			self.assertEqual(response.status_code, 302)
			self.assertEqual(response['Location'], '/?next=/create/' + listing_type + '/')

	def test_account_settings_requires_login(self):
		response = self.client.get(reverse('account_settings'))
		self.assertEqual(response.status_code, 302)
		self.assertIn('/login/', response['Location'])
