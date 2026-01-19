from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from quizzes.models import Quiz


class QuizMaxReoccurrencesTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        """Dane testowe dla całej klasy"""
        User = get_user_model()
        cls.maintainer = User.objects.create(
            email='test@example.com',
        )
        cls.maintainer.set_password('testpass123')
        cls.maintainer.save()

    def test_max_reoccurrences_positive_value(self):
        """Test: max_reoccurrences akceptuje wartości dodatnie"""
        quiz = Quiz.objects.create(
            max_reoccurrences=5,
            maintainer=self.maintainer
        )
        self.assertEqual(quiz.max_reoccurrences, 5)

    def test_max_reoccurrences_zero_value(self):
        """Test: max_reoccurrences akceptuje zero"""
        quiz = Quiz.objects.create(
            max_reoccurrences=0,
            maintainer=self.maintainer
        )
        self.assertEqual(quiz.max_reoccurrences, 0)

    def test_max_reoccurrences_negative_value(self):
        """Test: max_reoccurrences odrzuca wartości ujemne"""
        quiz = Quiz(
            max_reoccurrences=-1,
            maintainer=self.maintainer
        )
        with self.assertRaises((ValidationError, IntegrityError)):
            quiz.full_clean()  # Walidacja na poziomie modelu
            quiz.save()

    def test_max_reoccurrences_large_value(self):
        """Test: max_reoccurrences akceptuje duże liczby"""
        quiz = Quiz.objects.create(
            max_reoccurrences=999999,
            maintainer=self.maintainer
        )
        self.assertEqual(quiz.max_reoccurrences, 999999)

    def test_max_reoccurrences_update(self):
        """Test: aktualizacja wartości max_reoccurrences"""
        quiz = Quiz.objects.create(
            max_reoccurrences=5,
            maintainer=self.maintainer
        )
        quiz.max_reoccurrences = 10
        quiz.save()
        quiz.refresh_from_db()
        self.assertEqual(quiz.max_reoccurrences, 10)

    def test_max_reoccurrences_type_integer(self):
        """Test: max_reoccurrences jest typu int"""
        quiz = Quiz.objects.create(
            max_reoccurrences=5,
            maintainer=self.maintainer
        )
        self.assertIsInstance(quiz.max_reoccurrences, int)

    def test_max_reoccurrences_type_string_rejected(self):
        """Test: max_reoccurrences odrzuca stringi"""
        with self.assertRaises((ValueError, ValidationError, TypeError)):
            Quiz.objects.create(
                max_reoccurrences="text",
                maintainer=self.maintainer
            )

    def test_max_reoccurrences_none_value(self):
        """Test: max_reoccurrences odrzuca None jeśli pole wymagane"""
        field = Quiz._meta.get_field('max_reoccurrences')
        if not field.null:
            with self.assertRaises(IntegrityError):
                Quiz.objects.create(
                    max_reoccurrences=None,
                    maintainer=self.maintainer
                )

    def test_max_reoccurrences_default_value(self):
        """Test: sprawdź domyślną wartość max_reoccurrences"""
        field = Quiz._meta.get_field('max_reoccurrences')
        if field.has_default():
            quiz = Quiz(maintainer=self.maintainer)
            self.assertIsNotNone(quiz.max_reoccurrences)
            self.assertEqual(quiz.max_reoccurrences, field.default)

    def test_max_reoccurrences_field_type(self):
        """Test: weryfikacja typu pola w modelu"""
        field = Quiz._meta.get_field('max_reoccurrences')
        from django.db.models import IntegerField, PositiveIntegerField
        self.assertIsInstance(field, (IntegerField, PositiveIntegerField))

    def test_max_reoccurrences_queryset_filter(self):
        """Test: filtrowanie po max_reoccurrences"""
        Quiz.objects.create(max_reoccurrences=5, maintainer=self.maintainer)
        Quiz.objects.create(max_reoccurrences=10, maintainer=self.maintainer)
        Quiz.objects.create(max_reoccurrences=15, maintainer=self.maintainer)

        quizzes = Quiz.objects.filter(max_reoccurrences__gte=10)
        self.assertEqual(quizzes.count(), 2)

    def test_max_reoccurrences_queryset_ordering(self):
        """Test: sortowanie po max_reoccurrences"""
        Quiz.objects.create(max_reoccurrences=15, maintainer=self.maintainer)
        Quiz.objects.create(max_reoccurrences=5, maintainer=self.maintainer)
        Quiz.objects.create(max_reoccurrences=10, maintainer=self.maintainer)

        quizzes = Quiz.objects.order_by('max_reoccurrences')
        values = [q.max_reoccurrences for q in quizzes]
        self.assertEqual(values, [5, 10, 15])

    def test_max_reoccurrences_boundary_values(self):
        """Test: wartości graniczne dla PositiveIntegerField"""
        # Maksymalna wartość dla IntegerField (2^31 - 1)
        max_int = 2147483647
        quiz = Quiz.objects.create(
            max_reoccurrences=max_int,
            maintainer=self.maintainer
        )
        self.assertEqual(quiz.max_reoccurrences, max_int)

    def test_max_reoccurrences_type_float_conversion(self):
        """Test: max_reoccurrences z float - sprawdzanie rzeczywistego zachowania"""
        quiz = Quiz.objects.create(
            max_reoccurrences=5.7,
            maintainer=self.maintainer
        )
        # Sprawdzamy czy wartość została zapisana
        quiz.refresh_from_db()
        self.assertIn(quiz.max_reoccurrences, [5, 5.7, 6])
        self.assertTrue(isinstance(quiz.max_reoccurrences, (int, float)))
