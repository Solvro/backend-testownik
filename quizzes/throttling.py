from rest_framework.throttling import UserRateThrottle


class CopyQuizThrottle(UserRateThrottle):
    rate = "5/m"
