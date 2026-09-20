# Roadmap & kế hoạch xây dựng — Auto_ROK

Cập nhật: 2026-09-20 · Chịu sự điều chỉnh của [`docs/PROJECT_DECLARATION.md`](PROJECT_DECLARATION.md)
· Yêu cầu: [`docs/SRS.md`](SRS.md) · Thiết kế: [`docs/DESIGN_BRIEF.md`](DESIGN_BRIEF.md)

Bản này thay bản P0–P5 ngày 2026-09-19. Thứ tự đã đổi vì pass quan sát ngày 2026-09-20 tìm
ra một thứ chặn mọi thứ khác.

---

## Bảng điểm

| | Chỉ số | Hôm nay | Đích |
|---|---|---|---|
| **★** | Giờ chạy tự chủ không người chạm | ~0 | 1h → 4h → 15h |
| | Lần LLM vào cuộc / 100 tick | chưa đo | ≤ 5 |
| | % hàng đợi đầy **và** buff ≠ 0 | chưa đo | ≥ 85% |
| | Lần tự phát hiện game đổi | 0 | ≥ 1 |
| | % tri thức miền mới do hệ thống tự đề xuất | 0% | > 0 |

Ngưỡng theo `SRS §2.2`, **chờ người vận hành duyệt**.

**Tiến độ yêu cầu: 55/89 đã có test · 27 chưa xây · 5 khoá · 2 chưa kiểm.**

---

## Vì sao thứ tự này

Thứ tự cũ đặt hiệu năng OCR lên đầu. Sai. Pass quan sát cho thấy:

> **Agent không đọc được chỉ số hàng đợi `1/5`.** Và trong cùng khung hình có một mồi giả
> `(5/5)` từ tiến độ nhiệm vụ. Một regex `\d/5` sẽ kết luận hàng đợi đã đầy trong khi thật
> ra còn trống 4 slot — và **không có gì báo lỗi**.

Mục tiêu nghiệm thu của dự án là **đưa hàng đợi lên 5/5**. Không thể đạt một chỉ số mà mình
không đọc được, và **nguy hiểm hơn là đọc nhầm**. Nên mọi thứ khác lùi lại sau việc này.

Nguyên tắc sắp xếp còn lại giữ nguyên: **làm hết phần không cần game trước**, vì sự có mặt
của người vận hành là tài nguyên khan hiếm nhất.

---

## M1 — Đọc đúng · cần client một lần, chỉ quan sát

**Vì sao đầu tiên:** đọc sai còn tệ hơn không đọc. Cái mồi `(5/5)` là lỗi im lặng.

| Yêu cầu | Việc |
|---|---|
| `OCR-006` | Đọc `1/5` tại `x≈1321…1338, y≈116…125` — crop CPU cố định, cùng khuôn mẫu đã dùng cho nhãn `Units` |
| `STA-005` | Nối đất hàng đợi **theo vị trí**, cấm quét `n/5` toàn khung |
| `OCR-005` | Ép UTF-8; hiện xuất cp1252 và chạy được nhờ may |
| `MIS-013`,`MIS-014` | Nối cách đọc tồn kho `Total − From Items` vào code |

**Xong khi:** đọc đúng `1/5` trên khung thật · mồi `(5/5)` bị từ chối bằng test · tên có
dấu (`Šárka`) không làm gãy · tồn kho khớp header.

**Rủi ro:** thấp. Khuôn mẫu crop đã có tiền lệ trong repo.

---

## M2 — Nền móng · không cần game

| Yêu cầu | Việc |
|---|---|
| — | `pyproject.toml` + `conftest.py`, bỏ `sys.path` hack trong 32/42 script |
| `LLM-005` | Gộp hai danh sách lọc đã lệch về `autorok/llm/boundary.py` |
| — | Đưa `autorok.mission` vào `config/engineering_graph.yaml` |

**Xong khi:** `pytest` chạy từ thư mục bất kỳ · một danh sách lọc duy nhất ·
`check_local.py` xanh.

