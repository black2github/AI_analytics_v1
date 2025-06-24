#!/usr/bin/env python3
# run_tests.py - версия для Windows без эмодзи

import subprocess
import sys
import os


def setup_test_environment():
    """Настройка тестового окружения"""
    print("Setting up test environment...")

    # Устанавливаем переменную окружения для тестов
    os.environ['TESTING'] = 'true'

    # Проверяем наличие pytest-asyncio
    try:
        import pytest_asyncio
        print("OK: pytest-asyncio is available")
    except ImportError:
        print("ERROR: pytest-asyncio not found. Installing...")
        result = subprocess.run([
            "python", "-m", "pip", "install", "-r", "requirements-test.txt"
        ], capture_output=True, text=True)

        if result.returncode != 0:
            print(f"ERROR: Failed to install test requirements: {result.stderr}")
            return False
        print("OK: Test requirements installed successfully")

    return True


def run_tests():
    """Запуск всех тестов с различными опциями"""

    print("Running Requirements Analyzer Tests (Refactored Architecture)")
    print("=" * 60)

    # Настройка тестового окружения
    if not setup_test_environment():
        print("ERROR: Failed to setup test environment!")
        return False

    # Базовые тесты
    print("\nRunning unit tests...")
    result = subprocess.run([
        "python", "-m", "pytest",
        "tests/",
        "-v",
        "--tb=short",
        "--cov=app",
        "--cov-report=term-missing",
        "--asyncio-mode=auto",
        "--disable-warnings"
    ], text=True)

    if result.returncode != 0:
        print("ERROR: Unit tests failed!")
        print("\nRunning failed tests in verbose mode...")

        # Повторный запуск только упавших тестов для диагностики
        subprocess.run([
            "python", "-m", "pytest",
            "tests/",
            "--lf",  # last-failed
            "-v",
            "-s",
            "--tb=long",
            "--asyncio-mode=auto"
        ])
        return False

    print("SUCCESS: All tests passed!")

    # Генерация HTML отчета
    print("\nGenerating coverage report...")
    subprocess.run([
        "python", "-m", "pytest",
        "tests/",
        "--cov=app",
        "--cov-report=html:htmlcov",
        "--asyncio-mode=auto",
        "--disable-warnings"
    ])

    print("OK: Coverage report generated in htmlcov/index.html")
    return True


def run_specific_tests(test_pattern):
    """Запуск конкретных тестов"""
    print(f"Running tests matching: {test_pattern}")

    # Настройка тестового окружения
    if not setup_test_environment():
        return False

    result = subprocess.run([
        "python", "-m", "pytest",
        f"tests/{test_pattern}",
        "-v",
        "--asyncio-mode=auto",
        "--tb=short"
    ])
    return result.returncode == 0


def run_quick_tests():
    """Запуск быстрых тестов без coverage"""
    print("Running quick tests (no coverage)...")

    if not setup_test_environment():
        return False

    result = subprocess.run([
        "python", "-m", "pytest",
        "tests/",
        "-v",
        "--tb=short",
        "--asyncio-mode=auto",
        "--disable-warnings",
        "--continue-on-collection-errors"  # Продолжаем даже при ошибках сборки
    ])
    return result.returncode == 0


def run_legacy_compatibility_tests():
    """Запуск тестов совместимости с legacy кодом"""
    print("Running legacy compatibility tests...")

    if not setup_test_environment():
        return False

    # Запускаем основные тесты, которые должны работать после рефакторинга
    test_files = [
        "test_routes/",
        "test_confluence_loader.py",
        "test_filter_fragments.py",
        "test_history_cleaner.py",
        "test_jira_loader.py"
    ]

    result = subprocess.run([
                                "python", "-m", "pytest"
                            ] + [f"tests/{tf}" for tf in test_files] + [
                                "-v",
                                "--asyncio-mode=auto"
                            ])
    return result.returncode == 0


def run_content_filtering_tests():
    """Запуск тестов фильтрации контента"""
    print("Running content filtering tests...")

    if not setup_test_environment():
        return False

    filter_tests = [
        "test_filter_fragments.py",
        "test_approved_fragments_spacing.py",
        "test_link_spacing.py",
        "test_spacing_fixes.py",
        "test_table_lists.py",
        "test_headers_in_tables.py",
        "test_mixed_content_in_tables.py",
        "test_nested_table_lists.py",
        "test_regression.py"
    ]

    result = subprocess.run([
                                "python", "-m", "pytest"
                            ] + [f"tests/{tf}" for tf in filter_tests] + [
                                "-v",
                                "--asyncio-mode=auto"
                            ])
    return result.returncode == 0


def run_working_tests():
    """Запуск только заведомо работающих тестов"""
    print("Running only working tests (no RAG pipeline)...")

    if not setup_test_environment():
        return False

    working_tests = [
        "test_filter_fragments.py",
        "test_approved_fragments_spacing.py",
        "test_link_spacing.py",
        "test_spacing_fixes.py",
        "test_table_lists.py",
        "test_headers_in_tables.py",
        "test_mixed_content_in_tables.py",
        "test_nested_table_lists.py",
        "test_regression.py",
        "test_history_cleaner.py",
        "test_entity_extraction.py"
    ]

    result = subprocess.run([
                                "python", "-m", "pytest"
                            ] + [f"tests/{tf}" for tf in working_tests] + [
                                "-v",
                                "--asyncio-mode=auto"
                            ])
    return result.returncode == 0


if __name__ == "__main__":
    success = False

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "quick":
            success = run_quick_tests()
        elif command == "legacy":
            success = run_legacy_compatibility_tests()
        elif command == "filters":
            success = run_content_filtering_tests()
        elif command == "working":
            success = run_working_tests()
        elif command.endswith('.py'):
            success = run_specific_tests(command)
        else:
            success = run_specific_tests(command)
    else:
        success = run_tests()

    print("\n" + "=" * 60)
    if success:
        print("SUCCESS: All tests completed successfully!")
    else:
        print("FAILED: Some tests failed. Check the output above.")

    sys.exit(0 if success else 1)