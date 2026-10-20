import base64
import os
from pathlib import Path

from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from .forms import JobForm, ListingFilterForm
from .geo_seed import seed_geo_data
from .geo_utils import flag_emoji, normalize_search
from .serialiers import JobSerializer
from .models import AccountProfile, City, Country, Internship, Job, ListingInteraction, Resume, check_city_belongs_to_country


class ListingEngagementTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='engagement-user', password='test-password')
		AccountProfile.objects.create(user=self.user, role='worker', display_name='Engagement User')
		self.job = Job.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
		)
		self.internship = Internship.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			work_time=8,
			work_duration=12,
			job_title='Intern',
		)
		self.resume = Resume.objects.create(
			name='Candidate',
			surname='Example',
			email='candidate@example.com',
			phone_number='+998901234567',
			experience=1,
			wanted_salary=1000,
			wanted_work_time=8,
		)
		self.listings = (
			('job', self.job, 'job_detail'),
			('internship', self.internship, 'internship_detail'),
			('resume', self.resume, 'resume_detail'),
		)

	def test_detail_visits_likes_and_favorites_are_tracked_for_each_listing_type(self):
		self.client.force_login(self.user)

		for listing_type, item, detail_route in self.listings:
			detail_url = reverse(detail_route, args=[item.pk])
			response = self.client.get(detail_url)
			self.assertEqual(response.status_code, 200)
			item.refresh_from_db()
			self.assertEqual(item.view_count, 1)
			self.assertContains(response, 'Views')
			self.assertContains(response, 'Like')

			for action in ('like', 'favorite'):
				response = self.client.post(
					reverse('listing_interaction', args=[listing_type, item.pk, action]),
				)
				self.assertRedirects(response, detail_url)

			interaction = ListingInteraction.objects.get(
				user=self.user,
				content_type__model=listing_type,
				object_id=item.pk,
			)
			self.assertIsNotNone(interaction.viewed_at)
			self.assertIsNotNone(interaction.liked_at)
			self.assertIsNotNone(interaction.favorited_at)

		for activity in ('likes', 'views', 'favorites'):
			response = self.client.get(reverse('account_activity', args=[activity]))
			self.assertEqual(response.status_code, 200)
			self.assertEqual(len(response.context['entries']), 3)

	def test_like_and_favorite_actions_toggle_off(self):
		self.client.force_login(self.user)
		for action, timestamp_field in (('like', 'liked_at'), ('favorite', 'favorited_at')):
			action_url = reverse('listing_interaction', args=['job', self.job.pk, action])
			self.client.post(action_url)
			self.client.post(action_url)
			interaction = ListingInteraction.objects.get(user=self.user, object_id=self.job.pk)
			self.assertIsNone(getattr(interaction, timestamp_field))

	def test_view_count_is_once_per_account_and_once_per_guest_session(self):
		detail_url = reverse('job_detail', args=[self.job.pk])
		self.client.force_login(self.user)
		self.client.get(detail_url)
		first_view = ListingInteraction.objects.get(user=self.user, object_id=self.job.pk)
		first_viewed_at = first_view.viewed_at

		for _ in range(3):
			self.client.get(detail_url)

		self.job.refresh_from_db()
		first_view.refresh_from_db()
		self.assertEqual(self.job.view_count, 1)
		self.assertEqual(first_view.viewed_at, first_viewed_at)

		guest_client = self.client_class()
		for _ in range(3):
			guest_client.get(detail_url)

		self.job.refresh_from_db()
		self.assertEqual(self.job.view_count, 2)

		another_guest_client = self.client_class()
		another_guest_client.get(detail_url)
		self.job.refresh_from_db()
		self.assertEqual(self.job.view_count, 3)

	def test_listing_cards_show_engagement_state_below_the_heading(self):
		self.client.force_login(self.user)
		for action in ('like', 'favorite'):
			self.client.post(
				reverse('listing_interaction', args=['job', self.job.pk, action]),
				{'return_to': 'job'},
			)

		response = self.client.get(reverse('jobs_page'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'class="listing-card-engagement"')
		self.assertContains(response, 'aria-label="Views: 0"')
		self.assertContains(response, 'aria-pressed="true"')
		self.assertContains(response, 'class="listing-card-open"')
		self.assertContains(response, reverse('job_detail', args=[self.job.pk]))
		self.assertEqual(response.context['items'][0].like_count, 1)

	def test_engagement_actions_require_login(self):
		response = self.client.post(
			reverse('listing_interaction', args=['job', self.job.pk, 'like']),
		)
		self.assertRedirects(
			response,
			f'{reverse("login")}?next={reverse("listing_interaction", args=["job", self.job.pk, "like"])}',
		)
		self.assertFalse(ListingInteraction.objects.exists())


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

	def test_category_pages_and_api_pagination_twenty_items_per_page(self):
		for index in range(25):
			Job.objects.create(
				company_name=f'Company {index}',
				phone_number='+998901234567',
				salary=1000 + index,
				required_experience=1,
				work_time=8,
				job_title=f'Job {index}',
				requirements_of_job='Python',
			)
			Internship.objects.create(
				company_name=f'Company {index}',
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

		for view_name in ('jobs_page', 'internships_page', 'resumes_page'):
			page1_response = self.client.get(reverse(view_name))
			self.assertEqual(page1_response.status_code, 200)
			self.assertEqual(len(page1_response.context['items']), 20)
			self.assertTrue(page1_response.context['items'].has_next())
			self.assertEqual(page1_response.context['items'].paginator.num_pages, 2)
			self.assertContains(page1_response, 'class="listing-pagination"')
			self.assertContains(page1_response, 'page=2')

			page2_response = self.client.get(reverse(view_name), {'page': 2})
			self.assertEqual(page2_response.status_code, 200)
			self.assertEqual(len(page2_response.context['items']), 5)
			self.assertFalse(page2_response.context['items'].has_next())

		for api_path in ('/api/jobs/', '/api/internships/', '/api/resumes/'):
			api_response = self.client.get(api_path)
			self.assertEqual(api_response.status_code, 200)
			self.assertEqual(len(api_response.data['results']), 20)
			self.assertEqual(api_response.data['count'], 25)

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

	def test_listing_cards_show_compensation_and_resume_experience(self):
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
			experience=3,
			wanted_salary=4000,
			wanted_work_time=8,
		)

		home_response = self.client.get(reverse('home'))
		self.assertContains(home_response, '$1000')
		self.assertContains(home_response, '$125.00')
		self.assertContains(home_response, 'Unpaid')
		self.assertContains(home_response, '3 years experience')
		self.assertContains(home_response, '$4000')
		self.assertContains(home_response, '$500.00')

		for url, expected_text in (
			(reverse('jobs_page'), ('$1000', '$125.00')),
			(reverse('internships_page'), ('Unpaid',)),
			(reverse('resumes_page'), ('3 years experience', '$4000', '$500.00')),
		):
			response = self.client.get(url)
			for text in expected_text:
				self.assertContains(response, text)

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
		self.assertContains(response, 'Liked listings')
		self.assertContains(response, 'Recently viewed')
		self.assertContains(response, 'Favorites')
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
			self.assertContains(response, 'styles.css?v=listing-engagement-cards-2')
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

	def test_resume_hourly_income_uses_preferred_work_time(self):
		resume = Resume(
			name='Candidate',
			surname='Example',
			email='candidate@example.com',
			phone_number='+998901234567',
			experience=3,
			wanted_salary=4000,
			wanted_work_time=8,
		)

		self.assertEqual(resume.wanted_hourly_income, 500)

		resume.wanted_work_time = 0
		self.assertEqual(resume.wanted_hourly_income, 0)


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
		self.assertContains(job_response, '$1000')
		self.assertContains(job_response, '$125.00')
		self.assertContains(internship_response, 'Unpaid')
		self.assertContains(resume_response, '$1000')
		self.assertContains(resume_response, '$125.00')
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


class PasswordResetFlowTests(TestCase):
	def test_full_reset_flow(self):
		import re
		from django.core import mail
		user = User.objects.create_user(username='reset-user', email='reset@example.com', password='OldPass12345')
		self.assertContains(self.client.get(reverse('login')), reverse('password_reset'))
		response = self.client.post(reverse('password_reset'), {'email': 'reset@example.com'})
		self.assertRedirects(response, reverse('password_reset_done'))
		self.assertEqual(len(mail.outbox), 1)
		link = re.search(r'http://testserver(\S+)', mail.outbox[0].body).group(1)
		response = self.client.get(link, follow=True)
		post_url = response.redirect_chain[-1][0]
		response = self.client.post(post_url, {'new_password1': 'BrandNew98765x', 'new_password2': 'BrandNew98765x'})
		self.assertRedirects(response, reverse('password_reset_complete'))
		user.refresh_from_db()
		self.assertTrue(user.check_password('BrandNew98765x'))

	def test_unknown_email_sends_nothing(self):
		from django.core import mail
		response = self.client.post(reverse('password_reset'), {'email': 'nobody@example.com'})
		self.assertRedirects(response, reverse('password_reset_done'))
		self.assertEqual(len(mail.outbox), 0)

	def _post_reset(self, email, ip='8.8.8.8', **extra):
		return self.client.post(reverse('password_reset'), {'email': email}, REMOTE_ADDR=ip, **extra)

	def test_second_request_for_same_email_does_not_send(self):
		from django.core import mail
		User.objects.create_user(username='dup', email='dup@example.com', password='OldPass12345')
		self.assertRedirects(self._post_reset('dup@example.com'), reverse('password_reset_done'))
		self.assertEqual(len(mail.outbox), 1)
		# Same address with different case/whitespace is the same key.
		response = self._post_reset('  Dup@Example.com ', ip='8.8.4.4')
		self.assertRedirects(response, reverse('password_reset_done'), fetch_redirect_response=False)
		self.assertEqual(len(mail.outbox), 1)
		done = self.client.get(reverse('password_reset_done'))
		self.assertContains(done, '10 min')

	def test_throttle_notice_is_same_for_known_and_unknown_email(self):
		import re
		User.objects.create_user(username='known', email='known@example.com', password='OldPass12345')
		pages = []
		for email in ('known@example.com', 'ghost@example.com'):
			self._post_reset(email)
			self._post_reset(email)
			pages.append(re.sub(rb'csrfmiddlewaretoken" value="[^"]+', b'', self.client.get(reverse('password_reset_done')).content))
		self.assertEqual(pages[0], pages[1])

	def test_notice_is_shown_once(self):
		self._post_reset('once@example.com')
		self._post_reset('once@example.com')
		self.assertContains(self.client.get(reverse('password_reset_done')), '10 min')
		self.assertNotContains(self.client.get(reverse('password_reset_done')), '10 min')

	def test_email_can_be_requested_again_after_cooldown(self):
		from datetime import timedelta
		from django.core import mail
		from django.utils import timezone
		User.objects.create_user(username='later', email='later@example.com', password='OldPass12345')
		self._post_reset('later@example.com')
		self._post_reset('later@example.com')
		self.assertEqual(len(mail.outbox), 1)
		with patch('mainapp.ratelimit.timezone.now', return_value=timezone.now() + timedelta(minutes=10, seconds=1)):
			self._post_reset('later@example.com')
		self.assertEqual(len(mail.outbox), 2)

	def test_ip_limit_blocks_after_five_requests(self):
		from django.core import mail
		from datetime import timedelta
		from django.utils import timezone
		for n in range(7):
			User.objects.create_user(username=f'ip{n}', email=f'ip{n}@example.com', password='OldPass12345')
		for n in range(5):
			self._post_reset(f'ip{n}@example.com', ip='8.8.8.8')
		self.assertEqual(len(mail.outbox), 5)
		response = self._post_reset('ip5@example.com', ip='8.8.8.8')
		self.assertRedirects(response, reverse('password_reset_done'), fetch_redirect_response=False)
		self.assertEqual(len(mail.outbox), 5)
		self.assertContains(self.client.get(reverse('password_reset_done')), 'Too many reset requests')
		# The blocked request must not have consumed the address' own slot, and other IPs are unaffected.
		self._post_reset('ip5@example.com', ip='8.8.4.4')
		self.assertEqual(len(mail.outbox), 6)
		# Window expiry frees the IP.
		with patch('mainapp.ratelimit.timezone.now', return_value=timezone.now() + timedelta(minutes=10, seconds=1)):
			self._post_reset('ip6@example.com', ip='8.8.8.8')
		self.assertEqual(len(mail.outbox), 7)

	def test_spoofed_forwarded_for_is_ignored_by_default(self):
		from django.core import mail
		for n in range(6):
			User.objects.create_user(username=f'sp{n}', email=f'sp{n}@example.com', password='OldPass12345')
		for n in range(6):
			self._post_reset(f'sp{n}@example.com', ip='1.1.1.1', HTTP_X_FORWARDED_FOR=f'10.0.0.{n}, 192.0.2.{n}')
		self.assertEqual(len(mail.outbox), 5)

	def test_trusted_proxy_count_uses_nth_entry_from_right(self):
		from django.core import mail
		from django.test import override_settings
		for n in range(6):
			User.objects.create_user(username=f'tp{n}', email=f'tp{n}@example.com', password='OldPass12345')
		with override_settings(TRUSTED_PROXY_COUNT=1):
			for n in range(6):
				# Client-supplied left part changes every time; the proxy-appended right part is constant.
				self._post_reset(f'tp{n}@example.com', ip='10.1.1.1', HTTP_X_FORWARDED_FOR=f'192.0.2.{n}, 9.9.9.9')
		self.assertEqual(len(mail.outbox), 5)

	def test_ip_limit_skipped_when_only_proxy_address_is_known(self):
		from django.core import mail
		for n in range(7):
			User.objects.create_user(username=f'px{n}', email=f'px{n}@example.com', password='OldPass12345')
		for n in range(7):
			self._post_reset(f'px{n}@example.com', ip='10.2.3.4')
		self.assertEqual(len(mail.outbox), 7)


class SecurityHardeningTests(TestCase):
	def test_login_is_blocked_after_repeated_failures(self):
		User.objects.create_user(username='victim', password='Correct-Pass-123')
		for _ in range(10):
			response = self.client.post(reverse('login'), {'username': 'Victim', 'password': 'wrong'})
			self.assertContains(response, 'Invalid username or password.')
		# Even the correct password is refused now; unknown users get the very same message.
		response = self.client.post(reverse('login'), {'username': 'victim', 'password': 'Correct-Pass-123'})
		self.assertContains(response, 'Too many failed login attempts')
		self.assertFalse(response.wsgi_request.user.is_authenticated)
		for _ in range(11):
			response = self.client.post(reverse('login'), {'username': 'ghost', 'password': 'wrong'})
		self.assertContains(response, 'Too many failed login attempts')

	def test_login_ip_limit_applies_across_usernames(self):
		for n in range(10):
			self.client.post(reverse('login'), {'username': f'u{n}', 'password': 'wrong'}, REMOTE_ADDR='8.8.8.8')
		User.objects.create_user(username='other', password='Correct-Pass-123')
		response = self.client.post(reverse('login'), {'username': 'other', 'password': 'Correct-Pass-123'}, REMOTE_ADDR='8.8.8.8')
		self.assertContains(response, 'Too many failed login attempts')

	def test_password_reset_global_limit_works_without_public_ip(self):
		from django.core import mail
		from django.test import override_settings
		for n in range(4):
			User.objects.create_user(username=f'gl{n}', email=f'gl{n}@example.com', password='OldPass12345')
		with override_settings(PASSWORD_RESET_GLOBAL_LIMIT=3):
			for n in range(4):
				self.client.post(reverse('password_reset'), {'email': f'gl{n}@example.com'}, REMOTE_ADDR='10.2.3.4')
		self.assertEqual(len(mail.outbox), 3)

	def test_api_create_requires_matching_role(self):
		worker = User.objects.create_user(username='api-worker', password='worker-password')
		AccountProfile.objects.create(user=worker, role='worker', display_name='Worker')
		self.client.force_login(worker)
		for endpoint in ('jobs', 'internships'):
			response = self.client.post(f'/api/{endpoint}/', {'company_name': 'X'}, content_type='application/json')
			self.assertEqual(response.status_code, 403)
		company = User.objects.create_user(username='api-company', password='company-password')
		AccountProfile.objects.create(user=company, role='company', display_name='Company')
		self.client.force_login(company)
		response = self.client.post('/api/resumes/', {'name': 'X'}, content_type='application/json')
		self.assertEqual(response.status_code, 403)

	def test_oversized_image_is_rejected(self):
		from django.core.files.uploadedfile import SimpleUploadedFile
		from .validators import MAX_IMAGE_SIZE, validate_image_size
		validate_image_size(SimpleUploadedFile('ok.png', b'x' * 10))
		with self.assertRaises(ValidationError):
			validate_image_size(SimpleUploadedFile('big.png', b'x' * (MAX_IMAGE_SIZE + 1)))
		company = User.objects.create_user(username='big-company', password='company-password')
		AccountProfile.objects.create(user=company, role='company', display_name='Company')
		self.client.force_login(company)
		with patch('mainapp.validators.MAX_IMAGE_SIZE', 10):
			response = self.client.post(reverse('account_settings'), {
				'username': 'big-company',
				'email': 'company@example.com',
				'display_name': 'Company',
				'role': 'company',
				'company_photo': SimpleUploadedFile(
					'company.png',
					base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='),
					content_type='image/png',
				),
			})
		self.assertContains(response, 'Image is too large')
		company.account_profile.refresh_from_db()
		self.assertFalse(company.account_profile.company_photo)


class CountryCityTests(TestCase):
	@classmethod
	def setUpTestData(cls):
		# Names are unique and absent from the seed data (data migration), so tests do not clash with it.
		cls.country_a = Country.objects.create(name='Testland A', code='TA')
		cls.country_b = Country.objects.create(name='Testland B', code='TB')
		cls.city_a2 = City.objects.create(country=cls.country_a, name='Zeta')
		cls.city_a1 = City.objects.create(country=cls.country_a, name='Alpha')
		cls.city_b = City.objects.create(country=cls.country_b, name='Beta')

	def job_data(self, **extra):
		data = {
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
		}
		data.update(extra)
		return data

	def test_seed_data_is_loaded_and_idempotent(self):
		uzbekistan = Country.objects.get(code='UZ')
		self.assertTrue(uzbekistan.cities.filter(name='Tashkent', name_ru='Ташкент').exists())
		countries, cities = Country.objects.count(), City.objects.count()

		call_command('seed_geo', verbosity=0)

		self.assertEqual(Country.objects.count(), countries)
		self.assertEqual(City.objects.count(), cities)

	def test_cities_api_returns_cities_of_country_sorted_by_name(self):
		response = self.client.get(reverse('cities_api'), {'country': self.country_a.pk})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json(), [
			{'id': self.city_a1.pk, 'name': 'Alpha'},
			{'id': self.city_a2.pk, 'name': 'Zeta'},
		])

	def test_cities_api_without_country_or_unknown_country_returns_empty_list(self):
		self.assertEqual(self.client.get(reverse('cities_api')).json(), [])
		self.assertEqual(self.client.get(reverse('cities_api'), {'country': 999999}).json(), [])

	def test_cities_api_rejects_non_integer_country(self):
		response = self.client.get(reverse('cities_api'), {'country': 'abc'})

		self.assertEqual(response.status_code, 400)

	def test_cities_api_url_path(self):
		self.assertEqual(reverse('cities_api'), '/api/cities/')

	def test_form_city_queryset_is_empty_without_country(self):
		form = JobForm()

		self.assertEqual(form.fields['city'].queryset.count(), 0)

	def test_form_city_queryset_is_filtered_by_submitted_country(self):
		form = JobForm(self.job_data(country=self.country_a.pk))

		self.assertEqual(set(form.fields['city'].queryset), {self.city_a1, self.city_a2})

	def test_form_city_queryset_uses_instance_country_when_editing(self):
		job = Job.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
			country=self.country_b,
			city=self.city_b,
		)

		form = JobForm(instance=job)

		self.assertEqual(set(form.fields['city'].queryset), {self.city_b})
		self.assertEqual(form.initial['city'], self.city_b.pk)

	def test_form_accepts_city_of_selected_country(self):
		form = JobForm(self.job_data(country=self.country_a.pk, city=self.city_a1.pk))

		self.assertTrue(form.is_valid(), form.errors)
		job = form.save()
		self.assertEqual(job.location, 'Alpha, Testland A')

	def test_form_rejects_city_of_other_country(self):
		form = JobForm(self.job_data(country=self.country_a.pk, city=self.city_b.pk))

		self.assertFalse(form.is_valid())
		self.assertIn('city', form.errors)

	def test_form_rejects_city_without_country(self):
		form = JobForm(self.job_data(city=self.city_a1.pk))

		self.assertFalse(form.is_valid())
		self.assertIn('city', form.errors)

	def test_form_allows_empty_country_and_city(self):
		form = JobForm(self.job_data())

		self.assertTrue(form.is_valid(), form.errors)

	def test_helper_rejects_mismatch_and_missing_country(self):
		with self.assertRaises(ValidationError):
			check_city_belongs_to_country(self.country_b, self.city_a1)
		with self.assertRaises(ValidationError):
			check_city_belongs_to_country(None, self.city_a1)
		check_city_belongs_to_country(self.country_a, self.city_a1)
		check_city_belongs_to_country(None, None)

	def test_serializer_rejects_city_of_other_country(self):
		serializer = JobSerializer(data=self.job_data(country=self.country_a.pk, city=self.city_b.pk))

		self.assertFalse(serializer.is_valid())
		self.assertIn('city', serializer.errors)

	def test_serializer_accepts_matching_city_and_validates_partial_update(self):
		job = Job.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
			country=self.country_a,
			city=self.city_a1,
		)

		ok = JobSerializer(job, data={'city': self.city_a2.pk}, partial=True)
		bad = JobSerializer(job, data={'country': self.country_b.pk}, partial=True)

		self.assertTrue(ok.is_valid(), ok.errors)
		self.assertFalse(bad.is_valid())
		self.assertIn('city', bad.errors)

	def test_create_view_saves_country_and_city_and_detail_shows_location(self):
		company = User.objects.create_user(username='geo-company', password='company-password')
		AccountProfile.objects.create(user=company, role='company', display_name='Company')
		self.client.force_login(company)

		response = self.client.post(
			reverse('create_listing', args=['job']),
			self.job_data(country=self.country_a.pk, city=self.city_a1.pk),
		)

		job = Job.objects.get(owner=company)
		self.assertRedirects(response, reverse('job_detail', args=[job.pk]))
		self.assertEqual((job.country, job.city), (self.country_a, self.city_a1))
		detail = self.client.get(reverse('job_detail', args=[job.pk]))
		self.assertContains(detail, 'Alpha, Testland A')

	def test_create_page_renders_country_and_city_selects(self):
		company = User.objects.create_user(username='geo-company2', password='company-password')
		AccountProfile.objects.create(user=company, role='company', display_name='Company')
		self.client.force_login(company)

		response = self.client.get(reverse('create_listing', args=['job']))

		self.assertContains(response, 'name="country"')
		self.assertContains(response, 'name="city"')
		self.assertContains(response, 'data-cities-url="/api/cities/"')
		self.assertContains(response, 'country-city.js')

	def test_deleting_country_keeps_listing(self):
		job = Job.objects.create(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
			country=self.country_b,
			city=self.city_b,
		)

		self.country_b.delete()

		job.refresh_from_db()
		self.assertIsNone(job.country)
		self.assertIsNone(job.city)


