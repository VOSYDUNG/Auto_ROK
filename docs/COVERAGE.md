# Độ phủ hiện tại — Auto_ROK

Chụp ngày **2026-09-19**, tại commit merge `61d818b`.
Chịu sự điều chỉnh của [`docs/PROJECT_DECLARATION.md`](PROJECT_DECLARATION.md).

Tài liệu này là **bản chụp có ngày của số đo**, không phải bảng tuyên bố viết tay. Mọi con
số dưới đây đều lấy từ việc chạy thật trên máy, không chép lại từ tài liệu cũ. Khi cần
biết trạng thái *bây giờ*, chạy lệnh trong §7 chứ đừng tin bản chụp này.

---

## 1. Nghiệm thu G1–G6

Nguồn: `python scripts/audit_goal_readiness.py` — đọc bằng chứng thật trong
`workspace/evidence/`.

| Cổng | Kết quả | Ghi chú |
|---|---|---|
| G1 — cô lập input trên host | **pass** | có trace host thật, không input ngoài ý muốn |
| G2 — CPU / OCR / trạng thái | **pass** | thiết bị xử lý `cpu`, OpenCL tắt, CUDA 0 |
| G3 — holdout LLM local | **pass** | 12/12 ca, độ chính xác 1.0, chưa được reviewer độc lập duyệt |
| G4 — phê duyệt B003 theo occurrence | **pass** | gắn đúng occurrence hiện tại |
| G5 — hậu điều kiện GATHER live | **pass** | `Queue used` tăng 1, biên nhận VERIFIED |
| G6 — endurance | **blocked** | đã đăng ký 2/10 run · thành công 2/9 tối thiểu · **thiếu file uỷ quyền** |

**Trạng thái tổng: `blocked` tại G6.** Đây là trạng thái đúng và có chủ ý — G6 yêu cầu
người vận hành uỷ quyền tường minh, không được tự mở.

---

## 2. Quy mô mã nguồn

| Thành phần | Số lượng |
|---|---|
| `harness/` | 44 file, 8.664 dòng |
| `scripts/` | 55 file |
| `tests/` | 56 file |
| `operator_layer/` | 5 file |
| `knowledge/` | 9 file |
| `docs/` | 20 file + `docs/reference/` 10 file |

Kiểm thử cục bộ: **248 test pass** (`python -m pytest -q`).

---

## 3. Đồ thị kỹ thuật

Nguồn: `config/engineering_graph.yaml`, kiểm bằng `scripts/validate_engineering_graph.py`
→ **PASS**.

- **53 node**: 44 `implemented` · 8 `partial` · 1 `blocked`
- **101 cạnh**
- **Blocker đang mở: `A001`** — chữ ký hoàn thành sau nút Claim của nhánh alliance chưa
  được huấn luyện
- Thẩm quyền: 41 `canonical` · 8 `evidence` · 4 `operator`

### 8 node ở mức `partial`

`completion_audit` · `rapidocr_fixed_roi_backend` · `observation_corpus_holdout` ·
`local_decision_provider` · `local_llm_shadow_overlay` · `harness_comparison_protocol` ·
`r3_repetition_evidence` · `r3_endurance_authorization`

### 9 chiều độ phủ chưa đầy đủ (trên tổng 36)

`field_reconnaissance` · `game_state_mission_matrix` · `rapidocr_fixed_roi_backend` ·
`observation_corpus_holdout` · `r3_repetition_evidence` · `r3_endurance_authorization` ·
`local_llm_decision_canary` · `harness_comparison_protocol` · `commander_troop_policy`

### Nhánh mission

| Nhánh | Độ phủ |
|---|---|
| `GATHER_RESOURCE` | lát cắt đang nhận — G1–G5 đạt |
| `CLAIM_ALLIANCE_TERRITORY_RSS` | `partial` — chặn bởi A001 |
| `GPT_OSS_DECISION_PROVIDER` | `partial` |
| `MISSION_SCHEDULER` | `partial` |
| `BARBARIAN_FORT_RALLY` | `training_only` |
| `SWITCH_CHARACTER` | chưa phủ end-to-end |
| `EVENT_COORDINATION` | chưa phủ end-to-end |

---

## 4. Hiệu năng — đo ngày 2026-09-19

Đây là phần quan trọng nhất của bản chụp này, vì nó chỉ ra chỗ nghẽn thật.

| Thành phần | Đo được | Ngưỡng PRD | Kết luận |
|---|---|---|---|
| Phát input `SendInput` | **< 1 ms** | < 5 ms (N03) | đạt, còn dư rất nhiều |
| OCR lõi `Windows.Media.Ocr`, đã ấm | 170 ms | — | hợp lý |
| Nạp WinRT (`Add-Type`) | 90 ms | — | lẽ ra chỉ trả 1 lần |
| Khởi động `powershell.exe` | 185 ms | — | trả **mỗi lần gọi** |
| **Một khung hình qua `scripts/windows_ocr.ps1`** | **4.525 ms** | **< 400 ms (N02)** | **chưa đạt, lệch ~11x** |
| Một quyết định LLM local | 20.600 ms (trung vị) | < 10.000 ms (N04) | chưa đạt |

### Nguyên nhân của 4.525 ms

`scripts/windows_ocr.ps1` dài 711 dòng và gọi **11 lần** `RecognizeAsync`. Mỗi lần crop
được **ghi ra file PNG trên đĩa rồi decode lại**. Cộng thêm chi phí spawn process và parse
script cho mỗi khung hình.

