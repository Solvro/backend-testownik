from django.db import router
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.operations.base import Operation


class AlterOAuthApplicationClientIdLength(Operation):
    reduces_to_sql = True
    reversible = False

    def state_forwards(self, app_label, state):
        field = state.models[("oauth2_provider", "application")].fields["client_id"].clone()
        field.max_length = 2048
        state.alter_field(
            "oauth2_provider",
            "application",
            "client_id",
            field,
            preserve_default=True,
        )

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        old_model = from_state.apps.get_model("oauth2_provider", "Application")
        new_model = to_state.apps.get_model("oauth2_provider", "Application")
        if router.allow_migrate_model(schema_editor.connection.alias, new_model):
            old_field = old_model._meta.get_field("client_id")
            new_field = new_model._meta.get_field("client_id")
            schema_editor.alter_field(old_model, old_field, new_field)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        raise IrreversibleError(
            "Cannot safely shrink Application.client_id back to 255 characters without losing data."
        )

    def describe(self):
        return "Expand OAuth application client ID length"
