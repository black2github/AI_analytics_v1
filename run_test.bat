@echo off
REM ��������� ����� ���-����� � ����� � ��������
set LOGFILE=run_test.log

REM ������� ������� ���� (���� �����)
del "%LOGFILE%" >nul 2>&1

REM ���������� ����������� ���������
call venv\Scripts\activate.bat >> "%LOGFILE%" 2>&1

REM ������ FastAPI ����� uvicorn � ������� � ���
REM echo ������ uvicorn... >> "%LOGFILE%"
REM uvicorn app.main:app --host 127.0.0.1 --port 8000 >> "%LOGFILE%" 2>&1

REM # ��������� ������������ ��� ������������
REM pip install -r requirements-test.txt

REM # ������ ���� ������
python run_tests.py >> "%LOGFILE%" 2>&1

REM # ������ ���������� ������ ������
REM python run_tests.py test_history_cleaner.py
REM python run_tests.py test_rag_pipeline.py

REM # ������ ������ � ���������
REM pytest tests/ --cov=app --cov-report=html

REM # ������ ������ ������� ������
REM pytest tests/ -m "not slow"

REM # ������ � verbose ������
REM pytest tests/ -v -s