**Rủi ro:** thấp. Không đổi hành vi.

---

## M3 — Đủ nhanh để vừa một lượt · không cần game

**Vì sao ở đây chứ không sớm hơn:** 4,8 giây một khung không làm sai kết quả, nó chỉ làm
**một lượt vào nhân vật kéo dài**. Mà trần thời gian mỗi lượt (`MIS-015`) là bài toán 7h
sáng — nên tốc độ là tiền đề của M5, không phải của M1.

### Đo trước khi sửa — kết quả ngày 2026-09-20

| Giai đoạn | Thời gian | Tính chất |
|---|---|---|
| Khởi động `powershell.exe` | 185 ms | mỗi lần gọi |
| Nạp WinRT | 91 ms | mỗi lần gọi |
| Tạo engine OCR | 7 ms | rẻ |
| Đọc + giải mã ảnh chính | 279 ms | mỗi khung |
| **OCR toàn khung** | **143 ms** | **đây là phép tính thật** |
| Crop + scale + **ghi PNG ra đĩa** | **92 ms / lần** | ×11 ≈ 1.000 ms, **phí hoàn toàn** |
| Đọc lại từ đĩa + OCR crop | 39 ms / lần | ×11 ≈ 430 ms |

**Kết luận quyết định hướng sửa:** trong 4.863 ms, phần *tính toán thật* chỉ khoảng
**140 ms**. Phần còn lại là khởi động tiến trình, đi vòng qua đĩa, và giải mã lặp lại.

### Vì sao chưa viết lại bằng C/C++

Người vận hành nêu đúng rằng C/C++ nhanh hơn Python. Nhưng số đo cho thấy **nút thắt không
phải ngôn ngữ**: spawn tiến trình, I/O đĩa và giải mã ảnh **không nhanh lên vì viết bằng
C++**. Viết lại toàn bộ sẽ tốn hàng tuần để giải quyết 140 ms.

C/C++ chỉ đáng bàn **sau khi** M3.1–M3.3 xong. Khi đó 143 ms OCR lõi mới thành sàn thật,
và lúc đó mới có câu hỏi đúng để hỏi.

### M3.1 — Giải mã thẳng vùng cần, bỏ scale-rồi-mã-hoá-lại

> **Sửa tiền đề.** Bản kế hoạch đầu viết *"bỏ đường vòng qua đĩa, −1.000 ms"*. **Sai.**
> Đo lại ngày 2026-09-20 có warmup và lấy trung vị:
>
> | | |
> |---|---|
> | crop + scale bicubic | **49,0 ms** |
> | + mã hoá PNG **ra đĩa** | 85,0 ms |
> | + mã hoá PNG **vào bộ nhớ** | 90,1 ms |
> | **đĩa so với bộ nhớ** | **−5,1 ms — trong sai số** |
>
> Windows cache file làm việc ghi PNG tạm gần như ngang ghi RAM. Đĩa **không phải** nút
> thắt. Chi phí thật là **scale bicubic 49 ms** cộng **mã hoá PNG 36 ms**.
>
> Con số 92 ms/lần đo lần đầu là đúng, nhưng tôi quy sai nguyên nhân cho đĩa.

Cách đúng: dùng `BitmapDecoder` + `BitmapTransform` để **giải mã thẳng vùng cần ở đúng tỉ
lệ**, bỏ hẳn cả bước crop bằng `System.Drawing` lẫn bước mã hoá/giải mã PNG.

Đo được: **38,8 ms/lần gồm cả OCR**, so với ~124 ms của đường cũ.

**Một bẫy phải tránh:** `BitmapTransform` áp **scale trước rồi mới crop**, nên `Bounds`
phải tính trong toạ độ **đã phóng**, không phải toạ độ gốc. Đặt sai thì async operation
ném lỗi và trả `null` — không phải sai kết quả, mà là gãy hẳn.