Bản thân OCR không chậm — cách gọi nó mới chậm. Hướng sửa đã xác định, chưa thực hiện:
crop trong bộ nhớ; tiến trình OCR thường trú; nếu vẫn chưa đủ thì mới tới binary native.

### Ghi chú về C/C++

Đo đạc cho thấy chuột/phím chiếm dưới 1 ms, tức dưới 0,003% một vòng quan sát. Chuyển
sang C/C++ cho phần di chuyển chuột **không** mang lại lợi ích hiệu năng nào. Chỗ đáng
dùng ngôn ngữ native là đường OCR.

---

## 5. Nợ kỹ thuật đã xác định

| Vấn đề | Quy mô |
|---|---|
| Không có `pyproject.toml`, `__init__.py`, `conftest.py` | import chạy nhờ `sys.path.insert` lặp trong 32/42 script; một script hardcode đường dẫn tuyệt đối của máy này |
| `pytest` chỉ chạy được qua `python -m pytest` | gõ `pytest tests/` trực tiếp là gãy |
| CI chạy trên `ubuntu-latest` cho sản phẩm Windows-only | **22/56 file test** được chạy; 34 file chưa bao giờ chạy trên CI |
| CI có danh sách test viết cứng | thêm test mới không tự được chạy |
| `.github/workflows/alliance-claim.yml` | chỉ kích hoạt trên nhánh `gpt-alliance-01` đã bị xoá → file chết |
| 16 module `harness/` không có trong đồ thị kỹ thuật | gồm cả `mission_runtime.py` (module được import nhiều nhất, 42 file) và `windows_live_observation.py` |
| Hai bộ contract song song | `mission_runtime.py` (đang dùng) và `contracts.py`+`runtime.py`+`policy.py`; `runtime.py` và `policy.py` **không có file nào import** |
| Bốn đường chạy mission song song | chỉ đường `mission_loader→engine→runner` là chính thức |
| Đường guest/VM còn sót | trái với ranh giới ở §5 Tuyên bố dự án |
| Evidence bị check vào `config/` | `r3_registered_runs.json`, `observation_label_lock.json` là output chứ không phải config |
| Luật nghiệm thu không chạy được ngoài máy này | validator đòi mọi node `implemented` có file evidence tồn tại, mà `workspace/` nằm trong `.gitignore` |

---

## 6. Danh mục chưa xác minh

Theo §8 Tuyên bố dự án, các mục dưới đây được mang theo một cách công khai và sẽ được
huấn luyện dần bằng kiểm nghiệm thực địa. Chúng **không chặn việc xây dựng**, nhưng
**chặn việc tuyên bố đã nghiệm thu** phần liên quan.

| Mục | Vì sao chưa xác minh | Cách xác minh |
|---|---|---|
| Chu kỳ quay vòng hàng của Courier Station | mới quan sát được 1 vòng (~2h) | quan sát ít nhất 2 vòng liên tiếp |
| Lịch giờ vào Courier Station | người vận hành nêu "7h, 12h" làm ví dụ, chưa chốt là giờ cố định hay bám đồng hồ game | chốt với người vận hành, hoặc đo theo đồng hồ `time_remaining` |
| Loại tiền tệ không phải gem trên một số ô hàng | icon không đủ rõ trong ảnh chụp | chụp lại ở độ phân giải cao hơn |
| Tên các boost khác trong tab `BOOSTS` | không hiện tên trong ảnh chụp | mở từng ô, đọc khung chi tiết |
| Buff tăng tốc thu thập có dùng chung timer với nguồn khác (alliance/VIP/sự kiện) không | chưa quan sát | quan sát khi có nguồn thứ hai đang hoạt động |
| Nút nào trên Courier Station mở panel merchant | thấy 2 nút, chưa rõ nút nào | thử trong pass recon an toàn |
| Phím tắt `I` có mở Items không | người vận hành nêu, chưa kiểm trên client | kiểm trong pass recon an toàn |
| Thời gian quân đi và **thời gian quân về** | game không hiển thị | đo qua chênh lệch sự kiện trong bảng Troops |
| Ngưỡng N02 (OCR < 400 ms) có đạt được không sau khi sửa | chưa sửa | đo lại sau khi tối ưu |

---

## 7. Cách tái lập bản chụp này

```bash
python -m pytest -q
```
```bash
python scripts/validate_engineering_graph.py
```
```bash
python scripts/audit_goal_readiness.py
```

---

## 8. Mâu thuẫn tài liệu đã xử lý

Bản audit ngày 2026-09-19 tìm thấy 18 mâu thuẫn giữa các tài liệu, hoặc giữa tài liệu và
code. Các mâu thuẫn về **định nghĩa và phạm vi** đã được giải quyết bằng
`docs/PROJECT_DECLARATION.md`, `docs/GOAL.md` và `docs/PRD.md`:

- bốn tên gọi khác nhau cho sản phẩm → một chủ ngữ duy nhất;
- năm hệ đánh số nghiệm thu → chỉ còn G1–G6;
- ba bảng trạng thái viết tay lệch nhau → một nguồn tính bằng máy;
- entrypoint tuyên bố sai → `scripts/run_gather_tick.py`;
- tiếng Việt/Anh trộn không luật → quy tắc ngôn ngữ ở §7 Tuyên bố dự án;
- GOAL cũ viết ngược quan hệ LLM/harness → đã sửa và ghi rõ chỗ sửa.

Các mâu thuẫn còn lại thuộc loại **nợ kỹ thuật**, nằm ở §5, và được xử lý bằng code chứ
không bằng tài liệu.
