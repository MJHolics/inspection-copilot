# 검사 코파일럿 데모/서빙 컨테이너. 코어 의존만 설치해 경량 유지(벡터·Vision은 선택).
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# gradio 데모(HF Spaces·Cloud Run 공통). FastAPI 서빙을 원하면 아래 CMD로 교체:
#   CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "7860"]
EXPOSE 7860
CMD ["python", "demo.py"]
