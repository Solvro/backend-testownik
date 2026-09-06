from decimal import Decimal

from django.db import migrations

ACCOUNT_TYPES = ("guest", "email", "student", "lecturer")
ACCOUNT_LIMITS = {
    "basic": ("50000", "250000"),
    "silver": ("150000", "750000"),
    "gold": ("500000", "2500000"),
}
AI_MODELS = {
    "gpt-5.6-luna": ("GPT-5.6 Luna", "openai", "basic", "0.2", "1.2", "0.02"),
    "gpt-5.6-terra": ("GPT-5.6 Terra", "openai", "basic", "2", "12", "0.2"),
    "gpt-5.6-sol": ("GPT-5.6 Sol", "openai", "gold", "4", "20", "0.4"),
    "grok-4.6": ("Grok 4.6", "xai", "silver", "2", "6", "0.5"),
    "claude-fable-5": ("Claude Fable 5", "anthropic", "gold", "10", "50", "1"),
    "claude-opus-5": ("Claude Opus 5", "anthropic", "gold", "5", "25", "0.5"),
    "claude-sonnet-5": ("Claude Sonnet 5", "anthropic", "gold", "2", "10", "0.2"),
    "claude-haiku-4-5": ("Claude Haiku 4.5", "anthropic", "gold", "1", "5", "0.1"),
}


def seed_ai_configuration(apps, schema_editor):
    ai_model = apps.get_model("ai", "AIModel")
    account_limit = apps.get_model("ai", "AIAccountLimit")
    usage_settings = apps.get_model("ai", "AIUsageSettings")

    for model, (
        label,
        provider,
        minimum_account_level,
        input_weight,
        output_weight,
        cached_weight,
    ) in AI_MODELS.items():
        ai_model.objects.update_or_create(
            model=model,
            defaults={
                "label": label,
                "provider": provider,
                "minimum_account_level": minimum_account_level,
                "input_weight": Decimal(input_weight),
                "output_weight": Decimal(output_weight),
                "cached_weight": Decimal(cached_weight),
                "active": True,
            },
        )

    for account_type in ACCOUNT_TYPES:
        for account_level, (credits_session, credits_weekly) in ACCOUNT_LIMITS.items():
            account_limit.objects.update_or_create(
                account_type=account_type,
                account_level=account_level,
                defaults={
                    "credits_session": int("0" if account_type == "guest" else credits_session),
                    "credits_weekly": int("0" if account_type == "guest" else credits_weekly),
                },
            )

    usage_settings.objects.update_or_create(
        pk=1,
        defaults={
            "limits_enabled": False,
            "grace_buffer_credits": Decimal("2000"),
            "staff_bypass_limits": True,
            "default_model_id": "gpt-5.6-luna",
            "fallback_model_id": "gpt-5.6-luna",
            "fallback_throttle_seconds": 15,
            "fallback_max_output_tokens": 500,
            "limits_reset_at": None,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0001_initial"),
    ]

    # Seeded models can be referenced by usage history through protected foreign
    # keys. Reversing this migration must not delete that history; rolling the app
    # back to zero removes the schema in 0001 immediately afterwards anyway.
    operations = [migrations.RunPython(seed_ai_configuration, migrations.RunPython.noop)]