**Rủi ro thật cần kiểm:** đường cũ scale bằng `HighQualityBicubic` của `System.Drawing`,
đường mới scale bằng bộ nội suy của WinRT. **Khác thuật toán thì có thể khác kết quả OCR.**
`BitmapTransform.InterpolationMode` có `Cubic`, nhưng không đảm bảo trùng từng pixel.

→ Bắt buộc chạy `M3.4` **trước khi** nhận M3.1. Nếu kết quả lệch một ký tự, M3.1 bị từ
chối, không phải được chấp nhận như một đánh đổi.

**Dự kiến:** −85 ms mỗi crop có scale. Với các crop hiện có ≈ **−500 đến −900 ms**.

### M3.2 — Gọi Windows.Media.Ocr thẳng từ Python

> **Sửa hướng.** Bản đầu viết *"tiến trình OCR thường trú, −276 ms"*. Đúng nhưng nhỏ. Người
> vận hành hỏi thẳng: *"hay do ta chồn chân vào một framework?"* — và số đo nói **đúng**.

Phân rã 1.036 ms còn lại, sau khi đã xoá khối 3 giây:

| Giai đoạn | ms | Việc thật? |
|---|---|---|
| spawn `powershell.exe` | 185 | không |
| nạp WinRT (`Add-Type`) | 116 | không |
| băm SHA-256 ảnh | 151 | **không — Python đã băm rồi** |
| giải mã PNG | 325 | **không — Python đã có pixel rồi** |
| **OCR + dựng element** | **73** | **CÓ** |
| dựng JSON | 22 | ranh giới |

**73 ms việc thật trên 1.036 ms — 7%.** Còn lại là thuế ranh giới tiến trình và làm lại
việc đã làm: `windows_capture_backend.py` có sẵn mảng numpy (dòng 222) và đã tính SHA-256
(dòng 233), rồi mã hoá PNG, ghi đĩa, để PowerShell đọc lại, **băm lại**, **giải mã lại**.

**Không cần C/C++.** `Windows.Media.Ocr` là WinRT, Python gọi thẳng được qua `winrt-*`
(pywinrt 3.2.1, có bản cp312). Cùng một engine.

**Đã đo trên bản mẫu:**

| | |
|---|---|
| Qua PowerShell | 1.036 ms |
| **Python gọi thẳng** | **93 ms** |
| Nhanh hơn | **11,1 lần** |
| Tổng từ đầu M3 | 4.863 → 93 ms = **52 lần** |
| Ngưỡng N02 (400 ms) | **ĐẠT** |

**`OCR-004` đã kiểm: 75 element, lệch 0** — trùng cả `text`, `bbox`, `line_index`,
`word_index`.

#### Và nó lộ ra một lỗi đang sống

Khi đối chiếu, một phần tử lệch: PowerShell ra `'Crown`, Python ra `æCrown`. Không phải OCR
khác nhau — **PowerShell xuất stdout bằng CP437 (codepage OEM)**, và `0x91` trong CP437
chính là `æ`. Giải mã bằng cp1252 thì ra `'`.

`harness/windows_live_observation.py` gọi `subprocess.run(..., text=True)` **không chỉ định
encoding**, nên dùng locale mặc định — tức **đang đọc sai ký tự ngay lúc này, âm thầm**.

Đây là `OCR-005`, và nó nghiêm trọng hơn tôi ghi hôm qua: không phải "may mà chạy được", mà
là **đang hỏng**. Chuyển sang Python gọi thẳng xoá luôn cả lớp encoding này.

### M3.3 — Một mũi nhọn, không phải dao đa năng

Nguyên tắc của người vận hành: *"module ta tải về quá cồng kềnh để làm việc all-in-one,
nhưng có khi của chúng ta chỉ cần một mũi nhọn."*

`harness/queue_indicator.py` đã chứng minh: đọc `1/5` bằng template mất **0,207 ms**, còn
OCR tổng quát mất 4.863 ms **và đọc sai thành `115`**.

