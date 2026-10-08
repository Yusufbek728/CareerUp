import base64
import os
from pathlib import Path

from unittest.mock import patch

from django.core.management import call_command
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .forms import JobForm
from .models import AccountProfile, Internship, Job, Resume


class HomepagePaginationTests(TestCase):
	def test_listing_sections_are_paginated_independently(self):
		for index in range(11):
			Job.objects.create(
				company_name='Example Company',
				phone_number='+998901234567',
				salary=1000,
				required_experience=1,
				work_time=8,
				job_title=f'Job {index}',
				requirements_of_job='Python',
			)
			Internship.objects.create(
				company_name='Example Company',
				phone_number='+998901234567',
				work_time=8,
				work_duration=12,
				job_title=f'Internship {index}',
			)
			Resume.objects.create(
				name=f'Candidate {index}',
				surname='Example',
				email=f'candidate{index}@example.com',
				phone_number='+998901234567',
				experience=1,
				wanted_salary=1000,
				wanted_work_time=8,
			)

		response = self.client.get(reverse('home'))
		self.assertEqual(response.status_code, 200)
		for listing_type in ('jobs', 'internships', 'resumes'):
			self.assertEqual(len(response.context[listing_type].object_list), 9)
			self.assertTrue(response.context[listing_type].has_next())

		response = self.client.get(reverse('home'), {
			'jobs_page': 2,
			'internships_page': 2,
			'resumes_page': 2,
			'q': 'Example',
		})
		self.assertContains(
			response,
			'jobs_page=1&amp;internships_page=2&amp;resumes_page=2&amp;q=Example#jobs',
		)
		for listing_type in ('jobs', 'internships', 'resumes'):
			self.assertEqual(len(response.context[listing_type].object_list), 2)
			self.assertFalse(response.context[listing_type].has_next())

	def test_homepage_pagination_shows_at_most_nine_numbered_links(self):
		for index in range(100):
			Job.objects.create(
				company_name='Example Company',
				phone_number='+998901234567',
				salary=1000,
				required_experience=1,
				work_time=8,
				job_title=f'Job {index}',
				requirements_of_job='Python',
			)

		response = self.client.get(reverse('home'))

		self.assertEqual(len(response.context['jobs']), 9)
		self.assertEqual(len(response.context['jobs_page_numbers']), 9)
		self.assertContains(response, 'aria-label="Jobs pagination"')
		self.assertContains(response, 'jobs_page=9')

		response = self.client.get(reverse('home'), {'jobs_page': 2})
		self.assertEqual(response.context['jobs'].number, 2)
		self.assertEqual(len(response.context['jobs_page_numbers']), 9)

	def test_homepage_keeps_all_listing_sections_visible(self):
		Job.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
		)
		Internship.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			work_time=8,
			work_duration=12,
			job_title='Internship',
		)
		Resume.objects.create(
			name='Candidate',
			surname='Example',
			email='candidate@example.com',
			phone_number='+998901234567',
			experience=1,
			wanted_salary=1000,
			wanted_work_time=8,
		)

		response = self.client.get(reverse('home'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'id="jobs"')
		self.assertContains(response, 'id="internships"')
		self.assertContains(response, 'id="resumes"')
		self.assertContains(response, 'class="listing-card-media resume-card-media"')
		self.assertContains(response, 'class="job-card resume-card listing-card"')
		self.assertContains(response, 'href="#career" class="back-to-top"')

	def test_authenticated_user_actions_are_in_account_menu(self):
		user = User.objects.create_user(username='shukhrat', password='test-password')
		AccountProfile.objects.create(
			user=user,
			role='company',
			display_name='Shuhrat Atakhanov',
			company_photo='company_photos/company.png',
		)
		self.client.force_login(user)

		response = self.client.get(reverse('home'))

		self.assertContains(response, 'class="account-menu"')
		self.assertContains(response, 'Shuhrat Atakhanov')
		self.assertContains(response, 'class="account-avatar-image"')
		self.assertContains(response, 'company_photos/company.png')
		self.assertNotContains(response, 'Free')
		self.assertContains(response, 'My cards')
		self.assertContains(response, 'Account settings')
		self.assertContains(response, 'Log out')

	def test_category_pages_render_only_selected_listing_type(self):
		Job.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
		)
		Internship.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			work_time=8,
			work_duration=12,
			job_title='Internship',
		)
		Resume.objects.create(
			name='Candidate',
			surname='Example',
			email='candidate@example.com',
			phone_number='+998901234567',
			experience=1,
			wanted_salary=1000,
			wanted_work_time=8,
		)

		for view_name, expected_type in (
			('jobs_page', 'job'),
			('internships_page', 'internship'),
			('resumes_page', 'resume'),
		):
			response = self.client.get(reverse(view_name))
			self.assertEqual(response.status_code, 200)
			self.assertEqual(response.context['listing_type'], expected_type)
			self.assertTemplateUsed(response, 'mainapp/category_list.html')
			self.assertContains(response, 'theme.js?v=dark-pages-1&switch=3')
			self.assertContains(response, 'class="category-listing-body"')
			self.assertNotContains(response, 'hero-copy')
			self.assertContains(response, 'class="header site-header"')
			self.assertNotContains(response, 'class="header-search"')
			self.assertContains(response, 'class="listing-search"')
			self.assertContains(response, f'href="{reverse("home")}" class="back-link category-back-link"')
			self.assertContains(response, 'styles.css?v=site-header-global-1&switch=4')
			self.assertEqual(len(response.context['items']), 1)
			self.assertContains(response, f'return_to={expected_type}')
			if expected_type == 'resume':
				self.assertContains(response, 'class="listing-card-media resume-card-media"')

	def test_job_page_filters_salary_and_all_work_attributes_together(self):
		matching_job = Job.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=5000000,
			required_experience=1,
			work_time=8,
			job_title='Matching developer',
			requirements_of_job='Python',
			status='qidirilyapti',
			working_condition='remote',
			work_field='temporary',
			work_schedule_and_working_hours='5/2',
		)
		Job.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=8000000,
			required_experience=1,
			work_time=8,
			job_title='Other developer',
			requirements_of_job='Python',
			status='topilgan',
			working_condition='full_time',
			work_field='permament',
			work_schedule_and_working_hours='6/1',
		)

		response = self.client.get(reverse('jobs_page'), {
			'salary_min': 4000000,
			'salary_max': 6000000,
			'status': 'qidirilyapti',
			'working_condition': 'remote',
			'work_field': 'temporary',
			'work_schedule_and_working_hours': '5/2',
		})

		self.assertEqual(response.status_code, 200)
		self.assertEqual([item.pk for item in response.context['items']], [matching_job.pk])

	def test_internship_filters_work_attributes_without_salary(self):
		matching_internship = Internship.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			work_time=8,
			work_duration=12,
			job_title='Remote internship',
			status='qidirilyapti',
			working_condition='remote',
			work_field='temporary',
			work_schedule_and_working_hours='5/2',
		)
		Internship.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			work_time=8,
			work_duration=12,
			job_title='On-site internship',
			working_condition='full_time',
		)

		response = self.client.get(reverse('internships_page'), {
			'status': 'qidirilyapti',
			'working_condition': 'remote',
			'work_field': 'temporary',
			'work_schedule_and_working_hours': '5/2',
		})

		self.assertEqual(response.status_code, 200)
		self.assertEqual([item.pk for item in response.context['items']], [matching_internship.pk])
		self.assertNotContains(response, 'data-salary-min-range')

	def test_resume_page_filters_wanted_salary_and_work_preferences(self):
		matching_resume = Resume.objects.create(
			name='Candidate',
			surname='Example',
			email='candidate@example.com',
			phone_number='+998901234567',
			experience=1,
			wanted_salary=5000000,
			wanted_work_time=8,
			wanted_working_condition='remote',
			wanted_work_schedule_and_working_hours='5/2',
		)
		Resume.objects.create(
			name='Other',
			surname='Candidate',
			email='other@example.com',
			phone_number='+998901234568',
			experience=1,
			wanted_salary=8000000,
			wanted_work_time=8,
			wanted_working_condition='full_time',
		)

		response = self.client.get(reverse('resumes_page'), {
			'salary_min': 4000000,
			'salary_max': 6000000,
			'status': 'qidirilyapti',
			'working_condition': 'remote',
			'work_schedule_and_working_hours': '5/2',
		})

		self.assertEqual(response.status_code, 200)
		self.assertEqual([item.pk for item in response.context['items']], [matching_resume.pk])
		self.assertNotContains(response, 'name="work_field"')

	def test_category_filter_reports_invalid_salary_range(self):
		response = self.client.get(reverse('jobs_page'), {
			'salary_min': 6000000,
			'salary_max': 4000000,
		})

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.context['filters'].errors['salary_max'])
		self.assertContains(response, 'Maximum salary must be greater than or equal to minimum salary.')

