from rest_framework.throttling import UserRateThrottle

class JobThrottle(UserRateThrottle):
    rate = '50/minute'

class ResumeThrottle(UserRateThrottle):
    rate = '50/minute'

class InternshipThrottle(UserRateThrottle):
    rate = '50/minute'