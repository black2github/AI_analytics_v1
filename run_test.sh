# ��������� ������������ ��� ������������
pip install -r requirements-test.txt

# ������ ���� ������
python run_tests.py

# ������ ���������� ������ ������
python run_tests.py test_history_cleaner.py
python run_tests.py test_rag_pipeline.py

# ������ ������ � ���������
pytest tests/ --cov=app --cov-report=html

# ������ ������ ������� ������
pytest tests/ -m "not slow"

# ������ � verbose ������
pytest tests/ -v -s