class SuperAdminPaginationTests(TestCase):
	def setUp(self):
		self.admin = User.objects.create_superuser('pagination-admin', 'admin@example.com', 'password')
		AccountProfile.objects.create(user=self.admin, role='company', display_name='Administrator')
		self.client.force_login(self.admin)

	def test_listing_sections_are_paginated_independently(self):
		for index in range(11):
			Job.objects.create(
				company_name='Example Company',
				phone_number='+998901234567',
				salary=1000,
				required_experience=1,
				work_time=8,
				job_title=f'Job {index}',
				requirements_of_job='Python',
			)
			Internship.objects.create(
				company_name='Example Company',
				phone_number='+998901234567',
				work_time=8,
				work_duration=12,
				job_title=f'Internship {index}',
			)
			Resume.objects.create(
				name=f'Candidate {index}',
				surname='Example',
				email=f'candidate{index}@example.com',
				phone_number='+998901234567',
				experience=1,
				wanted_salary=1000,
				wanted_work_time=8,
			)

		response = self.client.get(reverse('super_admin'))
		for listing_type in ('jobs', 'internships', 'resumes'):
			self.assertEqual(len(response.context[listing_type].object_list), 10)
			self.assertTrue(response.context[listing_type].has_next())

		response = self.client.get(reverse('super_admin'), {
			'jobs_page': 2,
			'internships_page': 2,
			'resumes_page': 2,
			'q': 'Example',
		})
		self.assertContains(
			response,
			'jobs_page=1&amp;internships_page=2&amp;resumes_page=2&amp;q=Example#job-listings',
		)
		for listing_type in ('jobs', 'internships', 'resumes'):
			self.assertEqual(len(response.context[listing_type].object_list), 1)
			self.assertFalse(response.context[listing_type].has_next())


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


