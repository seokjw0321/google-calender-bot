from flask import Flask, request, jsonify
from openai import AzureOpenAI
import os
import json
import base64
import traceback # 에러 위치 추적용
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta  # <--- 이거 꼭 추가하세요!

app = Flask(__name__)

# --- 설정 확인 (디버깅용) ---
# 키가 제대로 들어왔는지 확인 (보안상 앞 3글자만 로그에 찍음)
AZURE_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
print(f"Azure Key Loaded: {AZURE_KEY[:3]}***") 

client = AzureOpenAI(
    api_key=AZURE_KEY,
    api_version="2024-02-15-preview",
    azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT")
)

DEPLOYMENT_NAME = os.environ.get("AZURE_DEPLOYMENT_NAME")
GOOGLE_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")

def add_to_calendar(data):
    if not GOOGLE_JSON:
        raise Exception("구글 인증 파일(GOOGLE_CREDENTIALS_JSON)이 환경변수에 없습니다!")
        
    creds_dict = json.loads(GOOGLE_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=['https://www.googleapis.com/auth/calendar']
    )
    service = build('calendar', 'v3', credentials=creds)
    
    # --- [수정된 부분: 날짜 안전장치] ---
    start_str = data['start_time']
    end_str = data.get('end_time', '')

    # 종료 시간이 비어있으면, 시작 시간 + 1시간으로 자동 설정
    if not end_str:
        # 문자열을 날짜 객체로 변환 (ISO 포맷)
        start_dt = datetime.fromisoformat(start_str)
        end_dt = start_dt + timedelta(hours=1)
        end_str = end_dt.isoformat()
    # ----------------------------------

    event = {
        'summary': data.get('summary', 'AI 일정'),
        'location': data.get('location', ''),
        'description': data.get('description', ''),
        'start': {'dateTime': start_str, 'timeZone': 'Asia/Seoul'},
        'end': {'dateTime': end_str, 'timeZone': 'Asia/Seoul'},
    }
    
    # 본인 이메일이 맞는지 다시 한번 확인하세요!
    result = service.events().insert(calendarId='rhdtka21@gmail.com', body=event).execute()
    return result.get('htmlLink')
    
# 어떤 주소로 들어오든 다 받게 설정
@app.route('/api', methods=['POST'])
@app.route('/api/index', methods=['POST'])
@app.route('/api/analyze', methods=['POST'])
def analyze():
    try:
        # 1. 파일 데이터 읽기 (Raw Data 방식)
        raw_data = request.data
        
        if not raw_data:
            # 데이터가 없으면 혹시 Form으로 보냈는지 확인
            if 'file' in request.files:
                raw_data = request.files['file'].read()
            else:
                return jsonify({"error": "이미지가 도착하지 않았습니다. 단축어 설정을 확인하세요."}), 400

        print(f"이미지 수신 완료. 크기: {len(raw_data)} bytes")

        # 2. Azure 전송 준비 (Base64 변환)
        base64_image = base64.b64encode(raw_data).decode('utf-8')

        # 3. Azure GPT-4o 분석
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {
                    "role": "system", 
                    "content": "일정 관리 비서야. 이미지에서 일정 정보를 추출해. 반드시 JSON 포맷(summary, location, description, start_time, end_time)으로 답해. 날짜는 ISO8601(YYYY-MM-DDTHH:MM:SS) 형식으로. 없는 내용은 빈카드로 둬."
                },
                {"role": "user", "content": [
                    {"type": "text", "text": "일정 등록해줘"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            response_format={"type": "json_object"},
            max_tokens=500
        )
        
        gpt_result = response.choices[0].message.content
        print(f"GPT 응답: {gpt_result}")
        event_data = json.loads(gpt_result)

        # 4. 캘린더 등록
        link = add_to_calendar(event_data)
        
        return jsonify({"message": "성공!", "link": link})

    except Exception as e:
        # 에러가 나면 폰 화면에 에러 내용을 그대로 보여줌 (★중요)
        error_msg = traceback.format_exc()
        print(f"에러 발생: {error_msg}")
        return jsonify({"error": "서버 내부 오류", "details": str(e), "trace": error_msg}), 500
