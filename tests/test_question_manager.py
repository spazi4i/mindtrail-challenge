import random
import unittest
from collections import Counter

from mindtrail_demo import Athlete, LEVELS, QuestionManager


def make_question(subject: str, level: str, index: int):
    return {
        "question": f"{subject}-{level}-Q{index}",
        "answer": f"{subject}-{level}-A{index}",
        "subject": subject,
        "level": level,
    }


def make_single_subject_bank(subject: str, per_level: int):
    return {
        level: [make_question(subject, level, i) for i in range(1, per_level + 1)]
        for level in LEVELS
    }


def make_interdisciplinary_bank(subject_names, per_level: int):
    return {
        "__interdisciplinary__": True,
        "subjects": {
            subject: make_single_subject_bank(subject, per_level)
            for subject in subject_names
        },
    }


class QuestionManagerTests(unittest.TestCase):
    def setUp(self):
        random.seed(12345)

    def test_single_subject_questions_are_unique_for_same_athlete(self):
        bank = make_single_subject_bank("Italiano", per_level=3)
        manager = QuestionManager(bank)

        self.assertEqual(manager.validate_unique_questions(8), {})

        athlete = Athlete(number=1, total_runs=9, total_questions=8, question_show_seconds=5)
        extracted = []
        for question_number in range(1, 9):
            level, question, answer, subject = manager.next_question(athlete, question_number, athlete.total_questions)
            extracted.append((subject, level, question, answer))

        self.assertEqual(len(extracted), 8)
        self.assertEqual(len(extracted), len(set(extracted)))

    def test_single_subject_validation_rejects_insufficient_unique_questions(self):
        bank = make_single_subject_bank("Italiano", per_level=1)
        manager = QuestionManager(bank)

        result = manager.validate_unique_questions(8)

        self.assertEqual(
            result,
            {
                "Facile": {"required": 2, "available": 1},
                "Media": {"required": 2, "available": 1},
                "Difficile": {"required": 2, "available": 1},
                "Plus": {"required": 2, "available": 1},
            },
        )

    def test_interdisciplinary_questions_are_balanced_by_subject_and_level(self):
        bank = make_interdisciplinary_bank(
            ["Italiano", "Inglese", "Scienze", "Anatomia"],
            per_level=3,
        )
        manager = QuestionManager(bank)

        self.assertEqual(manager.validate_unique_questions(8), {})

        athlete = Athlete(number=1, total_runs=9, total_questions=8, question_show_seconds=5)
        extracted = []
        subject_counter = Counter()
        level_counter = Counter()

        for question_number in range(1, 9):
            level, question, answer, subject = manager.next_question(athlete, question_number, athlete.total_questions)
            extracted.append((subject, level, question, answer))
            subject_counter[subject] += 1
            level_counter[level] += 1

        self.assertEqual(len(extracted), len(set(extracted)))
        self.assertEqual(subject_counter, Counter({"Anatomia": 2, "Inglese": 2, "Italiano": 2, "Scienze": 2}))
        self.assertEqual(level_counter, Counter({"Facile": 2, "Media": 2, "Difficile": 2, "Plus": 2}))

    def test_interdisciplinary_validation_rejects_non_divisible_question_count(self):
        bank = make_interdisciplinary_bank(
            ["Italiano", "Inglese", "Scienze", "Anatomia"],
            per_level=3,
        )
        manager = QuestionManager(bank)

        result = manager.validate_unique_questions(6)

        self.assertIn("error", result)
        self.assertIn("multiplo di 4", result["error"])

    def test_interdisciplinary_validation_rejects_missing_capacity(self):
        bank = {
            "__interdisciplinary__": True,
            "subjects": {
                "Italiano": {
                    "Facile": [make_question("Italiano", "Facile", 1), make_question("Italiano", "Facile", 2)],
                    "Media": [make_question("Italiano", "Media", 1), make_question("Italiano", "Media", 2)],
                    "Difficile": [make_question("Italiano", "Difficile", 1), make_question("Italiano", "Difficile", 2)],
                    "Plus": [],
                },
                "Inglese": {
                    "Facile": [make_question("Inglese", "Facile", 1), make_question("Inglese", "Facile", 2)],
                    "Media": [make_question("Inglese", "Media", 1), make_question("Inglese", "Media", 2)],
                    "Difficile": [make_question("Inglese", "Difficile", 1), make_question("Inglese", "Difficile", 2)],
                    "Plus": [],
                },
                "Scienze": {
                    "Facile": [make_question("Scienze", "Facile", 1), make_question("Scienze", "Facile", 2)],
                    "Media": [make_question("Scienze", "Media", 1), make_question("Scienze", "Media", 2)],
                    "Difficile": [make_question("Scienze", "Difficile", 1), make_question("Scienze", "Difficile", 2)],
                    "Plus": [],
                },
                "Anatomia": {
                    "Facile": [make_question("Anatomia", "Facile", 1), make_question("Anatomia", "Facile", 2)],
                    "Media": [make_question("Anatomia", "Media", 1), make_question("Anatomia", "Media", 2)],
                    "Difficile": [make_question("Anatomia", "Difficile", 1), make_question("Anatomia", "Difficile", 2)],
                    "Plus": [make_question("Anatomia", "Plus", 1)],
                },
            },
        }
        manager = QuestionManager(bank)

        result = manager.validate_unique_questions(8)

        self.assertIn("error", result)
        self.assertIn("domande uniche", result["error"])


if __name__ == "__main__":
    unittest.main()