class ThemeSwitcherLanguageTests(TestCase):
	def test_theme_switcher_includes_language_specific_labels(self):
		js_source = (Path(__file__).resolve().parent.parent / 'static' / 'mainapp' / 'theme.js').read_text(encoding='utf-8')
		self.assertIn('Change view', js_source)
		self.assertIn('Сменить вид', js_source)
		self.assertIn("Ko'rinishni o'zgartirish", js_source)
		self.assertIn('Theme selection', js_source)
		self.assertIn('Выбор темы', js_source)
		self.assertIn('Mavzu tanlovi', js_source)
		self.assertIn(".toLowerCase().split(/[-_]/)[0]", js_source)
		self.assertIn("body.dataset.themeSwitcher === 'off'", js_source)
		css_source = (Path(__file__).resolve().parent.parent / 'static' / 'mainapp' / 'styles.css').read_text(encoding='utf-8')
		self.assertIn('body.dark-theme .listing-pagination a.pagination-page.active', css_source)
		self.assertIn('body.dark-theme .back-to-top', css_source)


class ImageUploadTests(TestCase):
	def test_company_can_publish_job_with_work_photo(self):
		company = User.objects.create_user(username='company', password='company-password')
		AccountProfile.objects.create(user=company, role='company', display_name='Company')
		self.client.force_login(company)

		response = self.client.post(reverse('create_listing', args=['job']), {
			'company_name': 'Example Company',
			'work_photo': SimpleUploadedFile(
				'work.png',
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
		self.assertTrue(Job.objects.get().work_photo.name.startswith('work_photos/'))

	def test_company_photo_is_saved_from_account_settings(self):
		company = User.objects.create_user(username='photo-company', password='company-password')
		AccountProfile.objects.create(user=company, role='company', display_name='Company')
		self.client.force_login(company)

		response = self.client.post(reverse('account_settings'), {
			'username': 'photo-company',
			'email': 'company@example.com',
			'display_name': 'Company',
			'role': 'company',
			'company_photo': SimpleUploadedFile(
				'company.png',
				base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='),
				content_type='image/png',
			),
		}, follow=True)

		self.assertEqual(response.status_code, 200)
		company.account_profile.refresh_from_db()
		self.assertTrue(company.account_profile.company_photo.name.startswith('company_photos/'))


class ListingDetailPageTests(TestCase):
	def test_each_listing_type_uses_its_own_detail_template(self):
		job = Job.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
		)
		internship = Internship.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			work_time=8,
			work_duration=12,
			job_title='Internship',
		)
		resume = Resume.objects.create(
			name='Candidate',
			surname='Example',
			email='candidate@example.com',
			phone_number='+998901234567',
			experience=1,
			wanted_salary=1000,
			wanted_work_time=8,
		)

		job_response = self.client.get(reverse('job_detail', args=[job.pk]))
		internship_response = self.client.get(reverse('internship_detail', args=[internship.pk]))
		resume_response = self.client.get(reverse('resume_detail', args=[resume.pk]))

		self.assertEqual(job_response.status_code, 200)
		self.assertEqual(internship_response.status_code, 200)
		self.assertEqual(resume_response.status_code, 200)
		self.assertTemplateUsed(job_response, 'mainapp/job_detail.html')
		self.assertTemplateUsed(internship_response, 'mainapp/internship_detail.html')
		self.assertTemplateUsed(resume_response, 'mainapp/resume_detail.html')
		for response in (job_response, internship_response, resume_response):
			self.assertContains(response, 'theme.js?v=dark-pages-1&switch=3')
			self.assertContains(response, 'class="header site-header"')

	def test_detail_back_link_returns_to_originating_listing_page(self):
		job = Job.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
		)

		home_response = self.client.get(reverse('job_detail', args=[job.pk]), {'return_to': 'home'})
		jobs_response = self.client.get(reverse('job_detail', args=[job.pk]), {'return_to': 'job'})
		invalid_response = self.client.get(reverse('job_detail', args=[job.pk]), {'return_to': '//example.com'})

		self.assertContains(home_response, f'href="{reverse("home")}" class="back-link"')
		self.assertContains(jobs_response, f'href="{reverse("jobs_page")}" class="back-link"')
		self.assertContains(invalid_response, f'href="{reverse("home")}" class="back-link"')

	def test_detail_pages_use_shared_global_header(self):
		job = Job.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
		)

		response = self.client.get(reverse('job_detail', args=[job.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'class="header site-header"')
		self.assertContains(response, 'class="language-current"')
		self.assertContains(response, 'theme.js?v=dark-pages-1&switch=3')
		self.assertContains(response, 'aria-label="Listing categories"')
		self.assertNotContains(response, 'language-select')
		self.assertNotContains(response, 'Back home')
		self.assertContains(response, 'Developer')


class ListingCrudTests(TestCase):
	def test_owner_can_delete_listing_from_edit_page(self):
		company = User.objects.create_user(username='company-owner', password='company-password')
		AccountProfile.objects.create(user=company, role='company', display_name='Company')
		self.client.force_login(company)
		job = Job.objects.create(
			owner=company,
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
		)

		response = self.client.post(reverse('edit_listing', args=['job', job.pk]), {
			'action': 'delete_listing',
		})

		self.assertRedirects(response, reverse('my_listings'))
		self.assertFalse(Job.objects.filter(pk=job.pk).exists())


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

	def test_staff_can_edit_listing_with_work_photo(self):
		self.client.force_login(self.admin)
		job = Job.objects.create(
			owner=self.account,
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
		)

		response = self.client.post(reverse('super_admin_edit_listing', args=['job', job.pk]), {
			'company_name': 'Example Company',
			'work_photo': SimpleUploadedFile(
				'admin-work.png',
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

		self.assertRedirects(response, reverse('super_admin'))
		job.refresh_from_db()
		self.assertTrue(job.work_photo.name.startswith('work_photos/'))

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