Rà 11 lần nhận dạng hiện tại, tách làm hai nhóm:

- **Trường cố định, font bitmap** — số tài nguyên, cấp mỏ, số quân, chỉ số hàng đợi. Đây là
  chỗ dùng template. Mỗi lần thay thế tiết kiệm **~131 ms** (39 ms OCR + 92 ms đĩa) và đổi
  lại được **độ chính xác tuyệt đối**.
- **Chữ thật sự biến thiên** — tên người chơi, mô tả vật phẩm. Giữ OCR, vì template không
  làm được.

**Đây là phần đáng giá nhất của M3**, và nó không phải tối ưu tốc độ — nó là **làm sạch
tín hiệu**, tốc độ chỉ là hệ quả. Xem `PROJECT_DECLARATION` §1.

### M3.4 — Chứng minh không đổi kết quả

`OCR-004`: đầu ra sau tối ưu phải **giống hệt từng ký tự** trước đó trên toàn corpus. Không
có ngoại lệ — một tối ưu làm đổi kết quả OCR là một lỗi, không phải một đánh đổi.

**Xong khi:** < 400 ms/khung · corpus khớp từng ký tự · `OCR-005` (UTF-8) đã xong ở M1.

## M4 — Không bao giờ đứng hình · không cần game

| Yêu cầu | Việc |
|---|---|
| `LAD-007…009` | Thang 5 bậc `ORDER_WORK → OBSERVE_ONLY`, mỗi lần tụt ghi lý do, **không tồn tại trạng thái "không có mục tiêu"** |
| `LAD-010` | Nhận biết khan mỏ bằng **khung hình không đổi sau khi bấm Tìm kiếm** — tầng tri giác, không phải OCR |

**Xong khi:** một chu kỳ chạy offline từ trạng thái giả lập, tụt đủ 5 bậc khi bị chặn.

Đây là thứ `Mouse_key.py` thiếu và là lý do nó đóng băng mọi ngoại lệ.

---

## M5 — Tự lập lịch ngày · cần đo trên client

| Yêu cầu | Việc |
|---|---|
| `MIS-015` | Trần thời gian mỗi lượt vào nhân vật — **đo trước, chốt sau** |
| `MIS-016` | Lộ trình ngày tính từ trạng thái bền, không phải lịch cố định |

**Phải đo trước khi quyết:** giây cho mỗi nghiệp vụ daily · giây để gửi đủ 5 đạo · giây để
đổi nhân vật · tổng tải lúc reset 7h sáng.

**Quyết định của người vận hành sau khi có số:** nghiệp vụ nào giữ, nghiệp vụ nào bỏ lúc
cao điểm.

**Giả thuyết đề xuất, chờ số liệu bác bỏ:** hàng đợi là tài nguyên **dễ hỏng** — slot trống
mất thời gian đào vĩnh viễn, quà VIP thì một giờ sau vẫn còn. Nên lúc reset nên **gửi quân
hết mọi nhân vật trước, rồi mới quay lại làm daily**.

---

## M6 — Biên quyết định LLM · không cần game

| Yêu cầu | Việc | Trạng thái |
|---|---|---|
| `LLM-006` | Người nhận cho gói chiến lược — `decision_packets()` dựng gói rồi **vứt đi** | **XONG** |
| `LLM-007` | Bộ đếm tần suất gọi, đích ≤ 5/100 tick | bộ đếm **xong**, số thật chờ M7 |
| `LLM-008` | `retraining_required` phải nêu *cái gì đổi* và *khung hình nào chứng minh* | **XONG** |
| `LLM-009` | Model **đề xuất** tri thức, người vận hành duyệt; cấm tự ghi | **XONG** |
| `ONB-001…003` | Onboarding 6 pha; chỉ pha 0 được chặn | **XONG** |
| `ONB-004` | Khảo sát Tướng · City Hall · Chợ | **cần client** → M7 |

