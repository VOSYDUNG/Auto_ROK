# Design Brief — Auto_ROK

Ngày: 2026-09-19 · Chịu sự điều chỉnh của [`docs/PROJECT_DECLARATION.md`](PROJECT_DECLARATION.md)

Tài liệu này ghi kết quả **research kiến trúc** trên code đang có, rồi rút ra thiết kế cho
vòng vận hành mà LLM local làm chủ ngữ. Nó là cầu giữa `GOAL`/`PRD` và code.

---

## Phần I — Research kiến trúc

Đọc trực tiếp trên mã nguồn tại commit `102c6a1`. Mỗi phát hiện kèm đường dẫn để kiểm lại.

### R1. Đã có hai tầng quyết định, nhưng chưa nối vào nhau

Đây là phát hiện quan trọng nhất, vì nó nghĩa là phần lớn việc cần làm là **nối dây**, không
phải xây mới.

**Tầng chiến thuật — có đủ và đang chạy.**
`harness/local_llm_selector.py` → `OpenAICompatibleDecisionProvider.choose()`. Nhận một
`ToolSnapshot` đã lọc, trả về đúng một `ActionChoice` có sẵn, hoặc `{"action_id": null}` để
từ chối. Được `scripts/run_gather_tick.py:321` cắm vào `MissionRuntime`.

**Tầng chiến lược — có nhà sản xuất, không có người nhận.**
`harness/mission_scheduler.py` → `MissionScheduler.decision_packets()` duyệt các tín hiệu
`NEEDS_DECISION`/`UNKNOWN_STATE` và dựng gói hỏi LLM qua
`mission_timeline.bounded_llm_packet()`.

**Không một dòng nào trong repo tiêu thụ kết quả của `decision_packets()`.** Nó dựng gói rồi
trả về, và chuỗi dừng ở đó. Tầng chiến lược chưa bao giờ hỏi model.

Hệ quả: khi tôi đo LLM ở 20,6 giây và nói *"nó đang làm việc 4 nhánh không xứng"*, cái đo
được là **tầng chiến thuật**. Tầng đáng dùng LLM thì chưa từng chạy.

### R2. Hợp đồng dữ liệu gửi cho model đang bị siết đúng cách

`local_llm_selector.py` dùng **danh sách cho phép**, không phải danh sách cấm:

- `_MODEL_SCALAR_FACT_KEYS` — 9 khoá, đúng những gì cần cho lát cắt GATHER
- `_MODEL_MAPPING_FACT_KEYS` — lọc tới từng trường con
- `_MODEL_FORBIDDEN_KEY_PARTS` — chặn `bbox`, `rect`, `coord`, `point`, `screen`, `window`,
  `hwnd`, `pid`, `path`, `image`, `memory`

Bình luận trong code nói rõ ý đồ: *"Keep this allowlist narrow so new scene facts do not
silently expand model input."* Đây là thiết kế đúng và phải giữ.

**Nhưng có trùng lặp sẽ trôi.** `mission_scheduler.py` khai một danh sách cấm **thứ hai**
(`_FORBIDDEN_FACT_KEY_PARTS`, 8 phần) — gần giống nhưng **không bằng**: thiếu `memory` và
`window`. Hai danh sách ở hai file, không cái nào biết cái nào. Thêm một sự kiện nhạy cảm
mới thì phải nhớ sửa cả hai.

→ **Quyết định thiết kế:** gộp về một mô-đun ranh giới duy nhất, cả hai tầng cùng dùng.

### R3. Kho đo nhịp đã có sẵn bảng đúng

`harness/mission_knowledge.py` → SQLite với bốn bảng: `facts`, `occurrences`, `events`,
`change_signals`.

`change_signals` chính là kênh phát hiện game đổi mà PRD F12 cần — đã có bảng, chưa có
người ghi. `facts` đã có `observed_at`, `source`, `frame_id`, `evidence_ref`, tức đã gắn
nguồn gốc đúng chuẩn dự án.

→ Kho đo nhịp cho `autorok.mission` **không cần xây mới**, chỉ cần định nghĩa khoá và ghi vào.

### R4. `MissionScheduler.tick()` đã là nguyên thuỷ của "không bao giờ dừng"

Docstring của nó: *"Keeping this tick input-free lets the scheduler run while the local LLM
is unavailable."*

Nghĩa là đã có sẵn một nhịp chạy được **kể cả khi model chết**. Đó đúng là tầng mà nguyên tắc
*không-bao-giờ-dừng-ở-cấp-vòng-lặp* phải bám vào.

