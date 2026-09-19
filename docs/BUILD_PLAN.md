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
sáng — nên tốc độ là tiền đề của M4, không phải của M1.

| Yêu cầu | Việc |
|---|---|
| `OCR-003` | 4.863 ms → dưới 400 ms: crop trong bộ nhớ (bỏ 11 lần ghi/đọc PNG), tiến trình OCR thường trú |
| `OCR-004` | Kết quả sau tối ưu **giống hệt** trước trên toàn corpus |

**Xong khi:** < 400 ms/khung và corpus khớp từng ký tự.

**Chỉ khi vẫn chưa đạt mới tính tới binary native.** Phát input đang dưới 1 ms nên không có
gì để giành ở phía chuột.

---

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

| Yêu cầu | Việc |
|---|---|
| `LLM-006` | Người nhận cho gói chiến lược — hiện `decision_packets()` dựng gói rồi **vứt đi** |
| `LLM-008` | `retraining_required` phải nêu *cái gì đổi* và *khung hình nào chứng minh* |
| `LLM-009` | Model **đề xuất** tri thức, người vận hành duyệt; cấm tự ghi |
| `ONB-001…004` | Onboarding 6 pha; chỉ pha 0 được chặn |
| `LLM-007` | Đo tần suất gọi, đích ≤ 5/100 tick |

**Xong khi:** một chu kỳ lập kế hoạch chạy offline và trả về một `MissionIntent` hợp lệ.

Đây là lúc 20,6 giây chuyển từ lỗi chặn thành không quan trọng — ở tầng này harness đang
chờ quân về hàng giờ.

---

## M7 — Chạy thật · cần client, có phát input

| Việc | Ghi chú |
|---|---|
| Nối `autorok.mission` vào `run_gather_tick.py` | |
| **Hàng đợi một nhân vật lên 5/5** | mục tiêu nghiệm thu của người vận hành |
| Xoay vòng hai cấp qua 8 nhân vật | |
| Đo north star: giờ chạy tự chủ | 1h → 4h → 15h |

**Chặn bởi:** M1–M6. Và `G6` chặn bởi **chữ ký uỷ quyền của người vận hành**, không phải
bởi code.

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