**Xong khi:** một chu kỳ lập kế hoạch chạy offline và trả về một `MissionIntent` hợp lệ.

### M6.1 đã làm — tầng chiến lược có người nhận

`autorok/llm/intent.py` · `autorok/llm/strategy.py` · `harness/strategic_bridge.py`.

Ba quyết định đáng ghi lại:

**Harness dựng ứng viên, model chỉ trỏ.** Giống hệt tầng chiến thuật: model trả một
`intent_id`, và `intent_id` được ánh xạ ngược về một object harness đã tạo. Không khớp thì
**từ chối**, không sửa cho gần đúng.

**Không gọi model khi câu hỏi đã ngã ngũ.** Không có ứng viên → `HOLD`. Đúng một ứng viên →
lấy luôn. Chỉ từ hai ứng viên trở lên mới hỏi. Đây chính là `SC-02` được thực thi bằng cấu
trúc chứ không bằng lời dặn.

**Model chết thì harness tự quyết, và ghi rõ là mình quyết.** `decided_by` phân biệt
`MODEL` · `HARNESS_ONLY_OPTION` · `HARNESS_FALLBACK`. Thiếu trường này thì một đêm model
chết trông y hệt một đêm model quyết mọi bước.

Thứ tự ưu tiên dự phòng đang dùng **giả thuyết slot dễ hỏng** — gửi quân trước, việc daily
sau. Ghi rõ trong code là giả thuyết, chờ số của M5 bác bỏ hoặc xác nhận.

**Một lỗ hổng thật tìm được khi viết test:** `strip_forbidden` đi vào mapping lồng nhau
nhưng **không đi vào list**. Gói chiến lược mang `due_tasks` là *list các mapping*, nên
`client_window_rect` nằm trong đó sẽ đi thẳng qua hàm có nhiệm vụ chặn đúng thứ đó. Đã vá
và có test riêng.

### M6.2 đã làm — phản hồi đổi game, onboarding, và ranh giới bí mật

`autorok/llm/retraining.py` · `autorok/onboarding.py` · `tests/test_no_plaintext_credentials.py`.

**Tín hiệu đổi game không dựng được nếu thiếu bằng chứng.** `RetrainingSignal` bắt buộc
*cái gì đổi* và *khung hình nào chứng minh*, kiểm ngay lúc dựng object — không phải lọc về
sau. Và nó **không có chỗ nào** để ghi mục tiêu thay thế: báo nút `USE` biến mất là bằng
chứng, đoán nút bên cạnh là nút mới thì là bịa.

**`knowledge/` là của người vận hành, và điều đó được thi hành.** `write_proposal` **từ
chối** mọi đích nằm trong `knowledge/`, không phân biệt hoa thường. `KnowledgeProposal`
không có `apply()`, không có `accept()`. Test kiểm luôn rằng ghi một đề xuất không chạm
vào bất kỳ file tri thức thật nào. Đây là đường ranh giữa *được người nuôi* và *tự nuôi* —
nó phải là mã, không phải một dòng trong tài liệu.

**Onboarding: chỉ pha 0 được chặn, và điều đó không thể vi phạm.** Dựng một `PhaseResult`
`BLOCKED` ở pha 1–5 sẽ **ném lỗi**. Bước thiếu cũng được **ghi lại**, không im lặng bỏ
qua — bỏ qua thầm lặng sẽ làm `may_decide` đúng trên một lượt chạy chưa từng nhìn vào game.

Đáng ghi: nếu chỉ chạy pha 0 thì `may_decide` **vẫn đúng**, nhưng 5 pha thiếu tụt 5 bậc và
thang chạm đáy `OBSERVE_ONLY` — nơi không phát input. Được phép quyết định, nhưng không còn
gì để quyết ngoài việc quan sát. Đó là cách hai cơ chế khớp nhau, và test nói rõ điều đó.

