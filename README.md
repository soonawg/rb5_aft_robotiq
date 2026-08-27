# RB5 + AFT200 + Robotiq 실험 도구

RB5-850E, AIDIN AFT200-D80-C, Robotiq 2F-85를 Windows PC에서 설정하고
F/T 데이터를 수집·필터링하기 위한 최소 전달 패키지입니다.

## 연결 구성

```text
Windows PC ─Ethernet→ RB5 제어박스 ─CAN/5V→ AFT200
Windows PC ─USB→ DTECH USB-RS485 ─RS485→ Robotiq 2F-85
RB5 제어박스 ─24V/GND→ Robotiq 2F-85
```

- RB UI: 로봇과 AFT200 설정·운용
- `rb5_ui.py` 또는 Robotiq RUI: Windows COM 포트에 직접 연결된 그리퍼 운용
- 상세 설정 순서: [한국어 운용 매뉴얼](docs/setup-runbook-ko.md)

## 준비

1. [Rainbow Robotics 협동로봇 기술문서](https://rainbowrobotics.github.io/rb_cobot_docs/ko/)
   상단 `다운로드`에서 제어박스와 맞는 Windows LTS RB UI를 받습니다.
2. Windows에 Python 3를 설치합니다.
3. 저장소 루트에서 다음을 실행합니다.

```powershell
py -m pip install -r requirements.txt
```

## 실행

그리퍼 및 F/T 통합 화면:

```powershell
rb5\run_ui.bat
```

30초 F/T 원본 수집:

```powershell
py rb5\capture_ft.py --host 10.0.2.7 --seconds 30 --hz 50
```

최종 EMA 필터 적용:

```powershell
py rb5\filter_ft.py rb5\data\ft_20260827_134834.csv
```

## 포함 파일

| 파일 | 용도 |
|---|---|
| `docs/setup-runbook-ko.md` | 센서 설정, User Script Command, 재부팅, 운용 순서 |
| `rb5/capture_ft.py` | RB 제어박스 Modbus TCP에서 6축 원본 CSV 수집 |
| `rb5/filter_ft.py` | EMA, tare, 최근 1초 안정 질량 계산 |
| `rb5/rb5_ui.py` | F/T 표시와 Windows COM 방식 Robotiq 제어 |
| `rb5/run_ui.bat` | Windows UI 실행 |
| `rb5/data/ft_20260827_134834.csv` | 필터 개발에 사용한 50 Hz, 30초 원본 로그 |
| `rb5/data/ft_20260827_134834_final.csv` | 최종 필터 적용 예제 |

## 현재 검증 상태

- AFT200 등록, 6축 데이터 수신, 원본 CSV 수집 및 필터 실행: 완료
- 필터: EMA `alpha=0.1`, 최근 1초 peak-to-peak `30 g` 이하 안정 판정
- 예제 로그 마지막 1초: 표준편차 `2.61 g`, peak-to-peak `9.39 g`
- Robotiq: 과거 제어박스 USB 경로에서 고정 빨간 LED/무응답이 있었으며,
  Windows USB-COM 직접 연결 상태의 실장비 검증이 남아 있음

## 안전

- 배선 변경은 제어박스 전원을 완전히 끈 상태에서만 수행합니다.
- 최초 로봇 동작은 속도 5~10%에서 수행하고 물리 비상정지를 준비합니다.
- AFT200에는 5 V, Robotiq에는 24 V를 공급합니다.
- 로봇 이동은 RB UI 한 곳, 그리퍼 명령은 COM 프로그램 한 곳에서만 보냅니다.

RB Window 설치 파일과 제조사 프로그램은 이 저장소에 포함하지 않습니다. 공식
Rainbow Robotics 및 Robotiq 배포처에서 받아야 합니다.
