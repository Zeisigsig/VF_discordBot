# VF_discordBot
"모여봐요 발로의 숲" Discord Bot Code

## main.py
- 봇 구동 파일


## attendasnce_check.py
- 내전 인원 체크 파일


## nickname_commands.py
- 관전/대기/초기화 prefix 수정 파일


## 명령어
- 기본적으로 "!"로 시작함
- 유저의 닉네임은 [숫자2개(연도뒷자리)][스페이스][닉네임] 형태로 구성되어있어야함
- 기본 닉네임이 "00 홍길동" 일 경우 관전, 대기, 초기화에 따라 "관전_00 홍길동", "대기_00 홍길동", "00 홍길동"으로 분류
- 관전 명령어
  - nickname_commands.py의 WATCH_COMMANDS 참조
  - "!ㄱㅈ", "!rw", "!관전", "!rhkswjs", "!RW", "!ㄲㅉ", "!RHKSWJS"
- 대기 명령어
  - nickname_commands.py의 WAIT_COMMANDS 참조
  - "!ㄷㄱ", "!er", "!대기", "!eorl" ,"!ER", "!ㄸㄲ", "!EORL"
- 초기화 명령어
  - nickname_commands.py의 RESET_COMMANDS 참조
  - "!ㄱㄱ", "!rr", "!RR", "!ㄲㄲ"
- 내전 인원 체크 명령어
  - !내전 [유저명]
  - 유저명의 경우 ","로 구분
  - ex) !내전 00 홍길동, 김철수, 김영희, 06 박민수
    - 닉네임이 겹치지 않을시 연도 없이 사용 가능

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