### R5. `operator_layer/` là kho profile, đang nằm không

Merge ngày 2026-09-19. Có `OperatorSnapshot`, `Provenance` bắt buộc, `ObservedFact`,
`DerivedSignal` yêu cầu `evidence_keys` không rỗng, và `AccountQualityVector` với các chiều
`commander_depth`, `farm_network_capacity`.

**Không file nào import nó.** Nhưng đó chính xác là schema cho dữ liệu khảo sát nhân vật
(Tướng / City Hall / Chợ) mà người vận hành mô tả.

### R6. Nợ đã biết, không phát sinh thêm

Từ `docs/COVERAGE.md` §5, còn nguyên: chưa có `pyproject.toml`/`conftest.py`; CI chạy
22/56 file test trên Linux; 16 module `harness/` không có trong đồ thị; hai bộ contract song
song; bốn đường chạy mission song song; OCR 4.525 ms so với ngưỡng 400 ms.

---

## Phần II — Thiết kế

### D1. Hai tầng quyết định, hai nhịp, hai hợp đồng

Đây là trục của toàn bộ thiết kế.

| | **Tầng chiến lược** (mới nối) | **Tầng chiến thuật** (đang chạy) |
|---|---|---|
| Câu hỏi | *Bây giờ làm nhiệm vụ nào, cho nhân vật nào, gom loại gì?* | *Trong màn hình này, bấm ứng viên nào?* |
| Nhịp | mỗi chu kỳ lập kế hoạch (phút) | mỗi tick (giây) |
| Tần suất | thưa | dày |
| 20,6 s có phải vấn đề? | **không** — harness đang chờ quân về hàng giờ | **có** — nằm trên đường tới hạn |
| Đầu vào | trạng thái đội hình, tiến độ order, nhịp đã đo, buff còn lại | `ToolSnapshot` một khung hình |
| Đầu ra | một `MissionIntent` trong tập đã lọc | một `ActionChoice` trong tập đã lọc |
| Code | `MissionScheduler` + người nhận **cần viết** | `OpenAICompatibleDecisionProvider` |

**Hệ quả quan trọng:** phần lớn giá trị của LLM nằm ở tầng chiến lược, và ở đó độ trễ 20,6 s
là chấp nhận được. Tầng chiến thuật nên **giảm dần** sự tham gia của model — chỉ gọi khi
selector tất định thật sự bế tắc. Chỉ số `local_llm_entries_per_100_ticks` đo đúng điều này:
càng thấp thì harness càng sâu.

### D1b. Mọi module tri giác là một cảm biến, không phải bộ đoán

Hệ quả trực tiếp của phép loại suy nhúng trong `PROJECT_DECLARATION` §1.

Một encoder không bao giờ trả về vị trí phỏng đoán. Nó trả số, hoặc báo lỗi. Mọi module tri
giác ở đây phải có đúng tính chất đó:

| Bắt buộc | Vì sao |
|---|---|
| Trả giá trị **hoặc** mã từ chối, không có kiểu lai | Giá trị "chắc khoảng" là thứ lan ra cả hệ thống mà không ai chặn được |
| Từ chối phải **phân loại được** | `UNKNOWN_GLYPH` khác `NO_TEXT` khác `BAD_SHAPE` — mỗi cái dẫn tới xử lý khác nhau |
| Hoà nhau thì từ chối, không bẻ hoà | Chọn bừa là đoán khoác áo đọc |
| Chỉ nhìn ROI đã hiệu chỉnh, không quét cả khung | Quét cả khung là cách mồi `(5/5)` lọt vào |
| Không tự huấn luyện từ khung nó đọc hỏng | Hiệu chỉnh là thao tác có chủ ý, không phải tự bồi |

`harness/queue_indicator.py` là bản mẫu. Mọi cảm biến viết sau phải theo đúng hình dạng đó,
và khi rà soát một module tri giác thì rà đúng năm dòng trên.

**Cách dùng khi có lỗi:** tín hiệu bẩn thì sửa cảm biến, đừng sửa bên tiêu thụ. Nếu bên tiêu
thụ phải "xử lý trường hợp đọc ra 115" thì cảm biến đã sai, không phải bên tiêu thụ thiếu
phòng thủ.

### D2. Thang suy giảm — fail-closed ở hành động, không dừng ở vòng lặp

Người vận hành: *"tôi tác động nó thay đổi các quyết định thôi chứ không làm nó dừng vận hành"*.

