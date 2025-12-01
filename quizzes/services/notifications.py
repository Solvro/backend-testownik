from django.core.mail import send_mail, send_mass_mail
from django.template.loader import render_to_string
from django.conf import settings

def should_send_notification(user):
    if not user.email:
        return False
    return True

def notify_quiz_shared_to_users(quiz,user):
    if not should_send_notification(user):
        return
    subject = f'Quiz "{quiz.title}" został ci udostępniony'
    message = render_to_string('emails/quiz_shared.html', {
        'user': user,
        'quiz': quiz,
    })
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=message,
        fail_silently=True,
    )

def notify_quiz_shared_to_groups(quiz, group):
    users_to_notify = [
        user for user in group.members.all()
        if should_send_notification(user)
    ]

    messages = []
    for user in users_to_notify:
        subject = f'Quiz "{quiz.title}" został ci udostępniony'
        message = render_to_string('emails/quiz_shared.html', {
        'user': user,
        'quiz': quiz,
    })
        messages.append((subject, message, settings.DEFAULT_FROM_EMAIL, [user.email]))
    if messages:
        send_mass_mail(messages, fail_silently=True)