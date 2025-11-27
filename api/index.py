from flask import Flask, request, jsonify
from openai import AzureOpenAI
import os
import json
import base64
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Flask(__name__)

# --- 설정 (Vercel 환경변수에서 가져옴) ---
AZURE_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_KEY = os.environ.get("AZURE_OPENAI_API_KEY")
DEPLOYMENT_NAME = os.environ.get("AZURE_DEPLOYMENT_NAME") # 예: gpt-4o
GOOGLE_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")

# Azure 클라이언트
client = AzureOpenAI(
    api_key=AZURE_KEY,
    api_version="2025-01-01-preview",
    azure_endpoint=AZURE_ENDPOINT
)

# 구글 캘린더 등록 함수
def add_to_calendar(data):
    creds_dict = json.loads(GOOGLE_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=['https://www.googleapis.com/auth/calendar']
    )
    service = build('calendar', 'v3', credentials=creds)
    
    event = {
        'summary': data.get('summary', 'AI 일정'),
        'location': data.get('location', ''),
        'description': data.get('description', ''),
        'start': {'dateTime': data['start_time'], 'timeZone': 'Asia/Seoul'},
        'end': {'dateTime': data['end_time'], 'timeZone': 'Asia/Seoul'},
    }
    
    result = service.events().insert(calendarId='primary', body=event).execute()
    return result.get('htmlLink')

@app.route('/api/analyze', methods=['POST'])
def analyze():
    try:
        # 1. 아이폰에서 보낸 파일 받기
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        
        file = request.files['file']
        # 이미지를 base64로 인코딩 (Azure 전송용)
        base64_image = base64.b64encode(file.read()).decode('utf-8')

        # 2. Azure GPT-4o에게 분석 요청
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {
                    "role": "system", 
                    "content": "일정 관리 비서야. 이미지에서 일정 정보를 추출해. 반드시 JSON 포맷(summary, location, description, start_time, end_time)으로 답해. 날짜는 ISO8601(YYYY-MM-DDTHH:MM:SS) 형식으로."
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
        event_data = json.loads(gpt_result)

        # 3. 구글 캘린더 등록
        link = add_to_calendar(event_data)
        
        return jsonify({"message": "성공!", "link": link})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
