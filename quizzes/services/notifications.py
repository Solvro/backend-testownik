from django.core.mail import (
    send_mail,
    get_connection,
)
from django.core.mail.message import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings

def should_send_notification(user):
    if not user.email:
        return False
    return True

def notify_quiz_shared_to_users(quiz, user):
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
        html_message = render_to_string('emails/quiz_shared.html', {
            'user': user,
            'quiz': quiz,
        })
        email = EmailMultiAlternatives(
            subject=subject,
            body=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_message, 'text/html')
        messages.append(email)
    if messages:
        connection = get_connection(fail_silently=True)
        connection.send_messages(messages)