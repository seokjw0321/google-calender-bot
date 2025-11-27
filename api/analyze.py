from flask import Flask, request, jsonify
from openai import AzureOpenAI
import os
import json
import base64
import traceback
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone

app = Flask(__name__)

# --- 설정 로드 ---
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
    
    start_str = data['start_time']
    end_str = data.get('end_time', '')

    # 종료 시간이 비어있으면, 시작 시간 + 1시간으로 자동 설정
    if not end_str:
        try:
            start_dt = datetime.fromisoformat(start_str)
            end_dt = start_dt + timedelta(hours=1)
            end_str = end_dt.isoformat()
        except:
            pass # 날짜 변환 실패 시 그냥 둠

    event = {
        'summary': data.get('summary', 'AI 일정'),
        'location': data.get('location', ''),
        'description': data.get('description', ''),
        'start': {'dateTime': start_str, 'timeZone': 'Asia/Seoul'},
        'end': {'dateTime': end_str, 'timeZone': 'Asia/Seoul'},
    }
    
    # ★ 본인 이메일 확인 (rhdtka21@gmail.com)
    result = service.events().insert(calendarId='rhdtka21@gmail.com', body=event).execute()
    return result.get('htmlLink')

@app.route('/api', methods=['POST'])
@app.route('/api/index', methods=['POST'])
@app.route('/api/analyze', methods=['POST'])
def analyze():
    try:
        # 1. 한국 시간(KST) 구하기
        KST = timezone(timedelta(hours=9))
        now = datetime.now(KST)
        current_time_str = now.strftime("%Y년 %m월 %d일 %A %H:%M")
        print(f"현재 시간: {current_time_str}")

        user_content = []

        # ---------------------------------------------------------
        # [로직 분기] 텍스트(JSON)인지 이미지(File/Raw)인지 판단
        # ---------------------------------------------------------
        
        # (A) 시리/단축어에서 텍스트(JSON)로 보낸 경우
        if request.is_json:
            json_data = request.get_json()
            if 'text' in json_data:
                user_text = json_data['text']
                print(f"텍스트 입력 수신: {user_text}")
                user_content = [{"type": "text", "text": user_text}]

        # (B) 이미지를 보낸 경우 (기존 로직)
        if not user_content:
            raw_data = request.data
            # Form-data로 왔을 경우 처리
            if not raw_data and 'file' in request.files:
                raw_data = request.files['file'].read()
            
            if raw_data:
                print(f"이미지 입력 수신. 크기: {len(raw_data)} bytes")
                base64_image = base64.b64encode(raw_data).decode('utf-8')
                user_content = [
                    {"type": "text", "text": "이 이미지 내용을 바탕으로 일정을 등록해줘."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]

        # 데이터가 아무것도 없으면 에러
        if not user_content:
            return jsonify({"error": "데이터가 없습니다. (텍스트도 이미지도 아님)"}), 400

        # ---------------------------------------------------------
        # 2. Azure GPT-4o 분석 요청
        # ---------------------------------------------------------
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {
                    "role": "system", 
                    # 프롬프트 수정: "이미지에서" -> "입력된 내용(텍스트 또는 이미지)에서"
                    "content": f"**현재 시각은 {current_time_str}입니다**. 당신은 일정 관리 비서입니다. 사용자가 입력한 내용(텍스트 또는 이미지)에서 일정 정보를 추출하세요. 반드시 JSON 포맷(summary, location, description, start_time, end_time)으로 답하세요. 날짜는 ISO8601(YYYY-MM-DDTHH:MM:SS) 형식입니다. 없는 내용은 빈칸으로 두세요."
                },
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            max_tokens=500
        )
        
        gpt_result = response.choices[0].message.content
        print(f"GPT 응답: {gpt_result}")
        event_data = json.loads(gpt_result)

        # 3. 캘린더 등록
        link = add_to_calendar(event_data)
        
        return jsonify({"message": "성공!", "link": link})

    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"에러 발생: {error_msg}")
        return jsonify({"error": "서버 내부 오류", "details": str(e), "trace": error_msg}), 500
