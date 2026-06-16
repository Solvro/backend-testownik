from django.tasks import task


@task(queue_name="images")
def sync_user_photo_task(user_id, url: str):
    """Download + process a user's profile photo off the request thread.

    Enqueued from the OAuth login callback so logins are not blocked by the
    third-party avatar/photo service. Arguments are serialized by id (not the
    ORM instance) so the worker always reads a committed row.
    """
    from users.models import User
    from users.views.oauth import _sync_process_and_save_photo

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return

    _sync_process_and_save_photo(user, url)
