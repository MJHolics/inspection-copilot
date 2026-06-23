# 배포 가이드

## 로컬 실행

```bash
pip install -r requirements.txt
python demo.py                                   # gradio 데모 → http://localhost:7860
uvicorn app.server:app --host 0.0.0.0 --port 8000  # FastAPI 서빙(/health /inspect /eval)
```

LLM 키가 있으면 Analytics가 실제 SQL을 생성·실행한다(없어도 Knowledge·Report·라우팅·트레이싱은 동작):

```bash
export GEMINI_API_KEY=...   # 무료: https://aistudio.google.com/app/apikey
```

## Hugging Face Spaces (gradio SDK, 무료 — 권장)

1. HF에서 **New Space → SDK: Gradio** 생성.
2. 이 레포를 Space에 push(또는 파일 업로드). 진입점은 `demo.py`.
3. Space의 **README.md** 맨 위에 아래 프런트매터를 넣는다(GitHub README와 별개):

   ```yaml
   ---
   title: Inspection Copilot
   emoji: 🔎
   colorFrom: blue
   colorTo: indigo
   sdk: gradio
   app_file: demo.py
   pinned: false
   ---
   ```

4. Space **Settings → Secrets**에 `GEMINI_API_KEY`를 등록(Analytics 실행용, 선택).
5. 빌드가 끝나면 라이브 URL이 생성된다 → README/이력서에 링크.

> `requirements.txt`는 코어 의존만 담아 빌드를 가볍게 했다(Vision/벡터 검색 의존은 주석 처리 —
> 해당 페이즈에서 활성화).

## Docker / Cloud Run

```bash
docker build -t inspection-copilot .
docker run -p 7860:7860 -e GEMINI_API_KEY=$GEMINI_API_KEY inspection-copilot
```

Cloud Run 등에 올리면 `app.server:app`(FastAPI)로 CMD를 바꿔 JSON API로 서빙할 수도 있다.