**`SAF-006` đóng luôn.** Quét toàn repo tìm **giá trị** gán cho mật khẩu/token/khoá, bỏ qua
placeholder và mô tả. Đã gài thử một mẫu giả vào `config/` để xác nhận test **đỏ đúng lúc**
rồi mới gỡ ra — một bộ quét không bao giờ bắt được gì thì không phải là bộ quét.

Chỗ để bí mật khi xây đăng nhập: **Windows Credential Manager**, người vận hành nhập một
lần, đọc lúc chạy. Không commit, không log, không đưa vào mission fact.

Đây là lúc 20,6 giây chuyển từ lỗi chặn thành không quan trọng — ở tầng này harness đang
chờ quân về hàng giờ.

---

## M7 — Chạy thật · cần client, có phát input

### Phát hiện 2026-09-20 — game có chu kỳ NGÀY/ĐÊM

Đây là rủi ro hệ thống, không phải lỗi một module. Ban đêm client phủ tối toàn
bản đồ. Đo trên cùng một khung nhìn cách nhau vài phút: độ sáng trung bình vùng
toạ độ **117,6 → 74,6**.

Hệ quả đã thấy: cảm biến toạ độ viết bằng OCR đạt **7/7 ban ngày**, rồi trả
`PARTIAL` ngay trên đúng khung nhìn đó khi trời tối. **Không scale nào đọc được
cả hai** — scale 2 đúng ban ngày và sai ban đêm, scale 1,5 thì ngược lại. Đã thử
grayscale, min-max stretch, Otsu, CLAHE, nhị phân ngưỡng cố định, mỗi cái ở bốn
scale: không cái nào đọc được hết.

**Cách chữa đúng: đo tương phản cục bộ, không đo độ sáng tuyệt đối.** Cảm biến
toạ độ nay đếm số cột có pixel sáng hơn **trung vị của chính vùng đó**. Trung vị
trôi theo tông màu nên phép đo đứng yên: 121 cột ban ngày (trung vị 115), 132 cột
ban đêm (trung vị 54), so với 0–2 cột khi không phải world map.

**Việc phải làm:** mọi ROI hiệu chỉnh trước đó trong ngày **đều đo trên khung ban
ngày**. Cần đo lại ban đêm: `top_resource_bar`, `queue_indicator_profile`,
`resource_level_profile`, `main_view_profiles`. Chưa đo thì phải coi là chưa biết.

---


| Việc | Ghi chú |
|---|---|
| Nối `autorok.mission` vào `run_gather_tick.py` | |
| **Hàng đợi một nhân vật lên 5/5** | mục tiêu nghiệm thu của người vận hành |
| Xoay vòng hai cấp qua 8 nhân vật | |
| Đo north star: giờ chạy tự chủ | 1h → 4h → 15h |

**Chặn bởi:** M1–M6. Và `G6` chặn bởi **chữ ký uỷ quyền của người vận hành**, không phải
bởi code.

---

## M7.1 — Hoàn thiện MỘT nhân vật trước khi nhân rộng

Người vận hành, 2026-09-20: *"phải hoàn thiện 1 nhân vật trước khi upscale sang
nhân vật khác, rồi mới qua tài khoản khác"*. Thứ tự này là ràng buộc, không phải
gợi ý — nhân rộng một quy trình chưa ổn định thì chỉ nhân lên số lỗi.

### Số đo thực địa — bảng Troops, 2026-09-20

| # | Cặp tướng | Quân | Còn lại | Toạ độ |
|---|---|---|---|---|
| 1 | Wak Chanil Ajaw / Ishida Mitsunari | 44.675 | *đang đi* 00:00:33 → Lvl 6 Cropland | X:1100 Y:589 |
| 2 | Seondeok / Cleopatra VII | 15.123 | 03:44:36 | X:1083 Y:570 |
| 3 | Constance / Matilda of Flanders | 35.416 | 03:13:14 | X:1082 Y:567 |
| 4 | Centurion / Joan of Arc | 39.757 | 02:48:50 | X:1077 Y:575 |
| 5 | Šárka / Gaius Marius | 34.391 | 02:06:52 | X:1065 Y:586 |

