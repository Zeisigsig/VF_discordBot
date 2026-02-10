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
