@echo off
REM run_test.bat - версия для Windows
setlocal EnableDelayedExpansion

REM Установка имени лог-файла с датой и временем
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "YYYY=%dt:~0,4%"
set "MM=%dt:~4,2%"
set "DD=%dt:~6,2%"
set "HH=%dt:~8,2%"
set "Min=%dt:~10,2%"
set "Sec=%dt:~12,2%"
set LOGFILE=run_test_%YYYY%%MM%%DD%_%HH%%Min%%Sec%.log

echo ========================================
echo Requirements Analyzer Test Runner (Refactored)
echo Log file: %LOGFILE%
echo ========================================

REM Проверяем наличие виртуального окружения
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at venv\Scripts\activate.bat
    echo Please create virtual environment first:
    echo   python -m venv venv
    echo   venv\Scripts\activate.bat
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

REM Активируем виртуальное окружение
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Устанавливаем переменную окружения для тестов
set TESTING=true

REM Выводим версию Python для отладки
echo Python version:
python --version

REM Выбор режима запуска на основе параметра
if "%1"=="quick" (
    echo Running quick tests...
    python run_tests.py quick > "%LOGFILE%" 2>&1
    set TEST_RESULT=!ERRORLEVEL!
) else if "%1"=="legacy" (
    echo Running legacy compatibility tests...
    python run_tests.py legacy > "%LOGFILE%" 2>&1
    set TEST_RESULT=!ERRORLEVEL!
) else if "%1"=="filters" (
    echo Running content filtering tests...
    python run_tests.py filters > "%LOGFILE%" 2>&1
    set TEST_RESULT=!ERRORLEVEL!
) else if "%1"=="" (
    echo Running all tests with coverage...
    python run_tests.py > "%LOGFILE%" 2>&1
    set TEST_RESULT=!ERRORLEVEL!
) else (
    echo Running specific tests: %1
    python run_tests.py %1 > "%LOGFILE%" 2>&1
    set TEST_RESULT=!ERRORLEVEL!
)

REM Показываем последние строки лога
echo.
echo ========== Last 10 lines of log ==========
powershell "Get-Content '%LOGFILE%' | Select-Object -Last 10"
echo ==========================================

REM Проверяем результат
if !TEST_RESULT! equ 0 (
    echo.
    echo ============================================
    echo OK TESTS PASSED SUCCESSFULLY!
    echo ============================================
    echo Full log saved to: %LOGFILE%
    if exist "htmlcov\index.html" (
        echo Coverage report: htmlcov\index.html
        echo To view: start htmlcov\index.html
    )
) else (
    echo.
    echo ============================================
    echo !!! TESTS FAILED!
    echo ============================================
    echo Check the log file: %LOGFILE%
    echo.
    echo Quick troubleshooting commands:
    echo   run_test.bat quick     - Run fast tests only
    echo   run_test.bat legacy    - Run legacy compatibility tests
    echo   run_test.bat filters   - Run content filtering tests
    echo   run_test.bat test_routes - Run specific test module
    echo.
    echo View full log:
    echo   type %LOGFILE%
)

echo.
echo Press any key to exit...
pause >nul