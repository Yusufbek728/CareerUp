from django.core.management.base import BaseCommand

from mainapp.models import Internship, Job


class Command(BaseCommand):
    help = 'Create demo jobs and internships for the local site.'

    def handle(self, *args, **options):
        jobs = [
            ('Frontend Developer', 'Northstar Labs', 1800, 2),
            ('Backend Python Developer', 'Orbit Systems', 2200, 3),
            ('Product Designer', 'Mosaic Studio', 1500, 1),
            ('QA Automation Engineer', 'Brightline Tech', 1700, 2),
            ('Data Analyst', 'Vertex Commerce', 1600, 1),
            ('Mobile Flutter Developer', 'Pulse Mobile', 2100, 2),
            ('Content Strategist', 'Signal House', 1200, 1),
            ('DevOps Engineer', 'Cloud Harbor', 2400, 3),
            ('Customer Success Manager', 'Lumen Services', 1100, 2),
            ('HR Business Partner', 'Peoplewise', 1400, 3),
            ('Financial Analyst', 'Summit Group', 1550, 2),
            ('Technical Writer', 'Open Atlas', 1000, 1),
        ]
        internships = [
            ('Frontend Development Intern', 'Northstar Labs', 12),
            ('Python Development Intern', 'Orbit Systems', 16),
            ('UX Research Intern', 'Mosaic Studio', 10),
            ('QA Testing Intern', 'Brightline Tech', 12),
            ('Business Analytics Intern', 'Vertex Commerce', 14),
            ('Flutter Development Intern', 'Pulse Mobile', 16),
            ('Social Media Intern', 'Signal House', 8),
            ('Cloud Engineering Intern', 'Cloud Harbor', 16),
            ('Customer Support Intern', 'Lumen Services', 10),
            ('Recruiting Intern', 'Peoplewise', 12),
            ('Accounting Intern', 'Summit Group', 14),
            ('Technical Writing Intern', 'Open Atlas', 10),
        ]

        for index, (title, company, salary, experience) in enumerate(jobs, start=1):
            job, _ = Job.objects.get_or_create(
                job_title=title,
                company_name=company,
                defaults={
                    'phone_number': '+998901234567',
                    'salary': salary,
                    'required_experience': experience,
                    'work_time': 8,
                    'requirements_of_job': 'Strong communication, ownership and a growth mindset.',
                    'working_condition': 'full_time',
                    'work_schedule_and_working_hours': '5/2',
                    'work_field': 'permament',
                    'status': 'qidirilyapti',
                },
            )
            self._set_demo_photo(job, index)

        for index, (title, company, duration) in enumerate(internships, start=13):
            internship, _ = Internship.objects.get_or_create(
                job_title=title,
                company_name=company,
                defaults={
                    'phone_number': '+998901234567',
                    'work_time': 6,
                    'work_duration': duration,
                    'working_condition': 'part_time',
                    'work_schedule_and_working_hours': '5/2',
                    'work_field': 'temporary',
                    'status': 'qidirilyapti',
                },
            )
            self._set_demo_photo(internship, index)

        self.stdout.write(self.style.SUCCESS(
            f'Created or kept {len(jobs)} jobs and {len(internships)} internships.'
        ))

    @staticmethod
    def _set_demo_photo(listing, index):
        photo_name = f'work_photos/demo-work-{index:02d}.png'
        if listing.work_photo.name != photo_name:
            listing.work_photo.name = photo_name
            listing.save(update_fields=['work_photo'])