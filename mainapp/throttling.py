from rest_framework.throttling import UserRateThrottle

class JobThrottle(UserRateThrottle):
    rate = '50/minute'

class ResumeThrottle(UserRateThrottle):
    rate = '50/minute'

class InternshipThrottle(UserRateThrottle):
    rate = '50/minute'

class CityThrottle(UserRateThrottle):
    # Own scope: otherwise the cache key is shared with the other 'user'-scoped throttles.
    scope = 'cities'
    # Typing in the city combobox sends a (debounced) request per pause, so this is higher than the listings.
    rate = '300/minute'