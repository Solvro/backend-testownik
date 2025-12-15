from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.core.mail.message import EmailMultiAlternatives
from django.template.loader import render_to_string


def should_send_notification(user):
    if not user.email:
        return False
    try:
        return user.settings.notify_quiz_shared
    except user._meta.model.settings.RelatedObjectDoesNotExist:
        return True # domyślnie True jeśli brak ustawień (tak jak w modelu user)


def notify_quiz_shared_to_users(quiz, user):
    if not should_send_notification(user):
        return
    subject = f'Quiz "{quiz.title}" został ci udostępniony'
    text_message = render_to_string('emails/quiz_shared.txt', {
        'user': user,
        'quiz': quiz,
    })
    html_message = render_to_string('emails/quiz_shared.html', {
        'user': user,
        'quiz': quiz,
    })
    send_mail(
        subject=subject,
        message=text_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=html_message,
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

        text_message = render_to_string('emails/quiz_shared.txt', {
            'user': user,
            'quiz': quiz,
        })
        html_message = render_to_string('emails/quiz_shared.html', {
            'user': user,
            'quiz': quiz,
        })
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_message, 'text/html')
        messages.append(email)
    if messages:
        connection = get_connection(fail_silently=True)
        connection.send_messages(messages)