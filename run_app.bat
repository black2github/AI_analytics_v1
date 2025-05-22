@echo off
REM ��������� ����� ���-����� � ����� � ��������
set LOGFILE=run_app.log

REM ������� ������� ���� (���� �����)
del "%LOGFILE%" >nul 2>&1

REM ���������� ����������� ���������
call venv\Scripts\activate.bat >> "%LOGFILE%" 2>&1

REM ������������� ���������� ��������� PYTHONPATH
set PYTHONPATH=app

REM ������ FastAPI ����� uvicorn � ������� � ���
echo ������ uvicorn... >> "%LOGFILE%"
uvicorn app.main:app --host 127.0.0.1 --port 8000 >> "%LOGFILE%" 2>&1

REM ���������� � �����
echo ���������. ������� ����� ������� ��� ������... >> "%LOGFILE%"
pause
