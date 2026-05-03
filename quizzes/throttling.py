from rest_framework.throttling import UserRateThrottle


class CopyQuizThrottle(UserRateThrottle):
    rate = "5/m"


class QuizStatsThrottle(UserRateThrottle):
    """
    Stats endpoints can run several aggregations per call (basic + first-answer
    subquery + optional per-question / per-session breakdown). 60/min per user
    is generous for interactive dashboards but caps abusive polling.
    """

    scope = "quiz_stats"
    rate = "60/m"