**Tổng quân đã ra đồng: 169.362 / 189.000 = 89,6%.**

**Đính chính:** trước đó tôi đọc `Units 34.391/189.000` trên panel New Troop là
"đạo quân chỉ đầy 18%" và đề xuất thêm bước bấm MAX. **Sai.** 189.000 là tổng
quân trong thành, không phải sức chứa một chuyến. Chênh lệch giữa các chuyến
(15.123 … 44.675, **3,0 lần**) đi theo **cấp tướng** — Seondeok 27/27 chở 15k,
Centurion 37/27 chở 39,7k. Đòn bẩy là **nâng cấp tướng**, không phải nút MAX.

**Đuôi rảnh: 01:37:44 — chiếm 44% chu kỳ.** Slot về sớm nhất (02:06:52) nằm
không tới khi cả lô về (03:44:36, và chuyến #1 còn chưa bắt đầu đào nên con số
thật còn dài hơn). Đây chính là đại lượng `Character.idle_tail()` tính, nay có
số thật lần đầu.

**Giả thuyết mạnh nhất, cần kiểm ngay:** mốc của người vận hành là 2h00–2h30
(farm mạnh) và 3h30–4h00 (farm yếu), **cả hai đều giả định buff thu thập 50%
đang chạy**. Quan sát 03:44:36 rơi đúng dải **yếu**. Nhiều khả năng **buff đang
tắt** — và đó là đòn bẩy lớn nhất hiện có, đúng thứ người vận hành hỏi.

### Hiệu suất vòng lặp, đo trên 11 lượt recon hôm nay

```
238 tick   ·   13% tick thực sự bấm gì đó   ·   29% UNKNOWN_STATE
```

Gửi được 5 đạo quân tốn ~238 tick. Đạt 5/5 **một lần** không phải là xong;
**lặp lại được mà không cần người can thiệp** mới là xong.

### Bốn việc, theo thứ tự phụ thuộc

**1. Cảm biến bảng Troops — thiếu, và là mảnh còn thiếu lớn nhất.**
`knowledge/gathering_continuity_2026-09-19.yaml` đã ghi bảng này là *"the
authoritative surface for measuring farm rhythm"*, nhưng chưa có code đọc nó.
Mỗi dòng cho: toạ độ mỏ, cặp tướng, số quân, **thời gian đào còn lại**.

Đây là nguồn dữ liệu cho `MIS-006` (chu kỳ khấu hao theo đạo chậm nhất) và
`MIS-007` (chỉ vào lại khi cả 5 về) — hiện `Character.batch_home_at()` **không
có nguồn nào cấp số**. Panel này lấp đúng chỗ đó.

Lưu ý ngữ nghĩa đã ghi trong `LLM_GAMEPLAY_SPEC` Pha 3: đồng hồ `Gathering` là
**thời gian đào còn lại, KHÔNG gồm đường về**. Thời gian về phải suy ra.

**2. Vòng dùng vật phẩm — buff không được chạm đáy.**
Tri thức đã có đủ và **chưa có code**:
- `8-Hour Enhanced Gathering`, **cộng dồn THỜI LƯỢNG, không cộng phần trăm**
- 3 vật phẩm = phủ 24h; không có lý do canh lúc hết hạn
- Hộp xác nhận **tự nói ra tổng thời lượng sau khi dùng** → đó là postcondition
- **BẪY:** `YES` màu **đỏ, bên TRÁI**; `NO` màu **xanh, bên PHẢI** — ngược quy
  ước thường gặp. Nối đất **bắt buộc theo nhãn chữ**, cấm theo màu hoặc vị trí
  (`SAF-004`)
- Tiêu vật phẩm là **spend-class**: một lần xác nhận có thể tiêu nhiều món →
  cần cổng phê duyệt của người vận hành (`SAF-005`)