class GeoReferenceDataTests(TestCase):
	"""Full country/city reference (migration 0021 / seed_geo): data, localization, search API, list filters."""

	@classmethod
	def setUpTestData(cls):
		cls.uz = Country.objects.get(code='UZ')
		cls.us = Country.objects.get(code='US')
		cls.tashkent = City.objects.get(country=cls.uz, name='Tashkent')

	def make_job(self, **extra):
		data = dict(
			company_name='Example Company',
			phone_number='+998901234567',
			salary=1000,
			required_experience=1,
			work_time=8,
			job_title='Developer',
			requirements_of_job='Python',
		)
		data.update(extra)
		return Job.objects.create(**data)

	def cities(self, lang='en', **params):
		response = self.client.get(reverse('cities_api'), params, headers={'accept-language': lang})
		self.assertEqual(response.status_code, 200)
		return response.json()

	# --- data ---------------------------------------------------------------------------------------------

	def test_all_countries_are_seeded_with_iso_codes_and_names_in_three_languages(self):
		self.assertGreaterEqual(Country.objects.count(), 240)
		self.assertEqual(Country.objects.filter(code__isnull=True).count(), 0)
		self.assertEqual(
			Country.objects.exclude(name_ru='').exclude(name_uz='').exclude(name_en='').count(),
			Country.objects.count(),
		)
		self.assertEqual((self.uz.name_en, self.uz.name_ru, self.uz.name_uz), ('Uzbekistan', 'Узбекистан', 'Oʻzbekiston'))
		self.assertGreater(City.objects.count(), 5000)
		self.assertGreater(self.uz.cities.count(), 100)

	def test_seed_is_idempotent_and_changes_nothing_on_second_run(self):
		countries, cities = Country.objects.count(), City.objects.count()

		result = seed_geo_data(Country, City)

		self.assertEqual(result, (0, 0, 0, 0))
		self.assertEqual((Country.objects.count(), City.objects.count()), (countries, cities))

	def test_seed_adopts_legacy_rows_without_changing_their_ids(self):
		kyrgyzstan = Country.objects.get(code='KG')
		bishkek = City.objects.get(country=kyrgyzstan, name='Bishkek')
		pks = (kyrgyzstan.pk, bishkek.pk)
		# Put the rows back into the state the first (13-country) seed left them in.
		Country.objects.filter(pk=kyrgyzstan.pk).update(name='Кыргызстан', name_en='', name_ru='', name_uz='', priority=0)
		City.objects.filter(pk=bishkek.pk).update(name='Бишкек', name_en='', name_ru='', name_uz='', geoname_id=None, population=0)
		job = self.make_job(country=kyrgyzstan, city=bishkek)

		seed_geo_data(Country, City)

		job.refresh_from_db()
		self.assertEqual((job.country_id, job.city_id), pks)
		self.assertEqual(Country.objects.get(pk=pks[0]).name, 'Kyrgyzstan')
		bishkek.refresh_from_db()
		self.assertEqual((bishkek.name, bishkek.name_ru), ('Bishkek', 'Бишкек'))
		self.assertGreater(bishkek.population, 0)
		self.assertEqual(City.objects.filter(country=kyrgyzstan, name_ru='Бишкек').count(), 1)

	def test_helpers(self):
		self.assertEqual(flag_emoji('uz'), '\U0001F1FA\U0001F1FF')
		self.assertEqual(flag_emoji(None), '')
		self.assertEqual(flag_emoji('U1'), '')
		self.assertEqual(normalize_search("  Qo'qon Köln Ёлка "), 'qoqon koln елка')
		self.assertEqual(normalize_search('Qoʻqon'), 'qoqon')

	# --- localization -------------------------------------------------------------------------------------

	def test_names_follow_the_active_language_with_english_fallback(self):
		with translation.override('ru'):
			self.assertEqual(str(self.uz), 'Узбекистан')
			self.assertEqual(self.tashkent.localized_name, 'Ташкент')
			self.assertEqual(str(Country(name='Nowhere', code='NW')), 'Nowhere')  # no Russian name -> canonical name
		with translation.override('uz'):
			self.assertEqual(str(self.uz), 'Oʻzbekiston')
			self.assertEqual(self.tashkent.localized_name, 'Toshkent')
		with translation.override('en'):
			self.assertEqual(str(self.uz), 'Uzbekistan')
			self.assertEqual(self.uz.display_name, '\U0001F1FA\U0001F1FF Uzbekistan')

	def test_localized_country_queryset_puts_featured_first_then_sorts_by_language(self):
		with translation.override('ru'):
			names = list(Country.objects.localized().values_list('name_ru', flat=True))
		self.assertEqual(names[:3], ['Узбекистан', 'Россия', 'Казахстан'])
		rest = names[13:]
		self.assertEqual(rest, sorted(rest))

	# --- cities API ---------------------------------------------------------------------------------------

	def test_cities_api_orders_by_population_and_limits(self):
		cities = self.cities(country=self.uz.pk, limit=5)

		self.assertEqual(len(cities), 5)
		self.assertEqual(cities[0], {'id': self.tashkent.pk, 'name': 'Tashkent'})
		ordered = list(
			City.objects.filter(pk__in=[c['id'] for c in cities]).order_by('-population').values_list('pk', flat=True)
		)
		self.assertEqual([c['id'] for c in cities], ordered)

	def test_cities_api_limit_is_validated_and_capped(self):
		self.assertEqual(len(self.cities(country=self.us.pk)), 50)  # default
		self.assertEqual(len(self.cities(country=self.us.pk, limit=1000)), 100)  # capped
		self.assertEqual(len(self.cities(country=self.us.pk, limit=0)), 1)
		response = self.client.get(reverse('cities_api'), {'country': self.us.pk, 'limit': 'many'})
		self.assertEqual(response.status_code, 400)

	def test_cities_api_search_is_case_accent_and_apostrophe_insensitive(self):
		self.assertEqual(self.cities(country=self.uz.pk, q='TASHK')[0]['id'], self.tashkent.pk)
		self.assertEqual(self.cities(country=self.uz.pk, q='toshkent')[0]['id'], self.tashkent.pk)
		self.assertEqual(self.cities(country=self.uz.pk, q='ташкент')[0]['id'], self.tashkent.pk)
		self.assertEqual(self.cities(country=self.uz.pk, q='ТАШКЕНТ')[0]['id'], self.tashkent.pk)
		germany = Country.objects.get(code='DE')
		koln = City.objects.get(country=germany, name='Köln')
		self.assertIn(koln.pk, [c['id'] for c in self.cities(country=germany.pk, q='koln')])
		self.assertIn(koln.pk, [c['id'] for c in self.cities(country=germany.pk, q='KÖLN')])
		qoqon = City.objects.get(country=self.uz, name_ru='Коканд')
		self.assertEqual(self.cities(country=self.uz.pk, q="qo'qon")[0]['id'], qoqon.pk)

	def test_cities_api_search_only_returns_cities_of_the_requested_country(self):
		self.assertEqual(self.cities(country=self.us.pk, q='tashkent'), [])
		self.assertEqual(self.cities(country=self.uz.pk, q='zzzzzz-nothing'), [])

	def test_cities_api_prefix_matches_come_before_other_matches(self):
		names = [c['name'] for c in self.cities(country=self.us.pk, q='san', limit=100)]

		self.assertTrue(names)
		first_other = next((i for i, n in enumerate(names) if not normalize_search(n).startswith('san')), len(names))
		self.assertTrue(all(normalize_search(n).startswith('san') for n in names[:first_other]))
		self.assertTrue(all(not normalize_search(n).startswith('san') for n in names[first_other:]))

	def test_cities_api_returns_names_in_the_request_language(self):
		self.assertEqual(self.cities(lang='ru', country=self.uz.pk, q='tashkent')[0]['name'], 'Ташкент')
		self.assertEqual(self.cities(lang='uz', country=self.uz.pk, q='tashkent')[0]['name'], 'Toshkent')
		self.assertEqual(self.cities(lang='en', country=self.uz.pk, q='tashkent')[0]['name'], 'Tashkent')

	# --- forms --------------------------------------------------------------------------------------------

	def test_city_select_renders_only_the_selected_city_but_validates_any_city_of_the_country(self):
		new_york = City.objects.get(country=self.us, name='New York City')
		other = City.objects.filter(country=self.us).exclude(pk=new_york.pk).first()
		job = self.make_job(country=self.us, city=new_york)

		html = str(JobForm(instance=job)['city'])
		self.assertEqual(html.count('<option'), 2)  # empty choice + the selected city
		self.assertIn('data-combobox="remote"', html)
		self.assertIn('data-remote-url="/api/cities/"', html)

		data = {
			'company_name': 'X', 'phone_number': '+998901234567', 'salary': 1, 'required_experience': 1, 'work_time': 8,
			'job_title': 'Dev', 'requirements_of_job': 'x', 'working_condition': 'full_time',
			'work_schedule_and_working_hours': '5/2', 'work_field': 'permament', 'status': 'qidirilyapti',
			'country': self.us.pk, 'city': other.pk,
		}
		valid = JobForm(data)
		self.assertTrue(valid.is_valid(), valid.errors)
		data['country'] = self.uz.pk
		invalid = JobForm(data)
		self.assertFalse(invalid.is_valid())
		self.assertIn('city', invalid.errors)

	def test_country_select_lists_all_countries_with_flags_and_featured_first(self):
		with translation.override('ru'):
			html = str(JobForm()['country'])
		self.assertEqual(html.count('<option'), Country.objects.count() + 1)
		self.assertIn('\U0001F1FA\U0001F1FF Узбекистан', html)
		self.assertLess(html.index('Узбекистан'), html.index('Россия'))
		self.assertLess(html.index('Россия'), html.index('Австралия'))
		self.assertIn('data-combobox="local"', html)
		self.assertIn('data-search="Uzbekistan Узбекистан Oʻzbekiston UZ"', html)  # found in any language / by ISO code
		self.assertRegex(html, r'data-search="[^"]*Соединенные Штаты[^"]* USA America США')  # common aliases

	# --- list pages ---------------------------------------------------------------------------------------

	def test_jobs_page_filters_by_country_and_city_and_shows_location_with_flag(self):
		samarkand = City.objects.get(country=self.uz, name='Samarkand')
		self.make_job(job_title='Tashkent job', country=self.uz, city=self.tashkent)
		self.make_job(job_title='Samarkand job', country=self.uz, city=samarkand)
		self.make_job(job_title='Texas job', country=self.us)
		self.make_job(job_title='Nowhere job')

		by_country = self.client.get(reverse('jobs_page'), {'country': self.uz.pk})
		self.assertContains(by_country, 'Tashkent job')
		self.assertContains(by_country, 'Samarkand job')
		self.assertNotContains(by_country, 'Texas job')
		self.assertNotContains(by_country, 'Nowhere job')

		by_city = self.client.get(reverse('jobs_page'), {'country': self.uz.pk, 'city': samarkand.pk})
		self.assertContains(by_city, 'Samarkand job')
		self.assertNotContains(by_city, 'Tashkent job')
		self.assertContains(by_city, 'class="listing-card-location"')
		self.assertContains(by_city, '\U0001F1FA\U0001F1FF Samarkand, Uzbekistan')
		self.assertContains(by_city, 'name="country"')
		self.assertContains(by_city, 'country-city.js')

		self.assertContains(self.client.get(reverse('jobs_page')), 'Texas job')

	def test_internship_and_resume_pages_filter_by_country(self):
		common = dict(company_name='C', phone_number='+998901234567', work_time=8, work_duration=4)
		Internship.objects.create(job_title='UZ intern', country=self.uz, **common)
		Internship.objects.create(job_title='US intern', country=self.us, **common)
		person = dict(surname='Person', phone_number='+998901234567', experience=1, wanted_salary=1, wanted_work_time=8)
		Resume.objects.create(name='Uzbek', email='a@example.com', country=self.uz, **person)
		Resume.objects.create(name='American', email='b@example.com', country=self.us, **person)

		internships = self.client.get(reverse('internships_page'), {'country': self.us.pk})
		self.assertContains(internships, 'US intern')
		self.assertNotContains(internships, 'UZ intern')
		resumes = self.client.get(reverse('resumes_page'), {'country': self.uz.pk})
		self.assertContains(resumes, 'Uzbek Person')
		self.assertNotContains(resumes, 'American Person')

	def test_location_filter_is_kept_in_pagination_links_with_other_filters(self):
		for index in range(25):
			self.make_job(job_title=f'Paged {index}', country=self.uz, city=self.tashkent)
		params = {'country': self.uz.pk, 'city': self.tashkent.pk, 'status': 'qidirilyapti'}

		response = self.client.get(reverse('jobs_page'), params)

		html = response.content.decode()
		link = next(part for part in html.split('<a ') if 'page=2' in part.split('>')[0])
		for expected in (f'country={self.uz.pk}', f'city={self.tashkent.pk}', 'status=qidirilyapti'):
			self.assertIn(expected, link)
		self.assertContains(self.client.get(reverse('jobs_page'), {**params, 'page': 2}), 'Paged')

	def test_filter_form_rejects_city_of_another_country(self):
		form = ListingFilterForm({'country': self.us.pk, 'city': self.tashkent.pk})

		self.assertFalse(form.is_valid())
		self.assertIn('city', form.errors)
		self.assertTrue(ListingFilterForm({'country': self.uz.pk, 'city': self.tashkent.pk}).is_valid())
		self.assertTrue(ListingFilterForm({}).is_valid())

	def test_home_page_cards_show_location(self):
		self.make_job(job_title='Home job', country=self.uz, city=self.tashkent)

		response = self.client.get(reverse('home'))

		self.assertContains(response, 'Home job')
		self.assertContains(response, '\U0001F1FA\U0001F1FF Tashkent, Uzbekistan')

	def test_list_page_query_count_does_not_grow_with_the_number_of_cards(self):
		self.make_job(job_title='N+1 first', country=self.uz, city=self.tashkent)
		before = self.count_queries(reverse('jobs_page'))
		for index in range(6):
			self.make_job(job_title=f'N+1 {index}', country=self.us)

		self.assertEqual(self.count_queries(reverse('jobs_page')), before)

	def count_queries(self, url):
		from django.db import connection
		from django.test.utils import CaptureQueriesContext

		with CaptureQueriesContext(connection) as context:
			self.client.get(url)
		return len(context)

	# --- REST API -----------------------------------------------------------------------------------------

	def test_rest_api_filters_by_country_and_city(self):
		self.make_job(job_title='API uz', country=self.uz, city=self.tashkent)
		self.make_job(job_title='API us', country=self.us)

		by_country = self.client.get('/api/jobs/', {'country': self.us.pk}).json()
		by_city = self.client.get('/api/jobs/', {'city': self.tashkent.pk}).json()

		self.assertEqual([job['job_title'] for job in by_country['results']], ['API us'])
		self.assertEqual([job['job_title'] for job in by_city['results']], ['API uz'])
