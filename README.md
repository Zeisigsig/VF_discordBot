# VF_discordBot
"모여봐요 발로의 숲" Discord Bot Code

## 파일 구성
- `main.py` — 봇 구동 파일. 토큰 로드, 인텐트 설정, 서브 모듈 초기화
- `nickname_commands.py` — 관전/대기/초기화 접두어 수정 (텍스트 명령)
- `attendance_check.py` — 내전 인원 체크
- `status_panel.py` — 관전/대기/초기화 버튼 패널

## 사전 설정

### 1. 의존성
```
python3 -m venv venv
venv/bin/pip install discord.py python-dotenv
```

### 2. `.env` (저장소에 올리지 않음)
`src/.env` 에 봇 토큰을 넣는다.
```
DISCORD_BOT_TOKEN=봇토큰
```

### 3. Developer Portal 인텐트
Bot 설정에서 아래 두 개를 **켜야 한다**. 끄면 봇이 기동되지 않거나 명령이 동작하지 않는다.
- SERVER MEMBERS INTENT
- MESSAGE CONTENT INTENT

### 4. 봇 역할 권한
- `닉네임 관리` — 다른 멤버의 닉네임을 변경하는 데 필요
- `메시지 관리` — 명령 메시지 자동 삭제에 필요
- **봇 역할이 대상 멤버의 역할보다 위에 있어야 한다.** 아래에 있으면 닉네임 변경이 거부된다(서버 소유자는 변경 불가)

### 5. 런타임 파일
- `src/panel_state.json` — 설치된 패널의 채널/메시지 ID를 기억한다. 자동 생성되며 저장소에 올리지 않는다

## 닉네임 규칙
- 유저의 닉네임은 `[숫자2개(연도뒷자리)][스페이스][닉네임]` 형태로 구성되어 있어야 한다
- 기본 닉네임이 `00 홍길동` 일 경우 관전, 대기, 초기화에 따라 `관전_00 홍길동`, `대기_00 홍길동`, `00 홍길동` 으로 분류
- 이 형태가 아니면 `!내전` 집계와 버튼 패널이 해당 유저를 처리하지 못한다

## 버튼 패널
봇 전용 채널에 상시 띄워두는 패널. 텍스트 명령과 동작이 같고, **응답이 누른 본인에게만 보인다.**
응답은 10초 후 자동으로 사라지므로 직접 "메시지 닫기"를 누를 필요가 없다.

- 설치: 봇 전용 채널에서 `!패널설치` (관리자 전용, 1회만)
  - 같은 채널에서 다시 실행하면 기존 패널의 문구/버튼을 최신 코드로 갱신한다 (문구를 수정했을 때 사용)
  - 다른 채널에서 실행하면 기존 패널을 지우고 옮길지 확인한다
  - 봇을 재시작해도 기존 패널의 버튼은 계속 동작한다
- 채널 설정: `@everyone` 의 `메시지 보내기` 를 끄면 패널만 남아 깔끔하다
- 버튼
  - `관전` — `관전_` 부여. 이미 관전이면 변경하지 않고 안내만 한다
  - `대기` — `대기_` 부여. 이미 대기이면 변경하지 않고 안내만 한다
  - `초기화` — 접두어를 제거해 기본형으로 되돌린다. 접두어가 겹치거나(`관전_대기_00 홍길동`) 앞에 엉뚱한 문자가 붙은 경우도 복구한다

## 텍스트 명령어
- 기본적으로 `!` 로 시작함
- 명령 메시지와 응답은 자동으로 삭제된다 (응답은 5초 후)
- 관전 명령어
  - nickname_commands.py의 WATCH_COMMANDS 참조
  - "!ㄱㅈ", "!rw", "!관전", "!rhkswjs", "!RW", "!ㄲㅉ", "!RHKSWJS"
- 대기 명령어
  - nickname_commands.py의 WAIT_COMMANDS 참조
  - "!ㄷㄱ", "!er", "!대기", "!eorl" ,"!ER", "!ㄸㄲ", "!EORL"
- 초기화 명령어
  - nickname_commands.py의 RESET_COMMANDS 참조
  - "!ㄱㄱ", "!rr", "!RR", "!ㄲㄲ"
- 내전 인원 체크 명령어 (관리자 전용)
  - `!내전 [유저명]`
  - 유저명은 `,` 로 구분하고, **연도 없이 이름만 입력한다**
  - ex) `!내전 홍길동, 김철수, 김영희, 박민수`
  - 연도를 붙여 입력하면(`00 홍길동`) 인식되지 않으므로 주의
  - 실행하면 `⏳ 내전 인원을 확인하고 있습니다...` 가 먼저 뜨고, 완료되면 그 메시지가 결과로 바뀐다
  - 하는 일
    - 명단에 있고 음성 채널에 있는 유저 → 접두어 제거
    - 명단에 없는데 음성 채널에 있는 유저 → `관전_` 부여
    - 명단에 있는데 음성 채널에 없는 유저 → 미접속으로 보고
  - 대상 음성 채널은 `attendance_check.py` 의 `VOICE_CHANNEL_NAME` 참조

## 봇 운영 환경
- Google Cloud f1-micro
- 봇 디렉토리네 venv 생성
  - python3 -m venv venv
- service code: sudo vi /etc/systemd/system/discord-bot.service
```
[Unit]
Description=Discord Bot
After=network.target

[Service]
Type=simple
User=username
WorkingDirectory=/home/username/VF_discordBot/src
ExecStart=/home/username/VF_discordBot/src/venv/bin/python main.py
Restart=always
RestartSec=5
EnvironmentFile=/home/username/VF_discordBot/src/.env
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```
- service run
```
sudo systemctl daemon-reload
sudo systemctl enable discord-bot
sudo systemctl start discord-bot

sudo systemctl status discord-bot
```
- service stop and update
  - status시 서비스가 죽거나, 서비스 파일 코드 내용 수정 후 update가 필요한 경우
```
sudo systemctl stop discord-bot
sudo systemctl daemon-reload
sudo systemctl restart discord-bot

sudo systemctl status discord-bot
```
  - 단순히 python 코드만 수정했을 경우
```
sudo systemctl restart discord-bot
``` 