**3. Vòng nạp lại — hiện mỗi chuyến là một lệnh tay.**
Biết lúc nào quân về (từ việc 1) thì tự gửi lại. Không có việc này thì 5/5 là
một ảnh chụp, không phải một nhịp.

**4. Độ tin cậy — 13% tick có tác dụng là quá thấp.**
Phần lớn tick trôi vào `UNKNOWN_STATE` giữa các hoạt ảnh. Không chặn 5/5 nhưng
chặn việc chạy không người trông.

### Xong MỘT nhân vật khi nào

| Cổng | Điều kiện | Đo bằng |
|---|---|---|
| A | Đạt 5/5 **hai lô liên tiếp**, không can thiệp tay | log occurrence |
| B | Buff thu thập **không chạm 0** suốt hai lô đó | đọc buff + sổ dùng item |
| C | Quân về được **phát hiện và nạp lại tự động** | cảm biến bảng Troops |
| D | Chu kỳ đo được rơi vào dải **2h00–2h30** khi có buff | bảng Troops |

**Chỉ khi A–D xanh mới sang nhân vật thứ hai.** Sang nhân vật là thêm bước
chuyển nhân vật; sang tài khoản là thêm đăng nhập — mỗi bậc thêm một lớp lỗi
mới, và không lớp nào đáng thêm khi lớp dưới còn rung.

---

## M8 — Giao hàng · sau cùng

| Yêu cầu | Trạng thái |
|---|---|
| `DEL-012…015` | cách đã biết: tele **một lần mỗi chiến dịch**, ô đích phải `Unoccupied`, nối đất `Teleport`/`March` theo nhãn chữ |
| `DEL-002…004` | khoá: thi hành, xác minh, nối đất người nhận |

**Vì sao sau cùng:** giao hàng chuyển tài sản **không hoàn tác được**, và vì slot dùng chung
nên mỗi chuyến là một slot không farm. Chỉ nên làm khi phần farm đã chạy ổn định.

**An toàn:** game cho giao hết, nên không có trần hành động nào để dựa vào. **Sổ cái đúng là
cơ chế an toàn duy nhất** — đã cưỡng chế bằng `evidence_ref` bắt buộc.

---

## Phụ thuộc

```
M1 đọc đúng ──┬─→ M3 đủ nhanh ──→ M5 tự lập lịch ──┐
              │                                     ├─→ M7 chạy thật ──→ M8 giao hàng
M2 nền móng ──┴─→ M4 không đứng hình ──→ M6 LLM ────┘
```

**Song song được:** M2 với M1 · M3 với M4.
**Không song song được:** M5 chờ M3 · M7 chờ tất cả · M8 chờ M7.

---

## Cần người vận hành

| Việc | Loại | Chặn |
|---|---|---|
| Duyệt ngưỡng `SC-01…05` | quyết định | đo lường ở M7 |
| Sản lượng ngày thật (`SC-06`) | quyết định | so sánh với trần |
| Điều hướng UI để tôi chụp | thao tác | M1, M5 |
| Nghiệp vụ nào bỏ lúc cao điểm | quyết định **sau khi đo** | M5 |
| Ký `R3_ENDURANCE_AUTHORIZATION` | quyết định | `G6` |

---

## Không làm trong vòng này

| Việc | Vì sao hoãn |
|---|---|
| Chuyển `harness/` vào `autorok/` | 44 module + 58 file test; làm khi đã ổn định |
| Đăng nhập đổi tài khoản | đổi nhân vật trong game đủ cho 2×4 |
| Nhánh alliance (`A001`) | GATHER chưa đóng thì chưa mở nhánh hai |
| Giao diện vận hành | bản HUD cũ người vận hành nói không dùng được; thiết kế lại sau M6 |
| ~~CI~~ | **đã xoá hẳn** — chạy trên máy ảo thuê, trái ranh giới dự án |
