from collections.abc import Mapping

from usos_api.services.courses import CourseClassTypeDescription, CourseClassTypesIndex

from users.models import CourseClassType


def _lang_text(value: Mapping[str, str | None] | None, lang: str = "pl") -> str | None:
    if value is None:
        return None
    return value.get(lang) or value.get("en") or value.get("pl")


def _class_type_names(data: CourseClassTypeDescription) -> tuple[str, str]:
    name = data.get("name")
    return _lang_text(name, "pl") or "", _lang_text(name, "en") or ""


async def sync_class_types(class_types: CourseClassTypesIndex) -> int:
    for class_type_id, class_type_data in class_types.items():
        name_pl, name_en = _class_type_names(class_type_data)
        await CourseClassType.objects.aupdate_or_create(
            id=class_type_id,
            defaults={
                "name_pl": name_pl,
                "name_en": name_en,
            },
        )
    return len(class_types)


async def get_class_types() -> dict[str, CourseClassType]:
    return {class_type.id: class_type async for class_type in CourseClassType.objects.all()}