Mâu thuẫn với kiến trúc hiện tại (dừng trước mọi bất định) được giải bằng cách tách hai cấp:

```
Cấp hành động  : fail-closed. Không nối đất được, không phê duyệt được → KHÔNG bấm.
Cấp vòng lặp   : không dừng. Hành động bị chặn → tụt xuống mục tiêu yếu hơn.
```

Thang tụt, từ mạnh xuống yếu:

1. `ORDER_WORK` — làm theo hạn mức người vận hành giao
2. `DEFAULT_FARM` — tỉ lệ 1:1:1:2, mỏ cấp cao xuống thấp
3. `SCARCITY_FILL` — bỏ ưu tiên cấp và loại, miễn lấp đầy hàng đợi
4. `DAILY_CITIZEN` — VIP, quà, Courier Station, đóng góp liên minh theo nhịp hồi
5. `OBSERVE_ONLY` — chỉ quan sát và ghi bằng chứng, không phát input

Bậc 3 là **luật khan mỏ** của người vận hành, đã hiện thực trong
`autorok/mission/allocation.py`. Bậc 5 là đáy: hệ thống vẫn sống, vẫn ghi nhận, chờ người.

**Quy tắc:** tụt bậc phải được ghi lại kèm lý do. Tụt bậc kéo dài là bằng chứng về vương
quốc, và là thứ LLM cần được cho biết, không phải thứ harness nuốt im.

### D3. Một mô-đun ranh giới duy nhất cho dữ liệu gửi model

Gộp hai danh sách lọc ở R2 về `autorok/llm/boundary.py`. Cả tầng chiến lược lẫn chiến thuật
cùng gọi. Thêm sự kiện nhạy cảm mới thì sửa một chỗ.

Giữ nguyên nguyên tắc **danh sách cho phép**, không chuyển sang danh sách cấm.

### D4. Hai hàng đợi, hai động cơ

| Hàng đợi | Sức chứa | Động cơ | Trạng thái |
|---|---|---|---|
| Hành quân (farm) | 5 / nhân vật | cố định | đã mô hình hoá |
| Vận chuyển (giao) | số xe | **cấp Chợ** | **chưa quan sát** |

Lịch giao bị chặn bởi hàng đợi thứ hai, cộng chi phí **tele lại gần** phải trả trước. Đây là
bài toán logistics, không phải một cú bấm. Khoá cho tới khi đọc được bảng *cấp Chợ → hàng mỗi
lượt* trên client thật.

### D5. Nhịp đo gieo bằng kinh nghiệm, thay dần bằng số đo

`CycleSource.OPERATOR_BASELINE` (2h15 / 3h45) cho phép scheduler chạy từ ngày đầu.
`CycleSource.MEASURED` thay thế khi có mẫu thật. Hai giá trị **không được phép lẫn nhau** —
đã cưỡng chế bằng kiểu dữ liệu trong `autorok/mission/fleet.py`.

Cả hai mốc đều giả định buff 50% đang chạy. Buff tắt thì lịch sai → **buff là đầu vào của
lịch biểu**, không phải tiện ích năng suất.

### D6. Bản đồ mô-đun đích

```
autorok/
  mission/     order, fleet, allocation        ← ĐÃ XONG, 48 test
               ladder (thang suy giảm)          ← cần viết
               survey  (khảo sát → profile)     ← cần client
               delivery (logistics giao hàng)   ← KHOÁ, cần quan sát Chợ
  llm/         boundary (gộp R2)                ← cần viết
               strategic (người nhận cho R1)    ← cần viết
  knowledge/   đọc knowledge/*.yaml
harness/       giữ nguyên, là tầng cơ chế 80%
operator_layer/ kho profile tài khoản (R5)      ← cần nối dây
```

---

## Phần III — Câu hỏi còn mở

| # | Câu hỏi | Chặn cái gì |
|---|---|---|
| 1 | Bảng *cấp Chợ → hàng mỗi lượt* | toàn bộ `delivery` |
| 2 | Đường giao: kéo bản đồ hay Chợ → Support | `delivery` |
| 3 | Thuế bao nhiêu phần trăm | tính `gross_required` thật |
| 4 | Màn chi tiết tài nguyên loại trừ item nằm ở đâu | đo tiến độ order |
| 5 | Chu kỳ xoay hàng Courier Station | lịch `DAILY_CITIZEN` |

Câu 1, 2, 4, 5 trả lời được bằng một pass quan sát an toàn, không phát input.
Câu 3 người vận hành cho số.
